"""
Bloque "Pendientes" del inicio (app/pedidos/pendientes.py): lo que cada persona tiene que
hacer. Sale del estado de los pedidos y NO se va por abrir el pedido: solo cuando se hace.
"""
from datetime import date, timedelta

from app.extensions import db
from app.models import Pedido
from tests.conftest import login, pedido_cliente, reservar_lotes, subir_foto, pdf_proforma


def _salir(client):
    client.post("/auth/logout")


def _grupos(client, usuario):
    """{clave del grupo: su HTML} de lo que ve este usuario en el bloque "Pendientes" del inicio."""
    login(client, usuario)
    html = client.get("/").get_data(as_text=True)
    _salir(client)
    if 'id="pendientes"' not in html:
        # El cliente no tiene ese bloque: lo que le toca son las líneas con punto de "Tus pedidos
        # en curso" (data-toca="responder" | "recibir" | "mensajes")
        return {t.split('"')[0]: t.split('<div class="mini-pasos"')[0] for t in html.split('data-toca="')[1:]}
    bloque = html.split('id="pendientes"')[1]
    trozos = bloque.split('data-grupo="')[1:]
    return {t.split('"')[0]: t.split("</section>")[0] for t in trozos}


def _entrada(client, cantidad=10):
    login(client, "admin")
    client.post("/inventario/movimiento", data={"articulo": "producto-1", "tipo": "entrada", "cantidad": cantidad,
                                                "lote": "L1", "caducidad": "2099-12-31"})
    _salir(client)


def _pedir_proforma(client, cantidad=1):
    login(client, "cliA"); pedido_cliente(client, cantidad=cantidad, con_proforma=True); _salir(client)
    return db.session.scalar(db.select(Pedido).order_by(Pedido.id.desc()))


def _enviar_proforma(client, p, usuario="loga"):
    login(client, usuario)
    client.post(f"/pedidos/{p.id}/proforma/enviar", data={
        "valida_hasta": (date.today() + timedelta(days=30)).isoformat(), "plazo_entrega": "5 días",
        "pdf": pdf_proforma()})
    _salir(client)


def test_sin_nada_que_hacer_el_bloque_lo_dice(app, client):
    login(client, "ofi")
    assert "No hay nada pendiente." in client.get("/").get_data(as_text=True)


def test_la_proforma_pasa_de_pendiente_de_yikon_a_pendiente_del_cliente(app, client):
    _entrada(client)
    p = _pedir_proforma(client)
    ref = p.referencia_interna
    # la tienen pendiente quienes envían proformas de ese cliente: su FAS y Facturación (Almacén, no)
    assert ref in _grupos(client, "loga")["proformas"] and ref in _grupos(client, "fac")["proformas"]
    assert _grupos(client, "ofi") == {}
    assert "proformas" not in _grupos(client, "logb")              # FAS de otra clínica
    assert _grupos(client, "cliA") == {}                           # el cliente, de momento, solo espera
    # abrir el pedido NO la quita: sigue pendiente hasta que se envía
    login(client, "loga"); client.get(f"/pedidos/{p.id}"); _salir(client)
    assert ref in _grupos(client, "loga")["proformas"]
    _enviar_proforma(client, p)
    assert "proformas" not in _grupos(client, "loga")
    assert f'href="/pedidos/{p.id}"' in _grupos(client, "cliA")["responder"]
    # el cliente acepta: deja de tenerla pendiente y Almacén tiene un pedido por empezar
    login(client, "cliA"); client.post(f"/pedidos/{p.id}/proforma/responder", data={"aceptar": "1"}); _salir(client)
    assert _grupos(client, "cliA") == {}
    assert ref in _grupos(client, "ofi")["aceptados"]
    assert ref in _grupos(client, "loga")["aceptados"]             # su FAS también lo sigue (aunque no prepara)
    assert "aceptados" not in _grupos(client, "logb")              # el de otra clínica, no


def test_cambios_pedidos_por_el_cliente_vuelven_a_ser_pendiente_de_yikon(app, client):
    _entrada(client)
    p = _pedir_proforma(client)
    _enviar_proforma(client, p)
    login(client, "cliA")
    client.post(f"/pedidos/{p.id}/proforma/responder", data={"cambios": "1", "comentario": "Otra fecha, por favor"})
    _salir(client)
    assert "el cliente ha pedido cambios" in _grupos(client, "loga")["proformas"]


def test_lotes_por_asignar_hasta_que_se_asignan(app, client):
    p = _pedir_proforma(client, cantidad=2)            # sin stock: la proforma sale "a confirmar"
    assert "lotes" not in _grupos(client, "fac")       # mientras se prepara la proforma aún no cuenta
    _enviar_proforma(client, p)
    grupo = _grupos(client, "fac")["lotes"]
    assert p.referencia_interna in grupo and "faltan 2 unidades" in grupo and f'/pedidos/{p.id}#lotes' in grupo
    assert "faltan 2 unidades" in _grupos(client, "loga")["lotes"]     # su FAS también lo ve
    assert "lotes" not in _grupos(client, "logb")
    assert "lotes" not in _grupos(client, "ofi")                     # Almacén: aún es proforma, no lo ve
    login(client, "cliA"); client.post(f"/pedidos/{p.id}/proforma/responder", data={"aceptar": "1"}); _salir(client)
    assert "faltan 2 unidades" in _grupos(client, "ofi")["lotes"]    # aceptado: ya le toca a Almacén
    _entrada(client)
    assert "faltan 2 unidades" in _grupos(client, "ofi")["lotes"]      # que entre mercancía no lo resuelve solo
    login(client, "ofi"); reservar_lotes(client, p.id); _salir(client)
    assert "lotes" not in _grupos(client, "ofi")


def test_validar_enviar_y_recibir(app, client):
    _entrada(client)
    login(client, "cliA"); pedido_cliente(client); _salir(client)
    p = db.session.scalar(db.select(Pedido))
    login(client, "admin"); client.post(f"/pedidos/{p.id}/preparacion")
    subir_foto(client, p.id); client.post(f"/pedidos/{p.id}/enviar-validacion"); _salir(client)
    assert "1 foto" in _grupos(client, "loga")["validar"]
    assert "validar" not in _grupos(client, "logb") and "validar" not in _grupos(client, "ofi")
    login(client, "loga"); client.post(f"/pedidos/{p.id}/validar", data={"aprobar": "1"}); _salir(client)
    assert "validar" not in _grupos(client, "loga")
    assert p.referencia_interna in _grupos(client, "ofi")["enviar"]
    assert p.referencia_interna in _grupos(client, "loga")["enviar"] and "enviar" not in _grupos(client, "logb")
    login(client, "ofi")
    client.post(f"/pedidos/{p.id}/estado", data={"estado": "enviado", "confirmar_stock": "1",
                                                 "transportista": "SEUR", "numero_seguimiento": "T1"})
    _salir(client)
    assert db.session.get(Pedido, p.id).estado == "enviado" and "enviar" not in _grupos(client, "ofi")
    assert p.referencia_interna in _grupos(client, "cliA")["recibir"]
    login(client, "cliA"); client.post(f"/pedidos/{p.id}/recibido"); _salir(client)
    assert "recibir" not in _grupos(client, "cliA")


def test_devuelto_por_el_fas_con_su_comentario(app, client):
    _entrada(client)
    login(client, "cliA"); pedido_cliente(client); _salir(client)
    p = db.session.scalar(db.select(Pedido))
    login(client, "admin"); client.post(f"/pedidos/{p.id}/preparacion")
    subir_foto(client, p.id); client.post(f"/pedidos/{p.id}/enviar-validacion"); _salir(client)
    login(client, "loga"); client.post(f"/pedidos/{p.id}/validar", data={"rechazar": "1", "comentario": "Falta un kit"}); _salir(client)
    grupo = _grupos(client, "ofi")["devueltos"]
    assert p.referencia_interna in grupo and "«Falta un kit»" in grupo and "Devueltos por Soporte de cliente" in grupo
    del_fas = _grupos(client, "loga")["devueltos"]       # el FAS que lo devolvió lo sigue viendo, con otro título
    assert p.referencia_interna in del_fas and "Devueltos por ti, pendientes de corregir" in del_fas
    assert "devueltos" not in _grupos(client, "logb")


def test_mensajes_sin_leer_hasta_que_se_leen(app, client):
    _entrada(client)
    login(client, "cliA"); pedido_cliente(client)
    p = db.session.scalar(db.select(Pedido))
    client.post(f"/mensajes/pedido/{p.id}", data={"texto": "¿Cuándo llega?"})
    _salir(client)
    # Yikon: los mensajes no van en "Pendientes" sino en su botón flotante
    assert "mensajes" not in _grupos(client, "loga")
    login(client, "loga")
    assert client.get("/mensajes/flotante/cuenta").get_json() == {"sin_leer": 1}
    client.get(f"/mensajes/pedido/{p.id}/nuevos?abierto=1")         # al abrir su chat, deja de estar pendiente
    assert client.get("/mensajes/flotante/cuenta").get_json() == {"sin_leer": 0}
    _salir(client)
    assert "mensajes" not in _grupos(client, "cliA")                # el suyo no es pendiente para él
