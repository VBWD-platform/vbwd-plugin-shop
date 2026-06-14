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

    # Build the full schema exactly ONCE for the whole session, resetting the
    # public schema first (clearing any table or ENUM type left by a prior
    # crashed run or a sibling suite sharing this ``*_test`` DB). A per-test
    # create_all()/drop_all() strands standalone PG ENUM types and races other
    # suites on the shared catalog — see vbwd/testing/integration_db.py. Each
    # test then isolates by TRUNCATE-ing data, not by dropping the schema.
    with flask_app.app_context():
        from vbwd.extensions import db as _db
        from vbwd.testing.integration_db import reset_schema_and_create_all

        # Importing the package registers every shop model with SQLAlchemy so
        # the one-time create_all() builds the full set of shop_* tables.
        import plugins.shop.shop.models  # noqa: F401

        reset_schema_and_create_all(_db)

    yield flask_app

    with flask_app.app_context():
        from vbwd.extensions import db as _db

        _db.engine.dispose()


@pytest.fixture
def db(app):
    """Isolate each test by TRUNCATE-ing data; the schema is built once per
    session in the ``app`` fixture."""
    from vbwd.extensions import db as _db

    with app.app_context():
        from vbwd.testing.integration_db import truncate_all_tables

        truncate_all_tables(_db)
        # S85.2: shop pricing goes through the core PriceFactory, which reads
        # the default currency from the catalog (truncated above) — re-seed it.
        _seed_default_currency(_db)
        yield _db
        _db.session.remove()


def _seed_default_currency(_db) -> None:
    """Seed the baseline EUR currency so the ``PriceFactory`` resolves a code.

    S85.2: shop pricing now goes through the core ``PriceFactory``, which reads
    the default currency from the catalog (S84). Plugin integration tests build
    a fresh empty schema, so the baseline row must be seeded — through the model,
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
