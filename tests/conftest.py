"""Test fixtures for shop plugin tests.

Mirrors the pattern from plugins/cms/tests/conftest.py — session-scoped Flask app
bound to a `<dbname>_test` database, function-scoped `db` fixture that runs
create_all() / drop_all() around each test.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../..")))

os.environ["FLASK_ENV"] = "testing"
os.environ["TESTING"] = "true"


def _test_db_url() -> str:
    base = os.getenv("DATABASE_URL", "postgresql://vbwd:vbwd@postgres:5432/vbwd")
    prefix, _, dbname = base.rpartition("/")
    dbname = dbname.split("?")[0]
    return f"{prefix}/{dbname}_test"


def _ensure_test_db(url: str) -> None:
    from sqlalchemy import create_engine, text

    main_url = url.rsplit("/", 1)[0] + "/postgres"
    dbname = url.rsplit("/", 1)[1].split("?")[0]
    engine = create_engine(main_url, isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": dbname}
            ).scalar()
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{dbname}"'))
    finally:
        engine.dispose()


def _ensure_shop_enabled(flask_app) -> None:
    """Enable shop (+ its ``email`` dep) so ``on_enable`` runs and registers the
    shop entity-type / DI repos.

    A fresh per-plugin CI clone has no ``plugins.json``, so the plugin is
    discovered-but-not-enabled and its registrations never fire (the entity-type
    and tags/custom-field tests then see nothing). Idempotent — a no-op when the
    plugin is already enabled (e.g. local dev state via the shared manifest).
    """
    from vbwd.plugins.base import PluginStatus

    manager = getattr(flask_app, "plugin_manager", None)
    if manager is None:
        return
    with flask_app.app_context():
        for name in ("email", "shop"):  # dependency first
            plugin = manager.get_plugin(name)
            if plugin is None or plugin.status == PluginStatus.ENABLED:
                continue
            try:
                manager.enable_plugin(name)
            except ValueError:
                # A dependency may be absent in this environment; enable directly
                # so the plugin's own registrations still fire.
                if plugin.status == PluginStatus.INITIALIZED:
                    plugin.enable()


@pytest.fixture(scope="session")
def app():
    from vbwd.app import create_app

    url = _test_db_url()
    _ensure_test_db(url)
    test_config = {
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": url,
        "SQLALCHEMY_TRACK_MODIFICATIONS": False,
        "RATELIMIT_ENABLED": False,
        "RATELIMIT_STORAGE_URL": "memory://",
    }
    flask_app = create_app(test_config)

    # Build the schema once per process (create_all, checkfirst — never drops,
    # so it cannot wipe data) and commit baseline reference rows once. Each test
    # then isolates itself via a rolled-back transaction (no TRUNCATE, no DROP) —
    # see vbwd/testing/integration_db.py.
    with flask_app.app_context():
        from vbwd.extensions import db as _db
        from vbwd.testing.integration_db import ensure_schema_and_baseline

        # Importing the package registers every shop model with SQLAlchemy so
        # the one-time create_all() builds the full set of shop_* tables.
        import plugins.shop.shop.models  # noqa: F401

        ensure_schema_and_baseline(_db)

    _ensure_shop_enabled(flask_app)

    yield flask_app

    with flask_app.app_context():
        from vbwd.extensions import db as _db

        _db.engine.dispose()


@pytest.fixture
def db(app):
    """Isolate each test in a rolled-back transaction (self-cleaning, no wipe).

    The schema + baseline reference rows are built once in the ``app`` fixture;
    each test runs inside a transaction that is rolled back at teardown, so
    nothing it writes persists. See vbwd/testing/integration_db.py.
    """
    from vbwd.extensions import db as _db

    with app.app_context():
        from vbwd.testing.integration_db import rollback_isolation

        with rollback_isolation(_db):
            # S85.2: shop pricing goes through the core PriceFactory, which reads
            # the default currency from the catalog. Seed the baseline EUR row
            # inside the test's own transaction so the route/repository paths see
            # it on the same connection; it rolls back with the test's writes.
            _seed_default_currency(_db)
            yield _db


def _seed_default_currency(_db) -> None:
    """Seed the baseline EUR currency so the ``PriceFactory`` resolves a code.

    S85.2: shop pricing now goes through the core ``PriceFactory``, which reads
    the default currency from the catalog (S84). Plugin integration tests seed
    the baseline row inside the rolled-back transaction — through the model,
    never raw SQL.
    """
    from decimal import Decimal
    from uuid import uuid4

    from vbwd.models.currency import Currency

    if not _db.session.query(Currency).filter_by(code="EUR").first():
        _db.session.add(
            Currency(
                id=uuid4(),
                code="EUR",
                name="Euro",
                symbol="€",
                exchange_rate=Decimal("1.0"),
                decimal_places=2,
            )
        )
        _db.session.commit()
