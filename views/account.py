from flask import Blueprint, abort, flash, g, redirect, render_template, request, send_from_directory, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from db import get_db
from models import ROLE_ADMIN, ROLE_TRANSPORTER, VERIF_NONE, VERIF_PENDING, User, Vehicle
from security import DOC_MIMETYPES, UploadError, delete_document, login_required, save_document, uploads_dir
from utils import FormError, clean, num, whatsapp_number

bp = Blueprint("account", __name__)


@bp.get("/profile")
@login_required()
def profile():
    return render_template("profile.html", user=g.user, form={})


@bp.post("/profile")
@login_required()
def update_profile():
    user, db = g.user, get_db()
    f, errors = request.form, []

    name = clean(f.get("name"), 100)
    phone = clean(f.get("phone"), 30)
    dni = clean(f.get("dni"), 20) or None
    address = clean(f.get("address"), 200) or None
    license_number = clean(f.get("license_number"), 50) or None if user.role == ROLE_TRANSPORTER else user.license_number

    if len(name) < 2:
        errors.append("Ingresá tu nombre.")
    if user.role != ROLE_ADMIN and not whatsapp_number(phone):
        errors.append("Ingresá un WhatsApp válido con código de área, por ejemplo 2944 123456.")

    # Archivos: se validan por contenido. Si algo falla, se descartan los que ya se hayan guardado.
    new_files, old_files = {}, []
    uploads = [("dni_file", "dni_file", "dni")]
    if user.role == ROLE_TRANSPORTER:
        uploads.append(("license_file", "license_file", "license"))
    for field, attr, kind in uploads:
        storage = request.files.get(field)
        if storage and storage.filename:
            try:
                new_files[attr] = save_document(storage, user.id, kind)
            except UploadError as exc:
                errors.append(f"{'DNI' if kind == 'dni' else 'Licencia'}: {exc}")

    if errors:
        for stored in new_files.values():
            delete_document(stored)
        for e in errors:
            flash(e, "danger")
        return render_template("profile.html", user=user, form=f), 400

    docs_changed = bool(new_files) or dni != user.dni or license_number != user.license_number
    for attr, stored in new_files.items():
        old_files.append(getattr(user, attr))
        setattr(user, attr, stored)
    user.name, user.phone, user.dni, user.address, user.license_number = name, phone or None, dni, address, license_number

    if docs_changed and user.role != ROLE_ADMIN:
        # Cualquier cambio en la documentación vuelve a revisión (incluso si ya estaba verificada).
        user.verification_status = VERIF_PENDING if user.docs_complete else VERIF_NONE
        user.verification_note = None
    db.commit()
    for old in old_files:
        delete_document(old)

    if docs_changed and user.verification_status == VERIF_PENDING:
        flash("Datos guardados. Tu documentación quedó en revisión.", "success")
    else:
        flash("Datos guardados.", "success")
    return redirect(url_for("account.profile"))


@bp.post("/profile/password")
@login_required()
def change_password():
    user, f = g.user, request.form
    new = f.get("new_password") or ""
    if not check_password_hash(user.password_hash, f.get("current_password") or ""):
        flash("La contraseña actual no es correcta.", "danger")
    elif not 8 <= len(new) <= 128:
        flash("La nueva contraseña tiene que tener entre 8 y 128 caracteres.", "danger")
    elif new != f.get("confirm_password"):
        flash("Las contraseñas nuevas no coinciden.", "danger")
    else:
        user.password_hash = generate_password_hash(new)
        get_db().commit()
        flash("Cambiaste tu contraseña.", "success")
    return redirect(url_for("account.profile"))


@bp.post("/profile/vehicle")
@login_required("transporter")
def update_vehicle():
    user, f, errors = g.user, request.form, []
    name = clean(f.get("vehicle_name"), 80)
    if len(name) < 2:
        errors.append("Ponele un nombre al vehículo (ej. Kangoo 2018).")
    values = {}
    for key, label, lo, hi in (("length", "Largo de caja", 20, 2000), ("width", "Ancho de caja", 20, 400),
                               ("height", "Alto de caja", 20, 400), ("max_weight_kg", "Capacidad de carga", 10, 40000)):
        try:
            values[key] = num(f.get(key), label, lo, hi)
        except FormError as exc:
            errors.append(str(exc))
    try:
        rate = num(f.get("rate_per_km"), "Tarifa por km", 0, 100000, integer=True)
    except FormError as exc:
        errors.append(str(exc))
    if errors:
        for e in errors:
            flash(e, "danger")
        return redirect(url_for("account.profile"))

    vehicle = user.primary_vehicle
    if vehicle is None:
        vehicle = Vehicle(owner_id=user.id)
        get_db().add(vehicle)
    vehicle.name, vehicle.rate_per_km = name, rate
    for key, value in values.items():
        setattr(vehicle, key, value)
    get_db().commit()
    flash("Actualizaste tu vehículo.", "success")
    return redirect(url_for("account.profile"))


@bp.get("/documents/<int:user_id>/<kind>")
@login_required()
def document(user_id: int, kind: str):
    """Los documentos solo los ve su dueño o un admin. Se responde 404 (no 403) para no revelar que existen."""
    if kind not in {"dni", "license"} or (g.user.id != user_id and g.user.role != ROLE_ADMIN):
        abort(404)
    owner = get_db().get(User, user_id)
    stored = None if owner is None else (owner.dni_file if kind == "dni" else owner.license_file)
    if not stored:
        abort(404)
    return send_from_directory(uploads_dir(), stored, mimetype=DOC_MIMETYPES[stored.rsplit(".", 1)[1]])
