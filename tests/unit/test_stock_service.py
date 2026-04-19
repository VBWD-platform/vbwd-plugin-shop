"""Unit tests for StockService — Sprint 06b."""
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from plugins.shop.shop.services.stock_service import (
    StockService,
    InsufficientStockError,
)
from plugins.shop.shop.models.stock_block import StockBlockStatus


@pytest.fixture()
def stock_repo():
    return MagicMock()


@pytest.fixture()
def block_repo():
    return MagicMock()


@pytest.fixture()
def event_bus():
    return MagicMock()


@pytest.fixture()
def service(stock_repo, block_repo, event_bus):
    return StockService(stock_repo, block_repo, event_bus)


class TestBlockStock:
    def test_block_stock_succeeds_when_sufficient(self, service, stock_repo, block_repo):
        warehouse_stock = MagicMock()
        warehouse_stock.available = 50
        warehouse_stock.reserved = 0
        warehouse_stock.warehouse_id = uuid4()
        stock_repo.find_best_warehouse.return_value = warehouse_stock

        block = service.block_stock(
            product_id=uuid4(), quantity=5, session_id="sess-123"
        )

        assert warehouse_stock.reserved == 5
        stock_repo.save.assert_called_with(warehouse_stock)
        block_repo.save.assert_called_once()

    def test_block_stock_raises_when_insufficient(self, service, stock_repo):
        stock_repo.find_best_warehouse.return_value = None
        stock_repo.get_total_available.return_value = 2

        with pytest.raises(InsufficientStockError, match="Insufficient stock"):
            service.block_stock(
                product_id=uuid4(), quantity=10, session_id="sess-456"
            )

    def test_block_stock_publishes_event(self, service, stock_repo, event_bus):
        warehouse_stock = MagicMock()
        warehouse_stock.available = 100
        warehouse_stock.reserved = 0
        warehouse_stock.warehouse_id = uuid4()
        stock_repo.find_best_warehouse.return_value = warehouse_stock

        service.block_stock(
            product_id=uuid4(), quantity=3, session_id="sess-789"
        )

        event_bus.publish.assert_called_once()
        assert event_bus.publish.call_args[0][0] == "stock.blocked"


class TestCommitStock:
    def test_commit_converts_blocks_to_permanent(self, service, block_repo, stock_repo):
        block = MagicMock()
        block.product_id = uuid4()
        block.warehouse_id = uuid4()
        block.variant_id = None
        block.quantity = 5
        block_repo.find_active_by_session.return_value = [block]

        warehouse_stock = MagicMock()
        warehouse_stock.reserved = 5
        warehouse_stock.quantity = 50
        stock_repo.find_by_product_and_warehouse.return_value = warehouse_stock

        count = service.commit_stock("sess-123")

        assert count == 1
        assert block.status == StockBlockStatus.COMMITTED
        assert warehouse_stock.reserved == 0
        assert warehouse_stock.quantity == 45

    def test_commit_returns_zero_when_no_blocks(self, service, block_repo):
        block_repo.find_active_by_session.return_value = []
        assert service.commit_stock("no-blocks") == 0


class TestReleaseStock:
    def test_release_restores_reserved(self, service, block_repo, stock_repo):
        block = MagicMock()
        block.product_id = uuid4()
        block.warehouse_id = uuid4()
        block.variant_id = None
        block.quantity = 3
        block_repo.find_active_by_session.return_value = [block]

        warehouse_stock = MagicMock()
        warehouse_stock.reserved = 3
        stock_repo.find_by_product_and_warehouse.return_value = warehouse_stock

        count = service.release_stock("sess-123")

        assert count == 1
        assert block.status == StockBlockStatus.RELEASED
        assert warehouse_stock.reserved == 0


class TestCleanupExpired:
    def test_cleanup_releases_expired_blocks(self, service, block_repo, stock_repo):
        block = MagicMock()
        block.product_id = uuid4()
        block.warehouse_id = uuid4()
        block.variant_id = None
        block.quantity = 2
        block_repo.find_expired.return_value = [block]

        warehouse_stock = MagicMock()
        warehouse_stock.reserved = 2
        stock_repo.find_by_product_and_warehouse.return_value = warehouse_stock

        count = service.cleanup_expired_blocks()

        assert count == 1
        assert block.status == StockBlockStatus.EXPIRED
        assert warehouse_stock.reserved == 0

    def test_cleanup_returns_zero_when_none_expired(self, service, block_repo):
        block_repo.find_expired.return_value = []
        assert service.cleanup_expired_blocks() == 0


class TestRestoreStock:
    def test_restore_increments_quantity(self, service, stock_repo):
        warehouse_stock = MagicMock()
        warehouse_stock.quantity = 45
        stock_repo.find_by_product_and_warehouse.return_value = warehouse_stock

        service.restore_stock(
            product_id=uuid4(),
            warehouse_id=uuid4(),
            quantity=5,
        )

        assert warehouse_stock.quantity == 50
        stock_repo.save.assert_called_with(warehouse_stock)
