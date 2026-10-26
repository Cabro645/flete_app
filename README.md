# FleteApp Patagonia

Marketplace de fletes y carga compartida para la Comarca Andina: los **clientes** publican un envío, los **fleteros** ofertan, el cliente acepta y coordinan por WhatsApp. Un **admin** verifica DNI y licencia de los fleteros.

## Arranque rápido

```bash
python -m venv venv
venv\Scripts\activate            # Windows   (Linux/Mac: source venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env           # (Linux/Mac: cp)  y completá lo que quieras

flask --app app create-admin     # te pide email, nombre y contraseña
flask --app app run --debug      # http://127.0.0.1:5000
```

La base (SQLite) y los documentos subidos viven en `instance/`. **No** va a git ni se sirve públicamente.

## Cómo funciona

1. Cliente: publica retiro/entrega (mapa + direcciones), qué envía, cantidad y modalidad.
2. Fletero: ve solo las cargas que **entran en su vehículo** (medidas con rotación, peso y volumen útil al 80 %), con un precio de referencia según su tarifa por km, y envía su oferta.
3. Cliente: compara ofertas (con insignia ✓ Verificado), acepta una (las demás se rechazan) y contacta por WhatsApp.
4. El teléfono del cliente recién se muestra al fletero **cuando su oferta es aceptada**.
5. Entregado → archivado.

Estados: envío `searching → assigned → delivered` (o `cancelled`); oferta `pending → accepted / rejected / withdrawn / cancelled`.

## Producción

```bash
gunicorn wsgi:app --workers 3 --bind 0.0.0.0:8000     # Windows: waitress-serve --call wsgi:create_app
```
Antes de publicar:
- `SECRET_KEY` definida por entorno, `SESSION_COOKIE_SECURE=1`, y servir **siempre por HTTPS**.
- `TRUST_PROXY=1` si hay nginx/Render/Railway delante.
- Respaldar `instance/` (base + documentos) o usar Postgres con `DATABASE_URL`.
- Nunca correr con `--debug` ni `FLASK_DEBUG=1`.
- Los documentos de identidad son datos personales: en Argentina aplica la Ley 25.326 (Protección de Datos Personales). Conviene tener política de privacidad y términos antes de abrir al público.

## Administración

- `flask --app app create-admin` / `flask --app app set-password` (mientras no haya recuperación por email).
- `/admin`: verificar o rechazar documentación (con motivo), suspender/reactivar usuarios, ver envíos.
- `REQUIRE_VERIFIED_TRANSPORTERS=1` exige verificación para ofertar.

## Pruebas

```bash
python -m unittest discover -s tests -v
```

## Límites conocidos (a propósito, para una v1)

- **Distancia** = línea recta × `ROAD_FACTOR` (1,25). Es una estimación; para ruteo real, integrar OSRM/Google/Mapbox en `cargo.estimate_road_km`.
- **Precios**: las tarifas por km de ejemplo (`catalog.py`) quedan viejas rápido; cada fletero las edita en su perfil. El precio de referencia es orientativo.
- **Sin pagos** ni seguro: el acuerdo y el pago se hacen entre las partes.
- **Sin email**: no hay recuperación de contraseña automática ni avisos por mail (usar `set-password` o sumar SMTP).
- **Anti fuerza bruta en memoria**: vale por proceso; con varios workers o servidores conviene Redis o un proxy con rate limiting.
- **Esquema**: las tablas se crean solas, pero cambios futuros requieren migraciones (Alembic / Flask-Migrate).
- Bootstrap y Leaflet se cargan desde CDN sin SRI; para endurecer, hospedarlos localmente o agregar hashes de integridad.



## Lo que todavía falta
“Real” de verdad, para cobrar y operar, necesita cosas que no puedo hacer desde acá:
- Pagos, por ejemplo Mercado Pago.
- Avisos por email o WhatsApp cuando llega una oferta.
- Recuperar contraseña.
- Un servidor donde publicarla.
- Revisar seguro de carga y los requisitos legales para trasladar animales, que dependen de tu jurisdicción.
- Actualizar las tarifas por km, que son de referencia.
