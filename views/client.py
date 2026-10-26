from datetime import timedelta

from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from cargo import estimate_road_km
from catalog import CATALOGO_PLANO, MODULOS_CATALOGO
from db import get_db
from models import (OFFER_ACCEPTED, OFFER_CANCELLED, OFFER_PENDING, OFFER_REJECTED, SHIP_ASSIGNED, SHIP_CANCELLED,
                    SHIP_DELIVERED, SHIP_SEARCHING, Offer, Shipment, User)
from security import login_required
from utils import FormError, clean, parse_date, today_ar, try_num

bp = Blueprint("client", __name__, url_prefix="/client")

# Bariloche → El Bolsón como punto de partida del mapa (igual que la versión original).
DEFAULT_COORDS = {"orig_lat": -41.1334, "orig_lon": -71.3103, "dest_lat": -41.9676, "dest_lon": -71.5401}


def _coords_from(form) -> dict:
    out = {}
    for key, default in DEFAULT_COORDS.items():
        try:
            out[key] = float(form.get(key, default))
        except (TypeError, ValueError):
            out[key] = default
    return out


def _render_dashboard(form=None, status=200):
    db, form = get_db(), form or {}
    base = (select(Shipment).where(Shipment.client_id == g.user.id)
            .options(selectinload(Shipment.offers).selectinload(Offer.transporter).selectinload(User.vehicles))
            .order_by(Shipment.created_at.desc()))
    shipments = db.scalars(base.where(Shipment.archived.is_(False))).all()
    archived = db.scalars(base.where(Shipment.archived.is_(True)).limit(50)).all()
    return render_template("client_dashboard.html", modulos=MODULOS_CATALOGO, shipments=shipments, archived=archived,
                           form=form, today=today_ar().isoformat(), **_coords_from(form)), status


@bp.get("")
@login_required("client")
def dashboard():
    return _render_dashboard()


@bp.post("/shipments")
@login_required("client")
def publish():
    f, errors = request.form, []

    # 1) Qué se transporta
    choice = f.get("item_select")
    if choice == "custom":
        item_name = clean(f.get("custom_name"), 100)
        if len(item_name) < 2:
            errors.append("Describí qué querés enviar (nombre del objeto).")
        length = try_num(errors, f.get("custom_length"), "Largo", 1, 1500)
        width = try_num(errors, f.get("custom_width"), "Ancho", 1, 1500)
        height = try_num(errors, f.get("custom_height"), "Alto", 1, 1500)
        weight = try_num(errors, f.get("custom_weight"), "Peso", 0.1, 50000)
    elif choice in CATALOGO_PLANO:
        it = CATALOGO_PLANO[choice]
        item_name, length, width, height, weight = it["name"], it["length"], it["width"], it["height"], it["weight"]
    else:
        item_name = length = width = height = weight = None
        errors.append("Elegí qué querés enviar.")
    quantity = try_num(errors, f.get("quantity", 1), "Cantidad", 1, 20, integer=True)

    # 2) Ruta
    coords = {}
    for key, label, lo, hi in (("orig_lat", "Latitud de retiro", -56, -21), ("orig_lon", "Longitud de retiro", -74, -53),
                               ("dest_lat", "Latitud de entrega", -56, -21), ("dest_lon", "Longitud de entrega", -74, -53)):
        coords[key] = try_num(errors, f.get(key), label, lo, hi)
    orig_address, dest_address = clean(f.get("orig_address"), 200), clean(f.get("dest_address"), 200)
    if len(orig_address) < 3:
        errors.append("Indicá la dirección o el lugar de retiro.")
    if len(dest_address) < 3:
        errors.append("Indicá la dirección o el lugar de entrega.")

    distance = None
    if all(v is not None for v in coords.values()):
        distance = estimate_road_km(coords["orig_lat"], coords["orig_lon"], coords["dest_lat"], coords["dest_lon"],
                                    current_app.config["ROAD_FACTOR"])
        if distance < 0.3:
            errors.append("El retiro y la entrega están en el mismo lugar. Revisá los puntos del mapa.")

    # 3) Fecha, modalidad, notas
    pickup = None
    try:
        pickup = parse_date(f.get("pickup_date"))
        if pickup and not today_ar() <= pickup <= today_ar() + timedelta(days=365):
            errors.append("La fecha de retiro tiene que ser entre hoy y dentro de un año.")
    except FormError as exc:
        errors.append(str(exc))
    if f.get("modality") not in {"shared", "exclusive"}:
        errors.append("Elegí la modalidad: compartido o exclusivo.")
    notes = (f.get("notes") or "").strip()[:500] or None

    if errors:
        for e in errors:
            flash(e, "danger")
        return _render_dashboard(f, 400)

    db = get_db()
    db.add(Shipment(
        client_id=g.user.id, item_name=item_name, quantity=quantity,
        unit_length=length, unit_width=width, unit_height=height, unit_weight_kg=weight,
        orig_address=orig_address, dest_address=dest_address, distance_km=distance, **coords,
        pickup_date=pickup, notes=notes, is_shared=f.get("modality") == "shared",
    ))
    db.commit()
    flash(f"Envío publicado: {quantity}× {item_name}, unos {distance:g} km. Los fleteros ya pueden ofertar.", "success")
    return redirect(url_for("client.dashboard"))


def _own_shipment(shipment_id: int) -> Shipment:
    s = get_db().get(Shipment, shipment_id)
    if s is None or s.client_id != g.user.id:
        abort(404)
    return s


@bp.post("/offers/<int:offer_id>/accept")
@login_required("client")
def accept_offer(offer_id: int):
    db = get_db()
    offer = db.get(Offer, offer_id)
    if offer is None or offer.shipment.client_id != g.user.id:
        abort(404)
    shipment = offer.shipment
    if shipment.status != SHIP_SEARCHING or offer.status != OFFER_PENDING:
        flash("Esa oferta ya no está disponible.", "warning")
        return redirect(url_for("client.dashboard"))
    if not offer.transporter.is_active:
        flash("Ese fletero ya no está disponible.", "warning")
        return redirect(url_for("client.dashboard"))

    offer.status = OFFER_ACCEPTED
    for other in shipment.offers:
        if other.id != offer.id and other.status == OFFER_PENDING:
            other.status = OFFER_REJECTED
    shipment.status = SHIP_ASSIGNED
    db.commit()
    flash(f"Aceptaste la oferta de {offer.transporter.name}. Coordiná los detalles por WhatsApp.", "success")
    return redirect(url_for("client.dashboard"))


@bp.post("/shipments/<int:shipment_id>/delivered")
@login_required("client")
def mark_delivered(shipment_id: int):
    s = _own_shipment(shipment_id)
    if s.status == SHIP_ASSIGNED:
        s.status = SHIP_DELIVERED
        get_db().commit()
        flash("¡Listo! Marcaste el envío como recibido.", "success")
    return redirect(url_for("client.dashboard"))


@bp.post("/shipments/<int:shipment_id>/cancel")
@login_required("client")
def cancel(shipment_id: int):
    s = _own_shipment(shipment_id)
    if s.status in {SHIP_SEARCHING, SHIP_ASSIGNED}:
        for o in s.offers:
            if o.status == OFFER_PENDING:
                o.status = OFFER_REJECTED
            elif o.status == OFFER_ACCEPTED:
                o.status = OFFER_CANCELLED
        s.status = SHIP_CANCELLED
        get_db().commit()
        flash("Envío cancelado.", "info")
    return redirect(url_for("client.dashboard"))


@bp.post("/shipments/<int:shipment_id>/archive")
@login_required("client")
def archive(shipment_id: int):
    s = _own_shipment(shipment_id)
    if s.status in {SHIP_DELIVERED, SHIP_CANCELLED}:
        s.archived = True
        get_db().commit()
        flash("Envío archivado. Lo encontrás en el historial.", "info")
    return redirect(url_for("client.dashboard"))
