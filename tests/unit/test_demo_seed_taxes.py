"""Unit specs for the shop demo-seed tax linking (S85.4).

The shop catalog seeder must link the canonical demo VAT to its demo products
so the price disclosure shows gross > net. The link is idempotent and runs
independently of product creation (products are skipped on re-run, but the tax
link must still be ensured), and the tax is resolved by code through the core
linker — no cross-plugin import.
"""
from unittest.mock import MagicMock, patch

from plugins.shop.shop import demo_seed


def test_link_product_taxes_links_canonical_vat_to_demo_products():
    """Every present demo product gets the canonical VAT linked."""
    session = MagicMock()
    products = {}

    def _filter_by(**kwargs):
        result = MagicMock()
        result.first.return_value = products.get(kwargs.get("slug"))
        return result

    session.query.return_value.filter_by.side_effect = _filter_by

    # Two demo products exist in the DB.
    demo_slugs = [item["slug"] for item in demo_seed._products_data()]
    products[demo_slugs[0]] = MagicMock(taxes=[])
    products[demo_slugs[1]] = MagicMock(taxes=[])

    with patch.object(demo_seed, "link_demo_tax") as link_demo_tax:
        demo_seed._link_product_taxes(session)

    # Only the present products are passed to the linker (missing ones skipped).
    linked = []
    for call in link_demo_tax.call_args_list:
        linked.extend(call.args[1])
    assert set(linked) == {products[demo_slugs[0]], products[demo_slugs[1]]}


def test_link_product_taxes_noop_when_no_products_present():
    """When no demo product rows exist the linker is not called with any."""
    session = MagicMock()
    session.query.return_value.filter_by.return_value.first.return_value = None

    with patch.object(demo_seed, "link_demo_tax") as link_demo_tax:
        demo_seed._link_product_taxes(session)

    linked = []
    for call in link_demo_tax.call_args_list:
        linked.extend(call.args[1])
    assert linked == []


def test_seed_catalog_calls_link_product_taxes():
    """``seed_catalog`` ensures product tax links on every run (S85.4)."""
    session = MagicMock()

    with patch.object(
        demo_seed, "_seed_warehouse_products", return_value=0
    ), patch.object(demo_seed, "_populate_cms_content"), patch.object(
        demo_seed, "_populate_email_templates"
    ), patch.object(
        demo_seed, "_link_product_taxes"
    ) as link_product_taxes:
        demo_seed.seed_catalog(session)

    link_product_taxes.assert_called_once_with(session)
