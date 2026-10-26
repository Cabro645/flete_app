"""Engine + sesión por request. Reemplaza los `Session()` / `db.close()` manuales del código original
(que se olvidaban de cerrar la sesión en varios caminos y causaban DetachedInstanceError)."""
from pathlib import Path

from flask import current_app, g
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from models import Base


def init_db(app) -> None:
    url = app.config.get("DATABASE_URL")
    if not url:
        url = "sqlite:///" + (Path(app.instance_path) / "flete_app.db").as_posix()
    if url.startswith("postgres://"):  # formato viejo que todavía dan algunos hostings
        url = url.replace("postgres://", "postgresql://", 1)

    engine = create_engine(url, pool_pre_ping=True)

    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _sqlite_fk(dbapi_conn, _record):  # SQLite ignora las FK salvo que se pidan
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()

    Base.metadata.create_all(engine)
    app.extensions["engine"] = engine
    app.extensions["session_factory"] = sessionmaker(bind=engine, expire_on_commit=False)

    @app.teardown_appcontext
    def _close_db(exc):
        session = g.pop("db", None)
        if session is not None:
            if exc:
                session.rollback()
            session.close()


def get_db() -> Session:
    if "db" not in g:
        g.db = current_app.extensions["session_factory"]()
    return g.db
