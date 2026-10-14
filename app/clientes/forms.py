import re

from flask_babel import gettext as _, lazy_gettext as _l
from flask_wtf import FlaskForm
from wtforms import BooleanField, EmailField, SelectMultipleField, StringField, SubmitField, TextAreaField
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

    def validate_prefijo(self, campo):
        campo.data = (campo.data or "").strip() or prefijo_desde_nombre(self.nombre.data)
        if not re.fullmatch(r"[A-Za-z0-9]{2,10}", campo.data):
            raise ValidationError(_("De 2 a 10 letras o números, sin espacios ni tildes."))
        # único sin distinguir mayúsculas: "DiNA" y "dina" serían confusos
        existente = db.session.scalar(
            db.select(Cliente).where(db.func.lower(Cliente.prefijo) == campo.data.lower()))
        if existente and existente is not self._cliente:
            raise ValidationError(_("Ese prefijo ya lo usa %(nombre)s. Escribe otro.", nombre=existente.nombre))
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

    def validate_cif(self, campo):
        if not campo.data:
            campo.data = None
            return
        campo.data = campo.data.strip().upper().replace("-", "").replace(" ", "")
        existente = db.session.scalar(db.select(Cliente).filter_by(cif=campo.data))
        if existente and existente is not self._cliente:
            raise ValidationError(_("Ese CIF ya está registrado (%(nombre)s).", nombre=existente.nombre))


from flask import render_template, request
from app.models import Cliente  # O el modelo que corresponda
from app.extensions import db  # Asegúrate de importar tu instancia de db


