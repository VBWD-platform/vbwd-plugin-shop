"""S154 D4 — shop pings cms's IndexNow seam on product/category change.

Unit level: the cms import is monkeypatched (no DB, no cms source needed), so
these run against the per-plugin isolated CI (shop without cms) too, where the
import naturally raises ``ImportError`` and every assertion still holds (no-op,
never a crash).

Engineering requirements (binding, restated): TDD-first · DevOps-first · SOLID ·
DI · DRY · Liskov · clean code · NO OVERENGINEERING.
"""
import logging
from unittest.mock import MagicMock

from plugins.shop.shop.services import seo_indexnow


def _switch_on(monkeypatch, enabled=True):
    monkeypatch.setattr(seo_indexnow, "seo_indexing_enabled", lambda key: enabled)


def _fake_cms_ping(monkeypatch):
    ping = MagicMock()
    monkeypatch.setattr(seo_indexnow, "_import_ping_indexnow_urls", lambda: ping)
    return ping


def test_notify_product_changed_pings_the_product_path_when_switch_on(monkeypatch):
    ping = _fake_cms_ping(monkeypatch)
    _switch_on(monkeypatch, True)

    seo_indexnow.notify_product_changed("blue-mug")

    ping.assert_called_once_with(["/shop/product/blue-mug"])


def test_notify_product_changed_noop_when_switch_off(monkeypatch):
    ping = _fake_cms_ping(monkeypatch)
    _switch_on(monkeypatch, False)

    seo_indexnow.notify_product_changed("blue-mug")

    ping.assert_not_called()


def test_notify_product_changed_noop_without_a_slug(monkeypatch):
    ping = _fake_cms_ping(monkeypatch)
    _switch_on(monkeypatch, True)

    seo_indexnow.notify_product_changed("")
    seo_indexnow.notify_product_changed(None)

    ping.assert_not_called()


def test_notify_category_changed_pings_the_category_path_when_switch_on(monkeypatch):
    ping = _fake_cms_ping(monkeypatch)
    _switch_on(monkeypatch, True)

    seo_indexnow.notify_category_changed("books")

    ping.assert_called_once_with(["/shop/category/books"])


def test_notify_category_changed_noop_when_switch_off(monkeypatch):
    ping = _fake_cms_ping(monkeypatch)
    _switch_on(monkeypatch, False)

    seo_indexnow.notify_category_changed("books")

    ping.assert_not_called()


def test_noop_when_cms_is_not_importable(monkeypatch):
    def _missing_cms():
        raise ImportError("No module named 'plugins.cms'")

    monkeypatch.setattr(seo_indexnow, "_import_ping_indexnow_urls", _missing_cms)
    _switch_on(monkeypatch, True)

    # Never raises — the plugin keeps working with cms absent/disabled.
    seo_indexnow.notify_product_changed("blue-mug")
    seo_indexnow.notify_category_changed("books")


def test_notify_products_changed_batches_every_slug_into_one_ping(monkeypatch):
    ping = _fake_cms_ping(monkeypatch)
    _switch_on(monkeypatch, True)

    seo_indexnow.notify_products_changed(["blue-mug", "red-mug"])

    ping.assert_called_once_with(["/shop/product/blue-mug", "/shop/product/red-mug"])


def test_notify_products_changed_drops_blank_slugs(monkeypatch):
    ping = _fake_cms_ping(monkeypatch)
    _switch_on(monkeypatch, True)

    seo_indexnow.notify_products_changed(["blue-mug", "", None])

    ping.assert_called_once_with(["/shop/product/blue-mug"])


def test_notify_products_changed_noop_when_switch_off(monkeypatch):
    ping = _fake_cms_ping(monkeypatch)
    _switch_on(monkeypatch, False)

    seo_indexnow.notify_products_changed(["blue-mug", "red-mug"])

    ping.assert_not_called()


def test_notify_products_changed_noop_when_no_slugs(monkeypatch):
    ping = _fake_cms_ping(monkeypatch)
    _switch_on(monkeypatch, True)

    seo_indexnow.notify_products_changed([])

    ping.assert_not_called()


def test_ping_failure_is_swallowed(monkeypatch, caplog):
    ping = MagicMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(seo_indexnow, "_import_ping_indexnow_urls", lambda: ping)
    _switch_on(monkeypatch, True)

    with caplog.at_level(logging.WARNING):
        seo_indexnow.notify_product_changed("blue-mug")

    assert caplog.records
