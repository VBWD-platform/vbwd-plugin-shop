"""Unit tests for shop models — Sprint 06a."""
from uuid import uuid4

from plugins.shop.shop.models.product import Product
from plugins.shop.shop.models.warehouse_stock import WarehouseStock
from plugins.shop.shop.models.stock_block import StockBlockStatus
from plugins.shop.shop.models.order import OrderStatus


class TestWarehouseStockProperties:
    def test_available_is_quantity_minus_reserved(self):
        stock = WarehouseStock()
        stock.quantity = 100
        stock.reserved = 30
        assert stock.available == 70

    def test_available_never_negative(self):
        stock = WarehouseStock()
        stock.quantity = 5
        stock.reserved = 10
        assert stock.available == 0

    def test_is_low_stock_below_threshold(self):
        stock = WarehouseStock()
        stock.quantity = 8
        stock.reserved = 0
        stock.low_stock_threshold = 10
        assert stock.is_low_stock is True

    def test_is_low_stock_above_threshold(self):
        stock = WarehouseStock()
        stock.quantity = 50
        stock.reserved = 0
        stock.low_stock_threshold = 10
        assert stock.is_low_stock is False

    def test_is_out_of_stock_when_all_reserved(self):
        stock = WarehouseStock()
        stock.quantity = 5
        stock.reserved = 5
        assert stock.is_out_of_stock is True

    def test_is_not_out_of_stock_when_available(self):
        stock = WarehouseStock()
        stock.quantity = 5
        stock.reserved = 3
        assert stock.is_out_of_stock is False


class TestOrderStatus:
    def test_all_statuses_defined(self):
        expected = [
            "PENDING",
            "CONFIRMED",
            "PROCESSING",
            "SHIPPED",
            "DELIVERED",
            "COMPLETED",
            "CANCELLED",
            "REFUNDED",
            "PARTIALLY_REFUNDED",
        ]
        actual = [status.value for status in OrderStatus]
        for status_value in expected:
            assert status_value in actual


class TestStockBlockStatus:
    def test_all_statuses_defined(self):
        expected = ["ACTIVE", "COMMITTED", "RELEASED", "EXPIRED"]
        actual = [status.value for status in StockBlockStatus]
        for status_value in expected:
            assert status_value in actual


class TestProductToDict:
    def test_to_dict_returns_expected_keys(self):
        product = Product()
        product.id = uuid4()
        product.name = "Test Product"
        product.slug = "test-product"
        product.description = "A test product"
        product.sku = "TEST-001"
        product.price = 29.99
        product.is_active = True
        product.has_variants = False
        product.weight = None
        product.dimensions = {}
        product.tax_class = "standard"
        product.images = []
        product.variants = []
        product.created_at = None
        product.updated_at = None

        result = product.to_dict()

        assert result["name"] == "Test Product"
        assert result["slug"] == "test-product"
        assert result["sku"] == "TEST-001"
        assert result["is_active"] is True
        assert result["variants"] == []
