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
    yield flask_app

    with flask_app.app_context():
        from vbwd.extensions import db as _db

        _db.engine.dispose()


@pytest.fixture
def db(app):
    """Create all shop tables, yield the db handle, drop all after the test."""
    from vbwd.extensions import db as _db

    with app.app_context():
        # Importing the package registers every shop model with SQLAlchemy
        # so create_all() builds the full set of shop_* tables.
        import plugins.shop.shop.models  # noqa: F401

        # Make setup idempotent regardless of any state a previous (possibly
        # aborted, possibly crashed) test left behind: drop leftover tables,
        # then the standalone PG ENUM types MetaData.drop_all() does NOT drop
        # (userstatus/userrole on the core User model). Left behind, the next
        # create_all fails with a duplicate pg_type error. Run the cleanup on a
        # dedicated short-lived autocommit engine that shares no transaction or
        # locks with the app's pooled connections, so it can never deadlock.
        _db.drop_all()
        _drop_leftover_enum_types()
        _db.create_all()
        yield _db
        _db.session.remove()
        _db.drop_all()


def _drop_leftover_enum_types() -> None:
    """Drop the public-schema PG ENUM types ``drop_all()`` leaves behind.

    Uses its own autocommit engine (disposed immediately) rather than the
    application's pooled engine: the cleanup then holds no long-lived lock and
    cannot deadlock with the session-scoped app's lingering connections.
    """
    from sqlalchemy import create_engine, text

    engine = create_engine(_test_db_url(), isolation_level="AUTOCOMMIT")
    try:
        with engine.connect() as connection:
            type_names = (
                connection.execute(
                    text(
                        "SELECT typname FROM pg_type "
                        "JOIN pg_namespace "
                        "ON pg_type.typnamespace = pg_namespace.oid "
                        "WHERE typtype = 'e' AND nspname = 'public'"
                    )
                )
                .scalars()
                .all()
            )
            for type_name in type_names:
                connection.execute(text(f'DROP TYPE IF EXISTS "{type_name}" CASCADE'))
    finally:
        engine.dispose()
