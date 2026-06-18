"""S99.0 — the shop search-result price display uses the CONFIGURED currency.

``_format_price`` previously hard-coded ``"EUR"`` as its fallback. The contract
(S99) is one billing currency = the ``default_currency`` core setting; the
display helper must read that, never a literal. Setting it to ``USD`` then
``GBP`` proves no literal remains.
"""
import pytest

from plugins.shop.shop.search_provider import _format_price


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path, monkeypatch):
    """Isolate the settings store: a throwaway var dir + no DB catalog provider.

    A prior test that built the Flask ``app`` may have left a DB-backed currency
    catalog provider wired globally (``register_currency_catalog_provider``).
    Clearing it keeps this pure-unit test free of an app context — currency
    validation stays structural-only, which is all this display helper needs.
    """
    from vbwd.services.core_settings_store import register_currency_catalog_provider

    monkeypatch.setenv("VBWD_VAR_DIR", str(tmp_path))
    register_currency_catalog_provider(None)
    yield tmp_path
    register_currency_catalog_provider(None)


@pytest.mark.parametrize("configured_currency", ["USD", "GBP"])
def test_format_price_uses_configured_default_currency(
    configured_currency, monkeypatch
):
    from vbwd.services.core_settings_store import update_core_settings

    update_core_settings(
        {
            "active_currencies": ["EUR", configured_currency],
            "default_currency": configured_currency,
        }
    )
    assert _format_price(12.5) == f"12.50 {configured_currency}"


def test_format_price_returns_none_for_missing_amount():
    assert _format_price(None) is None
