from datetime import date, timedelta

from flask_babel import gettext as _, lazy_gettext as _l
from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from wtforms import DateField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional, ValidationError

DIAS_VALIDEZ = 30   # (si no hay nada en Ajustes → Proformas; el valor de verdad sale de ajustes.proformas())


class ProformaForm(FlaskForm):
    """Lo que añade Yikon al enviar la proforma (los productos salen del pedido)."""
    valida_hasta = DateField(_l("Válida hasta"), default=lambda: date.today() + timedelta(days=DIAS_VALIDEZ),
                             validators=[DataRequired()])
    plazo_entrega = StringField(_l("Plazo de entrega estimado"), validators=[Optional(), Length(max=120)],
                                render_kw={"placeholder": _l("p. ej. 5–7 días laborables desde la confirmación")})
    notas = TextAreaField(_l("Notas para el cliente"), validators=[Optional(), Length(max=2000)], render_kw={"rows": 3},
                          description=_l("Las ve en la ficha del pedido (condiciones, transporte, observaciones…)."))
    pdf = FileField(_l("PDF de la proforma"), render_kw={"accept": "application/pdf,.pdf", "required": True},
                    description=_l("La proforma que habéis hecho (la vuestra o basada en el modelo). Es la que descargará el cliente."))
    submit = SubmitField(_l("Enviar proforma al cliente"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pdf_leido = None          # (nombre, extensión, bytes) si han subido un PDF válido

    def validate_pdf(self, campo):
        from app.archivos import ArchivoNoValido, leer_y_validar
        if not (campo.data and getattr(campo.data, "filename", "")):
            raise ValidationError(_("Adjunta el PDF de la proforma."))
        try:
            self.pdf_leido = leer_y_validar(campo.data, {"pdf"}, firma=b"%PDF")
        except ArchivoNoValido as e:
            raise ValidationError(str(e))

    def validate_valida_hasta(self, campo):
        if campo.data and campo.data < date.today():
            raise ValidationError(_("La fecha de validez no puede ser anterior a hoy."))


class RespuestaProformaForm(FlaskForm):
    """El cliente acepta la proforma o pide cambios (explicando cuáles)."""
    # Sin Optional(): cortaría la validación y no llegaría a validate_comentario
    comentario = TextAreaField(_l("¿Qué quiere cambiar?"), validators=[Length(max=2000)],
                               render_kw={"rows": 3, "required": True})
    aceptar = SubmitField(_l("✓ Aceptar y hacer el pedido"))
    cambios = SubmitField(_l("Pedir cambios"))

    def validate_comentario(self, campo):
        if self.cambios.data and not (campo.data or "").strip():
            raise ValidationError(_("Explica qué cambios necesitas."))


class RetirarProformaForm(FlaskForm):
    submit = SubmitField(_l("Retirar para cambiarla"))
