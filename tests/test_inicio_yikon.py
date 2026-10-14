"""
Inicio de Yikon en mosaico: la tira de fases, "Pendientes" con pestañas (y los retrasos marcados
con el reloj) y "Última actividad". Cada uno, solo lo que le corresponde.
"""
import re
from datetime import timedelta

from app import ajustes
from app.extensions import db
from app.models import Pedido, RegistroAuditoria, ahora
from tests.conftest import login, pedido_cliente


def _inicio(client, usuario):
    login(client, usuario)
    html = client.get("/").get_data(as_text=True)
    client.post("/auth/logout")
    return html


def _casilla(html, ident):
    return html.split(f'id="{ident}"')[1].split("</section>\n\n")[0]


def _grupo(html, clave):
    """El HTML de una pestaña de "Pendientes" (solo existe si tiene algo)."""
    return html.split(f'data-grupo="{clave}"')[1].split("</section>")[0]


def _texto(html):
    """El HTML sin etiquetas ni saltos (para comprobar frases que llevan negritas y enlaces)."""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", html))


def _pedido(client, usuario="cliA"):
    login(client, usuario); pedido_cliente(client); client.post("/auth/logout")
    return db.session.scalar(db.select(Pedido).order_by(Pedido.id.desc()))


def _envejecer(pedido, dias):
    """Como si todo lo apuntado de este pedido hubiera pasado hace `dias` días."""
    for r in db.session.scalars(db.select(RegistroAuditoria).filter_by(entidad="Pedido", entidad_id=pedido.id)):
        r.fecha = ahora() - timedelta(days=dias)
    db.session.commit()


def test_un_pedido_se_marca_con_el_reloj_al_pasar_su_plazo(app, client):
    p = _pedido(client)                                           # aceptado
    plazo = ajustes.plazos()["aceptado"]
    _envejecer(p, plazo - 1)
    grupo = _grupo(_inicio(client, "admin"), "aceptados")
    assert "espera-lenta" not in grupo and "más tiempo del previsto" not in grupo
    _envejecer(p, plazo + 2)
    grupo = _grupo(_inicio(client, "admin"), "aceptados")
    assert "espera-lenta" in grupo and "Con retraso:" in grupo and f"hace {plazo + 2} días" in grupo
    assert "1 lleva más tiempo del previsto" in grupo


def test_el_plazo_cuenta_desde_que_entro_en_el_estado_actual(app, client):
    p = _pedido(client)
    _envejecer(p, 30)                                             # se creó hace un mes...
    login(client, "ofi")
    assert client.post(f"/pedidos/{p.id}/preparacion").status_code == 302
    client.post("/auth/logout")
    grupo = _grupo(_inicio(client, "admin"), "preparacion")       # ...pero acaba de cambiar de estado
    assert p.referencia_interna in grupo and "espera-lenta" not in grupo and "hoy" in grupo


def test_los_retrasados_suben_arriba_de_su_pestana(app, client):
    pedidos = [_pedido(client) for _n in range(3)]
    _envejecer(pedidos[2], 9)                                     # el último creado es el que más espera
    grupo = _grupo(_inicio(client, "admin"), "aceptados")
    orden = [int(n) for n in re.findall(r'href="/pedidos/(\d+)"', grupo)]
    assert orden[0] == pedidos[2].id


def test_esperando_al_cliente_reune_proformas_sin_respuesta_y_envios_sin_confirmar(app, client):
    proforma, enviado, otro = _pedido(client), _pedido(client), _pedido(client, "cliB")
    proforma.estado, enviado.estado, otro.estado = "proforma_enviada", "enviado", "enviado"
    db.session.commit()
    grupo = _texto(_grupo(_inicio(client, "admin"), "esperando"))
    assert f"{proforma.referencia_interna} · Clínica A · proforma sin respuesta" in grupo
    assert f"{enviado.referencia_interna} · Clínica A · envío sin confirmar" in grupo and otro.referencia_interna in grupo
    grupo = _grupo(_inicio(client, "loga"), "esperando")          # Soporte de cliente: solo sus clientes
    assert enviado.referencia_interna in grupo and otro.referencia_interna not in grupo


def test_soporte_de_cliente_solo_ve_la_actividad_de_sus_clientes(app, client):
    pa, pb = _pedido(client, "cliA"), _pedido(client, "cliB")
    html = _inicio(client, "loga")
    actividad = _texto(_casilla(html, "actividad"))
    assert f"Clínica A ha creado el pedido {pa.referencia_interna}" in actividad and "Clínica B" not in actividad
    assert "<strong>Clínica A</strong>" in _casilla(html, "actividad") and pb.referencia_interna not in html


def test_la_actividad_no_cuenta_lo_que_hace_uno_mismo(app, client):
    p = _pedido(client)
    login(client, "ofi"); client.post(f"/pedidos/{p.id}/preparacion"); client.post("/auth/logout")
    frase = f"ofi ha empezado a preparar {p.referencia_interna}"
    assert frase in _texto(_casilla(_inicio(client, "admin"), "actividad"))
    assert frase not in _texto(_casilla(_inicio(client, "ofi"), "actividad"))


def test_el_inicio_son_la_tira_pendientes_y_actividad(app, client):
    _pedido(client)
    html = _inicio(client, "admin")
    pendientes = _casilla(html, "pendientes")
    assert 'data-bs-target="#grupo-aceptados"' in pendientes and 'id="grupo-aceptados"' in pendientes
    assert pendientes.count('class="pendientes-pestana active"') == 1 and 'id="pestana-aceptados"' in pendientes
    # cada línea dice el cliente, qué lleva y cuánto espera; la pestaña, su nombre corto y su número
    assert "Clínica A · 1 × " in _texto(pendientes) and "hoy" in pendientes and "Sin empezar <span" in pendientes
    tira = html.split('class="tira-fases')[1].split("</div>")[0]
    assert tira.count('class="fase est-') == 6 and "estado=aceptado" in tira and "Fact. vencidas" in tira
    for quitado in ("Últimos pedidos", 'id="parados"', 'id="alertas"'):
        assert quitado not in html, quitado


def test_las_pestanas_estan_siempre_aunque_esten_a_cero(app, client):
    pendientes = _casilla(_inicio(client, "admin"), "pendientes")          # sin ningún pedido
    claves = ("incidencias", "proformas", "aceptados", "preparacion", "devueltos", "lotes", "enviar", "validar", "facturar", "facturas_revisar",
              "facturas_devueltas", "facturas_enviar", "esperando")
    for clave in claves:
        assert f'id="pestana-{clave}"' in pendientes, clave
    assert 'id="pestana-mensajes"' not in pendientes                       # los mensajes van en el botón flotante
    # en el orden de la vida de un pedido, con sus nombres cortos
    import re
    assert re.findall(r'id="pestana-(\w+)"', pendientes) == [      # (paso 92: las incidencias, lo primero)
        "incidencias", "proformas", "aceptados", "lotes", "preparacion", "validar", "devueltos", "enviar", "facturar",
        "facturas_revisar", "facturas_devueltas", "facturas_enviar", "esperando"]
    assert "Sin lote <span" in pendientes and "Por enviar <span" in pendientes
    assert pendientes.count('<span class="cuenta">0</span>') == len(claves) and "No hay nada pendiente." in pendientes
    assert pendientes.count(' active') == 2                                # una pestaña y su panel: la primera
    # con algo en una sola, se abre esa y las demás siguen en su sitio
    _pedido(client)
    pendientes = _casilla(_inicio(client, "admin"), "pendientes")
    assert 'class="pendientes-pestana active" id="pestana-aceptados"' in pendientes
    assert pendientes.count('class="pendientes-pestana vacia"') == 11      # todas menos "Sin empezar" y "Sin lote" (no hay stock)
    # cada rol, las suyas: logística prepara pero no valida las fotos
    pendientes = _casilla(_inicio(client, "ofi"), "pendientes")
    assert 'id="pestana-preparacion"' in pendientes and 'id="pestana-validar"' not in pendientes


def test_en_preparacion_tiene_su_pestana_y_los_devueltos_van_aparte(app, client):
    p = _pedido(client)
    login(client, "ofi"); client.post(f"/pedidos/{p.id}/preparacion"); client.post("/auth/logout")
    pendientes = _casilla(_inicio(client, "ofi"), "pendientes")
    assert p.referencia_interna in _grupo(pendientes, "preparacion") and 'data-grupo="devueltos"' not in pendientes
    assert 'data-grupo="aceptados"' not in pendientes                      # ya no está "sin empezar"


def test_la_pagina_de_actividad_lo_tiene_todo_con_filtros_y_alcance(app, client):
    pa, pb = _pedido(client, "cliA"), _pedido(client, "cliB")
    login(client, "ofi"); client.post(f"/pedidos/{pa.id}/preparacion"); client.post("/auth/logout")
    assert 'href="/actividad">Ver toda la actividad' in _casilla(_inicio(client, "ofi"), "actividad")

    login(client, "ofi")
    pagina = _texto(client.get("/actividad").get_data(as_text=True))
    assert f"ofi ha empezado a preparar {pa.referencia_interna}" in pagina          # aquí sí sale lo propio
    assert f"Clínica A ha creado el pedido {pa.referencia_interna}" in pagina and pb.referencia_interna in pagina
    # por cliente y por fechas
    solo_b = _texto(client.get(f"/actividad?cliente_id={pb.cliente_id}").get_data(as_text=True))
    assert pb.referencia_interna in solo_b and pa.referencia_interna not in solo_b
    assert pa.referencia_interna not in client.get("/actividad?hasta=2000-01-01").get_data(as_text=True)
    assert pa.referencia_interna in client.get("/actividad?desde=2000-01-01&hasta=fecha-mala").get_data(as_text=True)
    client.post("/auth/logout")

    login(client, "loga")                                         # Soporte de cliente: solo sus clientes,
    pagina = client.get(f"/actividad?cliente_id={pb.cliente_id}").get_data(as_text=True)   # aunque pida otro
    assert pa.referencia_interna in pagina and pb.referencia_interna not in pagina and "Clínica B" not in pagina
    client.post("/auth/logout")
    login(client, "cliA")
    assert client.get("/actividad").status_code == 403


def test_la_actividad_no_incluye_cambios_de_precio_ni_de_lotes(app, client):
    p = _pedido(client)
    login(client, "admin")
    db.session.add(RegistroAuditoria(usuario_id=1, accion="editar", entidad="Pedido", entidad_id=p.id,
                                     detalle="lotes reservados: L1 × 2"))
    db.session.add(RegistroAuditoria(usuario_id=1, accion="editar", entidad="Pedido", entidad_id=p.id,
                                     detalle="precio 10 → 12"))
    db.session.commit()
    pagina = client.get("/actividad").get_data(as_text=True)
    assert pagina.count('class="actividad-fila"') == 1 and "ha creado el pedido" in pagina


def test_pendientes_marca_lo_nuevo_desde_tu_ultima_visita(app, client):
    from app.models import User
    p = _pedido(client)                                         # aceptado: "Sin empezar" para admin
    login(client, "admin"); client.get(f"/pedidos/{p.id}"); client.post("/auth/logout")   # lo ha visto
    pendientes = _casilla(_inicio(client, "admin"), "pendientes")
    assert "marca-nuevo" not in pendientes and "punto-nuevo" not in pendientes
    # Otra persona adjunta un documento después de su visita
    from app.models import VistaPedido
    for v in db.session.scalars(db.select(VistaPedido).filter_by(pedido_id=p.id)):
        v.fecha = ahora() - timedelta(minutes=1)                # la visita fue hace un minuto
    ofi = db.session.scalar(db.select(User).filter_by(email="ofi@ejemplo.com"))
    db.session.add(RegistroAuditoria(usuario_id=ofi.id, accion="editar", entidad="Pedido", entidad_id=p.id,
                                     detalle="documento adjuntado: OC.pdf", fecha=ahora()))
    db.session.commit()
    html = _inicio(client, "admin")
    fila = _grupo(html, "aceptados")
    assert "nuevo: documentos" in fila and f"/pedidos/{p.id}#documentos" in fila
    pestana = html.split('id="pestana-aceptados"')[1].split("</button>")[0]
    assert "punto-nuevo" in pestana and "Con novedades" in pestana            # la pestaña lleva el punto
    # Al abrir el pedido, se apaga
    login(client, "admin"); client.get(f"/pedidos/{p.id}"); client.post("/auth/logout")
    assert "marca-nuevo" not in _casilla(_inicio(client, "admin"), "pendientes")
