"""Catálogo de cargas típicas y vehículos de ejemplo. Medidas en cm, pesos en kg."""

MODULOS_CATALOGO = {
    "hogar": {
        "title": "Hogar, muebles y descanso",
        "icon": "🏠",
        "items": {
            "colchon_1plaza": {"name": "Colchón 1 plaza", "length": 190, "width": 90, "height": 20, "weight": 15, "icon": "🛏️"},
            "colchon_2plazas": {"name": "Colchón 2 plazas / Queen", "length": 190, "width": 140, "height": 25, "weight": 35, "icon": "🛌"},
            "sofa_3cuerpos": {"name": "Sofá / sillón 3 cuerpos", "length": 210, "width": 90, "height": 85, "weight": 60, "icon": "🛋️"},
            "mesa_comedor": {"name": "Mesa de comedor", "length": 150, "width": 90, "height": 75, "weight": 40, "icon": "🪵"},
        },
    },
    "electro": {
        "title": "Electrodomésticos y tecnología",
        "icon": "⚡",
        "items": {
            "heladera": {"name": "Heladera familiar", "length": 70, "width": 65, "height": 170, "weight": 75, "icon": "🧊"},
            "lavarropas": {"name": "Lavarropas automático", "length": 60, "width": 60, "height": 85, "weight": 65, "icon": "🌀"},
            "cocina": {"name": "Cocina a gas", "length": 60, "width": 60, "height": 85, "weight": 50, "icon": "🍳"},
        },
    },
    "construccion": {
        "title": "Materiales de construcción",
        "icon": "🧱",
        "items": {
            "bolson_arena": {"name": "Bolsón de arena / piedra (big bag)", "length": 100, "width": 100, "height": 100, "weight": 1000, "icon": "🪨"},
            "palet_ladrillos": {"name": "Palet de ladrillos / cerámicos", "length": 120, "width": 100, "height": 80, "weight": 800, "icon": "🧱"},
            "aberturas": {"name": "Ventana o puerta con marco", "length": 150, "width": 20, "height": 120, "weight": 35, "icon": "🚪"},
        },
    },
    "mascotas": {
        "title": "Mascotas y animales",
        "icon": "🐾",
        "items": {
            "perro_grande": {"name": "Mascota (perro mediano/grande con cucha)", "length": 100, "width": 70, "height": 75, "weight": 30, "icon": "🐕"},
        },
    },
}

# Vista plana key -> item (con su categoría), para validar en el servidor.
CATALOGO_PLANO = {
    key: {**item, "category": cat}
    for cat, modulo in MODULOS_CATALOGO.items()
    for key, item in modulo["items"].items()
}

# Vehículos para el alta rápida. Cada fletero puede editar medidas y tarifa desde su perfil.
# IMPORTANTE: tarifa_km (ARS por km) son valores de EJEMPLO; con la inflación quedan viejos rápido.
VEHICULOS_DEFAULT = {
    "moto": {"name": "Moto / Motomandatario", "length": 50, "width": 40, "height": 40, "max_weight": 20, "tarifa_km": 250},
    "auto": {"name": "Auto / Baúl o asientos", "length": 100, "width": 90, "height": 60, "max_weight": 150, "tarifa_km": 350},
    "carrito": {"name": "Carrito / Tráiler liviano", "length": 150, "width": 120, "height": 80, "max_weight": 400, "tarifa_km": 400},
    "remolque": {"name": "Remolque / Acoplado", "length": 250, "width": 150, "height": 120, "max_weight": 800, "tarifa_km": 500},
    "kangoo": {"name": "Furgón chico (Kangoo / Fiorino)", "length": 170, "width": 140, "height": 120, "max_weight": 600, "tarifa_km": 450},
    "pickup": {"name": "Camioneta 4x4 con caja", "length": 150, "width": 150, "height": 80, "max_weight": 1000, "tarifa_km": 600},
    "camion": {"name": "Camión de carga", "length": 350, "width": 200, "height": 200, "max_weight": 3500, "tarifa_km": 900},
}
