"""Validaciones, formatos y helpers de plantillas."""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta, timezone

AR_TZ = timezone(timedelta(hours=-3))  # Argentina no tiene horario de verano: offset fijo, sin depender de tzdata


class FormError(ValueError):
    """Error de validación con un mensaje apto para mostrar a la persona."""


def clean(value, max_len: int) -> str:
    return " ".join((value or "").split())[:max_len]


def num(value, label: str, lo: float, hi: float, integer: bool = False):
    try:
        v = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        raise FormError(f"{label}: ingresá un número válido.")
    if not math.isfinite(v) or v < lo or v > hi:
        raise FormError(f"{label}: tiene que estar entre {lo:g} y {hi:g}.")
    if integer:
        if v != int(v):
            raise FormError(f"{label}: ingresá un número entero.")
        return int(v)
    return v


def try_num(errors: list, *args, **kwargs):
    """Como num(), pero acumula el error en la lista y devuelve None (para mostrar todos juntos)."""
    try:
        return num(*args, **kwargs)
    except FormError as exc:
        errors.append(str(exc))
        return None


def today_ar() -> date:
    return datetime.now(AR_TZ).date()


def parse_date(value) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise FormError("Fecha de retiro: formato inválido.")


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


def valid_email(email: str) -> bool:
    return bool(_EMAIL_RE.match(email)) and len(email) <= 120


def whatsapp_number(raw: str | None) -> str:
    """Normaliza un teléfono argentino al formato de wa.me (549 + código de área + número, sin 0 ni 15).

    '2944 15 123456' -> '5492944123456'    '+54 9 2944 123456' -> '5492944123456'
    Números de otros países con '+' se aceptan tal cual. Devuelve '' si no se puede interpretar.
    """
    raw = (raw or "").strip()
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("00"):
        digits = digits[2:]
    if raw.startswith("+") and not digits.startswith("54"):
        return digits if 8 <= len(digits) <= 15 else ""
    if digits.startswith("54"):
        digits = digits[2:]
        if digits.startswith("9"):
            digits = digits[1:]
    digits = digits.lstrip("0")
    if len(digits) == 12:  # área + 15 + abonado
        for area_len in (2, 3, 4):
            if digits[area_len:area_len + 2] == "15":
                digits = digits[:area_len] + digits[area_len + 2:]
                break
    return "549" + digits if len(digits) == 10 else ""


# --- Filtros de Jinja -----------------------------------------------------------------
def ars(value) -> str:
    try:
        return "$ " + f"{int(round(float(value))):,}".replace(",", ".")
    except (TypeError, ValueError):
        return "—"


def localdt(value, fmt: str = "%d/%m/%Y %H:%M") -> str:
    if not value:
        return ""
    return value.replace(tzinfo=timezone.utc).astimezone(AR_TZ).strftime(fmt)


def localdate(value) -> str:
    return value.strftime("%d/%m/%Y") if value else ""

def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
