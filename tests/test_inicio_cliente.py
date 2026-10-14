"""
Inicio del cliente (app/main/inicio_cliente.py): pedidos en curso con su barra de pasos,
su contacto en Yikon y los documentos y facturas recientes. Solo lo de SU empresa.
"""
from datetime import date

from app.models import ahora  # facturas ya enviadas al cliente (las ve)
from app.extensions import db
from app.models import Cliente, DocumentoPedido, Factura, Pedido
from tests.conftest import login, pedido_cliente, pdf_proforma


def _inicio(client, usuario):
    login(client, usuario)
    html = client.get("/").get_data(as_text=True)
    client.post("/auth/logout")
    return html


def _bloque(html, ident):
    """El HTML de una de las tarjetas del inicio del cliente (hasta la siguiente)."""
    return html.split(f'id="{ident}"')[1].split('" id="')[0]


def _pedido(client, usuario="cliA", **kwargs):
    login(client, usuario)
    pedido_cliente(client, **kwargs)
    client.post("/auth/logout")
    return db.session.scalar(db.select(Pedido).order_by(Pedido.id.desc()))


def test_el_cliente_ve_sus_pedidos_en_curso_y_no_las_tarjetas(app, client):
    p = _pedido(client, cantidad=3)
    html = _inicio(client, "cliA")
    assert "fila-tarjetas" not in html
    en_curso = _bloque(html, "en-curso")
    assert p.referencia_interna in en_curso and "3 × " in en_curso
    assert en_curso.count('class="en-curso-fila"') == 1 and 'data-paso="2"' in en_curso      # aceptado
    # "data-pedido" es del formulario de pedido (pedido.js): si una fila lo llevara, rompería
    # la ventana "Hacer un pedido" de esta misma página
    assert 'data-pedido="' not in en_curso


def test_el_resto_de_roles_sigue_con_sus_tarjetas(app, client):
    _pedido(client)
    for usuario in ("admin", "ofi", "loga"):
        html = _inicio(client, usuario)
        assert "fila-tarjetas" in html and 'id="en-curso"' not in html, usuario


def test_el_paso_actual_avanza_con_el_pedido(app, client):
    p = _pedido(client, con_proforma=True)
    def actual():
        """(paso en el que está, nº de tramos rellenos de la barra, HTML de la fila)"""
        html = _bloque(_inicio(client, "cliA"), "en-curso")
        return int(html.split('data-paso="')[1].split('"')[0]), html.count('class="lleno"'), html
    paso, llenos, html = actual()
    assert (paso, llenos) == (1, 1) and "Proforma solicitada" in html and "est-proforma_solicitada" in html
    p.estado = "en_validacion"; db.session.commit()            # el proceso interno es un solo paso
    paso, llenos, html = actual()
    assert (paso, llenos) == (3, 3) and "En preparación" in html and "validación" not in html
    assert "var(--t-preparacion)" in html                      # la barra, del color de su estado
    p.estado, p.transportista, p.numero_seguimiento = "enviado", "SEUR", "TRACK-123"
    p.fecha_entrega_estimada = date(2026, 10, 9); db.session.commit()
    html = _bloque(_inicio(client, "cliA"), "proximo-envio")      # el envío tiene su casilla
    assert p.referencia_interna in html and "SEUR · TRACK-123" in html and "09/10/2026" in html
    p.estado = "entregado"; db.session.commit()                 # recibido: ya no está en curso
    assert "No tienes pedidos en curso." in _bloque(_inicio(client, "cliA"), "en-curso")


def test_no_ve_los_pedidos_de_otra_empresa(app, client):
    p = _pedido(client, "cliB")
    assert p.referencia_interna not in _inicio(client, "cliA")


def test_su_contacto_es_quien_lleva_su_empresa(app, client):
    contacto = _bloque(_inicio(client, "cliA"), "contacto-yikon")
    assert "loga@ejemplo.com" in contacto and "logb@ejemplo.com" not in contacto
    db.session.scalar(db.select(Cliente).filter_by(nombre="Clínica A")).logisticos = []
    db.session.commit()
    contacto = _bloque(_inicio(client, "cliA"), "contacto-yikon")  # sin nadie asignado: solo el enlace
    assert "Tu contacto en Yikon" not in contacto and "Escribir a tu contacto" in contacto


def test_documentos_y_facturas_recientes_solo_los_suyos(app, client):
    pa, pb = _pedido(client, "cliA"), _pedido(client, "cliB")
    for pedido, nombre in ((pa, "COA_A.pdf"), (pb, "COA_B.pdf")):
        db.session.add(DocumentoPedido(pedido=pedido, archivo=f"x-{nombre}", nombre_original=nombre, tamano=10))
        db.session.add(Factura(enviada_el=ahora(), numero=f"F-{nombre}", base_imponible=100, iva=21, total=121, cliente=pedido.cliente,
                               pedido=pedido, pdf_archivo=f"f-{nombre}", pdf_nombre="f.pdf", pdf_tamano=10))
    db.session.add(Factura(enviada_el=ahora(), numero="F-SIN-PDF", base_imponible=1, iva=0, total=1, cliente=pa.cliente))
    db.session.commit()
    docs = _bloque(_inicio(client, "cliA"), "documentos-recientes")
    assert "COA_A.pdf" in docs and "F-COA_A.pdf" in docs
    assert f"/pedidos/{pa.id}/documentos/" in docs and "/facturas/" in docs
    assert "COA_B.pdf" not in docs
    assert "F-SIN-PDF" not in docs and "121" not in docs       # sin PDF no hay nada que bajar; sin importes


def test_lo_que_le_toca_sale_arriba_en_la_linea_del_pedido_y_en_la_campana(app, client):
    """Sustituye al bloque "Pendientes" del cliente: un punto en la línea del pedido, sin acciones."""
    tranquilo = _pedido(client)                                 # aceptado: no espera nada de él
    enviado = _pedido(client)
    enviado.estado = "enviado"
    proforma = _pedido(client, con_proforma=True)
    proforma.estado = "proforma_enviada"
    db.session.commit()
    html = _inicio(client, "cliA")
    assert 'id="pendientes"' not in html
    en_curso = _bloque(html, "en-curso")
    assert "2 esperan algo de ti" in en_curso
    orden = [int(t.split('"')[0]) for t in en_curso.split('data-pedido-id="')[1:]]
    assert orden == [enviado.id, proforma.id, tranquilo.id]     # primero lo suyo; dentro, lo más avanzado
    # solo se señala (punto con su explicación): no hay enlaces de acción, eso se hace en el pedido
    assert 'title="Proforma por responder"' in en_curso and 'title="Pendiente de confirmar la recepción"' in en_curso
    assert "#proforma" not in en_curso and "Marcar como recibido" not in en_curso and "→" not in en_curso
    assert en_curso.count('data-toca="') == 2
    assert "1 envío por confirmar" in html and "1 proforma por responder" in html      # la campana

    for p in (enviado, proforma):
        p.estado = "aceptado"
    db.session.commit()
    en_curso = _bloque(_inicio(client, "cliA"), "en-curso")
    assert "espera" not in en_curso and 'data-toca="' not in en_curso


def test_la_casilla_de_pedidos_no_crece_y_lleva_a_la_lista_filtrada(app, client):
    for _n in range(10):
        _pedido(client)
    recibido = _pedido(client)
    recibido.estado = "entregado"
    db.session.commit()
    en_curso = _bloque(_inicio(client, "cliA"), "en-curso")
    assert en_curso.count('class="en-curso-fila"') == 8 and "8 de 10" in en_curso
    assert 'href="/pedidos/?estado=en_curso">Ver los 10' in en_curso
    login(client, "cliA")
    lista = client.get("/pedidos/?estado=en_curso").get_data(as_text=True)
    assert lista.count("/pedidos/") > 10 and f'/pedidos/{recibido.id}"' not in lista


def test_ultima_actividad_cuenta_lo_que_hacen_otros_en_sus_pedidos(app, client):
    from tests.conftest import reservar_lotes
    ajeno = _pedido(client, "cliB")                 # (primero: el atajo de los tests acepta todas las proformas)
    mio = _pedido(client, con_proforma=True)
    assert "Aquí verás lo último que pase en tus pedidos." in _bloque(_inicio(client, "cliA"), "actividad")
    login(client, "admin")
    client.post("/inventario/movimiento", data={"articulo": "producto-1", "tipo": "entrada", "cantidad": 10,
                                                "lote": "L1", "caducidad": "2099-12-31"})
    reservar_lotes(client, mio.id)
    assert client.post(f"/pedidos/{mio.id}/proforma/enviar", data={
        "valida_hasta": "2099-01-01", "plazo_entrega": "5 días", "notas": "", "pdf": pdf_proforma()}).status_code == 302
    client.post("/auth/logout")
    db.session.refresh(mio)
    assert mio.estado == "proforma_enviada"
    actividad = _bloque(_inicio(client, "cliA"), "actividad")
    assert f"Tienes la proforma de {mio.referencia_interna}" in actividad
    assert "lotes" not in actividad and ajeno.referencia_interna not in actividad   # ni lo interno ni lo de otros
    assert mio.referencia_interna not in _bloque(_inicio(client, "cliB"), "actividad")
