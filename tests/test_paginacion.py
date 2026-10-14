"""Paginación de las listas largas: 10 por página (se puede elegir 25 o 50), con ?pagina=N."""
from app.extensions import db
from app.models import Cliente
from conftest import login


def _clientes(n):
    db.session.add_all([Cliente(nombre=f"Clínica {i:02d}", cif=f"C{i:08d}", prefijo=f"P{i:02d}") for i in range(n)])
    db.session.commit()


def test_clientes_de_10_en_10_y_las_paginas_funcionan(app, client):
    _clientes(23)                                   # + Clínica A y B = 25 (todas con prefijo único: se ven en la tabla)
    login(client, "admin")
    html = client.get("/clientes/").get_data(as_text=True)
    assert html.count("/clientes/") > 0 and "1–10 de 25" in html
    assert 'href="/clientes/?pagina=2"' in html and "Página siguiente" in html
    html3 = client.get("/clientes/?pagina=3").get_data(as_text=True)
    assert "21–25 de 25" in html3
    # cada página trae otros clientes (antes se recortaba dos veces y no se pasaba de la primera)
    assert 'href="/clientes/3"' in client.get("/clientes/?pagina=1").get_data(as_text=True)    # Clínica 00
    assert 'href="/clientes/3"' not in html3 and 'href="/clientes/25"' in html3                   # Clínica 22
    assert "1–25 de 25" in client.get("/clientes/?por_pagina=25").get_data(as_text=True)


def test_con_10_o_menos_no_sale_el_pie(app, client):
    login(client, "admin")
    assert "por página" not in client.get("/clientes/").get_data(as_text=True)


def test_ficha_del_cliente_pedidos_y_facturas_paginados_por_separado(app, client):
    from datetime import date
    from app.models import Factura, Pedido
    db.session.add_all([Pedido(cliente_id=1, referencia=f"OC-{n}", referencia_interna=f"FICHA_{n:03d}", estado="aceptado")
                        for n in range(23)])
    db.session.add_all([Factura(numero=f"F-{n:03d}", cliente_id=1, fecha_emision=date(2026, 9, 1)) for n in range(12)])
    db.session.commit()
    login(client, "admin")
    html = client.get("/clientes/1").get_data(as_text=True)
    assert html.count("FICHA_") == 10 and "1–10 de 23" in html and "1–10 de 12" in html
    assert 'href="/clientes/1?pagina_pedidos=2#pedidos"' in html
    # pasar de página en pedidos no mueve las facturas
    html = client.get("/clientes/1?pagina_pedidos=3").get_data(as_text=True)
    assert html.count("FICHA_") == 3 and "21–23 de 23" in html and "1–10 de 12" in html
