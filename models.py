"""Modelos de datos (SQLAlchemy 2.0)."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    """UTC "naive": SQLite no guarda zona horaria, así que guardamos siempre UTC."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


# --- Constantes de estado -------------------------------------------------------------
ROLE_CLIENT, ROLE_TRANSPORTER, ROLE_ADMIN = "client", "transporter", "admin"

VERIF_NONE, VERIF_PENDING, VERIF_OK, VERIF_REJECTED = "unverified", "pending", "verified", "rejected"

SHIP_SEARCHING, SHIP_ASSIGNED, SHIP_DELIVERED, SHIP_CANCELLED = "searching", "assigned", "delivered", "cancelled"

OFFER_PENDING, OFFER_ACCEPTED, OFFER_REJECTED, OFFER_WITHDRAWN, OFFER_CANCELLED = (
    "pending", "accepted", "rejected", "withdrawn", "cancelled",
)

# (texto, color Bootstrap)
SHIPMENT_STATUS = {
    SHIP_SEARCHING: ("Buscando fletero", "primary"),
    SHIP_ASSIGNED: ("Fletero asignado", "success"),
    SHIP_DELIVERED: ("Entregado", "secondary"),
    SHIP_CANCELLED: ("Cancelado", "danger"),
}
OFFER_STATUS = {
    OFFER_PENDING: ("Pendiente", "warning"),
    OFFER_ACCEPTED: ("Aceptada", "success"),
    OFFER_REJECTED: ("Rechazada", "secondary"),
    OFFER_WITHDRAWN: ("Retirada", "secondary"),
    OFFER_CANCELLED: ("Cancelada", "danger"),
}


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    phone: Mapped[Optional[str]] = mapped_column(String(30))
    role: Mapped[str] = mapped_column(String(20))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    dni: Mapped[Optional[str]] = mapped_column(String(20))
    address: Mapped[Optional[str]] = mapped_column(String(200))
    license_number: Mapped[Optional[str]] = mapped_column(String(50))
    dni_file: Mapped[Optional[str]] = mapped_column(String(200))
    license_file: Mapped[Optional[str]] = mapped_column(String(200))

    verification_status: Mapped[str] = mapped_column(String(20), default=VERIF_NONE)
    verification_note: Mapped[Optional[str]] = mapped_column(String(300))
    reset_token: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    reset_token_expiry: Mapped[Optional[datetime]] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    vehicles: Mapped[list["Vehicle"]] = relationship(back_populates="owner", cascade="all, delete-orphan")
    shipments: Mapped[list["Shipment"]] = relationship(back_populates="client")

    @property
    def primary_vehicle(self) -> Optional["Vehicle"]:
        return self.vehicles[0] if self.vehicles else None

    @property
    def is_verified(self) -> bool:
        return self.verification_status == VERIF_OK

    @property
    def docs_complete(self) -> bool:
        """Lo mínimo que revisa el admin: fletero = DNI + licencia; cliente = DNI."""
        base = bool(self.dni and self.dni_file)
        if self.role == ROLE_TRANSPORTER:
            return base and bool(self.license_number and self.license_file)
        return base


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(primary_key=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    length: Mapped[float] = mapped_column(Float)   # cm útiles de la caja
    width: Mapped[float] = mapped_column(Float)
    height: Mapped[float] = mapped_column(Float)
    max_weight_kg: Mapped[float] = mapped_column(Float)
    rate_per_km: Mapped[int] = mapped_column(Integer, default=0)  # ARS por km

    owner: Mapped[User] = relationship(back_populates="vehicles")

    @property
    def volume_m3(self) -> float:
        return self.length * self.width * self.height / 1_000_000


class Shipment(Base):
    __tablename__ = "shipments"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)

    item_name: Mapped[str] = mapped_column(String(100))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_length: Mapped[float] = mapped_column(Float)   # cm, de UNA unidad
    unit_width: Mapped[float] = mapped_column(Float)
    unit_height: Mapped[float] = mapped_column(Float)
    unit_weight_kg: Mapped[float] = mapped_column(Float)

    orig_address: Mapped[str] = mapped_column(String(200))
    dest_address: Mapped[str] = mapped_column(String(200))
    orig_lat: Mapped[float] = mapped_column(Float)
    orig_lon: Mapped[float] = mapped_column(Float)
    dest_lat: Mapped[float] = mapped_column(Float)
    dest_lon: Mapped[float] = mapped_column(Float)
    distance_km: Mapped[float] = mapped_column(Float)   # km de ruta ESTIMADOS

    pickup_date: Mapped[Optional[date]] = mapped_column(Date)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    is_shared: Mapped[bool] = mapped_column(Boolean, default=True)
    status: Mapped[str] = mapped_column(String(20), default=SHIP_SEARCHING, index=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    client: Mapped[User] = relationship(back_populates="shipments")
    offers: Mapped[list["Offer"]] = relationship(
        back_populates="shipment", cascade="all, delete-orphan", order_by="Offer.price"
    )

    @property
    def description(self) -> str:
        return f"{self.quantity}× {self.item_name}" if self.quantity > 1 else self.item_name

    @property
    def total_weight_kg(self) -> float:
        return self.unit_weight_kg * self.quantity

    @property
    def total_volume_m3(self) -> float:
        return self.unit_length * self.unit_width * self.unit_height * self.quantity / 1_000_000

    @property
    def accepted_offer(self) -> Optional["Offer"]:
        return next((o for o in self.offers if o.status == OFFER_ACCEPTED), None)


class Offer(Base):
    __tablename__ = "offers"
    __table_args__ = (UniqueConstraint("shipment_id", "transporter_id", name="uq_offer_shipment_transporter"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    shipment_id: Mapped[int] = mapped_column(ForeignKey("shipments.id"), index=True)
    transporter_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    price: Mapped[int] = mapped_column(Integer)          # pesos argentinos enteros
    message: Mapped[Optional[str]] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default=OFFER_PENDING)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    shipment: Mapped[Shipment] = relationship(back_populates="offers")
    transporter: Mapped[User] = relationship()



class TransporterMovement(Base):
    __tablename__ = "transporter_movements"

    id: Mapped[int] = mapped_column(primary_key=True)
    transporter_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    origin: Mapped[str] = mapped_column(String(150))
    destination: Mapped[str] = mapped_column(String(150))
    vehicle_type: Mapped[str] = mapped_column(String(50))
    available_space: Mapped[str] = mapped_column(String(150))
    description: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="activo")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    transporter: Mapped[User] = relationship()
