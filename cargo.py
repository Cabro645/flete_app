"""Lógica de carga: ¿entra en el vehículo?, distancia y precio de referencia.

Reemplaza a tetris_logic.py (que nunca estaba conectado a la app). Mantiene la idea original
(medidas, peso y volumen) y suma lo que faltaba: la carga puede rotarse, y se considera una
eficiencia de empaque razonable en vez de asumir que el volumen se llena al 100 %.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

PACKING_EFFICIENCY = 0.80  # en la práctica no se aprovecha el 100 % del volumen de la caja


@dataclass(frozen=True)
class FitResult:
    ok: bool
    reason: str


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia en línea recta entre dos puntos."""
    r = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def estimate_road_km(lat1, lon1, lat2, lon2, road_factor: float = 1.25) -> float:
    """Kilómetros de ruta ESTIMADOS (línea recta × factor). No reemplaza a un ruteo real."""
    return round(haversine_km(lat1, lon1, lat2, lon2) * road_factor, 1)


def fit_check(length, width, height, unit_weight_kg, quantity, vehicle, packing: float = PACKING_EFFICIENCY) -> FitResult:
    """¿Esta carga entra en este vehículo? `vehicle` necesita length/width/height/max_weight_kg (cm / kg).

    1. Una unidad debe entrar en la caja pudiendo girarla (se comparan las medidas ordenadas).
    2. El peso total no puede superar la capacidad.
    3. El volumen total no puede superar el volumen útil (volumen de la caja × eficiencia).
    """
    item = sorted((length, width, height))
    box = sorted((vehicle.length, vehicle.width, vehicle.height))
    if any(i > b for i, b in zip(item, box)):
        return FitResult(False, "Una unidad es más grande que la caja del vehículo.")

    total_weight = unit_weight_kg * quantity
    if total_weight > vehicle.max_weight_kg:
        return FitResult(False, f"Pesa {total_weight:g} kg y el vehículo soporta {vehicle.max_weight_kg:g} kg.")

    volume_m3 = length * width * height * quantity / 1_000_000
    usable_m3 = vehicle.length * vehicle.width * vehicle.height / 1_000_000 * packing
    if volume_m3 > usable_m3:
        return FitResult(False, f"Ocupa {volume_m3:.2f} m³ y el espacio útil es de {usable_m3:.2f} m³.")

    return FitResult(True, "Entra en tu vehículo.")


def reference_price(distance_km: float, rate_per_km: int, shipment_volume_m3: float,
                    vehicle_volume_m3: float, is_shared: bool, min_fare: int = 0) -> int:
    """Precio ORIENTATIVO para que el fletero tenga un punto de partida. Él decide el valor real.

    Exclusivo: km × tarifa. Compartido: se paga la fracción del vehículo que ocupa la carga
    (mínimo 15 %), que es la propuesta de valor de la app. Se redondea a $500.
    """
    base = distance_km * rate_per_km
    if is_shared and vehicle_volume_m3 > 0:
        base *= min(1.0, max(0.15, shipment_volume_m3 / vehicle_volume_m3))
    return int(max(round(base / 500) * 500, min_fare))
