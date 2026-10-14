"""
Novedades de un pedido (app/pedidos/novedades.py): la marca "nuevo" en las secciones de la
ficha y en la lista de pedidos cuando OTRA persona ha cambiado algo desde tu última visita.
"""
import re
from datetime import date, timedelta
from io import BytesIO

from app.extensions import db
from app.models import Pedido, User
from app.pedidos.novedades import novedades_de
from tests.conftest import login, pedido_cliente, subir_foto, pdf_proforma


def _salir(client):
    client.post("/auth/logout")


def _pedido(client, con_proforma=False):
    """Pedido de la Clínica A (K1 = 1 × P1), con stock para poder reservar lotes."""
    login(client, "admin")
    client.post("/inventario/movimiento", data={"articulo": "producto-1", "tipo": "entrada", "cantidad": 10,
                                                "lote": "L1", "caducidad": "2099-12-31"})
    _salir(client)
    login(client, "cliA"); pedido_cliente(client, con_proforma=con_proforma); _salir(client)
    return db.session.scalar(db.select(Pedido).order_by(Pedido.id.desc()))


def _visita(client, usuario, p):
    """El usuario abre la ficha y sale. Devuelve el HTML que ha visto."""
    login(client, usuario)
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    _salir(client)
    return html


def _secciones_con_marca(html):
    """Claves de las secciones de la ficha que llevan la marca "nuevo" en su cabecera."""
    cabeceras = re.finditer(r'<section class="seccion-ficha[^"]*" id="([\w-]+)".*?</h2>', html, flags=re.S)
    return {m.group(1) for m in cabeceras if "data-nuevo" in m.group(0)}


def _novedades(usuario, p):
    u = db.session.scalar(db.select(User).filter_by(email=f"{usuario.lower()}@ejemplo.com"))
    return novedades_de(u, [p]).get(p.id, set())


def _subir_documento(client, p, nombre="coa.pdf"):
    client.post(f"/pedidos/{p.id}/documentos", data={"documento": (BytesIO(b"%PDF-1.4 datos"), nombre)},
                content_type="multipart/form-data")


def test_la_primera_visita_no_tiene_novedades(app, client):
    p = _pedido(client)
    login(client, "ofi"); _subir_documento(client, p); _salir(client)
    assert _secciones_con_marca(_visita(client, "loga", p)) == set()       # nunca lo había abierto


def test_lo_que_cambia_otra_persona_sale_como_nuevo_hasta_que_lo_ves(app, client):
    p = _pedido(client)
    _visita(client, "loga", p)
    login(client, "ofi"); _subir_documento(client, p); _salir(client)
    # en la lista de pedidos, la fila lleva la marca y dice qué ha cambiado
    login(client, "loga")
    lista = client.get("/pedidos/").get_data(as_text=True)
    assert "Novedades desde tu última visita: documentos" in lista and f'/pedidos/{p.id}#documentos' in lista
    # en la ficha, solo la sección de documentos
    assert _secciones_con_marca(client.get(f"/pedidos/{p.id}").get_data(as_text=True)) == {"documentos"}
    # ya lo ha visto: ni en la ficha ni en la lista
    assert _secciones_con_marca(client.get(f"/pedidos/{p.id}").get_data(as_text=True)) == set()
    assert "Novedades desde tu última visita" not in client.get("/pedidos/").get_data(as_text=True)


def test_lo_que_haces_tu_no_es_novedad_para_ti(app, client):
    p = _pedido(client)
    login(client, "ofi")
    client.get(f"/pedidos/{p.id}")
    _subir_documento(client, p)
    assert _novedades("ofi", p) == set()
    assert _novedades("admin", p) == set()             # admin aún no lo ha abierto nunca
    _salir(client)
    _visita(client, "admin", p)
    login(client, "ofi"); _subir_documento(client, p, "otro.pdf"); _salir(client)
    assert _novedades("admin", p) == {"documentos"} and _novedades("ofi", p) == set()


def test_cada_cambio_marca_su_seccion(app, client):
    p = _pedido(client)
    _visita(client, "loga", p)
    login(client, "admin")
    client.post(f"/pedidos/{p.id}/guardar", data={f"precio_kit_{p.kits[0].id}": "90,00"})
    assert _novedades("loga", p) == {"contenido"}
    client.post(f"/pedidos/{p.id}/lotes", data={"accion": "automatico"})       # (ya estaban: no cambia nada)
    assert _novedades("loga", p) == {"contenido"}
    lote_id = p.reservas[0].lote_id
    client.post(f"/inventario/reservas/{p.id}/liberar")
    assert _novedades("loga", p) == {"contenido", "lotes"}
    client.post(f"/pedidos/{p.id}/lotes", data={f"lote-{lote_id}": "1"})
    client.post(f"/pedidos/{p.id}/preparacion")
    assert _novedades("loga", p) == {"contenido", "lotes"}                     # empezar a preparar no es de ninguna sección
    subir_foto(client, p.id)
    client.post(f"/pedidos/{p.id}/enviar-validacion")
    assert _novedades("loga", p) == {"contenido", "lotes", "fotos"}
    client.post(f"/facturas/pedido/{p.id}", data={"numero": "F-1", "fecha_emision": date.today().isoformat(),
                                                  "fecha_vencimiento": (date.today() + timedelta(days=30)).isoformat()})
    assert _novedades("loga", p) == {"contenido", "lotes", "fotos", "facturas"}
    _salir(client)
    assert _secciones_con_marca(_visita(client, "loga", p)) == {"contenido", "lotes", "fotos", "facturas"}


def test_el_cliente_solo_ve_novedades_de_proforma_documentos_y_facturas(app, client):
    p = _pedido(client, con_proforma=True)
    _visita(client, "cliA", p)
    login(client, "loga")
    client.post(f"/pedidos/{p.id}/guardar", data={f"precio_kit_{p.kits[0].id}": "90,00"})
    client.post(f"/pedidos/{p.id}/lotes", data={"accion": "automatico"})
    assert _novedades("cliA", p) == set()              # contenido y lotes: cosas internas de Yikon
    client.post(f"/pedidos/{p.id}/proforma/enviar", data={
        "valida_hasta": (date.today() + timedelta(days=30)).isoformat(), "plazo_entrega": "5 días",
        "pdf": pdf_proforma()})
    _subir_documento(client, p)
    _salir(client)
    assert _novedades("cliA", p) == {"proforma", "documentos"}
    html = _visita(client, "cliA", p)
    assert _secciones_con_marca(html) == {"proforma", "documentos"} and not re.search(r"\bL1\b", html)   # (el nombre del lote, no un trozo del token CSRF)
    # y al revés: cuando el cliente la acepta, es novedad para el FAS
    _visita(client, "loga", p)
    login(client, "cliA"); client.post(f"/pedidos/{p.id}/proforma/responder", data={"aceptar": "1"}); _salir(client)
    assert _novedades("loga", p) == {"proforma"}


def test_el_fas_no_recibe_novedades_de_pedidos_de_otros_clientes(app, client):
    p = _pedido(client)                                 # Clínica A
    login(client, "logb")                               # FAS de la Clínica B: ni lo puede abrir
    assert client.get(f"/pedidos/{p.id}").status_code == 404
    _salir(client)
    login(client, "ofi"); _subir_documento(client, p); _salir(client)
    login(client, "logb")
    assert "Novedades desde tu última visita" not in client.get("/pedidos/").get_data(as_text=True)


def test_la_lista_de_pedidos_marca_los_que_tienen_novedades(app, client):
    """(El inicio ya no lleva tabla de pedidos: la marca "nuevo" está en la lista.)"""
    p = _pedido(client)
    _visita(client, "loga", p)
    login(client, "ofi"); _subir_documento(client, p); _salir(client)
    login(client, "loga")
    lista = client.get("/pedidos/").get_data(as_text=True)
    assert f'/pedidos/{p.id}#documentos' in lista and "Novedades desde tu última visita: documentos" in lista
    client.get(f"/pedidos/{p.id}")                       # al abrirlo deja de salir
    assert "Novedades desde tu última visita" not in client.get("/pedidos/").get_data(as_text=True)
