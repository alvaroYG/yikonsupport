"""`flask datos-prueba` crea un caso de cada sin fallar (si un cambio en la plataforma rompe algún
paso, este test lo dice antes de que lo descubras al preparar las pruebas a mano)."""
from app import create_app
from app.extensions import db
from app.models import Factura, Pedido


def test_datos_prueba_crea_todos_los_casos():
    app = create_app("test")
    app.config["ENTORNO"] = "dev"                      # el comando solo funciona en desarrollo
    app.config["MENSAJES_DESHACER_SEGUNDOS"] = 10
    with app.app_context():
        resultado = app.test_cli_runner().invoke(args=["datos-prueba", "--si"])
        assert resultado.exception is None, resultado.output
        estados = {p.estado for p in db.session.scalars(db.select(Pedido))}
        assert {"proforma_solicitada", "proforma_enviada", "cambios_solicitados", "aceptado", "en_preparacion",
                "en_validacion", "validado", "enviado", "entregado", "cancelado"} <= estados
        assert {f.fase for f in db.session.scalars(db.select(Factura))} >= {"revision", "cambios", "por_enviar", "enviada"}
        assert app.config["MENSAJES_DESHACER_SEGUNDOS"] == 10   # deja la configuración como estaba
        db.session.remove()
        db.drop_all()


def test_datos_prueba_no_hace_nada_fuera_de_desarrollo():
    app = create_app("test")
    with app.app_context():
        db.create_all()
        resultado = app.test_cli_runner().invoke(args=["datos-prueba", "--si"])
        assert "Solo en desarrollo" in resultado.output
        assert db.session.scalar(db.select(Pedido)) is None
        db.drop_all()


def test_entrar_como_no_existe_fuera_de_desarrollo(app, client):
    from tests.conftest import login
    login(client, "cliA")
    assert client.post("/pruebas/entrar-como", data={"usuario_id": 1}).status_code == 404
    assert "Modo pruebas" not in client.get("/").get_data(as_text=True)


def test_sobre_mis_datos_no_borra_y_usa_mis_clientes(app):
    """Con --sobre-mis-datos: no borra nada, usa los clientes y kits que hay y crea solo lo que falta."""
    from app.models import Cliente, User
    antes_usuarios = {u.email for u in db.session.scalars(db.select(User))}
    app.config["ENTORNO"] = "dev"
    resultado = app.test_cli_runner().invoke(args=["datos-prueba", "--si", "--sobre-mis-datos"])
    assert resultado.exception is None, resultado.output
    assert antes_usuarios <= {u.email for u in db.session.scalars(db.select(User))}     # no borra a nadie
    clientes = {c.nombre for c in db.session.scalars(db.select(Cliente))}
    assert clientes == {"Clínica A", "Clínica B"}                                        # ni crea clientes
    pedidos = db.session.scalars(db.select(Pedido).where(Pedido.referencia.like("PRUEBA%"))).all()
    assert {"cancelado", "enviado", "en_validacion"} <= {p.estado for p in pedidos}
    assert {p.cliente.nombre for p in pedidos} == clientes
    assert "Quién es quién" in resultado.output


def test_sobre_mis_datos_se_puede_repetir(app):
    """Ejecutarlo dos veces no falla (el lote de stock de prueba ya existe: se reutiliza)."""
    app.config["ENTORNO"] = "dev"
    for _vez in range(2):
        resultado = app.test_cli_runner().invoke(args=["datos-prueba", "--si", "--sobre-mis-datos"])
        assert resultado.exception is None, resultado.output
    canceladas = {p.referencia for p in db.session.scalars(db.select(Pedido).where(Pedido.referencia.like("PRUEBA · cancelado%")))}
    assert canceladas == {"PRUEBA · cancelado", "PRUEBA · cancelado (2)"}
