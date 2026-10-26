"""Pruebas. Correr con:  python -m unittest discover -s tests -v   (o pytest)"""
import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app  # noqa: E402
from cargo import estimate_road_km, fit_check, haversine_km, reference_price  # noqa: E402
from catalog import VEHICULOS_DEFAULT  # noqa: E402
from db import get_db  # noqa: E402
from models import Offer, Shipment, User  # noqa: E402
from utils import whatsapp_number  # noqa: E402

KANGOO = SimpleNamespace(length=170, width=140, height=120, max_weight_kg=600)
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100


class CargoTests(unittest.TestCase):
    def test_queen_mattress_does_not_fit_kangoo(self):  # el caso del tetris_logic original
        self.assertFalse(fit_check(190, 140, 25, 35, 1, KANGOO).ok)

    def test_single_mattress_fits_rotated(self):
        self.assertTrue(fit_check(160, 90, 20, 20, 1, KANGOO).ok)

    def test_rotation_allowed(self):  # 170 de alto entra "acostada" o parada según sorted()
        self.assertTrue(fit_check(170, 65, 70, 75, 1, KANGOO).ok)

    def test_weight_limit(self):
        r = fit_check(100, 100, 100, 1000, 1, KANGOO)
        self.assertFalse(r.ok)
        self.assertIn("kg", r.reason)

    def test_volume_limit_uses_packing_efficiency(self):
        # 10 lavarropas: 0.306 m3 c/u = 3.06 m3 > 0.8 * 2.856 m3 aunque cada uno entre solo
        self.assertFalse(fit_check(60, 60, 85, 20, 10, KANGOO).ok)
        self.assertTrue(fit_check(60, 60, 85, 20, 3, KANGOO).ok)

    def test_distance_bariloche_el_bolson(self):
        d = haversine_km(-41.1334, -71.3103, -41.9676, -71.5401)
        self.assertAlmostEqual(d, 95, delta=3)
        self.assertGreater(estimate_road_km(-41.1334, -71.3103, -41.9676, -71.5401, 1.25), d)

    def test_reference_price_shared_is_cheaper_but_has_floor(self):
        excl = reference_price(100, 450, 0.5, 2.8, False, 10000)
        shared = reference_price(100, 450, 0.5, 2.8, True, 10000)
        self.assertEqual(excl, 45000)
        self.assertLess(shared, excl)
        self.assertGreaterEqual(shared, 10000)
        self.assertEqual(reference_price(1, 450, 0.01, 2.8, True, 10000), 10000)


class WhatsappTests(unittest.TestCase):
    def test_formats(self):
        for raw in ("2944 15 123456", "+54 9 2944 123456", "02944-123456", "(0294) 4 123456", "5492944123456"):
            self.assertEqual(whatsapp_number(raw), "5492944123456", raw)

    def test_foreign_and_invalid(self):
        self.assertEqual(whatsapp_number("+34 600 123 456"), "34600123456")
        self.assertEqual(whatsapp_number("123"), "")
        self.assertEqual(whatsapp_number(""), "")
        self.assertEqual(whatsapp_number(None), "")


class AppCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app({"TESTING": True, "SECRET_KEY": "test", "DATABASE_URL": f"sqlite:///{self.tmp.name}/t.db"})
        self.app.instance_path = self.tmp.name
        self.ctx = self.app.app_context()
        self.ctx.push()
        import security
        security._attempts.clear()  # el contador anti fuerza bruta es global al proceso

    def tearDown(self):
        self.ctx.pop()
        self.app.extensions["engine"].dispose()
        self.tmp.cleanup()

    # --- helpers ---
    def new_client(self):
        c = self.app.test_client()
        self.arm(c)
        return c

    @staticmethod
    def arm(c):
        """Login/registro rotan la sesión (anti fijación), así que se vuelve a fijar el token CSRF de prueba."""
        with c.session_transaction() as s:
            s["_csrf"] = "tok"

    def post(self, c, url, data=None, **kw):
        data = dict(data or {})
        data.setdefault("csrf_token", "tok")
        return c.post(url, data=data, **kw)

    def register(self, role, email, name="Persona", vehicle="kangoo", phone="2944 123456"):
        c = self.new_client()
        data = {"name": name, "email": email, "password": "clave-segura-1", "phone": phone, "vehicle_type": vehicle}
        r = self.post(c, f"/register/{role}", data)
        self.assertEqual(r.status_code, 302, r.get_data(as_text=True)[:500])
        self.arm(c)
        return c

    def shipment_form(self, **over):
        d = {"item_select": "heladera", "quantity": "1", "orig_address": "Onelli 450, Bariloche",
             "dest_address": "San Martín 1200, El Bolsón", "orig_lat": "-41.1334", "orig_lon": "-71.3103",
             "dest_lat": "-41.9676", "dest_lon": "-71.5401", "modality": "shared"}
        d.update(over)
        return d

    def make_admin(self):
        from werkzeug.security import generate_password_hash
        db = get_db()
        db.add(User(name="Admin", email="admin@x.com", password_hash=generate_password_hash("admin-clave-1"), role="admin"))
        db.commit()
        c = self.new_client()
        r = self.post(c, "/login", {"email": "admin@x.com", "password": "admin-clave-1"})
        self.assertEqual(r.status_code, 302)
        self.arm(c)
        return c


class FlowTests(AppCase):
    def test_full_happy_path(self):
        client = self.register("client", "cli@x.com", "Ana Cliente")
        trans = self.register("transporter", "fle@x.com", "Beto Fletero")

        # El cliente publica; los datos quedan normalizados en el servidor
        r = self.post(client, "/client/shipments", self.shipment_form(quantity="2"))
        self.assertEqual(r.status_code, 302)
        s = get_db().query(Shipment).one()
        self.assertEqual((s.description, s.status), ("2× Heladera familiar", "searching"))
        self.assertGreater(s.distance_km, 100)

        # El fletero la ve (entra), pero NO ve el teléfono ni el apellido del cliente
        html = trans.get("/transporter").get_data(as_text=True)
        self.assertIn("Heladera familiar", html)
        self.assertIn("Entra en tu vehículo", html)
        self.assertNotIn("2944 123456", html)
        self.assertNotIn("Cliente</strong>", html)

        # Ofertar, y actualizar la misma oferta no duplica
        self.post(trans, "/transporter/offers", {"shipment_id": s.id, "price": "90000", "message": "Salgo el lunes"})
        self.post(trans, "/transporter/offers", {"shipment_id": s.id, "price": "85000"})
        db = get_db()
        db.expire_all()
        offers = db.query(Offer).all()
        self.assertEqual((len(offers), offers[0].price), (1, 85000))

        # El cliente ve la oferta con link de WhatsApp bien formado, y la acepta
        html = client.get("/client").get_data(as_text=True)
        self.assertIn("https://wa.me/5492944123456", html)
        self.assertIn("$ 85.000", html)
        self.post(client, f"/client/offers/{offers[0].id}/accept")
        db.expire_all()
        self.assertEqual(db.get(Shipment, s.id).status, "assigned")

        # Ahora sí el fletero ve el contacto del cliente y marca entregado
        html = trans.get("/transporter").get_data(as_text=True)
        self.assertIn("Ana Cliente", html)
        self.assertIn("wa.me/5492944123456", html)
        self.post(trans, f"/transporter/offers/{offers[0].id}/delivered")
        db.expire_all()
        self.assertEqual(db.get(Shipment, s.id).status, "delivered")

        # Archivar
        self.post(client, f"/client/shipments/{s.id}/archive")
        db.expire_all()
        self.assertTrue(db.get(Shipment, s.id).archived)
        self.assertIn("Historial", client.get("/client").get_data(as_text=True))

    def test_accepting_rejects_other_offers(self):
        client = self.register("client", "cli@x.com")
        t1 = self.register("transporter", "t1@x.com", "Uno")
        t2 = self.register("transporter", "t2@x.com", "Dos")
        self.post(client, "/client/shipments", self.shipment_form())
        sid = get_db().query(Shipment).one().id
        self.post(t1, "/transporter/offers", {"shipment_id": sid, "price": "100000"})
        self.post(t2, "/transporter/offers", {"shipment_id": sid, "price": "90000"})
        db = get_db(); db.expire_all()
        winner = db.query(Offer).filter_by(price=90000).one()
        self.post(client, f"/client/offers/{winner.id}/accept")
        db.expire_all()
        self.assertEqual(sorted(o.status for o in db.query(Offer).all()), ["accepted", "rejected"])
        # y ya no se puede ofertar
        late = self.register("transporter", "t3@x.com", "Tres")
        self.post(late, "/transporter/offers", {"shipment_id": sid, "price": "1000"})
        db.expire_all()
        self.assertEqual(db.query(Offer).count(), 2)

    def test_offer_blocked_when_cargo_does_not_fit(self):
        client = self.register("client", "cli@x.com")
        trans = self.register("transporter", "fle@x.com")  # Kangoo
        self.post(client, "/client/shipments", self.shipment_form(item_select="colchon_2plazas"))
        sid = get_db().query(Shipment).one().id
        self.assertNotIn("Colchón 2 plazas", trans.get("/transporter").get_data(as_text=True))  # filtrada
        self.assertIn("Colchón 2 plazas", trans.get("/transporter?all=1").get_data(as_text=True))
        self.post(trans, "/transporter/offers", {"shipment_id": sid, "price": "50000"})  # forzado a mano
        self.assertEqual(get_db().query(Offer).count(), 0)

    def test_custom_item_and_validation(self):
        client = self.register("client", "cli@x.com")
        ok = self.post(client, "/client/shipments", self.shipment_form(
            item_select="custom", custom_name="Bicicleta", custom_length="180", custom_width="60",
            custom_height="100", custom_weight="14"))
        self.assertEqual(ok.status_code, 302)
        for bad in ({"item_select": "nope"}, {"quantity": "0"}, {"orig_lat": "abc"}, {"orig_lat": "10"},
                    {"orig_address": ""}, {"pickup_date": "2001-01-01"}, {"modality": "x"},
                    {"dest_lat": "-41.1334", "dest_lon": "-71.3103"}):
            r = self.post(client, "/client/shipments", self.shipment_form(**bad))
            self.assertEqual(r.status_code, 400, bad)
        self.assertEqual(get_db().query(Shipment).count(), 1)

    def test_cancel_and_cancel_rejects_offers(self):
        client = self.register("client", "cli@x.com")
        trans = self.register("transporter", "fle@x.com")
        self.post(client, "/client/shipments", self.shipment_form())
        sid = get_db().query(Shipment).one().id
        self.post(trans, "/transporter/offers", {"shipment_id": sid, "price": "1000"})
        self.post(client, f"/client/shipments/{sid}/cancel")
        db = get_db(); db.expire_all()
        self.assertEqual(db.get(Shipment, sid).status, "cancelled")
        self.assertEqual(db.query(Offer).one().status, "rejected")


class SecurityTests(AppCase):
    def test_password_is_hashed(self):
        self.register("client", "cli@x.com")
        user = get_db().query(User).one()
        self.assertNotIn("clave-segura-1", user.password_hash)
        self.assertTrue(user.password_hash.startswith(("scrypt:", "pbkdf2:")))

    def test_csrf_required(self):
        c = self.new_client()
        r = c.post("/login", data={"email": "a@b.com", "password": "x"})  # sin token
        self.assertEqual(r.status_code, 400)

    def test_role_isolation(self):
        client = self.register("client", "cli@x.com")
        trans = self.register("transporter", "fle@x.com")
        self.assertEqual(client.get("/transporter").status_code, 403)
        self.assertEqual(trans.get("/client").status_code, 403)
        self.assertEqual(client.get("/admin").status_code, 403)
        self.assertEqual(self.new_client().get("/client").status_code, 302)  # sin sesión -> login

    def test_cannot_touch_other_clients_shipments(self):
        a = self.register("client", "a@x.com")
        b = self.register("client", "b@x.com")
        trans = self.register("transporter", "fle@x.com")
        self.post(a, "/client/shipments", self.shipment_form())
        sid = get_db().query(Shipment).one().id
        self.post(trans, "/transporter/offers", {"shipment_id": sid, "price": "1000"})
        oid = get_db().query(Offer).one().id
        self.assertEqual(self.post(b, f"/client/offers/{oid}/accept").status_code, 404)
        self.assertEqual(self.post(b, f"/client/shipments/{sid}/cancel").status_code, 404)
        other = self.register("transporter", "otro@x.com")
        self.assertEqual(self.post(other, f"/transporter/offers/{oid}/withdraw").status_code, 404)

    def test_login_throttle_and_suspension(self):
        self.register("client", "cli@x.com")
        c = self.new_client()
        codes = [self.post(c, "/login", {"email": "cli@x.com", "password": "mal"}).status_code for _ in range(7)]
        self.assertEqual(codes[:5], [401] * 5)
        self.assertEqual(codes[5], 429)
        # aun con la clave correcta queda bloqueado un rato
        self.assertEqual(self.post(c, "/login", {"email": "cli@x.com", "password": "clave-segura-1"}).status_code, 429)

    def test_suspended_user_cannot_login(self):
        self.register("client", "cli@x.com")
        admin = self.make_admin()
        uid = get_db().query(User).filter_by(email="cli@x.com").one().id
        self.post(admin, f"/admin/users/{uid}/toggle-active")
        r = self.post(self.new_client(), "/login", {"email": "cli@x.com", "password": "clave-segura-1"})
        self.assertEqual(r.status_code, 403)

    def test_bad_registration(self):
        c = self.new_client()
        for data in ({"name": "A", "email": "x@x.com", "password": "clave-segura-1", "phone": "2944123456"},
                     {"name": "Ana", "email": "no-es-mail", "password": "clave-segura-1", "phone": "2944123456"},
                     {"name": "Ana", "email": "x@x.com", "password": "corta", "phone": "2944123456"},
                     {"name": "Ana", "email": "x@x.com", "password": "clave-segura-1", "phone": "12"}):
            self.assertEqual(self.post(c, "/register/client", data).status_code, 400, data)
        self.register("client", "dup@x.com")
        r = self.post(self.new_client(), "/register/client",
                      {"name": "Otra", "email": "DUP@x.com", "password": "clave-segura-1", "phone": "2944123456"})
        self.assertEqual(r.status_code, 400)


class DocumentTests(AppCase):
    def upload(self, c, data, name="dni.png"):
        import io
        return c.post("/profile", data={"csrf_token": "tok", "name": "Beto", "phone": "2944 123456", "dni": "30111222",
                                        "license_number": "L123", "dni_file": (io.BytesIO(data), name)},
                      content_type="multipart/form-data")

    def test_fake_image_rejected_by_content(self):
        c = self.register("transporter", "fle@x.com")
        r = self.upload(c, b"<?php echo 1; ?>", "foto.png")
        self.assertEqual(r.status_code, 400)
        self.assertIsNone(get_db().query(User).one().dni_file)

    def test_documents_are_private_and_verification_flow(self):
        c = self.register("transporter", "fle@x.com")
        other = self.register("client", "otro@x.com")
        self.assertEqual(self.upload(c, PNG).status_code, 302)
        db = get_db(); db.expire_all()
        u = db.query(User).filter_by(email="fle@x.com").one()
        self.assertTrue(u.dni_file.endswith(".png"))
        self.assertEqual(u.verification_status, "unverified")  # falta la licencia
        self.assertNotIn("static", u.dni_file)

        self.assertEqual(c.get(f"/documents/{u.id}/dni").status_code, 200)
        self.assertEqual(other.get(f"/documents/{u.id}/dni").status_code, 404)
        self.assertEqual(self.new_client().get(f"/documents/{u.id}/dni").status_code, 302)
        self.assertEqual(self.app.test_client().get(f"/static/uploads/{u.dni_file}").status_code, 404)

        import io
        c.post("/profile", data={"csrf_token": "tok", "name": "Beto", "phone": "2944 123456", "dni": "30111222",
                                 "license_number": "L123", "license_file": (io.BytesIO(PNG), "l.png")},
               content_type="multipart/form-data")
        db.expire_all()
        u = db.query(User).filter_by(email="fle@x.com").one()
        self.assertEqual(u.verification_status, "pending")

        admin = self.make_admin()
        self.assertEqual(admin.get(f"/documents/{u.id}/license").status_code, 200)
        self.assertIn("fle@x.com", admin.get("/admin").get_data(as_text=True))
        self.post(admin, f"/admin/users/{u.id}/verify")
        db.expire_all()
        self.assertTrue(db.get(User, u.id).is_verified)
        self.assertIn("Verificado", c.get("/transporter").get_data(as_text=True) + c.get("/profile").get_data(as_text=True))

        # cambiar el DNI vuelve a revisión
        self.upload(c, PNG)
        db.expire_all()
        self.assertEqual(db.get(User, u.id).verification_status, "pending")

        # rechazo exige motivo
        self.post(admin, f"/admin/users/{u.id}/reject", {"note": ""})
        db.expire_all()
        self.assertEqual(db.get(User, u.id).verification_status, "pending")
        self.post(admin, f"/admin/users/{u.id}/reject", {"note": "Foto borrosa"})
        db.expire_all()
        self.assertEqual(db.get(User, u.id).verification_note, "Foto borrosa")

    def test_oversize_rejected(self):
        c = self.register("client", "cli@x.com")
        self.app.config["MAX_UPLOAD_BYTES"] = 50
        self.assertEqual(self.upload(c, PNG).status_code, 400)


class PagesAndVehicleTests(AppCase):
    def test_every_page_renders(self):
        client = self.register("client", "cli@x.com")
        trans = self.register("transporter", "fle@x.com")
        admin = self.make_admin()
        self.assertEqual(self.new_client().get("/").status_code, 200)
        for c, urls in ((client, ["/client", "/profile"]), (trans, ["/transporter", "/transporter?all=1", "/profile"]),
                        (admin, ["/admin", "/admin?q=fle&role=transporter", "/profile"])):
            for u in urls:
                self.assertEqual(c.get(u).status_code, 200, u)
        self.assertEqual(client.get("/no-existe").status_code, 404)

    def test_update_vehicle_and_password(self):
        trans = self.register("transporter", "fle@x.com")
        r = self.post(trans, "/profile/vehicle", {"vehicle_name": "Sprinter", "length": "320", "width": "170",
                                                  "height": "190", "max_weight_kg": "1200", "rate_per_km": "800"})
        self.assertEqual(r.status_code, 302)
        v = get_db().query(User).one().primary_vehicle
        self.assertEqual((v.name, v.length, v.rate_per_km), ("Sprinter", 320, 800))
        self.post(trans, "/profile/vehicle", {"vehicle_name": "X", "length": "-5"})
        self.assertEqual(get_db().query(User).one().primary_vehicle.name, "Sprinter")

        self.post(trans, "/profile/password", {"current_password": "mala", "new_password": "nueva-clave-2", "confirm_password": "nueva-clave-2"})
        self.assertIsNone(self.post(self.new_client(), "/login", {"email": "fle@x.com", "password": "nueva-clave-2"}).headers.get("Location"))
        self.post(trans, "/profile/password", {"current_password": "clave-segura-1", "new_password": "nueva-clave-2", "confirm_password": "nueva-clave-2"})
        r = self.post(self.new_client(), "/login", {"email": "fle@x.com", "password": "nueva-clave-2"})
        self.assertEqual(r.status_code, 302)

    def test_require_verified_flag(self):
        self.app.config["REQUIRE_VERIFIED_TRANSPORTERS"] = True
        client = self.register("client", "cli@x.com")
        trans = self.register("transporter", "fle@x.com")
        self.post(client, "/client/shipments", self.shipment_form())
        sid = get_db().query(Shipment).one().id
        self.post(trans, "/transporter/offers", {"shipment_id": sid, "price": "1000"})
        self.assertEqual(get_db().query(Offer).count(), 0)

    def test_cli_create_admin(self):
        runner = self.app.test_cli_runner()
        res = runner.invoke(args=["create-admin", "--email", "boss@x.com", "--name", "Boss", "--password", "super-clave-9"])
        self.assertEqual(res.exit_code, 0, res.output)
        self.assertEqual(get_db().query(User).filter_by(role="admin").count(), 1)

    def test_default_vehicles_are_consistent(self):
        for spec in VEHICULOS_DEFAULT.values():
            self.assertTrue(all(spec[k] > 0 for k in ("length", "width", "height", "max_weight", "tarifa_km")))


if __name__ == "__main__":
    unittest.main()
