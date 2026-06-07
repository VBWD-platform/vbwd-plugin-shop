"""Shop entity exchangers for the S46 data-exchange seam (S46.6).

Exposes the shop catalog + orders through the core ``EntityExchanger`` contract
so they appear on the generic Settings → Import/Export page and the per-list
controls.

Entities:

* ``shop_products`` (``Product``, natural key ``slug``) — import+export. ``slug``
  is the stable required-unique key (``sku`` is nullable, so it is exported but
  not used as the natural key).
* ``shop_orders`` (``Order``, natural key ``order_number``) — **export-only**:
  an order is created by the payment-capture flow and binds a user + invoice +
  its line items via UUID FKs / a cascade child relationship the engine owns, so
  it is not structurally importable. Per Liskov ``import_`` raises
  :class:`UnsupportedOperationError`. The export redacts the customer
  shipping/billing address PII unless the caller holds the PII permission.

Design notes:

* **Reused perms** — the plugin already ships ``shop.products.*`` /
  ``shop.orders.*``; each exchanger maps ``export_permission`` /
  ``import_permission`` onto those (single source of truth).
* **DRY** — products reuse :class:`BaseModelExchanger`; only the narrow
  ``_SessionModelRepository`` adapter is added (mirrors core / CMS).
* **No core change** — registration happens in ``ShopPlugin.on_enable`` through
  the shared ``db.session``; core imports no ``plugins.*`` module.

Engineering requirements (binding, restated): TDD-first; DevOps-first; SOLID
(one exchanger per entity, narrow ports); DI (session injected); DRY; Liskov
(orders export-only raises); clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin shop --full``.
"""
from typing import Any, List, Optional

from vbwd.services.data_exchange.base_model_exchanger import BaseModelExchanger
from vbwd.services.data_exchange.port import (
    CLUSTER_SALES,
    EntityExchanger,
    Envelope,
    ExportSelector,
    ImportResult,
    UnsupportedOperationError,
)
from vbwd.services.data_exchange.registry import data_exchange_registry

# Existing shop permissions (single source — ShopPlugin.admin_permissions).
PERM_PRODUCTS_VIEW = "shop.products.view"
PERM_PRODUCTS_MANAGE = "shop.products.manage"
PERM_ORDERS_VIEW = "shop.orders.view"


class _SessionModelRepository:
    """Narrow model repo satisfying the ``BaseModelExchanger`` contract (ISP).

    Mirrors core's / CMS's adapter: the shop repositories expose paginated /
    domain finders rather than the four flat methods the base exchanger needs.
    """

    def __init__(self, session: Any, model_class: type, natural_key: str) -> None:
        self._session = session
        self._model_class = model_class
        self._natural_key = natural_key

    def find_all(self) -> List[Any]:
        return self._session.query(self._model_class).all()

    def find_by_natural_key(self, value: Any) -> Optional[Any]:
        column = getattr(self._model_class, self._natural_key)
        return self._session.query(self._model_class).filter(column == value).first()

    def add(self, instance: Any) -> None:
        self._session.add(instance)

    def delete_all(self) -> None:
        self._session.query(self._model_class).delete()


class _PermissionMappedModelExchanger(BaseModelExchanger):
    """A ``BaseModelExchanger`` whose perms map onto existing shop perms."""

    def __init__(
        self,
        *,
        view_permission: str,
        manage_permission: str,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._view_permission = view_permission
        self._manage_permission = manage_permission

    @property
    def export_permission(self) -> str:
        return self._view_permission

    @property
    def import_permission(self) -> str:
        return self._manage_permission


class ShopOrdersExchanger(EntityExchanger):
    """``Order`` records, keyed by ``order_number`` — export-only.

    An order is created by the payment-capture flow and binds a user, an invoice
    and its line items; it is not a portable catalog row, so it is export-only.
    ``import_`` raises (Liskov) rather than pretending to upsert.
    """

    entity_key = "shop_orders"
    label = "Shop Orders"
    cluster = CLUSTER_SALES
    natural_key = "order_number"
    supports_export = True
    supports_import = False
    supported_formats = frozenset({"json"})
    secret_fields = frozenset()
    pii_fields = frozenset({"shipping_address", "billing_address"})

    _ROW_FIELDS = (
        "order_number",
        "user_id",
        "invoice_id",
        "status",
        "shipping_address",
        "billing_address",
        "shipping_method",
        "shipping_cost",
        "tracking_number",
        "subtotal",
        "tax_amount",
        "total_amount",
        "currency",
        "notes",
    )

    def __init__(self, session: Any) -> None:
        self._session = session

    def export(self, selector: ExportSelector, *, include_pii: bool) -> Envelope:
        from plugins.shop.shop.models.order import Order

        rows = self._session.query(Order).all()
        if selector.ids:
            wanted = set(selector.ids)
            rows = [row for row in rows if row.order_number in wanted]
        serialised = [self._serialise(row, include_pii=include_pii) for row in rows]
        return Envelope(entity_key=self.entity_key, rows=serialised)

    def _serialise(self, row: Any, *, include_pii: bool) -> dict:
        result: dict = {}
        for field_name in self._ROW_FIELDS:
            value = getattr(row, field_name)
            if field_name == "status" and value is not None:
                value = value.value
            if field_name in self.pii_fields and not include_pii:
                value = None
            result[field_name] = value
        return result

    def import_(self, payload: dict, *, mode: str, dry_run: bool) -> ImportResult:
        raise UnsupportedOperationError(
            "shop orders are export-only: an order is owned by the payment-capture "
            "flow and cannot be imported"
        )

    @property
    def export_permission(self) -> str:
        return PERM_ORDERS_VIEW


def build_shop_exchangers(session: Any) -> List[EntityExchanger]:
    """Construct the shop exchangers bound to ``session``."""
    from plugins.shop.shop.models.product import Product

    return [
        _PermissionMappedModelExchanger(
            entity_key="shop_products",
            label="Shop Products",
            cluster=CLUSTER_SALES,
            natural_key="slug",
            model_class=Product,
            repository=_SessionModelRepository(session, Product, "slug"),
            session=session,
            public_fields=[
                "slug",
                "name",
                "description",
                "sku",
                "price",
                "currency",
                "price_float",
                "is_active",
                "is_digital",
                "has_variants",
                "sort_order",
                "dimensions",
                "product_metadata",
                "tax_class",
            ],
            view_permission=PERM_PRODUCTS_VIEW,
            manage_permission=PERM_PRODUCTS_MANAGE,
        ),
        ShopOrdersExchanger(session),
    ]


def register_shop_exchangers(session: Any) -> None:
    """Register the shop exchangers into the registry (idempotent).

    Called from ``ShopPlugin.on_enable``. Re-registering replaces by key, so a
    repeat enable (per-test app) is clear-safe.
    """
    for exchanger in build_shop_exchangers(session):
        data_exchange_registry.register(exchanger)
