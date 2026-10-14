"""Buscador, paginación y ordenar por las cabeceras: Kits, Productos, Clientes, Pedidos, Facturas e
Inventario (utils.ordenar / utils.ordenar_lista y la macro th_orden)."""
import re
from datetime import date

from app.extensions import db
from app.models import Cliente, ComponenteKit, Factura, Kit, Producto, ahora
from tests.conftest import login, pedido_cliente


def _tablas(html):
    """Solo el cuerpo de las tablas (la página lleva más cosas con nombres: la ventana de pedido…)."""
    return "".join(re.findall(r"<tbody>(.*?)</tbody>", html, re.S))


def _orden_en(html, textos):
    """Los textos, en el orden en que salen en las tablas de la página (los que no salen, fuera)."""
    html = _tablas(html)
    return sorted((t for t in textos if t in html), key=html.index)


def _productos(*datos):
    for ref, nombre, precio in datos:
        db.session.add(Producto(referencia=ref, nombre=nombre, precio=precio))
    db.session.commit()


def test_productos_por_cabeceras(app, client):
    _productos(("ZZ-1", "alfa", 30), ("AA-1", "Charlie", 5), ("MM-1", "bravo", 999))
    login(client, "admin")
    nombres = ["alfa", "bravo", "Charlie"]
    html = client.get("/productos/?orden=nombre").get_data(as_text=True)
    assert _orden_en(html, nombres) == ["alfa", "bravo", "Charlie"]             # sin distinguir mayúsculas
    html = client.get("/productos/?orden=-nombre").get_data(as_text=True)
    assert _orden_en(html, nombres) == ["Charlie", "bravo", "alfa"]
    html = client.get("/productos/?orden=precio").get_data(as_text=True)
    assert _orden_en(html, nombres) == ["Charlie", "alfa", "bravo"]             # 5, 30, 999 (número, no texto)
    html = client.get("/productos/?orden=referencia").get_data(as_text=True)
    assert _orden_en(html, ["AA-1", "MM-1", "ZZ-1"]) == ["AA-1", "MM-1", "ZZ-1"]
    # La cabecera activa: flecha, aria-sort y el siguiente clic invierte. Mantiene la búsqueda y vuelve a la página 1
    html = client.get("/productos/?orden=nombre&q=a&pagina=2").get_data(as_text=True)
    th = re.search(r'<th[^>]*aria-sort="ascending".*?</th>', html, re.S).group(0)
    assert "Nombre" in th and "▲" in th and "orden=-nombre" in th and "q=a" in th and "pagina=1" in th
    assert 'aria-sort="none"' in html and "↕" in html
    assert 'name="orden" value="nombre"' in html                                 # el buscador no pierde el orden
    # Un orden que no existe (o tocado a mano) no rompe nada: orden de siempre
    assert client.get("/productos/?orden=password").status_code == 200
    assert client.get("/productos/?orden=-").status_code == 200


def _kit(ref, nombre, productos, activo=True, precio=10):
    kit = Kit(referencia=ref, nombre=nombre, precio=precio, cerrado=False, activo=activo,
              componentes=[ComponenteKit(producto=p, cantidad=n) for p, n in productos])
    db.session.add(kit)
    return kit


def test_kits_buscador_tambien_por_sus_productos(app, client):
    _productos(("YK001-001", "NGS Universal Index Kit", 1), ("XK-043", "Sample Preservation Buffer", 1))
    yk, xk = (db.session.scalar(db.select(Producto).filter_by(referencia=r)) for r in ("YK001-001", "XK-043"))
    _kit("PGTA-24", "PGT-A 24 rxn", [(xk, 2), (yk, 1)])
    _kit("NICS-24", "NICS 24 rxn", [(xk, 2)])
    db.session.commit()
    login(client, "loga")                                           # (Soporte de cliente: ve los kits)
    html = _tablas(client.get("/productos/kits?q=yk001").get_data(as_text=True))
    assert "PGT-A 24 rxn" in html and "NICS 24 rxn" not in html and "Kit uno" not in html
    assert "<mark" in html and "YK001-001" in html                   # se marca el producto que coincide
    html = _tablas(client.get("/productos/kits?q=nics").get_data(as_text=True))
    assert "NICS 24 rxn" in html and "PGT-A 24 rxn" not in html
    assert "Ningún kit coincide" in client.get("/productos/kits?q=nada-de-nada").get_data(as_text=True)
    assert client.get("/productos/kits?q=100%25_").status_code == 200        # % y _ se buscan tal cual


def test_kits_paginados_y_ordenados_con_los_inactivos_al_final(app, client):
    p1 = db.session.get(Producto, 1)
    for i in range(12):
        _kit(f"K-{i:02d}", f"Kit {chr(65 + i)}", [(p1, 1 + i % 3)], precio=100 - i)
    _kit("K-OFF", "Kit AAA inactivo", [(p1, 1)], activo=False)
    db.session.commit()
    login(client, "admin")
    html = client.get("/productos/kits").get_data(as_text=True)
    assert "1–10 de 14" in html and "Kit AAA inactivo" not in html          # 13 + el K1 del escenario
    html = client.get("/productos/kits?orden=nombre&por_pagina=50").get_data(as_text=True)
    nombres = ["Kit A", "Kit B", "Kit L", "Kit uno", "Kit AAA inactivo"]
    assert _orden_en(html, nombres) == nombres                      # el inactivo, al final aunque sea «AAA»
    html = client.get("/productos/kits?orden=precio&por_pagina=50").get_data(as_text=True)
    assert _orden_en(html, ["Kit L", "Kit A", "Kit uno"]) == ["Kit L", "Kit uno", "Kit A"]   # 89, y a 100 los dos: el más antiguo antes
    html = client.get("/productos/kits?orden=-productos&por_pagina=50").get_data(as_text=True)
    assert "Referencia" in html and "K-00" in html                  # columna Referencia aparte
    assert client.get("/productos/kits?orden=productos&pagina=2").status_code == 200


def test_clientes_por_cabeceras(app, client):
    db.session.add(Cliente(nombre="aaa Primera", prefijo="AAA", ciudad="Zaragoza", ver_precios=True))
    db.session.commit()
    login(client, "admin")
    nombres = ["aaa Primera", "Clínica A", "Clínica B"]
    assert _orden_en(client.get("/clientes/?orden=-nombre").get_data(as_text=True), nombres) == nombres[::-1]
    assert _orden_en(client.get("/clientes/?orden=precios").get_data(as_text=True), nombres)[0] == "aaa Primera"
    # Soporte de cliente: Clínica A → loga, Clínica B → logb, la nueva sin nadie (al final)
    html = client.get("/clientes/?orden=-fas").get_data(as_text=True)
    assert _orden_en(html, nombres) == ["Clínica B", "Clínica A", "aaa Primera"]
    assert 'name="orden" value="-fas"' in html


def test_pedidos_por_cliente_y_por_estado_del_flujo(app, client):
    login(client, "cliB"); pedido_cliente(client, referencia="OC-B"); client.post("/auth/logout")
    login(client, "cliA"); pedido_cliente(client, referencia="OC-A", con_proforma=True); client.post("/auth/logout")
    login(client, "admin")
    html = client.get("/pedidos/?orden=cliente").get_data(as_text=True)
    assert _orden_en(html, ["OC-A", "OC-B"]) == ["OC-A", "OC-B"]
    html = client.get("/pedidos/?orden=-cliente").get_data(as_text=True)
    assert _orden_en(html, ["OC-A", "OC-B"]) == ["OC-B", "OC-A"]
    # Estado por el flujo: «proforma solicitada» (A) va antes que «aceptado» (B), aunque alfabéticamente no
    html = client.get("/pedidos/?orden=estado").get_data(as_text=True)
    assert _orden_en(html, ["OC-A", "OC-B"]) == ["OC-A", "OC-B"]
    # La fecha empieza por lo más reciente; el Excel sale en el mismo orden que la lista
    assert "orden=-fecha" in html
    assert client.get("/pedidos/exportar.xlsx?orden=-cliente").status_code == 200


def test_facturas_por_numero_y_cliente(app, client):
    for n, c in (("F-002", 1), ("F-010", 2), ("F-001", 2)):
        db.session.add(Factura(enviada_el=ahora(), numero=n, cliente_id=c, fecha_emision=date(2026, 9, 1), total=1))
    db.session.commit()
    login(client, "admin")
    assert _orden_en(client.get("/facturas/?orden=numero").get_data(as_text=True), ["F-001", "F-002", "F-010"]) == \
        ["F-001", "F-002", "F-010"]
    html = client.get("/facturas/?orden=cliente").get_data(as_text=True)
    assert _orden_en(html, ["F-002", "F-010"]) == ["F-002", "F-010"]          # Clínica A antes que Clínica B
    assert client.get("/facturas/exportar.xlsx?orden=-numero").status_code == 200


def _entrada(client, producto_id, cantidad, lote, caducidad="2099-12-31"):
    return client.post("/inventario/movimiento", data={"articulo": f"producto-{producto_id}", "tipo": "entrada",
                                                       "cantidad": cantidad, "lote": lote, "caducidad": caducidad})


def test_inventario_buscador_y_orden(app, client):
    _productos(("ZZ-9", "Tubos", 1), ("AB-1", "Buffer", 1))
    login(client, "admin")
    tubos, buffer = (db.session.scalar(db.select(Producto).filter_by(referencia=r)) for r in ("ZZ-9", "AB-1"))
    _entrada(client, tubos.id, 50, "LT-1")
    _entrada(client, buffer.id, 5, "LB-1")
    html = client.get("/inventario/?q=tub").get_data(as_text=True)
    kits, productos = (_tablas(t) for t in html.split('id="tab-productos"'))
    assert "Tubos" in productos and "Buffer" not in productos and "Kit 1" not in productos
    assert "Kit uno" not in kits                                        # el kit K1 no lleva nada «tub»
    html = client.get("/inventario/?q=kit 1").get_data(as_text=True)
    assert "Kit uno" in _tablas(html.split('id="tab-productos"')[0])    # el kit, por el producto que lleva
    productos = client.get("/inventario/?orden=-disponible").get_data(as_text=True).split('id="tab-productos"')[1]
    assert _orden_en(productos, ["Tubos", "Buffer", "Kit 1"]) == ["Tubos", "Buffer", "Kit 1"]   # 50, 5, 0
    productos = client.get("/inventario/?orden=referencia").get_data(as_text=True).split('id="tab-productos"')[1]
    assert _orden_en(productos, ["AB-1", "P1", "ZZ-9"]) == ["AB-1", "P1", "ZZ-9"]
    html = client.get("/inventario/?orden=nombre&solo_bajo=1").get_data(as_text=True)
    # Las cabeceras vuelven a su pestaña (#kits / #productos) sin perder «solo stock bajo»
    assert re.search(r'href="/inventario/\?orden=-nombre&amp;solo_bajo=1[^"]*#productos"', html)
    assert re.search(r'href="/inventario/\?orden=-nombre&amp;solo_bajo=1[^"]*#kits"', html)
    assert 'name="solo_bajo" value="1"' in html                          # el buscador no pierde el filtro


def test_movimientos_buscador_y_orden(app, client):
    _productos(("ZZ-9", "Tubos", 1))
    login(client, "admin")
    tubos = db.session.scalar(db.select(Producto).filter_by(referencia="ZZ-9"))
    _entrada(client, tubos.id, 50, "LT-1")
    _entrada(client, 1, 7, "LP-1")
    html = client.get("/inventario/movimientos?q=lt-1").get_data(as_text=True)
    assert "LT-1" in html and "LP-1" not in html
    assert "LP-1" in client.get("/inventario/movimientos?q=kit 1").get_data(as_text=True)   # por el artículo
    html = client.get("/inventario/movimientos?orden=cantidad").get_data(as_text=True)
    assert _orden_en(html, ["LP-1", "LT-1"]) == ["LP-1", "LT-1"]                         # +7, +50
    html = client.get("/inventario/movimientos?orden=-articulo").get_data(as_text=True)
    assert _orden_en(html, ["LP-1", "LT-1"]) == ["LT-1", "LP-1"]                         # Tubos, Kit 1
    assert "Ningún movimiento coincide" in client.get("/inventario/movimientos?q=nada").get_data(as_text=True)
