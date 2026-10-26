from flask import Blueprint, flash, g, redirect, render_template, request, session, url_for
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from werkzeug.security import check_password_hash, generate_password_hash

from catalog import VEHICULOS_DEFAULT
from db import get_db
from models import ROLE_CLIENT, ROLE_TRANSPORTER, User, Vehicle
from security import clear_failures, home_for, is_throttled, login_required, register_failure, start_session
from utils import clean, valid_email, whatsapp_number

bp = Blueprint("auth", __name__)


def _login_page(status=200, **ctx):
    ctx.setdefault("active_tab", "login")
    ctx.setdefault("form", {})
    return render_template("login.html", **ctx), status


@bp.get("/")
def index():
    if g.user:
        return redirect(home_for(g.user))
    return _login_page()


@bp.post("/login")
def login():
    email = clean(request.form.get("email"), 120).lower()
    password = request.form.get("password") or ""
    key = f"{request.remote_addr}|{email}"

    if is_throttled(key):
        return _login_page(429, errors=["Demasiados intentos fallidos. Esperá unos minutos y volvé a probar."])

    user = get_db().scalar(select(User).where(User.email == email))
    if user and check_password_hash(user.password_hash, password):
        if not user.is_active:
            return _login_page(403, errors=["Tu cuenta está suspendida. Escribinos para resolverlo."])
        clear_failures(key)
        start_session(user)
        return redirect(home_for(user))

    register_failure(key)
    return _login_page(401, errors=["Email o contraseña incorrectos."], form=request.form)


def _register(role: str):
    db, f = get_db(), request.form
    tab = "reg-client" if role == ROLE_CLIENT else "reg-trans"
    name, email = clean(f.get("name"), 100), clean(f.get("email"), 120).lower()
    password, phone = f.get("password") or "", clean(f.get("phone"), 30)
    vehicle_type = f.get("vehicle_type")

    errors = []
    if len(name) < 2:
        errors.append("Ingresá tu nombre.")
    if not valid_email(email):
        errors.append("El email no es válido.")
    if not 8 <= len(password) <= 128:
        errors.append("La contraseña tiene que tener entre 8 y 128 caracteres.")
    if not whatsapp_number(phone):
        errors.append("Ingresá un WhatsApp válido con código de área, por ejemplo 2944 123456.")
    if role == ROLE_TRANSPORTER and vehicle_type not in VEHICULOS_DEFAULT:
        errors.append("Elegí un tipo de vehículo.")
    if not errors and db.scalar(select(User.id).where(User.email == email)):
        errors.append("Ese email ya está registrado. Probá ingresar.")
    if errors:
        return _login_page(400, errors=errors, active_tab=tab, form=f)

    user = User(name=name, email=email, password_hash=generate_password_hash(password), phone=phone, role=role)
    db.add(user)
    try:
        db.flush()
        if role == ROLE_TRANSPORTER:
            spec = VEHICULOS_DEFAULT[vehicle_type]
            db.add(Vehicle(owner_id=user.id, name=spec["name"], length=spec["length"], width=spec["width"],
                           height=spec["height"], max_weight_kg=spec["max_weight"], rate_per_km=spec["tarifa_km"]))
        db.commit()
    except IntegrityError:  # dos registros simultáneos con el mismo email
        db.rollback()
        return _login_page(400, errors=["Ese email ya está registrado. Probá ingresar."], active_tab=tab, form=f)

    start_session(user)
    if role == ROLE_TRANSPORTER:
        flash("¡Cuenta creada! Revisá los datos de tu vehículo y cargá tu DNI y licencia para que te verifiquemos.", "success")
        return redirect(url_for("account.profile"))
    flash("¡Cuenta creada! Ya podés publicar tu primer envío.", "success")
    return redirect(url_for("client.dashboard"))


@bp.post("/register/client")
def register_client():
    return _register(ROLE_CLIENT)


@bp.post("/register/transporter")
def register_transporter():
    return _register(ROLE_TRANSPORTER)


@bp.post("/logout")
@login_required()
def logout():
    session.clear()
    return redirect(url_for("auth.index"))

import secrets
from datetime import timedelta
from utils import utcnow

@bp.get("/forgot-password")
def forgot_password_form():
    return render_template("forgot_password.html")

@bp.post("/forgot-password")
def forgot_password():
    db = get_db()
    email = clean(request.form.get("email"), 120).lower()
    user = db.scalar(select(User).where(User.email == email))
    if user:
        token = secrets.token_urlsafe(32)
        user.reset_token = token
        user.reset_token_expiry = utcnow() + timedelta(hours=2)
        db.commit()
        reset_link = url_for('auth.reset_password', token=token, _external=True)
        flash(f"Se generó el enlace de recuperación para {email}. En producción se enviaría por email o WhatsApp: {reset_link}", "success")
    else:
        flash("Si el email existe en el sistema, recibirás las instrucciones.", "info")
    return redirect(url_for("auth.index"))

@bp.get("/reset-password/<token>")
def reset_password_form(token):
    db = get_db()
    user = db.scalar(select(User).where(User.reset_token == token))
    if not user or not user.reset_token_expiry or user.reset_token_expiry < utcnow():
        flash("El enlace de recuperación es inválido o expiró.", "danger")
        return redirect(url_for("auth.index"))
    return render_template("reset_password.html", token=token)

@bp.post("/reset-password/<token>")
def reset_password(token):
    db = get_db()
    user = db.scalar(select(User).where(User.reset_token == token))
    if not user or not user.reset_token_expiry or user.reset_token_expiry < utcnow():
        flash("El enlace de recuperación es inválido o expiró.", "danger")
        return redirect(url_for("auth.index"))
    
    password = request.form.get("password") or ""
    if len(password) < 8:
        flash("La nueva contraseña debe tener al menos 8 caracteres.", "danger")
        return render_template("reset_password.html", token=token)
    
    user.password_hash = generate_password_hash(password)
    user.reset_token = None
    user.reset_token_expiry = None
    db.commit()
    flash("Contraseña restablecida con éxito. Ya podés ingresar.", "success")
    return redirect(url_for("auth.index"))
