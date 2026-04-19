"""Unit tests for ShopLineItemHandler — Sprint 06b."""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from vbwd.events.line_item_registry import LineItemContext
from vbwd.models.enums import LineItemType
from plugins.shop.shop.handlers.line_item_handler import (
    ShopLineItemHandler,
)


@pytest.fixture()
def handler():
    return ShopLineItemHandler(session_factory=MagicMock(), event_bus=MagicMock())


@pytest.fixture()
def context():
    invoice = MagicMock()
    invoice.id = uuid4()
    invoice.user_id = uuid4()
    invoice.currency = "EUR"
    return LineItemContext(invoice=invoice, user_id=invoice.user_id, container=MagicMock())


def _make_line_item(item_type, plugin=None, extra=None):
    line_item = MagicMock()
    line_item.item_type = item_type
    line_item.item_id = uuid4()
    line_item.extra_data = extra or {}
    if plugin:
        line_item.extra_data["plugin"] = plugin
    return line_item


class TestCanHandle:
    def test_handles_custom_shop(self, handler, context):
        line_item = _make_line_item(LineItemType.CUSTOM, plugin="shop")
        assert handler.can_handle_line_item(line_item, context) is True

    def test_rejects_custom_non_shop(self, handler, context):
        line_item = _make_line_item(LineItemType.CUSTOM, plugin="booking")
        assert handler.can_handle_line_item(line_item, context) is False

    def test_rejects_subscription(self, handler, context):
        line_item = _make_line_item(LineItemType.SUBSCRIPTION)
        assert handler.can_handle_line_item(line_item, context) is False

    def test_rejects_token_bundle(self, handler, context):
        line_item = _make_line_item(LineItemType.TOKEN_BUNDLE)
        assert handler.can_handle_line_item(line_item, context) is False

    def test_rejects_custom_no_plugin(self, handler, context):
        line_item = _make_line_item(LineItemType.CUSTOM)
        assert handler.can_handle_line_item(line_item, context) is False
