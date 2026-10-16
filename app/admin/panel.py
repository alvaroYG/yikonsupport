"""Agrupa los formularios originales, sin copiar ni reducir sus controles."""
import hashlib
import json
from datetime import date, timedelta

from flask import abort, flash, g, redirect, render_template, request, url_for
from flask_babel import gettext as _, lazy_gettext as _l
from flask_login import current_user
from flask_wtf import FlaskForm
from markupsafe import Markup

from app.admin.routes import bp
from app import control_admin as control
from app.extensions import db
from app.models import Ajuste, Cliente, User
from app.permisos import requiere_permiso

TEMAS = {'operativa': _l('Operativa'), 'comunicaciones': _l('Comunicaciones'),
         'acceso': _l('Acceso y permisos'), 'sistema': _l('Empresa y sistema')}
DESTINOS = {
    'admin.ajustes': ('operativa', 'plazos'),
    'admin.ajustes_proformas': ('operativa', 'proformas'),
    'admin.ajustes_correos': ('comunicaciones', 'correos'),
    'admin.ajustes_avisos': ('comunicaciones', 'avisos'),
    'admin.ajustes_apartados': ('acceso', 'apartados'),
    'admin.ajustes_seguridad': ('acceso', 'seguridad'),
    'admin.ajustes_empresa': ('sistema', 'empresa'),
}
RESTABLECER = {'plazos': ('plazo.',), 'proformas': ('proforma.',), 'seguridad': ('seguridad.',),
              'apartados': ('apartado.',), 'avisos': ('aviso.',),
              'inventario': ('control.caducidad',), 'sistema': ('control.copia', 'control.inactivos', 'control.correos', 'control.revision')}


@bp.before_request
def _agrupar_get():
    if request.method == 'GET' and request.endpoint in DESTINOS:
        tema, seccion = DESTINOS[request.endpoint]
        return ajustes_panel(tema, seccion)


@bp.context_processor
def _contexto_panel():
    return dict(temas_ajustes=TEMAS, destinos_ajustes=DESTINOS)


def _fragmento(funcion):
    """Renderiza la misma vista con base mínima y formularios con action explícito."""
    anterior = getattr(g, 'ajustes_embebidos', False)
    g.ajustes_embebidos = True
    try:
        return Markup(funcion())
    finally:
        g.ajustes_embebidos = anterior


@bp.route('/ajustes/panel/<tema>')
@requiere_permiso('ajustes.editar')
def ajustes_panel(tema, seccion=None):
    if tema not in TEMAS:
        abort(404)
    from app.admin import routes, ajustes_mas, ajustes_apartados, ajustes_correos
    grupos = {
        'operativa': [('plazos', _('Plazos de pedidos'), routes.ajustes),
                      ('inventario', _('Inventario'), lambda: controles('inventario')),
                      ('proformas', _('Proformas'), ajustes_mas.ajustes_proformas),
                      ('pausa', _('Nuevas solicitudes de pedido'), lambda: pausa_form())],
        'comunicaciones': [('anuncios', _('Avisos publicados para clientes'), anuncios_form),
                           ('correos', _('Correos al cliente'), ajustes_correos.ajustes_correos),
                           ('avisos', _('Avisos internos'), ajustes_mas.ajustes_avisos)],
        'acceso': [('seguridad', _('Seguridad'), ajustes_mas.ajustes_seguridad),
                   ('apartados', _('Qué ve cada rol'), ajustes_apartados.ajustes_apartados)],
        'sistema': [('empresa', _('Datos de Yikon'), ajustes_mas.ajustes_empresa),
                    ('sistema', _('Avisos de funcionamiento'), lambda: controles('sistema')),
                    ('mantenimiento', _('Modo mantenimiento'), mantenimiento_form)],
    }
    seccion = request.args.get('seccion') or seccion or grupos[tema][0][0]
    partes = [(clave, titulo, _fragmento(fn)) for clave, titulo, fn in grupos[tema]]
    return render_template('admin/panel.html', tema=tema, title=TEMAS[tema], partes=partes,
                           abierta=seccion, restaurables=RESTABLECER)


def volver(tema, seccion):
    return redirect(url_for('admin.ajustes_panel', tema=tema, seccion=seccion, _anchor=seccion))


def controles(grupo):
    campos = ['caducidad'] if grupo == 'inventario' else ['copia', 'inactivos', 'correos', 'revision']
    return render_template('admin/_controles.html', grupo=grupo, campos=campos, definiciones=control.CAMPOS,
                           valores={c: control.numero(c) for c in campos}, form=FlaskForm())


@bp.route('/ajustes/controles/<grupo>', methods=['POST'])
@requiere_permiso('ajustes.editar')
def guardar_controles(grupo):
    if grupo not in ('inventario', 'sistema') or not FlaskForm().validate_on_submit():
        abort(400)
    campos = ['caducidad'] if grupo == 'inventario' else ['copia', 'inactivos', 'correos', 'revision']
    nuevos = {c: request.form.get(c, type=int) for c in campos}
    if any(nuevos[c] is None or not control.CAMPOS[c][2] <= nuevos[c] <= control.CAMPOS[c][3] for c in campos):
        flash(_('Revisa los límites de los valores introducidos.'), 'danger')
    else:
        for c, n in nuevos.items():
            control.guardar('control.' + c, None if n == control.defecto(c) else n)
        db.session.commit()
        flash(_('Guardado.'), 'success')
    return volver('operativa' if grupo == 'inventario' else 'sistema', grupo)


def pausa_form(cliente_id=None):
    return render_template('admin/_pausa.html', pausa=control.pausa(cliente_id), cliente_id=cliente_id, form=FlaskForm())


@bp.route('/ajustes/pausa', methods=['POST'])
@requiere_permiso('ajustes.editar')
def guardar_pausa():
    if not FlaskForm().validate_on_submit():
        abort(400)
    cliente_id = request.form.get('cliente_id', type=int)
    if request.form.get('cliente_id') and not cliente_id:
        abort(400)
    if cliente_id:
        db.get_or_404(Cliente, cliente_id)
    textos = {i: request.form.get('pausa_' + i, '').strip() for i in ('es', 'en')}
    if any(len(v) > 600 for v in textos.values()):
        abort(400)
    control.guardar(f'pausa.{cliente_id or "global"}', json.dumps(dict(textos, activa=request.form.get('pausada') == '1'), ensure_ascii=False))
    db.session.commit()
    flash(_('Guardado.'), 'success')
    return redirect(url_for('clientes.detalle', id=cliente_id) + '#pausa-pedidos') if cliente_id else volver('operativa', 'pausa')


def mantenimiento_form():
    from app import mantenimiento
    return render_template('admin/_mantenimiento.html', mantenimiento=mantenimiento.estado(), form=FlaskForm())


def anuncios_form():
    from app import aviso_clientes
    anuncios = control.anuncios()
    elegido = next((a for a in anuncios if a['id'] == request.args.get('editar')), {})
    return render_template('admin/_anuncios.html', anuncios=anuncios, elegido=elegido,
        estado_anuncio=control.estado_anuncio, clientes=db.session.scalars(db.select(Cliente).order_by(Cliente.nombre)).all(),
        form=FlaskForm(), aviso=aviso_clientes.datos(), estado_aviso=aviso_clientes.estado(), max_aviso=aviso_clientes.MAX_TEXTO)


@bp.route('/ajustes/anuncios', methods=['POST'])
@requiere_permiso('ajustes.editar')
def guardar_anuncio():
    if not FlaskForm().validate_on_submit():
        abort(400)
    id = request.form.get('id') or control.nuevo_id()
    if len(id) != 32 or any(c not in '0123456789abcdef' for c in id):
        abort(400)
    if request.form.get('id') and db.session.get(Ajuste, 'anuncio.' + id) is None:
        abort(404)
    if request.form.get('accion') == 'retirar':
        a = json.loads(control.leer('anuncio.' + id))
        a['publicado'] = False
    else:
        a = {c: request.form.get(c, '').strip() for c in ('titulo', 'es', 'en', 'desde', 'hasta')}
        if not a['titulo'] or len(a['titulo']) > 120 or not (a['es'] or a['en']) or max(len(a['es']), len(a['en'])) > 600:
            abort(400)
        try:
            for c in ('desde', 'hasta'):
                if a[c]:
                    date.fromisoformat(a[c])
            ids = sorted(set(int(i) for i in request.form.getlist('clientes')))
        except ValueError:
            abort(400)
        if a['desde'] and a['hasta'] and a['desde'] > a['hasta']:
            flash(_('La fecha «hasta» no puede ser anterior a «desde».'), 'danger')
            return volver('comunicaciones', 'anuncios')
        if request.form.get('destinatarios') == 'seleccion':
            if not ids or len(db.session.scalars(db.select(Cliente.id).where(Cliente.id.in_(ids))).all()) != len(ids):
                abort(400)
            a['clientes'] = ids
        elif request.form.get('destinatarios') == 'todos':
            a['clientes'] = []
        else:
            abort(400)
        a['publicado'] = request.form.get('publicado') == '1'
    control.guardar('anuncio.' + id, json.dumps(a, ensure_ascii=False, sort_keys=True))
    db.session.commit()
    flash(_('Guardado.'), 'success')
    return volver('comunicaciones', 'anuncios')


@bp.route('/usuarios/<int:id>/acceso', methods=['POST'])
@requiere_permiso('usuarios.gestionar')
def usuario_acceso(id):
    from app.auditoria import registrar
    if not FlaskForm().validate_on_submit():
        abort(400)
    user = db.get_or_404(User, id)
    accion = request.form.get('accion')
    if accion == 'cerrar':
        db.session.execute(db.update(User).where(User.id == id).values(sesion_version=User.sesion_version + 1))
        registrar('editar', user, 'cierre de todas las sesiones')
    elif accion == 'password':
        user.cambiar_password = request.form.get('exigir') == '1'
        registrar('editar', user, f'cambio obligatorio de contraseña: {user.cambiar_password}')
    else:
        abort(400)
    db.session.commit()
    flash(_('Control de acceso actualizado.'), 'success')
    return redirect(url_for('admin.editar_usuario', id=id))


def _restauracion(grupo):
    prefijos = RESTABLECER[grupo]
    filas = db.session.scalars(db.select(Ajuste).order_by(Ajuste.clave)).all()
    return [f for f in filas if any(f.clave.startswith(p) if p.endswith('.') else f.clave == p for p in prefijos)]


@bp.route('/ajustes/restaurar/<grupo>', methods=['GET', 'POST'])
@requiere_permiso('ajustes.editar')
def ajustes_restaurar(grupo):
    if grupo not in RESTABLECER:
        abort(404)
    filas = _restauracion(grupo)
    huella = hashlib.sha256(json.dumps([(f.clave, f.valor) for f in filas]).encode()).hexdigest()
    form = FlaskForm()
    if form.validate_on_submit():
        if request.form.get('huella') != huella:
            flash(_('Los ajustes han cambiado. Revisa de nuevo la vista previa.'), 'warning')
            return redirect(url_for('admin.ajustes_restaurar', grupo=grupo))
        for f in filas:
            db.session.delete(f)
        db.session.commit()
        flash(_('Valores de fábrica restaurados para esta sección.'), 'success')
        return volver('acceso' if grupo in ('seguridad', 'apartados') else 'comunicaciones' if grupo == 'avisos' else 'sistema' if grupo == 'sistema' else 'operativa', grupo)
    from app import ajustes, seguridad
    def fabrica(clave):
        if clave.startswith('apartado.'):
            from app import apartados
            _, apartado, rol = clave.split('.')
            return _('Sí') if apartados.de_fabrica(apartado, rol) else _('No')
        if clave.startswith('aviso.'):
            from app import avisos_internos
            _, aviso, rol = clave.split('.')
            return _('Sí') if rol in avisos_internos.AVISOS[aviso].de_fabrica else _('No')
        if clave.startswith('plazo.'):
            return ajustes.PLAZOS[clave[6:]][0]
        if clave.startswith('seguridad.'):
            return seguridad.de_fabrica(clave[10:])
        if clave.startswith('control.'):
            return control.defecto(clave[8:])
        return ajustes.VALIDEZ_DE_FABRICA if clave == 'proforma.validez' else _('Vacío')
    return render_template('admin/restaurar.html', title=_('Restaurar valores de fábrica'),
        filas=filas, fabrica=fabrica, form=form, huella=huella, grupo=grupo)
