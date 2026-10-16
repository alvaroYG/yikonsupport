"""Controles operativos, sin cambiar las claves ni los valores de ajustes existentes."""
import json
from datetime import date
from uuid import uuid4

from flask import current_app
from flask_babel import gettext as _, lazy_gettext as _l

from app.extensions import db
from app.models import Ajuste

CAMPOS = {
    'caducidad': (_l('Anticipación de caducidades'), 7, 1, 365, _l('días')),
    'copia': (_l('Avisar sin copia reciente tras'), 2, 1, 365, _l('días')),
    'inactivos': (_l('Cuenta sin entrar durante'), 90, 1, 3650, _l('días')),
    'correos': (_l('Revisar correos fallidos de las últimas'), 168, 1, 8760, _l('horas')),
    'revision': (_l('Correo pendiente de revisión durante'), 2, 1, 365, _l('días')),
}


def leer(clave, defecto=''):
    fila = db.session.get(Ajuste, clave)
    return fila.valor if fila is not None else defecto


def guardar(clave, valor):
    fila = db.session.get(Ajuste, clave)
    if valor is None:
        if fila is not None:
            db.session.delete(fila)
    elif fila is None:
        db.session.add(Ajuste(clave=clave, valor=str(valor)))
    else:
        fila.valor = str(valor)


def defecto(campo):
    return current_app.config.get('DIAS_AVISO_CADUCIDAD', 7) if campo == 'caducidad' else CAMPOS[campo][1]


def numero(campo):
    try:
        n = int(leer('control.' + campo, str(defecto(campo))))
        return n if CAMPOS[campo][2] <= n <= CAMPOS[campo][3] else defecto(campo)
    except (ValueError, TypeError):
        return defecto(campo)


def pausa(cliente_id=None):
    try:
        return json.loads(leer(f'pausa.{cliente_id or "global"}', '{}'))
    except (ValueError, TypeError):
        return {}


def bloqueo(cliente_id, idioma='es'):
    for p in (pausa(), pausa(cliente_id)):
        if p.get('activa'):
            return p.get(idioma) or p.get('es') or p.get('en') or _('Temporalmente no se aceptan nuevas solicitudes de pedido.')
    return None


def anuncios():
    resultado = []
    for a in db.session.scalars(db.select(Ajuste).where(Ajuste.clave.startswith('anuncio.')).order_by(Ajuste.clave)):
        try:
            valor = json.loads(a.valor)
            resultado.append(dict(valor, id=a.clave.removeprefix('anuncio.')))
        except (ValueError, TypeError):
            continue
    return resultado


def estado_anuncio(a, hoy=None):
    hoy = (hoy or date.today()).isoformat()
    if not a.get('publicado'):
        return _('Borrador')
    if a.get('desde') and a['desde'] > hoy:
        return _('Programado')
    if a.get('hasta') and a['hasta'] < hoy:
        return _('Finalizado')
    return _('Visible')


def anuncios_para(usuario, idioma, hoy=None):
    from app.aviso_clientes import huella
    if usuario.rol != 'cliente':
        return []
    hoy = (hoy or date.today()).isoformat()
    resultado = []
    for a in anuncios():
        if (not a.get('publicado') or (a.get('clientes') and usuario.cliente_id not in a['clientes'])
                or (a.get('desde') and a['desde'] > hoy) or (a.get('hasta') and a['hasta'] < hoy)):
            continue
        texto = a.get(idioma) or a.get('es') or a.get('en')
        marca = huella(json.dumps(a, sort_keys=True, ensure_ascii=False))
        if texto and (usuario.anuncios_cerrados or {}).get(a['id']) != marca:
            resultado.append(dict(a, texto=texto, huella=marca))
    return resultado


def nuevo_id():
    return uuid4().hex


def registrar_auditoria():
    """El antes/después se guarda en la MISMA transacción, incluso con autoflush."""
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    if event.contains(Session, 'before_flush', _auditar_ajustes):
        return
    event.listen(Session, 'before_flush', _auditar_ajustes)


def _auditar_ajustes(sesion, _contexto, _instancias):
    from flask import has_request_context
    from flask_login import current_user
    from sqlalchemy import inspect
    from app.models import RegistroAuditoria, PlantillaCorreo
    if not has_request_context() or not current_user.is_authenticated:
        return
    for fila in list(sesion.new) + list(sesion.dirty) + list(sesion.deleted):
        if isinstance(fila, PlantillaCorreo):
            for campo in ('asunto', 'cuerpo'):
                hist = inspect(fila).attrs[campo].history
                antes = None if fila in sesion.new else (hist.deleted[0] if hist.deleted else getattr(fila, campo))
                despues = None if fila in sesion.deleted else getattr(fila, campo)
                if antes != despues:
                    clave = f'correo.{fila.clave}.{fila.idioma}.{campo}'
                    sesion.add(RegistroAuditoria(usuario_id=current_user.id, accion='editar', entidad='Ajuste',
                        objeto=clave, detalle='Cambio de plantilla de correo', ajuste_clave=clave,
                        valor_anterior=antes, valor_nuevo=despues))
            continue
        if not isinstance(fila, Ajuste):
            continue
        hist = inspect(fila).attrs.valor.history
        if fila in sesion.new:
            antes, despues = None, fila.valor
        elif fila in sesion.deleted:
            antes, despues = fila.valor, None
        elif hist.has_changes():
            antes, despues = hist.deleted[0] if hist.deleted else None, fila.valor
        else:
            continue
        if antes == despues:
            continue
        sesion.add(RegistroAuditoria(usuario_id=current_user.id, accion='editar', entidad='Ajuste',
            objeto=fila.clave[:250], detalle='Cambio de configuración', ajuste_clave=fila.clave,
            valor_anterior=antes, valor_nuevo=despues))
