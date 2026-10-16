"""Controles de admin: límites del servidor, conservación, sesiones y auditoría."""
import json
import re
from datetime import date, timedelta
from io import BytesIO

import pytest
from flask import g
from openpyxl import load_workbook

from app import control_admin as control
from app.extensions import db
from app.models import Ajuste, User, Pedido, RegistroAuditoria, CorreoEnviado, ahora
from tests.conftest import login, pedido_cliente, contenido, doc_pedido


def usuario(nombre):
    return db.session.scalar(db.select(User).where(User.email == nombre.lower() + '@ejemplo.com'))


def entrar(client, nombre, recordar=False):
    g.pop('_login_user', None)
    return client.post('/auth/login', data={'email': nombre+'@ejemplo.com', 'password': 'password123', 'recordar': 'y' if recordar else ''})


def pedir(client, method, url, **kwargs):
    g.pop('_login_user', None)
    return getattr(client, method)(url, **kwargs)


@pytest.mark.parametrize('tema,campos', [
    ('operativa', ['plazo_aceptado', 'plazo_proforma_enviada', 'validez', 'plazo_es', 'notas_en', 'caducidad', 'pausada']),
    ('comunicaciones', ['aviso_es', 'aviso_en', 'desde', 'hasta', 'con_logo', 'logo', 'avisos', 'recibe', 'clientes']),
    ('acceso', ['fallos', 'ventana_minutos', 'invitacion_dias', 'reset_horas', 'inactividad_horas', 'ver']),
    ('sistema', ['copia', 'inactivos', 'revision', 'correos', 'activado', 'mensaje']),
])
def test_panel_conserva_controles_y_sus_destinos(app, client, tema, campos):
    login(client, 'admin')
    html = client.get('/admin/ajustes/panel/'+tema).get_data(as_text=True)
    for nombre in campos:
        assert f'name="{nombre}"' in html
    for form in re.findall(r'<form\b[^>]*>', html):
        if 'method="post"' in form:
            assert 'action=' in form
    assert html.count('<html') == 1


def test_reorganizar_no_modifica_valores(app, client):
    control.guardar('proforma.notas.en', 'Existing note')
    control.guardar('plazo.aceptado', '17')
    db.session.commit()
    login(client, 'admin')
    antes = [(a.clave, a.valor) for a in db.session.scalars(db.select(Ajuste).order_by(Ajuste.clave))]
    for tema in ('operativa', 'comunicaciones', 'acceso', 'sistema'):
        assert client.get('/admin/ajustes/panel/'+tema).status_code == 200
    assert antes == [(a.clave, a.valor) for a in db.session.scalars(db.select(Ajuste).order_by(Ajuste.clave))]


def test_controles_validados_y_auditados(app, client):
    login(client, 'admin')
    for invalido in ('0', '-1', '366', 'x'):
        client.post('/admin/ajustes/controles/inventario', data={'caducidad': invalido})
        assert control.numero('caducidad') == 7
    client.post('/admin/ajustes/controles/inventario', data={'caducidad': '30'})
    client.post('/admin/ajustes/controles/inventario', data={'caducidad': '60'})
    assert control.numero('caducidad') == 60
    r = db.session.scalar(db.select(RegistroAuditoria).where(RegistroAuditoria.ajuste_clave == 'control.caducidad').order_by(RegistroAuditoria.id.desc()))
    assert (r.valor_anterior, r.valor_nuevo, r.usuario_id) == ('30', '60', usuario('admin').id)
    assert '60' in client.get('/inventario/caducidades').get_data(as_text=True)


def test_restaurar_solo_seccion_y_rechazar_vista_obsoleta(app, client):
    login(client, 'admin')
    control.guardar('control.caducidad', '30')
    control.guardar('control.copia', '6')
    db.session.commit()
    html = client.get('/admin/ajustes/restaurar/inventario').get_data(as_text=True)
    token = re.search(r'name="huella" value="([a-f0-9]+)"', html)[1]
    control.guardar('control.caducidad', '45')
    db.session.commit()
    client.post('/admin/ajustes/restaurar/inventario', data={'huella': token})
    assert control.numero('caducidad') == 45
    html = client.get('/admin/ajustes/restaurar/inventario').get_data(as_text=True)
    token = re.search(r'name="huella" value="([a-f0-9]+)"', html)[1]
    client.post('/admin/ajustes/restaurar/inventario', data={'huella': token})
    assert control.numero('caducidad') == 7 and control.numero('copia') == 6


def test_revocacion_invalida_sesion_y_cookie_recordarme(app, client):
    otro = app.test_client()
    entrar(otro, 'cliA', recordar=True)
    cookie = otro.get_cookie('remember_token')
    assert cookie is not None
    entrar(client, 'admin')
    pedir(client, 'post', f'/admin/usuarios/{usuario("cliA").id}/acceso', data={'accion': 'cerrar'})
    assert '/auth/login' in pedir(otro, 'get', '/pedidos/').location
    nuevo = app.test_client()
    nuevo.set_cookie('remember_token', cookie.value)
    assert '/auth/login' in pedir(nuevo, 'get', '/pedidos/').location
    entrar(nuevo, 'cliA')
    assert pedir(nuevo, 'get', '/pedidos/').status_code == 200


def test_cambio_obligatorio_no_permite_operar_hasta_password_distinto(app, client):
    login(client, 'admin')
    uid = usuario('cliA').id
    client.post(f'/admin/usuarios/{uid}/acceso', data={'accion': 'password', 'exigir': '1'})
    otro = app.test_client()
    entrar(otro, 'cliA')
    assert pedir(otro, 'get', '/pedidos/').location.endswith('/auth/cuenta')
    assert pedir(otro, 'post', '/pedidos/nuevo', data={}).location.endswith('/auth/cuenta')
    pedir(otro, 'post', '/auth/cuenta', data={'actual': 'password123', 'nueva': 'password123', 'confirmar': 'password123'})
    assert usuario('cliA').cambiar_password
    pedir(otro, 'post', '/auth/cuenta', data={'actual': 'password123', 'nueva': 'otra-password123', 'confirmar': 'otra-password123'})
    assert not usuario('cliA').cambiar_password
    assert pedir(otro, 'get', '/pedidos/').status_code == 200


def test_pausa_por_empresa_y_global_bloquea_post_y_repetir(app, client):
    login(client, 'admin')
    client.post('/admin/ajustes/pausa', data={'cliente_id': '1', 'pausada': '1', 'pausa_es': 'Pausa A'})
    client.post('/auth/logout')
    login(client, 'cliA')
    assert client.get('/pedidos/nuevo?repetir=1').status_code == 403
    assert pedido_cliente(client).status_code == 403
    assert db.session.scalar(db.select(db.func.count(Pedido.id))) == 0
    assert 'Pausa A' in client.get('/').get_data(as_text=True)
    client.post('/auth/logout')
    login(client, 'cliB')
    assert client.get('/pedidos/nuevo').status_code == 200
    client.post('/auth/logout')
    login(client, 'admin')
    client.post('/admin/ajustes/pausa', data={'pausada': '1', 'pausa_es': 'Pausa global'})
    assert control.bloqueo(2) == 'Pausa global'


def test_creacion_interna_en_pausa_exige_y_registra_motivo(app, client):
    login(client, 'admin')
    client.post('/admin/ajustes/pausa', data={'pausada': '1'})
    def datos():
        return dict(cliente_id=1, fecha='2026-10-16', contenido=contenido([(1, 1, {1: 1})]), documento=doc_pedido())
    assert client.post('/pedidos/nuevo', data=datos()).status_code == 400
    assert db.session.scalar(db.select(db.func.count(Pedido.id))) == 0
    assert client.post('/pedidos/nuevo', data=dict(datos(), motivo_excepcion='Envío urgente acordado')).status_code == 302
    assert db.session.scalar(db.select(RegistroAuditoria).where(RegistroAuditoria.detalle.contains('Envío urgente acordado')))


def test_excepcion_estado_sin_motivo_no_muta_pedido(app, client):
    login(client, 'cliA')
    pedido_cliente(client)
    p = db.session.scalar(db.select(Pedido))
    p.estado = 'cancelado'
    db.session.commit()
    client.post('/auth/logout')
    login(client, 'admin')
    # Ir a recibido desde cancelado es una excepción.
    client.post(f'/pedidos/{p.id}/estado', data={'estado': 'entregado', 'confirmar_stock': '1'})
    db.session.refresh(p)
    assert p.estado == 'cancelado'


def test_anuncios_audiencia_fechas_borrador_cierre_e_idioma(app, client):
    login(client, 'admin')
    data = dict(titulo='Privado A', es='Solo para A', en='Only for A', destinatarios='seleccion', clientes=['1'], publicado='1')
    assert client.post('/admin/ajustes/anuncios', data=data).status_code == 302
    a = control.anuncios()[0]
    assert control.anuncios_para(usuario('cliB'), 'es') == []
    assert control.anuncios_para(usuario('cliA'), 'en')[0]['texto'] == 'Only for A'
    client.post('/auth/logout')
    login(client, 'cliA')
    html = client.get('/').get_data(as_text=True)
    assert 'Solo para A' in html
    marca = control.anuncios_para(usuario('cliA'), 'es')[0]['huella']
    client.post('/aviso-clientes/cerrar', data={'anuncio_id': a['id'], 'huella': marca})
    assert not control.anuncios_para(usuario('cliA'), 'es')
    client.post('/auth/logout')
    login(client, 'admin')
    client.post('/admin/ajustes/anuncios', data=dict(data, id=a['id'], es='Nuevo texto'))
    assert control.anuncios_para(usuario('cliA'), 'es')[0]['texto'] == 'Nuevo texto'
    client.post('/admin/ajustes/anuncios', data=dict(data, id=a['id'], desde='2099-01-01'))
    assert not control.anuncios_para(usuario('cliA'), 'es')
    client.post('/admin/ajustes/anuncios', data=dict(data, id=a['id'], publicado=''))
    assert not control.anuncios_para(usuario('cliA'), 'es')


def test_auditoria_exporta_mismos_filtros_y_valores(app, client):
    login(client, 'admin')
    client.post('/admin/ajustes/controles/inventario', data={'caducidad': 30})
    r = client.get('/admin/auditoria?tipo=Ajuste&q=control.caducidad&exportar=1')
    libro = load_workbook(BytesIO(r.data))
    filas = list(libro.active.values)
    assert len(filas) == 2 and filas[1][-1] == '30'
    assert client.get('/admin/auditoria?desde=2026-10-20&hasta=2026-10-01').status_code == 400


@pytest.mark.parametrize('nombre', ['cliA', 'loga', 'ofi', 'fac'])
def test_nuevos_controles_solo_admin(app, client, nombre):
    login(client, nombre)
    for url in ('/admin/ajustes/controles/inventario', '/admin/ajustes/pausa', '/admin/ajustes/anuncios', '/admin/usuarios/1/acceso'):
        assert client.post(url, data={}).status_code == 403
    assert client.get('/admin/ajustes/panel/operativa').status_code == 403


def test_filtro_correos_respeta_ventana_horas(app, client):
    db.session.add_all([CorreoEnviado(para='a@example.com', asunto='Reciente', estado='fallido', fecha=ahora()-timedelta(hours=2)),
                        CorreoEnviado(para='a@example.com', asunto='Antiguo', estado='fallido', fecha=ahora()-timedelta(hours=50))])
    db.session.commit()
    login(client, 'admin')
    html = client.get('/admin/correos?estado=fallido&horas=24').get_data(as_text=True)
    assert 'Reciente' in html and 'Antiguo' not in html
