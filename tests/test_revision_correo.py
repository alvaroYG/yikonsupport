from email.message import EmailMessage
from flask import request
import pytest
from app.extensions import db
from app.models import CorreoBorrador
from app.correo import _a_la_cola, _entregar, construir_compuesto
from tests.conftest import login


@pytest.fixture
def revision(app, client):
    @app.post('/prueba-borrador')
    def generar():
        msg = construir_compuesto(['cliA@ejemplo.com'], {
            'asunto': 'Asunto original', 'texto': 'Mensaje original',
            'html': '<p>Mensaje original</p>', 'logo': None})
        msg.meta = {'tipo': request.args.get('tipo', 'cliente.preparacion')}
        if request.args.get('directo'):
            _entregar(msg)
        else:
            _a_la_cola(msg, msg.meta)
            if request.args.get('rollback'):
                db.session.rollback()
            else:
                db.session.commit()
        return '', 204
    login(client, 'admin')
    return client


def pendientes(client):
    return client.get('/correos-revision/pendientes').get_json()['correos']


def editar(client, b, accion='enviar', **extra):
    return client.post('/correos-revision/' + str(b['id']), json={
        'version': b['version'], 'accion': accion,
        'asunto': 'Asunto revisado', 'texto': 'Texto revisado <script>no ejecutar</script>', **extra})


@pytest.mark.parametrize('directo', [False, True])
def test_no_sale_hasta_confirmacion_y_edita_html(app, revision, directo):
    revision.post('/prueba-borrador' + ('?directo=1' if directo else ''))
    assert not app.extensions.get('correos_enviados')
    [b] = pendientes(revision)
    assert editar(revision, b).status_code == 200
    [msg] = app.extensions['correos_enviados']
    assert msg['Subject'] == 'Asunto revisado'
    assert 'Texto revisado' in msg.get_content()
    assert '<script>' not in msg.get_body(preferencelist=('html',)).get_content()
    assert pendientes(revision) == []
    assert editar(revision, b).status_code == 409
    assert len(app.extensions['correos_enviados']) == 1


def test_guardar_descartar_y_conflicto(app, revision):
    revision.post('/prueba-borrador')
    [b] = pendientes(revision)
    assert editar(revision, b, 'guardar').status_code == 200
    assert editar(revision, b).status_code == 409
    [nuevo] = pendientes(revision)
    assert nuevo['asunto'] == 'Asunto revisado'
    assert editar(revision, nuevo, 'descartar').status_code == 200
    assert not app.extensions.get('correos_enviados')
    assert pendientes(revision) == []


def test_rollback_no_deja_borradores(app, revision):
    revision.post('/prueba-borrador?rollback=1')
    assert pendientes(revision) == []
    assert not app.extensions.get('correos_enviados')


def test_privacidad_por_autor_y_cliente(app, revision):
    revision.post('/prueba-borrador')
    [b] = pendientes(revision)
    revision.post('/auth/logout'); login(revision, 'loga')
    assert pendientes(revision) == []
    assert editar(revision, b).status_code == 404
    revision.post('/auth/logout'); login(revision, 'cliA')
    assert revision.get('/correos-revision/pendientes').status_code == 403
    assert editar(revision, b).status_code == 403


def test_reset_y_eventos_cliente_siguen_automaticos(app, revision):
    revision.post('/prueba-borrador?tipo=restablecer')
    assert len(app.extensions['correos_enviados']) == 1
    assert pendientes(revision) == []
    revision.post('/auth/logout'); login(revision, 'cliA')
    revision.post('/prueba-borrador')
    assert len(app.extensions['correos_enviados']) == 2


def test_invitacion_pendiente_y_validacion(app, revision):
    revision.post('/prueba-borrador?tipo=invitacion')
    [b] = pendientes(revision)
    assert editar(revision, b, asunto='Mal\r\nBcc: otra@ejemplo.com').status_code == 400
    assert editar(revision, b, texto='').status_code == 400
    assert not app.extensions.get('correos_enviados')


def test_csrf(app, revision):
    revision.post('/prueba-borrador')
    [b] = pendientes(revision)
    app.config['WTF_CSRF_ENABLED'] = True
    assert editar(revision, b).status_code == 400
    assert not app.extensions.get('correos_enviados')


def test_fallo_requiere_nueva_confirmacion(app, revision, monkeypatch):
    import smtplib
    revision.post('/prueba-borrador')
    [b] = pendientes(revision)
    app.config['MAIL_BACKEND'] = 'smtp'
    def falla(*a, **k): raise OSError('fallo de prueba')
    monkeypatch.setattr(smtplib, 'SMTP', falla)
    assert editar(revision, b).status_code == 502
    [nuevo] = pendientes(revision)
    assert nuevo['estado'] == 'fallido'
    app.config['MAIL_BACKEND'] = 'memoria'
    assert editar(revision, nuevo).status_code == 200


def test_aviso_diferido_del_equipo_no_elude_revision(app, client):
    from app.models import Cliente, User
    from app.mensajes.servicio import enviar, avisar_si_sigue
    autor = db.session.scalar(db.select(User).filter_by(rol='admin'))
    cliente = db.session.get(Cliente, 1)
    with app.test_request_context():
        mensaje = enviar(autor, cliente, 'Mensaje de prueba', avisar=False)
        db.session.commit()
        avisar_si_sigue(mensaje.id)
    assert not app.extensions.get('correos_enviados')
    borradores = db.session.scalars(db.select(CorreoBorrador)).all()
    assert borradores and all(b.autor_id == autor.id for b in borradores)


def test_caducidad_elimina_contenido(app, revision):
    from app.models import ahora
    from datetime import timedelta
    revision.post('/prueba-borrador?tipo=invitacion')
    [b] = pendientes(revision)
    db.session.execute(db.update(CorreoBorrador).values(caduca=ahora()-timedelta(seconds=1)))
    db.session.commit()
    assert pendientes(revision) == []
    db.session.expire_all()
    assert db.session.get(CorreoBorrador,b['id']).mensaje is None


def test_cambio_estado_real_prepara_correo(app, client):
    from app.models import Pedido, Cliente, LineaPedido
    p = Pedido(cliente=db.session.get(Cliente,1), estado='aceptado', referencia_interna='CLA_123')
    p.lineas.append(LineaPedido(producto_id=1,cantidad=1,precio_unitario=100,iva_pct=21))
    db.session.add(p); db.session.commit()
    login(client,'admin')
    r = client.post(f'/pedidos/{p.id}/preparacion')
    assert r.status_code == 302
    assert not app.extensions.get('correos_enviados')
    lista = pendientes(client)
    assert lista and any('preparaci' in b['asunto'].lower() for b in lista)


def test_reenvio_tambien_exige_revision(app, revision):
    from app.models import CorreoEnviado
    from app.correo import reenviar
    from flask_login import login_user
    from app.models import User
    c=CorreoEnviado(para='destino@ejemplo.com',asunto='Anterior',texto='Texto anterior',estado='enviado',tipo='cliente.preparacion')
    db.session.add(c);db.session.commit()
    with app.test_request_context():
        login_user(db.session.scalar(db.select(User).filter_by(rol='admin')))
        reenviar(c)
    assert not app.extensions.get('correos_enviados')
    [b]=pendientes(revision)
    assert editar(revision,b).status_code == 200
    assert db.session.scalar(db.select(CorreoEnviado).filter_by(reenvio_de_id=c.id)).estado == 'enviado'


def test_sin_javascript_se_guarda_y_no_envia(app, revision):
    revision.post('/prueba-borrador')
    r=revision.get('/')
    assert r.status_code == 200
    assert 'modal-revision-correo' in r.get_data(as_text=True)
    assert not app.extensions.get('correos_enviados')
