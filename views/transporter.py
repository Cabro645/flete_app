from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from cargo import fit_check, reference_price
from db import get_db
from models import (OFFER_ACCEPTED, OFFER_PENDING, OFFER_WITHDRAWN, SHIP_ASSIGNED, SHIP_DELIVERED, SHIP_SEARCHING,
                    Offer, Shipment, User)
from security import login_required
from utils import FormError, clean, num

bp = Blueprint("transporter", __name__, url_prefix="/transporter")


@bp.get("")
@login_required("transporter")
def dashboard():
    db, cfg, vehicle = get_db(), current_app.config, g.user.primary_vehicle
    show_all = request.args.get("all") == "1"

    my_offers = db.scalars(
        select(Offer).where(Offer.transporter_id == g.user.id)
        .options(joinedload(Offer.shipment).joinedload(Shipment.client)).order_by(Offer.updated_at.desc())
    ).unique().all()
    offer_by_shipment = {o.shipment_id: o for o in my_offers}

    my_movements = db.scalars(
        select(TransporterMovement).where(TransporterMovement.transporter_id == g.user.id)
        .order_by(TransporterMovement.created_at.desc())
    ).all()

    open_shipments = db.scalars(
        select(Shipment).join(User, Shipment.client_id == User.id)
        .where(Shipment.status == SHIP_SEARCHING, Shipment.archived.is_(False), User.is_active.is_(True))
        .options(joinedload(Shipment.client)).order_by(Shipment.created_at.desc()).limit(200)
    ).unique().all()

    cards, hidden = [], 0
    for s in open_shipments:
        fit = (fit_check(s.unit_length, s.unit_width, s.unit_height, s.unit_weight_kg, s.quantity, vehicle)
               if vehicle else None)
        if vehicle and not fit.ok and not show_all and s.id not in offer_by_shipment:
            hidden += 1
            continue
        ref = (reference_price(s.distance_km, vehicle.rate_per_km, s.total_volume_m3, vehicle.volume_m3,
                               s.is_shared, cfg["MIN_FARE_ARS"]) if vehicle and vehicle.rate_per_km else None)
        cards.append({"s": s, "fit": fit, "ref": ref, "mine": offer_by_shipment.get(s.id)})

    return render_template("transporter_dashboard.html", cards=cards, hidden=hidden, show_all=show_all,
                           my_offers=my_offers, vehicle=vehicle, my_movements=my_movements)


@bp.post("/offers")
@login_required("transporter")
def send_offer():
    db, cfg, vehicle = get_db(), current_app.config, g.user.primary_vehicle
    back = redirect(url_for("transporter.dashboard"))
    try:
        shipment_id = int(request.form.get("shipment_id", ""))
        price = num(request.form.get("price"), "Precio", 1, 100_000_000, integer=True)
    except FormError as exc:
        flash(str(exc), "danger")
        return back
    except ValueError:
        flash("Envío inválido.", "danger")
        return back
    message = clean(request.form.get("message"), 500) or None

    shipment = db.get(Shipment, shipment_id)
    if shipment is None or shipment.status != SHIP_SEARCHING or shipment.archived:
        flash("Ese envío ya no recibe ofertas.", "warning")
        return back
    if cfg["REQUIRE_VERIFIED_TRANSPORTERS"] and not g.user.is_verified:
        flash("Para ofertar necesitás tener tu DNI y licencia verificados. Cargalos en tu perfil.", "warning")
        return back
    if vehicle is None:
        flash("Cargá los datos de tu vehículo en el perfil antes de ofertar.", "warning")
        return back
    fit = fit_check(shipment.unit_length, shipment.unit_width, shipment.unit_height,
                    shipment.unit_weight_kg, shipment.quantity, vehicle)
    if not fit.ok:
        flash(f"No podés ofertar por esta carga: {fit.reason}", "danger")
        return back

    existing = db.scalar(select(Offer).where(Offer.shipment_id == shipment.id, Offer.transporter_id == g.user.id))
    if existing and existing.status not in {OFFER_PENDING, OFFER_WITHDRAWN}:
        flash("Tu oferta para este envío ya fue resuelta.", "warning")
        return back
    if existing:
        existing.price, existing.message, existing.status = price, message, OFFER_PENDING
        flash("Actualizaste tu oferta.", "success")
    else:
        db.add(Offer(shipment_id=shipment.id, transporter_id=g.user.id, price=price, message=message))
        flash("Oferta enviada. Vas a ver la respuesta del cliente en «Mis ofertas».", "success")
    db.commit()
    return back


def _own_offer(offer_id: int) -> Offer:
    offer = get_db().get(Offer, offer_id)
    if offer is None or offer.transporter_id != g.user.id:
        abort(404)
    return offer


@bp.post("/offers/<int:offer_id>/withdraw")
@login_required("transporter")
def withdraw(offer_id: int):
    offer = _own_offer(offer_id)
    if offer.status == OFFER_PENDING:
        offer.status = OFFER_WITHDRAWN
        get_db().commit()
        flash("Retiraste tu oferta.", "info")
    return redirect(url_for("transporter.dashboard"))


@bp.post("/offers/<int:offer_id>/delivered")
@login_required("transporter")
def delivered(offer_id: int):
    offer = _own_offer(offer_id)
    if offer.status == OFFER_ACCEPTED and offer.shipment.status == SHIP_ASSIGNED:
        offer.shipment.status = SHIP_DELIVERED
        get_db().commit()
        flash("Marcaste el envío como entregado.", "success")
    return redirect(url_for("transporter.dashboard"))

from models import TransporterMovement

@bp.get("/movements/new")
@login_required("transporter")
def new_movement_form():
    return render_template("publish_movement.html")

@bp.post("/movements/new")
@login_required("transporter")
def create_movement():
    db = get_db()
    f = request.form
    origin = clean(f.get("origin"), 150)
    destination = clean(f.get("destination"), 150)
    vehicle_type = clean(f.get("vehicle_type"), 50)
    available_space = clean(f.get("available_space"), 150)
    description = clean(f.get("description"), 500)

    if not origin or not destination or not vehicle_type or not available_space:
        flash("Completá los campos obligatorios del trayecto.", "danger")
        return redirect(url_for("transporter.new_movement_form"))

    db.add(TransporterMovement(
        transporter_id=g.user.id,
        origin=origin,
        destination=destination,
        vehicle_type=vehicle_type,
        available_space=available_space,
        description=description or None
    ))
    db.commit()
    flash("¡Trayecto publicado con éxito en el feed principal!", "success")
    return redirect(url_for("transporter.dashboard"))

@bp.post("/movements/<int:mov_id>/cancel")
@login_required("transporter")
def cancel_movement(mov_id: int):
    db = get_db()
    mov = db.get(TransporterMovement, mov_id)
    if mov and mov.transporter_id == g.user.id:
        mov.status = "cancelado"
        db.commit()
        flash("Trayecto cancelado.", "info")
    return redirect(url_for("transporter.dashboard"))
