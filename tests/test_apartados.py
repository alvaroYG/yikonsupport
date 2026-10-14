"""Qué apartados ve cada rol: casillas en Ajustes → Qué ve cada rol (app/apartados.py)."""
from app import apartados
from app.extensions import db
from app.models import Ajuste, RegistroAuditoria, User
from app.permisos import roles_disponibles
from tests.conftest import login, pedido_cliente


def _como_venia(app):
    """Las casillas que vienen marcadas de fábrica (con la configuración de los tests)."""
    with app.test_request_context():
        return [f"{clave}:{rol}" for clave, ap in apartados.APARTADOS.items() for rol in ap.cambiables
                if apartados.de_fabrica(clave, rol)]


def _guardar(client, marcadas):
    login(client, "admin")
    r = client.post("/admin/ajustes/apartados", data={"accion": "guardar", "ver": marcadas})
    client.post("/auth/logout")
    return r


def _salir(client):
    client.post("/auth/logout")


def test_quitar_facturas_a_soporte_de_cliente(app, client):
    login(client, "cliA"); pedido_cliente(client); _salir(client)
    login(client, "loga")
    assert client.get("/facturas/").status_code == 200
    _salir(client)
    _guardar(client, [m for m in _como_venia(app) if m != "facturas:fas"])
    login(client, "loga")
    assert client.get("/facturas/").status_code == 403
    html = client.get("/pedidos/1").get_data(as_text=True)
    assert 'href="/facturas/"' not in html and 'id="facturas"' not in html          # ni menú ni sección
    _salir(client)
    login(client, "cliA")                                                          # al cliente no le cambia nada
    assert client.get("/facturas/mias").status_code == 200
    _salir(client)
    login(client, "admin")
    assert "facturas·fas sí→no" in db.session.scalar(db.select(RegistroAuditoria.detalle).filter_by(entidad="Ajuste"))


def test_lo_fijo_no_se_quita_aunque_lo_intenten(app, client):
    _guardar(client, [])                                       # todas las casillas desmarcadas
    login(client, "fac")
    assert client.get("/facturas/").status_code == 200 and client.get("/clientes/").status_code == 200
    _salir(client)
    login(client, "ofi")
    assert client.get("/inventario/").status_code == 200 and client.get("/pedidos/preparar").status_code == 200
    _salir(client)
    login(client, "loga")
    assert client.get("/pedidos/").status_code == 200
    assert client.get("/productos/").status_code == 403       # esto sí era una casilla


def test_quitar_a_facturacion_lo_cambiable(app, client):
    """Facturación: inventario (consulta) y estadísticas vienen puestos; admin se los puede quitar.
    Almacén ya no puede tener Clientes ni Estadísticas (sale «—» en la tabla)."""
    login(client, "fac")
    assert client.get("/inventario/").status_code == 200 and client.get("/estadisticas").status_code == 200
    _salir(client)
    marcadas = [c for c in _como_venia(app) if c not in ("inventario:facturacion", "estadisticas:facturacion")]
    _guardar(client, marcadas + ["clientes:logistica", "estadisticas:logistica"])        # (se ignoran)
    login(client, "fac")
    assert client.get("/inventario/").status_code == 403 and client.get("/estadisticas").status_code == 403
    _salir(client)
    login(client, "ofi")
    assert client.get("/clientes/").status_code == 403 and client.get("/estadisticas").status_code == 403


def test_tickets_y_documentos_en_pausa_se_activan_por_rol(app, client):
    app.config["SOPORTE_CHROMGO"] = app.config["DOCUMENTOS_INTERNOS"] = False     # como en producción
    login(client, "sop")
    assert client.get("/soporte/").status_code == 404
    _salir(client)
    with app.test_request_context():
        assert "soporte" not in roles_disponibles() and "cliente_chromgo" not in roles_disponibles()
    _guardar(client, _como_venia(app) + ["tickets:admin", "tickets:soporte", "documentos:logistica"])
    login(client, "sop")
    assert client.get("/soporte/").status_code == 200
    _salir(client)
    login(client, "chrA")                                      # Cliente ChromGo: aún no
    assert client.get("/soporte/").status_code == 403
    _salir(client)
    login(client, "ofi")
    assert client.get("/documentos/").status_code == 200
    _salir(client)
    login(client, "loga")
    assert client.get("/documentos/").status_code == 403
    _salir(client)
    login(client, "admin")
    html = client.get("/admin/usuarios/nuevo").get_data(as_text=True)
    assert 'value="soporte"' in html and 'value="cliente_chromgo"' not in html
    assert "acceso_chromgo" not in html                        # a los clientes no se les ha activado


def test_dejarlo_como_venia_y_solo_admin(app, client):
    _guardar(client, ["clientes:logistica"])
    assert db.session.scalar(db.select(db.func.count()).select_from(Ajuste).where(Ajuste.clave.like("apartado.%")))
    login(client, "admin")
    client.post("/admin/ajustes/apartados", data={"accion": "fabrica"})
    assert db.session.scalar(db.select(db.func.count()).select_from(Ajuste).where(Ajuste.clave.like("apartado.%"))) == 0
    html = client.get("/admin/ajustes/apartados").get_data(as_text=True)
    assert 'name="ver" value="facturas:fas"' in html and 'value="facturas:logistica"' not in html   # fija: sin casilla
    _salir(client)
    for usuario in ("ofi", "loga", "cliA"):
        login(client, usuario)
        assert client.get("/admin/ajustes/apartados").status_code == 403
        _salir(client)
