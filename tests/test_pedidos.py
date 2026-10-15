from decimal import Decimal

from app.extensions import db
from app.models import Cliente, Factura, Pedido, RegistroAuditoria
from tests.conftest import doc_pedido, ref, contenido, login, pedido_cliente


def test_pedido_de_cliente_genera_referencia_interna(app, client):
    login(client, "cliA")
    r = pedido_cliente(client, referencia="OC-1", cantidad=3)
    assert r.status_code == 302
    pedido_cliente(client, referencia="OC-2")
    refs = db.session.scalars(db.select(Pedido.referencia_interna).order_by(Pedido.id)).all()
    assert refs == [ref("CLA", 1), ref("CLA", 2)]
    p = db.session.scalar(db.select(Pedido).filter_by(referencia_interna=ref("CLA", 1)))
    assert p.estado == "aceptado" and p.lineas[0].cantidad == 3 and p.referencia == "OC-1"


def test_numeracion_independiente_por_cliente(app, client):
    login(client, "cliA"); pedido_cliente(client); pedido_cliente(client)
    client.post("/auth/logout")
    login(client, "cliB"); pedido_cliente(client)
    assert db.session.scalar(db.select(Pedido.referencia_interna).order_by(Pedido.id.desc())) == ref("CLB", 1)


def test_numero_no_se_reutiliza_si_se_borra_un_pedido(app, client):
    login(client, "cliA"); pedido_cliente(client); pedido_cliente(client)
    db.session.delete(db.session.scalar(db.select(Pedido).filter_by(referencia_interna=ref("CLA", 2))))
    db.session.commit()
    pedido_cliente(client)
    assert db.session.scalar(db.select(Pedido.referencia_interna).order_by(Pedido.id.desc())) == ref("CLA", 3)


def test_referencia_empresa_unica_por_cliente_no_global(app, client):
    login(client, "cliA"); pedido_cliente(client, referencia="PO-1")
    r = pedido_cliente(client, referencia="PO-1")
    assert "Ya hay un pedido" in r.get_data(as_text=True)
    client.post("/auth/logout")
    login(client, "cliB")
    assert pedido_cliente(client, referencia="PO-1").status_code == 302  # otra empresa: OK


def test_prefijo_automatico_desde_el_nombre(app, client):
    login(client, "admin")
    client.post("/clientes/nuevo", data={"nombre": "DiNA Science", "activo": "y"})
    assert db.session.scalar(db.select(Cliente.prefijo).filter_by(nombre="DiNA Science")) == "DiNA"
    r = client.post("/clientes/nuevo", data={"nombre": "dina bis", "activo": "y"})
    assert "ya lo usa" in r.get_data(as_text=True)


def test_flujo_logistics_y_factura(app, client):
    login(client, "loga")
    a = db.session.scalar(db.select(Cliente).filter_by(nombre="Clínica A"))
    # en un solo paso: cliente + productos
    client.post("/pedidos/nuevo", data={"uso": "ruo", "documento": doc_pedido(), "cliente_id": a.id, "fecha": "2026-09-01",
                                        "contenido": contenido(sueltos={1: 2})})
    pedido = db.session.scalar(db.select(Pedido))
    assert pedido.referencia_interna == ref("CLA", 1) and pedido.estado == "aceptado"
    assert pedido.base_imponible == 200
    # después se pueden retocar las líneas (p. ej. añadir una con otro precio)
    client.post(f"/pedidos/{pedido.id}/lineas", data={"producto_id": 1, "cantidad": 1, "precio": "70"})   # precio a mano
    assert pedido.base_imponible == 270 and pedido.total == Decimal("326.70")
    assert client.post(f"/pedidos/{pedido.id}/preparacion").status_code == 403   # preparar es de admin
    assert client.get(f"/facturas/nueva?pedido_id={pedido.id}").status_code == 403

    client.post("/auth/logout")
    login(client, "admin")
    r = client.post("/facturas/nueva", data={
        "numero": "F-2026-001", "cliente_id": a.id, "pedido_id": pedido.id,
        "fecha_emision": "2026-09-02", "base_imponible": "270", "iva": "56.70",
        "total": "326.70", "estado": "pendiente"})
    assert r.status_code == 302
    f = db.session.scalar(db.select(Factura))
    client.post(f"/facturas/{f.id}/pagada")
    assert db.session.get(Factura, f.id).estado == "pagada"
    assert db.session.scalar(db.select(db.func.count(RegistroAuditoria.id))) >= 5


def test_cliente_no_puede_tocar_lineas_ni_confirmar(app, client):
    login(client, "cliA"); pedido_cliente(client)
    p = db.session.scalar(db.select(Pedido))
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert "Dto. %" not in html and "Empezar preparación" not in html
    assert client.post(f"/pedidos/{p.id}/lineas", data={"producto_id": 1, "cantidad": 1, "descuento_pct": 100}).status_code == 403
    assert client.post(f"/pedidos/{p.id}/preparacion").status_code == 403
    client.post("/auth/logout")
    login(client, "admin")   # admin lo empieza a preparar
    client.post(f"/pedidos/{p.id}/preparacion")
    assert db.session.get(Pedido, p.id).estado == "en_preparacion"


def test_cliente_pide_varios_kits(app, client):
    from app.models import ComponenteKit, Kit, Producto
    p2 = Producto(referencia="P2", nombre="Producto 2", precio=50)
    db.session.add(Kit(referencia="K2", nombre="Kit dos", precio=80, componentes=[ComponenteKit(producto=p2, cantidad=1)]))
    db.session.commit()
    login(client, "cliA")
    r = client.post("/pedidos/nuevo", data={"uso": "ruo", "documento": doc_pedido(), 
        "contenido": contenido([(1, 2, {1: 2}), (2, 1, {p2.id: 5}), (1, 1, {1: 1})]),   # K1 dos veces
        "fecha": "2026-09-25", "referencia": "OC-VARIOS"})
    assert r.status_code == 302
    p = db.session.scalar(db.select(Pedido))
    assert [(k.kit.referencia, k.cantidad, k.modificado) for k in p.kits] == [
        ("K1", 2, False), ("K2", 1, True), ("K1", 1, False)]         # K2: 5 en vez de 1 → modificado
    assert sorted((l.producto.referencia, l.cantidad) for l in p.lineas) == [("P1", 1), ("P1", 2), ("P2", 5)]
    assert p.base_imponible == 2 * 100 + 80 + 100                     # precio de los kits


def test_pedido_sin_kits_no_se_crea(app, client):
    login(client, "cliA")
    r = client.post("/pedidos/nuevo", data={"uso": "ruo", "documento": doc_pedido(), "contenido": contenido([]), "fecha": "2026-09-25", "referencia": "X"})
    assert "al menos un kit" in r.get_data(as_text=True)
    assert db.session.scalar(db.select(db.func.count(Pedido.id))) == 0


def test_ventana_de_nuevo_pedido(app, client):
    login(client, "cliA")
    html = client.get("/").get_data(as_text=True)
    assert 'id="modal-pedido"' in html and 'data-bs-target="#modal-pedido"' in html
    assert client.get("/pedidos/").get_data(as_text=True).count('id="modal-pedido"') == 1
    # en la página "Nuevo pedido" no se duplica el formulario
    assert 'id="modal-pedido"' not in client.get("/pedidos/nuevo").get_data(as_text=True)
    client.post("/auth/logout")
    # admin y logistics también tienen la ventana (con el desplegable de cliente)
    login(client, "loga")
    html = client.get("/pedidos/").get_data(as_text=True)
    assert html.count('id="modal-pedido"') == 1 and 'name="cliente_id"' in html
    assert "Clínica A" in html and "Clínica B" not in html          # logistics: solo sus clientes


def test_referencia_de_empresa_obligatoria(app, client):
    login(client, "cliA")
    r = client.post("/pedidos/nuevo", data={"uso": "ruo", "documento": doc_pedido(), "contenido": contenido([(1, 1, {1: 1})]),
                                            "fecha": "2026-09-25", "referencia": "  "})
    assert "es obligatorio" in r.get_data(as_text=True)
    assert db.session.scalar(db.select(db.func.count(Pedido.id))) == 0


def test_la_ventana_muestra_la_proxima_referencia_interna(app, client):
    login(client, "cliA")
    assert ref("CLA", 1) in client.get("/").get_data(as_text=True)
    pedido_cliente(client)
    assert ref("CLA", 2) in client.get("/").get_data(as_text=True)
    # enseñarla no la "gasta": el siguiente pedido es de verdad el 2
    pedido_cliente(client)
    assert db.session.scalar(db.select(Pedido.referencia_interna).order_by(Pedido.id.desc())) == ref("CLA", 2)


def test_cambiar_estado_es_un_boton_con_ventana(app, client):
    from tests.conftest import pedido_cliente as _pedido
    login(client, "cliA"); _pedido(client); client.post("/auth/logout")
    p = db.session.scalar(db.select(Pedido))
    login(client, "admin")
    html = client.get(f"/pedidos/{p.id}").get_data(as_text=True)
    assert 'data-bs-target="#modal-estado"' in html and 'id="modal-estado"' in html and 'id="form-estado"' in html
    client.post("/auth/logout"); login(client, "cliA")
    assert 'id="modal-estado"' not in client.get(f"/pedidos/{p.id}").get_data(as_text=True)   # el cliente no


def test_la_lista_dice_cuantos_hay_y_deja_elegir_cuantos_por_pagina(app, client):
    from app.models import Cliente, Pedido
    a = db.session.scalar(db.select(Cliente).filter_by(nombre="Clínica A"))
    db.session.add_all([Pedido(cliente=a, referencia=f"OC-{n}", referencia_interna=f"PAG_{n:03d}", estado="aceptado")
                        for n in range(60)])
    db.session.commit()
    login(client, "admin")
    html = client.get("/pedidos/").get_data(as_text=True)
    assert "1–10 de 60" in html and "por_pagina=50" in html and html.count("PAG_") == 10     # 10 por página
    html = client.get("/pedidos/?por_pagina=50&pagina=2").get_data(as_text=True)
    assert "51–60 de 60" in html and html.count("PAG_") == 10
    assert client.get("/pedidos/?por_pagina=9999").get_data(as_text=True).count("PAG_") == 10   # tamaño no admitido


def test_la_referencia_lleva_el_anio_y_el_numero_vuelve_a_1_cada_anio(app, client, monkeypatch):
    from app import models
    from app.models import Cliente
    a = db.session.scalar(db.select(Cliente).filter_by(nombre="Clínica A"))
    login(client, "cliA")
    monkeypatch.setattr(models, "anio_actual", lambda: 2026)
    pedido_cliente(client); pedido_cliente(client)
    assert a.proxima_referencia_interna == "YK-2026-CLA-003"
    monkeypatch.setattr(models, "anio_actual", lambda: 2027)          # cambia el año
    assert a.proxima_referencia_interna == "YK-2027-CLA-001"
    pedido_cliente(client)
    refs = db.session.scalars(db.select(Pedido.referencia_interna).order_by(Pedido.id)).all()
    assert refs == ["YK-2026-CLA-001", "YK-2026-CLA-002", "YK-2027-CLA-001"]
    assert (a.contador_pedidos, a.anio_contador) == (1, 2027)


def test_los_clientes_con_pedidos_antiguos_siguen_su_cuenta_este_anio(app, client):
    """Lo que hace la migración: quien ya tenía 4 pedidos (CLA_004) sigue por el 5 este año."""
    from app.models import Cliente, anio_actual
    a = db.session.scalar(db.select(Cliente).filter_by(nombre="Clínica A"))
    a.contador_pedidos, a.anio_contador = 4, anio_actual()
    db.session.commit()
    assert a.proxima_referencia_interna == ref("CLA", 5)
