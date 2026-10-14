"""Buscador global: encuentra de todo, pero solo lo que cada usuario puede ver."""
from datetime import date, timedelta

from app.models import ahora  # facturas ya enviadas al cliente (las ve)
from app.extensions import db
from app.models import Cliente, Factura, Pedido, Ticket
from tests.conftest import login, pedido_cliente


def _grupos(client, q):
    """{clave del grupo: [títulos]} tal como los ve el usuario conectado (sin redirigir)."""
    from app.buscador import buscar
    with client:
        client.get("/")                                        # para tener current_user
        return {g["clave"]: [r["titulo"] for r in g["resultados"]] for g in buscar(q)}


def _escenario(client):
    """Un pedido y una factura por clínica, un ticket de la Clínica A y un lote."""
    for cli in ("cliA", "cliB"):
        login(client, cli); pedido_cliente(client, referencia=f"OC-ZETA-{cli}"); client.post("/auth/logout")
    pa, pb = db.session.scalars(db.select(Pedido).order_by(Pedido.id)).all()
    for p, n in ((pa, "F-ZETA-1"), (pb, "F-ZETA-2")):
        db.session.add(Factura(enviada_el=ahora(), numero=n, cliente_id=p.cliente_id, pedido=p, fecha_emision=date.today(),
                               base_imponible=100, iva=21, total=121))
    db.session.commit()
    login(client, "chrA")
    client.post("/soporte/nuevo", data={"asunto": "Zeta no carga", "categoria": "otro", "prioridad": "normal",
                                        "texto": "No carga"}, content_type="multipart/form-data")
    client.post("/auth/logout")
    login(client, "admin")
    client.post("/inventario/movimiento", data={"articulo": "producto-1", "tipo": "entrada", "cantidad": 5,
                                                "lote": "ZETA-LOTE", "caducidad": (date.today() + timedelta(days=90)).isoformat()})
    client.post("/auth/logout")
    return pa, pb


def test_admin_encuentra_de_todo(app, client):
    pa, pb = _escenario(client)
    login(client, "admin")
    g = _grupos(client, "zeta")
    assert set(g["pedidos"]) == {pa.referencia_interna, pb.referencia_interna}      # por la referencia del cliente
    assert set(g["facturas"]) == {"F-ZETA-1", "F-ZETA-2"} and g["lotes"] == ["ZETA-LOTE"]
    assert len(g["tickets"]) == 1 and "Zeta no carga" in g["tickets"][0]
    assert _grupos(client, "clínica")["clientes"] == ["Clínica A", "Clínica B"]
    assert "loga" in _grupos(client, "loga")["usuarios"]
    assert _grupos(client, "K1")["kits"] == ["Kit uno"]
    assert _grupos(client, "z") == {} and _grupos(client, "   ") == {}                # muy corto: no busca


def test_cada_rol_solo_encuentra_lo_suyo(app, client):
    pa, pb = _escenario(client)
    login(client, "loga")                                      # FAS de la Clínica A
    g = _grupos(client, "zeta")
    assert g["pedidos"] == [pa.referencia_interna] and g["facturas"] == ["F-ZETA-1"] and len(g["tickets"]) == 1
    assert "lotes" not in g                                    # ese lote no se ha enviado a sus clientes
    assert _grupos(client, "clínica")["clientes"] == ["Clínica A"]
    assert "usuarios" not in _grupos(client, "loga")
    client.post("/auth/logout")
    login(client, "logb")                                      # FAS de la Clínica B: ni el ticket de A
    g = _grupos(client, "zeta")
    assert g["pedidos"] == [pb.referencia_interna] and "tickets" not in g
    client.post("/auth/logout")
    login(client, "ofi")                                       # Logística: todos los pedidos, sin clientes ni tickets
    g = _grupos(client, "zeta")
    assert len(g["pedidos"]) == 2 and "tickets" not in g and g["lotes"] == ["ZETA-LOTE"]
    assert "clientes" not in _grupos(client, "clínica")
    client.post("/auth/logout")
    login(client, "cliB")                                      # cliente: solo lo de su empresa, sin lotes
    g = _grupos(client, "zeta")
    assert g == {"pedidos": [pb.referencia_interna], "facturas": ["F-ZETA-2"]}
    # "Kit": el producto del catálogo y SU pedido que lo lleva (no el de la otra clínica)
    assert _grupos(client, "clínica") == {}
    assert _grupos(client, "Kit") == {"productos": ["Kit 1"], "pedidos_producto": [pb.referencia_interna]}
    client.post("/auth/logout")
    login(client, "chrB")                                      # Cliente ChromGo de otra empresa: nada
    assert _grupos(client, "zeta") == {}
    client.post("/auth/logout")
    login(client, "sop")                                       # Soporte: solo tickets (y documentos)
    assert set(_grupos(client, "zeta")) == {"tickets"}


def test_pagina_sugerencias_y_salto_directo(app, client):
    pa, pb = _escenario(client)
    login(client, "admin")
    html = client.get("/buscar?q=zeta").get_data(as_text=True)
    assert pa.referencia_interna in html and "F-ZETA-2" in html and "ZETA-LOTE" in html
    datos = client.get("/buscar/sugerencias?q=zeta").get_json()
    assert pa.referencia_interna in datos["html"] and datos["q"] == "zeta"
    # un único resultado → va directo a él
    r = client.get(f"/buscar?q={pa.referencia_interna}")
    assert r.status_code == 302 and r.headers["Location"].endswith(f"/pedidos/{pa.id}")
    # textos raros no rompen (comodines, HTML, muy largos)
    for q in ("%", "__", "<script>alert(1)</script>", "x" * 500, "'; DROP TABLE pedidos; --"):
        r = client.get("/buscar", query_string={"q": q, "lista": 1})
        assert r.status_code == 200 and "<script>alert(1)</script>" not in r.get_data(as_text=True)
        assert client.get("/buscar/sugerencias", query_string={"q": q}).status_code == 200
    client.post("/auth/logout")
    assert client.get("/buscar?q=zeta").status_code == 302     # sin sesión: al login
    assert "/auth/login" in client.get("/buscar/sugerencias?q=zeta").headers["Location"]


def test_caracteres_raros_no_dan_error(app, client):
    """Revisión: "²" pasa isdigit() pero no int(); un NUL rompería el Excel; % y _ son texto, no comodines."""
    _escenario(client)
    login(client, "admin")
    for q in ("²²", "#²³", "a\x00b", "%%", "__"):
        assert client.get("/buscar", query_string={"q": q, "lista": 1}).status_code == 200, repr(q)
        assert client.get("/buscar/sugerencias", query_string={"q": q}).status_code == 200, repr(q)
        assert client.get("/inventario/rastrear-lote.xlsx", query_string={"q": q}).status_code == 200, repr(q)
    assert _grupos(client, "%%") == {} and _grupos(client, "__") == {}      # no "cualquier cosa"
    p = db.session.scalar(db.select(Pedido))
    r = client.post(f"/pedidos/{p.id}/estado", data={"estado": "cancelado", "lote-²": "1", "lote-1": "²"})
    assert r.status_code in (302, 403)


def test_pedidos_por_el_producto_que_llevan(app, client):
    """Buscar el nombre de un kit o producto saca los pedidos que lo contienen (cada uno, los suyos)."""
    from app.models import Producto
    pa, pb = _escenario(client)                       # los dos pedidos llevan el kit "Kit uno" (K1) con "Kit 1" (P1)
    otro = Producto(referencia="XK-043", nombre="Buffer de conservación", precio=10)
    db.session.add(otro); db.session.commit()
    login(client, "ofi")                              # un pedido más para la Clínica B, solo con el buffer suelto
    import json
    client.post("/pedidos/nuevo", data={"cliente_id": pb.cliente_id, "fecha": "2026-10-02",
                                        "contenido": json.dumps({"kits": [], "sueltos": [{"producto_id": otro.id, "cantidad": 4}]})})
    pc = db.session.scalar(db.select(Pedido).order_by(Pedido.id.desc()))
    from app.buscador import buscar
    with client:
        client.get("/")
        grupos = {g["clave"]: g for g in buscar("kit uno")}
        assert {r["titulo"] for r in grupos["pedidos_producto"]["resultados"]} == {pa.referencia_interna, pb.referencia_interna}
        assert "1 × Kit uno" in grupos["pedidos_producto"]["resultados"][0]["subtitulo"]        # dice por qué sale
        assert "pedidos" not in grupos                                                          # no por su referencia
        [r] = {g["clave"]: g for g in buscar("XK-043")}["pedidos_producto"]["resultados"]       # por referencia del producto
        assert r["titulo"] == pc.referencia_interna and "4 × Buffer de conservación" in r["subtitulo"]
    # "ver todos" → la lista de pedidos con ese filtro
    html = client.get("/pedidos/?contiene=buffer").get_data(as_text=True)
    assert pc.referencia_interna in html and pa.referencia_interna not in html and "Llevan un kit o producto con «buffer»" in html
    client.post("/auth/logout")
    login(client, "loga")                             # FAS de la Clínica A: solo el pedido de A
    assert _grupos(client, "kit uno")["pedidos_producto"] == [pa.referencia_interna]
    assert "pedidos_producto" not in _grupos(client, "buffer")
    client.post("/auth/logout")
    login(client, "cliB")                             # el cliente: los de su empresa
    assert set(_grupos(client, "buffer")["pedidos_producto"]) == {pc.referencia_interna}
    client.post("/auth/logout")
    login(client, "sop")                              # Soporte no ve pedidos
    assert "pedidos_producto" not in _grupos(client, "kit uno")
