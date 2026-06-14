"""Integration: shop entity exchangers (real PG) — S46.6.

* ``shop_products`` round-trips by ``slug`` (export → wipe → import → equal).
* ``shop_orders`` is export-only: ``import_`` raises
  ``UnsupportedOperationError`` (Liskov); its export redacts the
  shipping/billing address PII unless ``include_pii``.
* registration: after ``ShopPlugin._register_data_exchangers`` the exchangers
  appear in ``data_exchange_registry`` with cluster ``sales``.

Data is seeded through the ORM session (no raw SQL); the shared ``db`` fixture
creates + drops the test DB.

Engineering requirements (binding, restated): TDD-first; DevOps-first; SOLID/DI/
DRY; Liskov; no overengineering. Quality guard: ``bin/pre-commit-check.sh
--plugin shop --full``.
"""
import uuid

import pytest

from vbwd.services.data_exchange.envelope import build_envelope, rows_to_csv
from vbwd.services.data_exchange.port import (
    CLUSTER_SALES,
    ExportSelector,
    UnsupportedOperationError,
)
from plugins.shop.shop.models.order import Order, OrderStatus
from plugins.shop.shop.models.product import Product
from plugins.shop.shop.services.data_exchange.shop_exchangers import (
    build_shop_exchangers,
)
from vbwd.models.user import User


def _exchangers(session):
    return {
        exchanger.entity_key: exchanger for exchanger in build_shop_exchangers(session)
    }


class TestProductsRoundTrip:
    def test_round_trip_by_slug(self, db):
        slug = f"prod-{uuid.uuid4().hex[:8]}"
        db.session.add(Product(slug=slug, name="Widget", sku="SKU-1", price=12))
        db.session.commit()

        exchanger = _exchangers(db.session)["shop_products"]
        before = exchanger.export(ExportSelector(ids=[slug]), include_pii=False).rows
        assert before and before[0]["slug"] == slug
        assert before[0]["sku"] == "SKU-1"

        db.session.query(Product).filter(Product.slug == slug).delete()
        db.session.commit()

        payload = build_envelope("shop_products", before, instance="test")
        result = exchanger.import_(payload, mode="upsert", dry_run=False)
        assert result.created == 1

        rebuilt = db.session.query(Product).filter(Product.slug == slug).first()
        assert rebuilt is not None
        assert rebuilt.name == "Widget"
        assert rebuilt.sku == "SKU-1"


class TestOrdersExportOnly:
    def _seed_order(self, db):
        user = User(email=f"u-{uuid.uuid4().hex[:8]}@example.com", password_hash="x")
        db.session.add(user)
        db.session.commit()
        order = Order(
            user_id=user.id,
            order_number=f"ORD-{uuid.uuid4().hex[:8]}",
            status=OrderStatus.CONFIRMED,
            shipping_address={"line1": "1 Main St", "city": "Berlin"},
            billing_address={"line1": "1 Main St", "city": "Berlin"},
            subtotal=10,
            total_amount=10,
        )
        db.session.add(order)
        db.session.commit()
        return order

    def test_import_raises_unsupported(self, db):
        exchanger = _exchangers(db.session)["shop_orders"]
        payload = build_envelope("shop_orders", [], instance="test")
        with pytest.raises(UnsupportedOperationError):
            exchanger.import_(payload, mode="upsert", dry_run=False)

    def test_export_selected_by_primary_id(self, db):
        """fe-admin "Export selected" sends the order's primary id (UUID)."""
        order = self._seed_order(db)
        exchanger = _exchangers(db.session)["shop_orders"]
        rows = exchanger.export(
            ExportSelector(ids=[str(order.id)]), include_pii=False
        ).rows
        assert [r["order_number"] for r in rows] == [order.order_number]

    def test_export_redacts_address_pii(self, db):
        order = self._seed_order(db)
        exchanger = _exchangers(db.session)["shop_orders"]

        without_pii = exchanger.export(
            ExportSelector(ids=[order.order_number]), include_pii=False
        ).rows
        assert without_pii and without_pii[0]["shipping_address"] is None
        assert without_pii[0]["billing_address"] is None
        assert without_pii[0]["status"] == "CONFIRMED"

        with_pii = exchanger.export(
            ExportSelector(ids=[order.order_number]), include_pii=True
        ).rows
        assert with_pii[0]["shipping_address"]["city"] == "Berlin"


class TestCsvExport:
    """Sales entities list ``csv``; shop_orders' nested address CSV-exports."""

    def test_shop_orders_csv_export_with_nested_address(self, db):
        order = TestOrdersExportOnly()._seed_order(db)
        exchanger = _exchangers(db.session)["shop_orders"]
        assert "csv" in exchanger.supported_formats
        rows = exchanger.export(
            ExportSelector(ids=[order.order_number]), include_pii=True
        ).rows
        # The nested shipping/billing address dicts must not break the writer.
        csv_text = rows_to_csv(rows)
        assert "order_number" in csv_text.splitlines()[0]
        assert order.order_number in csv_text
        assert len(csv_text.splitlines()) >= 2


class TestRegistration:
    def test_on_enable_registers_shop_exchangers(self, db):
        from vbwd.services.data_exchange.registry import data_exchange_registry
        from plugins.shop import ShopPlugin

        plugin = ShopPlugin()
        plugin.initialize({})
        plugin._register_data_exchangers()

        by_key = {
            exchanger.entity_key: exchanger
            for exchanger in data_exchange_registry.all()
        }
        for key in ("shop_products", "shop_orders"):
            assert key in by_key
            assert by_key[key].cluster == CLUSTER_SALES
        assert by_key["shop_orders"].supports_import is False
