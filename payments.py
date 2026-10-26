"""Módulo de pagos (Mercado Pago / pasarelas)."""
from flask import current_app

def create_mercadopago_preference(shipment_id: int, amount: int, title: str) -> str:
    """Genera preferencia de pago de Mercado Pago o link de cobro."""
    # En producción real se usa mercadopago SDK con MP_ACCESS_TOKEN de .env
    token = current_app.config.get("MP_ACCESS_TOKEN", "TEST-TOKEN")
    return f"https://www.mercadopago.com.ar/checkout/v1/redirect?pref_id=MP-{shipment_id}-{amount}"
