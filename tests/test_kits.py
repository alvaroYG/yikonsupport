"""Kits: catálogo, precio automático por cliente, pedido por kits y edición en la ficha."""
from decimal import Decimal

from app.models import ahora  # facturas ya enviadas al cliente (las ve)
from app.extensions import db
from app.models import ComponenteKit, Kit, KitPedido, LineaPedido, Pedido, PrecioCliente, Producto
from tests.conftest import doc_pedido, contenido, llevar_a_validado, login, proforma_aceptada, reservar_lotes
from tests.test_inventario import _entrada, _estado


def _kit_completo():
    """Kit "KC" = 1 × P1 + 2 × P2, a 250 €."""
    p2 = Producto(referencia="P2", nombre="Tubos", precio=10)
    kit = Kit(referencia="KC", nombre="Kit completo", precio=250, cerrado=False,   # montado: stock de sus productos
              componentes=[ComponenteKit(producto_id=1, cantidad=1), ComponenteKit(producto=p2, cantidad=2)])
    db.session.add(kit); db.session.commit()
    return kit, p2


def _pedir(client, kits, sueltos=None, referencia="OC-K", **extra):
    r = client.post("/pedidos/nuevo", data={"documento": doc_pedido(), "contenido": contenido(kits, sueltos), "fecha": "2026-09-25",
                                            "referencia": referencia, **extra})
    proforma_aceptada()        # sin pasar por la proforma (eso se prueba en test_proformas.py)
    return r


# ---------------------------------------------------------------- catálogo
def test_admin_crea_y_edita_kits(app, client):
    login(client, "admin")
    p2 = Producto(referencia="P2", nombre="Tubos", precio=10); db.session.add(p2); db.session.commit()
    r = client.post("/productos/kits/nuevo", data={
        "referencia": "kn", "nombre": "Kit nuevo", "precio": "300", "iva_pct": "21.00", "activo": "y",
        "componentes-0-producto_id": 1, "componentes-0-cantidad": 1,
        "componentes-1-producto_id": p2.id, "componentes-1-cantidad": 4})
    assert r.status_code == 302
    kit = db.session.scalar(db.select(Kit).filter_by(referencia="KN"))
    assert sorted((c.producto.referencia, c.cantidad) for c in kit.componentes) == [("P1", 1), ("P2", 4)]
    # editar: quitar P1 y dejar 3 tubos
    client.post(f"/productos/kits/{kit.id}/editar", data={
        "referencia": "KN", "nombre": "Kit nuevo", "precio": "280", "iva_pct": "21.00", "activo": "y",
        "componentes-0-producto_id": p2.id, "componentes-0-cantidad": 3})
    db.session.refresh(kit)
    assert [(c.producto.referencia, c.cantidad) for c in kit.componentes] == [("P2", 3)] and kit.precio == 280
    # un kit sin productos no se guarda
    r = client.post("/productos/kits/nuevo", data={"referencia": "VACIO", "nombre": "x", "precio": "1",
                                                   "iva_pct": "21.00", "componentes-0-producto_id": 0})
    assert "Añade al menos un producto" in r.get_data(as_text=True)


def test_solo_admin_edita_kits(app, client):
    login(client, "loga")
    assert client.get("/productos/kits").status_code == 200          # logistics los ve
    assert client.get("/productos/kits/nuevo").status_code == 403
    client.post("/auth/logout"); login(client, "cliA")
    assert client.get("/productos/kits").status_code == 403


# ---------------------------------------------------------------- precios por cliente
def test_precio_especial_del_cliente_se_aplica_al_pedido(app, client):
    kit, p2 = _kit_completo()
    login(client, "admin")
    client.post("/clientes/1/precios", data={"kit_id": kit.id, "precio": "199,90"})
    assert db.session.scalar(db.select(PrecioCliente.precio).filter_by(cliente_id=1)) == Decimal("199.90")
    client.post("/auth/logout")
    login(client, "cliA"); _pedir(client, [(kit.id, 2, {1: 2, p2.id: 4})], referencia="A1"); client.post("/auth/logout")
    login(client, "cliB"); _pedir(client, [(kit.id, 1, {1: 1, p2.id: 2})], referencia="B1")
    a, b = db.session.scalars(db.select(Pedido).order_by(Pedido.id)).all()
    assert a.kits[0].precio_unitario == Decimal("199.90") and a.base_imponible == Decimal("399.80")
    assert b.kits[0].precio_unitario == 250                               # B: precio estándar
    # quitar el precio especial: los pedidos ya hechos no cambian
    client.post("/auth/logout"); login(client, "admin")
    precio = db.session.scalar(db.select(PrecioCliente))
    client.post(f"/clientes/1/precios/{precio.id}/borrar")
    assert db.session.scalar(db.select(PrecioCliente)) is None
    assert db.session.get(Pedido, a.id).kits[0].precio_unitario == Decimal("199.90")


def test_solo_admin_cambia_precios_de_clientes(app, client):
    kit, _p2 = _kit_completo()
    login(client, "loga")
    assert client.post("/clientes/1/precios", data={"kit_id": kit.id, "precio": "1"}).status_code == 403
    html = client.get("/clientes/1").get_data(as_text=True)
    assert "Precios especiales" in html and 'id="panel-precios-kits"' in html            # los ve


# ---------------------------------------------------------------- pedido por kits
def test_cliente_quita_productos_y_cambia_cantidades(app, client):
    kit, p2 = _kit_completo()
    login(client, "cliA")
    assert _pedir(client, [(kit.id, 2, {1: 2, p2.id: 0})]).status_code == 302     # sin tubos
    p = db.session.scalar(db.select(Pedido))
    kp = p.kits[0]
    assert [(l.producto_id, l.cantidad) for l in kp.lineas] == [(1, 2)] and kp.modificado
    assert kp.precio_unitario == 250 and p.base_imponible == 500           # precio del kit, no de sus productos


def test_el_cliente_no_puede_meter_productos_ajenos_al_kit_pero_si_sueltos(app, client):
    """Dentro de un kit solo van sus productos; fuera, el cliente puede pedir productos sueltos
    (desde el 14/10/2026; con catálogo propio, solo los suyos: test_catalogo_cliente.py)."""
    kit, p2 = _kit_completo()
    otro = Producto(referencia="OTRO", nombre="Otro", precio=999); db.session.add(otro); db.session.commit()
    login(client, "cliA")
    r = _pedir(client, [(kit.id, 1, {1: 1, otro.id: 5})])
    assert r.status_code == 200 and "No se ha podido leer" in r.get_data(as_text=True)
    r = _pedir(client, [(kit.id, 1, {1: 1})], sueltos={otro.id: 1})
    assert r.status_code == 302
    pedido = db.session.scalar(db.select(Pedido).order_by(Pedido.id.desc()))
    assert [(l.producto.referencia, l.cantidad) for l in pedido.lineas_sueltas] == [("OTRO", 1)]
    r = _pedir(client, [(kit.id, 1, {1: 0, p2.id: 0})])
    assert "no tiene ningún producto" in r.get_data(as_text=True)
    assert db.session.scalar(db.select(db.func.count(Pedido.id))) == 1        # solo el de los sueltos


def test_logistics_pide_kits_y_sueltos(app, client):
    kit, p2 = _kit_completo()
    login(client, "loga")
    client.post("/pedidos/nuevo", data={"documento": doc_pedido(), "cliente_id": 1, "fecha": "2026-09-25",
                                        "contenido": contenido([(kit.id, 1, {1: 1, p2.id: 2})], {p2.id: 5})})
    p = db.session.scalar(db.select(Pedido))
    assert not p.kits[0].modificado
    assert [(l.producto_id, l.cantidad, l.precio_unitario) for l in p.lineas_sueltas] == [(p2.id, 5, 10)]
    assert p.base_imponible == 250 + 50


def test_la_ficha_agrupa_por_kit_y_el_cliente_no_ve_precios(app, client):
    kit, p2 = _kit_completo()
    login(client, "cliA"); _pedir(client, [(kit.id, 1, {1: 1, p2.id: 2})])
    p = db.session.scalar(db.select(Pedido))
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert "Kit completo" in html and "Tubos" in html and "250" not in html and "precio_kit_" not in html
    client.post("/auth/logout"); login(client, "loga")
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert f'name="precio_kit_{p.kits[0].id}"' in html


# ---------------------------------------------------------------- edición en la ficha
def test_precio_a_mano_y_cantidades(app, client):
    kit, p2 = _kit_completo()
    login(client, "cliA"); _pedir(client, [(kit.id, 1, {1: 1, p2.id: 2})]); client.post("/auth/logout")
    p = db.session.scalar(db.select(Pedido)); kp = p.kits[0]
    linea_tubos = next(l for l in kp.lineas if l.producto_id == p2.id)
    login(client, "loga")
    client.post(f"/pedidos/{p.id}/guardar", data={f"precio_kit_{kp.id}": "1.234,50",
                                                   f"cantidad_linea_{linea_tubos.id}": "3"})
    db.session.refresh(kp)
    assert kp.precio_unitario == Decimal("1234.50") and linea_tubos.cantidad == 3 and kp.modificado
    # un valor no válido no guarda NADA
    client.post(f"/pedidos/{p.id}/guardar", data={f"precio_kit_{kp.id}": "barato",
                                                   f"cantidad_linea_{linea_tubos.id}": "9"})
    db.session.refresh(kp); db.session.refresh(linea_tubos)
    assert kp.precio_unitario == Decimal("1234.50") and linea_tubos.cantidad == 3
    # en preparación: el precio se puede cambiar, las cantidades ya no
    client.post("/auth/logout"); login(client, "admin")
    client.post(f"/pedidos/{p.id}/preparacion")
    client.post(f"/pedidos/{p.id}/guardar", data={f"precio_kit_{kp.id}": "1000",
                                                   f"cantidad_linea_{linea_tubos.id}": "7"})
    db.session.refresh(kp); db.session.refresh(linea_tubos)
    assert kp.precio_unitario == 1000 and linea_tubos.cantidad == 3
    # el cliente no puede guardar cambios
    client.post("/auth/logout"); login(client, "cliA")
    assert client.post(f"/pedidos/{p.id}/guardar", data={f"precio_kit_{kp.id}": "1"}).status_code == 403


def test_anadir_y_quitar_kits_en_la_ficha(app, client):
    kit, p2 = _kit_completo()
    login(client, "loga")
    client.post("/pedidos/nuevo", data={"documento": doc_pedido(), "cliente_id": 1, "fecha": "2026-09-25", "contenido": contenido(sueltos={1: 1})})
    p = db.session.scalar(db.select(Pedido))
    client.post(f"/pedidos/{p.id}/kits", data={"kit_id": kit.id, "cantidad": 2})
    db.session.refresh(p)
    assert len(p.kits) == 1 and sorted((l.producto_id, l.cantidad) for l in p.kits[0].lineas) == [(1, 2), (p2.id, 4)]
    # quitar un producto del kit → modificado; quitar el último → desaparece el kit
    kp = p.kits[0]
    lineas = list(kp.lineas)
    client.post(f"/pedidos/{p.id}/lineas/{lineas[0].id}/borrar")
    db.session.refresh(kp)
    assert kp.modificado and len(kp.lineas) == 1
    client.post(f"/pedidos/{p.id}/lineas/{lineas[1].id}/borrar")
    assert db.session.scalar(db.select(db.func.count(KitPedido.id))) == 0
    # quitar un kit entero borra también sus productos
    client.post(f"/pedidos/{p.id}/kits", data={"kit_id": kit.id, "cantidad": 1})
    kp = db.session.scalar(db.select(KitPedido))
    client.post(f"/pedidos/{p.id}/kits/{kp.id}/borrar")
    assert db.session.scalar(db.select(db.func.count(LineaPedido.id))) == 1     # solo el suelto


def test_el_stock_sale_de_los_productos_del_kit(app, client):
    kit, p2 = _kit_completo()
    login(client, "cliA"); _pedir(client, [(kit.id, 2, {1: 2, p2.id: 3})]); client.post("/auth/logout")
    p = db.session.scalar(db.select(Pedido))
    login(client, "admin"); client.post(f"/pedidos/{p.id}/preparacion"); client.post("/auth/logout")
    llevar_a_validado(client, p.id)
    login(client, "admin")
    _entrada(client, 10); _entrada(client, 10, producto_id=p2.id)
    reservar_lotes(client, p.id)             # el stock ha entrado después del pedido: se le asignan los lotes
    _estado(client, p, "enviado")
    assert db.session.get(Pedido, p.id).estado == "enviado"
    assert db.session.get(Producto, 1).stock == 8 and db.session.get(Producto, p2.id).stock == 7


def test_repetir_pedido_con_kits_modificados(app, client):
    import json
    import re
    kit, p2 = _kit_completo()
    login(client, "cliA"); _pedir(client, [(kit.id, 1, {1: 1, p2.id: 5})])
    p = db.session.scalar(db.select(Pedido))
    html = client.get(f"/pedidos/nuevo?repetir={p.id}").get_data(as_text=True)
    valor = re.search(r'name="contenido" type="hidden" value="([^"]*)"', html).group(1).replace("&#34;", '"')
    assert json.loads(valor)["kits"] == [{"kit_id": kit.id, "cantidad": 1,
                                          "productos": [{"producto_id": 1, "cantidad": 1}, {"producto_id": p2.id, "cantidad": 5}]}]


# ---------------------------------------------------------------- revisión de los kits
def test_json_manipulado_no_da_error_500(app, client):
    """Antes: NaN, 1e400, "3", listas anidadas sin fin... acababan en error 500."""
    login(client, "cliA")
    base = '{"kits": [{"kit_id": 1, "cantidad": %s, "productos": [{"producto_id": 1, "cantidad": %s}]}]}'
    malos = [base % ("1", "NaN"), base % ("1", "Infinity"), base % ("1", "1e400"), base % ('"1"', "1"),
             base % ("1", "2.5"), base % ("true", "1"), base % ("1", "-1"), base % ("5000", "1"),
             "[" * 5000 + "]" * 5000, "x" * 60000, '{"kits": "hola"}', "null"]
    for texto in malos:
        r = client.post("/pedidos/nuevo", data={"documento": doc_pedido(), "contenido": texto, "fecha": "2026-09-25", "referencia": "OC-X"})
        assert r.status_code == 200, texto[:40]
    assert db.session.scalar(db.select(db.func.count(Pedido.id))) == 0


def test_filas_repetidas_no_superan_el_maximo(app, client):
    login(client, "cliA")
    import json
    datos = {"kits": [{"kit_id": 1, "cantidad": 1,
                       "productos": [{"producto_id": 1, "cantidad": 100000}] * 5}]}
    r = client.post("/pedidos/nuevo", data={"documento": doc_pedido(), "contenido": json.dumps(datos), "fecha": "2026-09-25",
                                            "referencia": "OC-X"})
    assert r.status_code == 200 and db.session.scalar(db.select(db.func.count(Pedido.id))) == 0


def test_producto_dado_de_baja_sale_del_kit(app, client):
    kit, p2 = _kit_completo()
    p2.activo = False; db.session.commit()
    login(client, "cliA")
    html = client.get("/pedidos/nuevo").get_data(as_text=True)
    assert "Tubos" not in html                               # no se ofrece en la ventana
    _pedir(client, [(kit.id, 1, {1: 1, p2.id: 2})])         # ni se acepta si lo mandan igual
    assert db.session.scalar(db.select(db.func.count(Pedido.id))) == 0
    _pedir(client, [(kit.id, 1, {1: 1})])
    p = db.session.scalar(db.select(Pedido))
    assert not p.kits[0].modificado                          # el kit "estándar" ya no lleva tubos
    # añadir el kit desde la ficha tampoco mete el producto de baja
    client.post("/auth/logout"); login(client, "loga")
    client.post(f"/pedidos/{p.id}/kits", data={"kit_id": kit.id, "cantidad": 1})
    assert db.session.scalar(db.select(db.func.count(LineaPedido.id)).filter_by(producto_id=p2.id)) == 0


def test_enter_en_la_tabla_no_borra_el_primer_kit(app, client):
    """Antes: los ✕ eran del formulario de "Guardar", y Enter pulsaba el primero (quitar kit)."""
    login(client, "cliA"); _pedir(client, [(1, 1, {1: 1})]); client.post("/auth/logout")
    p = db.session.scalar(db.select(Pedido))
    login(client, "loga")
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    inicio = html.index(f'action="/pedidos/{p.id}/guardar"')
    formulario = html[inicio:html.index("</form>", inicio)]
    boton_quitar = formulario.index(f"/pedidos/{p.id}/kits/")
    assert 'form="form-quitar"' in formulario[boton_quitar - 200:boton_quitar]
    assert 'id="form-quitar"' in html
    # los formularios de añadir kit y producto no repiten id con otros campos de la página
    assert 'id="kit-cantidad"' in html and 'id="suelto-cantidad"' in html


def test_cambiar_el_numero_de_kits_en_la_ficha(app, client):
    kit, p2 = _kit_completo()
    login(client, "cliA"); _pedir(client, [(kit.id, 1, {1: 1, p2.id: 2})]); client.post("/auth/logout")
    p = db.session.scalar(db.select(Pedido)); kp = p.kits[0]
    login(client, "loga")
    datos = {f"cantidad_kit_{kp.id}": "3"}
    datos.update({f"cantidad_linea_{l.id}": str(l.cantidad) for l in kp.lineas})   # lo que manda la tabla
    client.post(f"/pedidos/{p.id}/guardar", data=datos)
    db.session.refresh(kp)
    assert kp.cantidad == 3 and not kp.modificado
    assert sorted((l.producto_id, l.cantidad) for l in kp.lineas) == [(1, 3), (p2.id, 6)]
    assert p.base_imponible == Decimal("750.00")
    assert client.post(f"/pedidos/{p.id}/guardar", data={f"cantidad_kit_{kp.id}": "0"}).status_code == 302
    db.session.refresh(kp)
    assert kp.cantidad == 3                                  # 0 no es válido: no cambia nada


def test_precios_desorbitados_se_rechazan(app, client):
    login(client, "cliA"); _pedir(client, [(1, 1, {1: 1})]); client.post("/auth/logout")
    p = db.session.scalar(db.select(Pedido)); kp = p.kits[0]
    login(client, "admin")
    for malo in ["1e20", "NaN", "-5", "999999999"]:
        client.post(f"/pedidos/{p.id}/guardar", data={f"precio_kit_{kp.id}": malo})
        client.post("/clientes/1/precios", data={"kit_id": 1, "precio": malo})
    db.session.refresh(kp)
    assert kp.precio_unitario == 100
    assert db.session.scalar(db.select(db.func.count(PrecioCliente.id))) == 0
    r = client.post(f"/pedidos/{p.id}/lineas", data={"producto_id": 1, "cantidad": 1, "precio": "1e12"})
    assert db.session.scalar(db.select(db.func.count(LineaPedido.id))) == 1


def test_con_factura_ya_no_se_cambian_precios(app, client):
    from datetime import date
    from app.models import Factura
    login(client, "cliA"); _pedir(client, [(1, 1, {1: 1})]); client.post("/auth/logout")
    p = db.session.scalar(db.select(Pedido)); kp = p.kits[0]
    db.session.add(Factura(enviada_el=ahora(), numero="F-9", cliente_id=1, pedido=p, fecha_emision=date(2026, 9, 1),
                           base_imponible=100, iva=21, total=121)); db.session.commit()
    login(client, "admin")
    assert f"precio_kit_{kp.id}" not in client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    client.post(f"/pedidos/{p.id}/guardar", data={f"precio_kit_{kp.id}": "5"})
    db.session.refresh(kp)
    assert kp.precio_unitario == 100


def test_orden_manual_de_los_productos_del_kit(app, client):
    """El orden de las filas del formulario es el orden del kit, y los pedidos nuevos lo siguen."""
    p2 = Producto(referencia="P2", nombre="Tubos", precio=10)
    p3 = Producto(referencia="P3", nombre="Placas", precio=10)
    db.session.add_all([p2, p3]); db.session.commit()
    login(client, "admin")
    base = {"referencia": "KO", "nombre": "Kit ordenado", "precio": "300", "iva_pct": "21.00", "activo": "y"}
    client.post("/productos/kits/nuevo", data={**base,
        "componentes-0-producto_id": p3.id, "componentes-0-cantidad": 1,
        "componentes-1-producto_id": 1, "componentes-1-cantidad": 2,
        "componentes-2-producto_id": p2.id, "componentes-2-cantidad": 3})
    kit = db.session.scalar(db.select(Kit).filter_by(referencia="KO"))
    assert [c.producto.referencia for c in kit.componentes] == ["P3", "P1", "P2"]
    # reordenar (como tras pulsar las flechas): P1, P2, P3 — mismas cantidades
    client.post(f"/productos/kits/{kit.id}/editar", data={**base,
        "componentes-0-producto_id": 1, "componentes-0-cantidad": 2,
        "componentes-1-producto_id": p2.id, "componentes-1-cantidad": 3,
        "componentes-2-producto_id": p3.id, "componentes-2-cantidad": 1})
    db.session.expire_all()
    kit = db.session.get(Kit, kit.id)
    assert [c.producto.referencia for c in kit.componentes] == ["P1", "P2", "P3"]
    from app.models import RegistroAuditoria
    assert "orden cambiado" in db.session.scalar(db.select(RegistroAuditoria.detalle)
                                                  .order_by(RegistroAuditoria.id.desc()))
    # un pedido nuevo lleva sus productos en ese orden, aunque lleguen desordenados
    client.post("/auth/logout"); login(client, "cliA")
    _pedir(client, [(kit.id, 1, {p3.id: 1, p2.id: 3, 1: 2})], referencia="OC-ORDEN")
    pedido = db.session.scalar(db.select(Pedido).filter_by(referencia="OC-ORDEN"))
    assert [l.producto.referencia for l in pedido.kits[0].lineas] == ["P1", "P2", "P3"]
