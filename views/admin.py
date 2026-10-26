from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for
from sqlalchemy import func, or_, select
from sqlalchemy.orm import joinedload

from db import get_db
from models import ROLE_ADMIN, VERIF_OK, VERIF_PENDING, VERIF_REJECTED, Shipment, User
from security import login_required
from utils import clean

bp = Blueprint("admin", __name__, url_prefix="/admin")


@bp.get("")
@login_required("admin")
def dashboard():
    db = get_db()
    q, role = clean(request.args.get("q"), 100).lower(), request.args.get("role", "")

    users_stmt = select(User).order_by(User.created_at.desc()).limit(200)
    if q:
        like = f"%{q}%"
        users_stmt = users_stmt.where(or_(func.lower(User.name).like(like), func.lower(User.email).like(like)))
    if role in {"client", "transporter", "admin"}:
        users_stmt = users_stmt.where(User.role == role)

    return render_template(
        "admin.html",
        users=db.scalars(users_stmt).all(),
        pending=db.scalars(select(User).where(User.verification_status == VERIF_PENDING).order_by(User.created_at)).all(),
        shipments=db.scalars(select(Shipment).options(joinedload(Shipment.client))
                             .order_by(Shipment.created_at.desc()).limit(30)).unique().all(),
        users_by_role=dict(db.execute(select(User.role, func.count()).group_by(User.role)).all()),
        shipments_by_status=dict(db.execute(select(Shipment.status, func.count()).group_by(Shipment.status)).all()),
        q=q, role=role,
    )


def _user_or_404(user_id: int) -> User:
    user = get_db().get(User, user_id)
    if user is None:
        abort(404)
    return user


@bp.post("/users/<int:user_id>/verify")
@login_required("admin")
def verify(user_id: int):
    user = _user_or_404(user_id)
    user.verification_status, user.verification_note = VERIF_OK, None
    get_db().commit()
    flash(f"Verificaste a {user.name}.", "success")
    return redirect(url_for("admin.dashboard"))


@bp.post("/users/<int:user_id>/reject")
@login_required("admin")
def reject(user_id: int):
    user = _user_or_404(user_id)
    note = clean(request.form.get("note"), 300)
    if not note:
        flash("Escribí el motivo para que la persona sepa qué corregir.", "danger")
        return redirect(url_for("admin.dashboard"))
    user.verification_status, user.verification_note = VERIF_REJECTED, note
    get_db().commit()
    flash(f"Rechazaste la documentación de {user.name}.", "info")
    return redirect(url_for("admin.dashboard"))


@bp.post("/users/<int:user_id>/toggle-active")
@login_required("admin")
def toggle_active(user_id: int):
    user = _user_or_404(user_id)
    if user.id == g.user.id or user.role == ROLE_ADMIN:
        flash("No se puede suspender a un administrador.", "warning")
    else:
        user.is_active = not user.is_active
        get_db().commit()
        flash(f"{user.name} quedó {'activo' if user.is_active else 'suspendido'}.", "success")
    return redirect(url_for("admin.dashboard"))
