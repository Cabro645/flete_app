"""Configuración central. Todo lo sensible viene de variables de entorno (ver .env.example)."""
import os
from datetime import timedelta

try:  # python-dotenv es opcional: si está instalado, carga el archivo .env
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


class Config:
    # Si SECRET_KEY no está definida, app.py genera una clave aleatoria y la guarda en instance/.
    SECRET_KEY = os.environ.get("SECRET_KEY")

    # SQLite por defecto (instance/flete_app.db). Para Postgres: postgresql://user:pass@host/db
    DATABASE_URL = os.environ.get("DATABASE_URL")

    # Sesiones / cookies
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE")  # poné 1 cuando uses HTTPS
    PERMANENT_SESSION_LIFETIME = timedelta(days=14)

    # Detrás de nginx / Render / Railway / Fly: poné 1 para leer la IP y el esquema reales.
    TRUST_PROXY = _bool("TRUST_PROXY")

    # Subidas (DNI / licencia)
    MAX_CONTENT_LENGTH = 12 * 1024 * 1024        # tope de todo el request
    MAX_UPLOAD_BYTES = 5 * 1024 * 1024           # tope por archivo

    # Negocio
    REQUIRE_VERIFIED_TRANSPORTERS = _bool("REQUIRE_VERIFIED_TRANSPORTERS")
    ROAD_FACTOR = float(os.environ.get("ROAD_FACTOR", "1.25"))   # km de ruta ≈ línea recta × factor
    MIN_FARE_ARS = int(os.environ.get("MIN_FARE_ARS", "10000"))  # piso del precio de referencia

    # Anti fuerza bruta en el login (por IP + email, en memoria)
    LOGIN_MAX_ATTEMPTS = int(os.environ.get("LOGIN_MAX_ATTEMPTS", "5"))
    LOGIN_WINDOW_SECONDS = int(os.environ.get("LOGIN_WINDOW_SECONDS", "600"))
