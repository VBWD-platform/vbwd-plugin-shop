"""S154 P2 / D3 — shop registers its sitemap providers whenever cms is INSTALLED.

cms owns the registry and only cms's own sitemap routes read it, so shop
registers as soon as ``plugins.cms.src.services.seo_registry`` imports —
independent of cms's enable state and of plugin enable order (a cms enabled
after shop then serves shop's chunks without a shop re-enable). With cms not
importable the registration is a silent no-op and shop still enables;
``on_disable`` takes the providers out again. The cms registry is faked (the
per-plugin CI clones shop without cms).

Engineering requirements (binding, restated): TDD-first · DevOps-first · SOLID ·
DI · DRY · Liskov · clean code · NO OVERENGINEERING.
"""
from types import SimpleNamespace

import pytest
from flask import Flask

from plugins.shop import ShopPlugin
from vbwd.plugins.base import PluginStatus


class _FakeSitemapRegistry:
    """The two cms registry functions shop calls, plus cms's entry type."""

    SitemapEntry = SimpleNamespace

    def __init__(self):
        self.providers = {}

    def register_sitemap_provider(self, provider):
        self.providers[provider.name] = provider

    def unregister_sitemap_provider(self, provider):
        self.providers.pop(provider.name, None)


@pytest.fixture
def fake_registry(monkeypatch):
    registry = _FakeSitemapRegistry()
    monkeypatch.setattr(
        ShopPlugin, "_import_cms_sitemap_registry", staticmethod(lambda: registry)
    )
    return registry


def _register(plugin_manager=None):
    app = Flask(__name__)
    if plugin_manager is not None:
        setattr(app, "plugin_manager", plugin_manager)
    plugin = ShopPlugin()
    with app.app_context():
        plugin._register_sitemap_providers()
    return plugin


def _plugin_manager_with_cms(cms_status):
    cms_plugin = SimpleNamespace(status=cms_status)
    return SimpleNamespace(
        get_plugin=lambda name: cms_plugin if name == "cms" else None
    )


def test_cms_installed_registers_both_providers(fake_registry):
    _register()

    assert sorted(fake_registry.providers) == ["shop-categories", "shop-products"]


@pytest.mark.parametrize(
    "cms_status",
    [PluginStatus.ENABLED, PluginStatus.INITIALIZED, PluginStatus.DISABLED],
)
def test_registration_ignores_cms_enable_state(fake_registry, cms_status):
    _register(_plugin_manager_with_cms(cms_status))

    assert sorted(fake_registry.providers) == ["shop-categories", "shop-products"]


def test_disable_unregisters_both_providers(fake_registry):
    plugin = _register()

    plugin._unregister_sitemap_providers()

    assert fake_registry.providers == {}


def test_cms_not_importable_is_a_no_op(monkeypatch):
    def _missing_cms():
        raise ImportError("No module named 'plugins.cms'")

    monkeypatch.setattr(
        ShopPlugin, "_import_cms_sitemap_registry", staticmethod(_missing_cms)
    )

    plugin = _register()

    plugin._unregister_sitemap_providers()  # never raises without registration
