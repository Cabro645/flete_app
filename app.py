"""FleteApp Patagonia — fábrica de la aplicación Flask.

Desarrollo:   flask --app app run --debug        (o: python app.py)
Producción:   gunicorn wsgi:app
"""
import os
import secrets
from pathlib import Path

import click
from flask import Flask, render_template
from sqlalchemy import select
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash

from config import Config
from db import get_db, init_db
from models import OFFER_STATUS, ROLE_ADMIN, SHIPMENT_STATUS, User
from security import init_security
from utils import ars, clean, localdate, localdt, valid_email, whatsapp_number

ERROR_MESSAGES = {
    400: "La sesión expiró o el formulario no es válido. Volvé a intentarlo.",
    403: "No tenés permiso para ver esta página.",
    404: "No encontramos lo que buscás.",
    413: "El archivo es demasiado grande.",
    429: "Demasiadas solicitudes. Esperá un momento.",
}


def _persistent_secret(app: Flask) -> str:
    """Sin SECRET_KEY en el entorno, genera una clave aleatoria y la guarda en instance/ (nunca en el código)."""
    path = Path(app.instance_path) / "secret_key"
    if not path.exists():
        path.write_text(secrets.token_hex(32))
        try:
            path.chmod(0o600)
        except OSError:
            pass
    return path.read_text().strip()


def create_app(test_config: dict | None = None) -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    app.config["SECRET_KEY"] = app.config.get("SECRET_KEY") or _persistent_secret(app)
    if app.config["TRUST_PROXY"]:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    init_db(app)
    init_security(app)

    from views import account, admin, auth, client, transporter
    for module in (auth, client, transporter, account, admin):
        app.register_blueprint(module.bp)

    app.jinja_env.filters.update(ars=ars, localdt=localdt, localdate=localdate, wa=whatsapp_number)
    app.jinja_env.globals.update(SHIPMENT_STATUS=SHIPMENT_STATUS, OFFER_STATUS=OFFER_STATUS)

    @app.errorhandler(HTTPException)
    def http_error(err):
        code = err.code or 500
        message = ERROR_MESSAGES.get(code, "Algo salió mal de nuestro lado. Probá de nuevo en unos minutos.")
        return render_template("error.html", code=code, message=message), code

    register_cli(app)
    return app


def register_cli(app: Flask) -> None:
    @app.cli.command("create-admin")
    @click.option("--email", prompt=True)
    @click.option("--name", prompt=True)
    @click.password_option()
    def create_admin(email, name, password):
        """Crea un usuario administrador."""
        email = clean(email, 120).lower()
        if not valid_email(email) or len(password) < 8:
            raise click.ClickException("Email inválido o contraseña de menos de 8 caracteres.")
        db = get_db()
        if db.scalar(select(User.id).where(User.email == email)):
            raise click.ClickException("Ese email ya existe.")
        db.add(User(name=clean(name, 100), email=email, password_hash=generate_password_hash(password), role=ROLE_ADMIN))
        db.commit()
        click.echo(f"Administrador {email} creado.")

    @app.cli.command("set-password")
    @click.option("--email", prompt=True)
    @click.password_option()
    def set_password(email, password):
        """Restablece la contraseña de un usuario (útil mientras no haya recuperación por email)."""
        user = get_db().scalar(select(User).where(User.email == clean(email, 120).lower()))
        if user is None or len(password) < 8:
            raise click.ClickException("No existe ese usuario o la contraseña tiene menos de 8 caracteres.")
        user.password_hash = generate_password_hash(password)
        get_db().commit()
        click.echo("Contraseña actualizada.")


if __name__ == "__main__":
    create_app().run(debug=os.environ.get("FLASK_DEBUG") == "1")
