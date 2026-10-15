import re

from flask_babel import gettext as _, lazy_gettext as _l
from flask_wtf import FlaskForm
from wtforms import (BooleanField, EmailField, HiddenField, SelectField, SelectMultipleField, StringField, SubmitField,
                     TextAreaField)
from wtforms.validators import DataRequired, Email, Length, Optional, ValidationError
from flask import render_template, request
from app.extensions import db
from app.models import Cliente, Pedido, User, prefijo_desde_nombre
from app.permisos import NOMBRE_FAS


class ClienteForm(FlaskForm):
    nombre = StringField(_l("Nombre comercial"), validators=[DataRequired(), Length(max=150)])
    razon_social = StringField(_l("Razón social"), validators=[Optional(), Length(max=200)])
    cif = StringField(_l("CIF / NIF"), validators=[Optional(), Length(max=20)])
    # Sin validators=[Optional()]: Optional() corta la validación si el campo está
    # vacío y entonces validate_prefijo no llegaría a ejecutarse para rellenarlo.
    prefijo = StringField(
        _l("Prefijo de pedidos"),
        description=_l("Para las referencias internas (DiNA → DiNA_001). "
                       "Si lo dejas vacío se toma la primera palabra del nombre."),
    )
    email = EmailField(_l("Email"), validators=[Optional(), Email()])
    telefono = StringField(_l("Teléfono"), validators=[Optional(), Length(max=30)])
    persona_contacto = StringField(_l("Persona de contacto"), validators=[Optional(), Length(max=120)])
    direccion = StringField(_l("Dirección"), validators=[Optional(), Length(max=250)])
    ciudad = StringField(_l("Ciudad"), validators=[Optional(), Length(max=100)])
    codigo_postal = StringField(_l("Código postal"), validators=[Optional(), Length(max=12)])
    provincia = StringField(_l("Provincia"), validators=[Optional(), Length(max=100)])
    pais = StringField(_l("País"), validators=[Optional(), Length(max=80)], default="España")
    # Datos de envío (salen en el albarán)
    envio_igual = BooleanField(_l("Se envía a la dirección de facturación"), default=True)
    envio_destinatario = StringField(_l("Destinatario / centro"), validators=[Optional(), Length(max=200)],
                                     description=_l("Vacío: la razón social."))
    envio_contacto = StringField(_l("Persona que recibe"), validators=[Optional(), Length(max=120)],
                                 description=_l("Vacío: la persona de contacto."))
    envio_telefono = StringField(_l("Teléfono de entrega"), validators=[Optional(), Length(max=30)],
                                 description=_l("Vacío: el teléfono de la empresa."))
    envio_direccion = StringField(_l("Dirección de envío"), validators=[Optional(), Length(max=250)])
    envio_codigo_postal = StringField(_l("Código postal"), validators=[Optional(), Length(max=12)])
    envio_ciudad = StringField(_l("Ciudad"), validators=[Optional(), Length(max=100)])
    envio_provincia = StringField(_l("Provincia"), validators=[Optional(), Length(max=100)])
    envio_pais = StringField(_l("País"), validators=[Optional(), Length(max=80)], default="España")
    envio_instrucciones = TextAreaField(_l("Instrucciones de entrega"), validators=[Optional(), Length(max=1000)],
                                        description=_l("Horario, planta, muelle… Sale en el albarán."))
    # Mapa de clientes: el punto lo pone el mapita del formulario al hacer clic (si no, se busca la ciudad)
    latitud = HiddenField()
    longitud = HiddenField()
    ubicacion_manual = HiddenField()
    logisticos = SelectMultipleField(
        _l("%(rol)s: personas asignadas", rol=NOMBRE_FAS), coerce=int,
        description=_l("Ctrl + clic para seleccionar varios."),
    )
    notas = TextAreaField(_l("Notas"), validators=[Optional()])
    activo = BooleanField(_l("Activo"), default=True)
    submit = SubmitField(_l("Guardar"))

    def __init__(self, *args, cliente=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._cliente = cliente
        logisticos = db.session.scalars(
            db.select(User).filter_by(rol="fas", activo=True).order_by(User.nombre)
        ).all()
        self.logisticos.choices = [(u.id, u.nombre) for u in logisticos]
        # Quién es su Soporte de cliente decide quién ve sus pedidos y su conversación: solo admin
        from flask_login import current_user
        if not current_user.puede("clientes.asignar_soporte"):
            del self.logisticos

    def validate_prefijo(self, campo):
        campo.data = (campo.data or "").strip() or prefijo_desde_nombre(self.nombre.data)
        if not re.fullmatch(r"[A-Za-z0-9]{2,10}", campo.data):
            raise ValidationError(_("De 2 a 10 letras o números, sin espacios ni tildes."))
        # único sin distinguir mayúsculas: "DiNA" y "dina" serían confusos
        existente = db.session.scalar(
            db.select(Cliente).where(db.func.lower(Cliente.prefijo) == campo.data.lower()))
        if existente and existente is not self._cliente:
            raise ValidationError(_("Ese prefijo ya lo usa %(nombre)s. Escribe otro.", nombre=existente.nombre)
                                  if _ve_todos() else _("Ese prefijo ya lo usa otro cliente. Escribe otro."))
        # Tampoco uno que otra empresa usó antes (y luego cambió): sus pedidos antiguos siguen
        # llamándose YK-2026-PREFIJO-1 (o PREFIJO_001, el formato de antes de octubre de 2026)
        # y la referencia interna es única.
        p = campo.data.lower()
        referencia = db.func.lower(Pedido.referencia_interna)
        usado = db.select(Pedido.id).where(db.or_(
            referencia.like(p + "\\_%", escape="\\"), referencia.like(f"yk-____-{p}-%")))
        if self._cliente is not None:
            usado = usado.where(Pedido.cliente_id != self._cliente.id)
        if db.session.scalar(usado.limit(1)):
            raise ValidationError(_("Ese prefijo ya se usó en pedidos de otra empresa. Escribe otro."))

    def punto(self):
        """(latitud, longitud) que viene del mapita, o None si no hay o no es válido."""
        try:
            lat, lon = float(self.latitud.data), float(self.longitud.data)
        except (TypeError, ValueError):
            return None
        return (lat, lon) if -90 <= lat <= 90 and -180 <= lon <= 180 else None

    def validate_cif(self, campo):
        if not campo.data:
            campo.data = None
            return
        campo.data = campo.data.strip().upper().replace("-", "").replace(" ", "")
        existente = db.session.scalar(db.select(Cliente).filter_by(cif=campo.data))
        if existente and existente is not self._cliente:
            # (Soporte de cliente no ve los clientes de otros: sin el nombre)
            raise ValidationError(_("Ese CIF ya está registrado (%(nombre)s).", nombre=existente.nombre)
                                  if _ve_todos() else _("Ese CIF ya está registrado en otro cliente."))


def _ve_todos():
    from flask_login import current_user
    return current_user.puede("clientes.editar")


class UsuarioClienteForm(FlaskForm):
    """Un usuario de la empresa cliente, desde su ficha (Soporte de cliente y admin). Siempre con el rol
    Cliente y en esta empresa; sin contraseña: se le manda la invitación para que la elija él."""
    nombre = StringField(_l("Nombre"), validators=[DataRequired(), Length(max=100)])
    email = EmailField(_l("Email"), validators=[DataRequired(), Email(), Length(max=120)])
    idioma = SelectField(_l("Idioma"), choices=[("", _l("Automático (el de su navegador)")),
                                               ("es", "Español"), ("en", "English")],
                         default="", description=_l("Idioma de la web y de los emails que recibe."))
    activo = BooleanField(_l("Activo"), default=True,
                          description=_l("Desactivado no puede entrar (sus pedidos y mensajes se quedan)."))
    submit = SubmitField(_l("Guardar"))

    def __init__(self, *args, usuario=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._usuario = usuario

    def validate_email(self, campo):
        campo.data = campo.data.strip().lower()
        existente = db.session.scalar(db.select(User).filter_by(email=campo.data))
        if existente and existente is not self._usuario:
            raise ValidationError(_("Ya existe un usuario con ese email."))

