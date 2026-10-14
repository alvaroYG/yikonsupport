from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from flask_wtf.file import MultipleFileField
from wtforms import SelectField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, ValidationError

from app.mensajes.servicio import MAX_ADJUNTOS, MAX_TEXTO


class MensajeForm(FlaskForm):
    # strip: un mensaje de solo espacios o saltos de línea cuenta como vacío
    texto = TextAreaField(_l("Mensaje"), filters=[lambda s: (s or "").strip()],
                          validators=[Length(max=MAX_TEXTO, message=_l("Máximo %(max)d caracteres."))])
    adjuntos = MultipleFileField(_l("Adjuntar archivos"), render_kw={"multiple": True},
                                 description=_l("Hasta %(n)s archivos de 15 MB: PDF, Word, Excel, imagen…", n=MAX_ADJUNTOS))
    submit = SubmitField(_l("Enviar"))

    def hay_adjuntos(self):
        return any(f and getattr(f, "filename", "") for f in (self.adjuntos.data or []))

    def validate_texto(self, campo):
        # Vale un mensaje solo con texto, solo con archivos, o con las dos cosas
        if not campo.data and not self.hay_adjuntos():
            raise ValidationError(_l("Escribe un mensaje o adjunta un archivo."))


class NuevoMensajeForm(MensajeForm):
    """Ventana "Mensaje nuevo" de la página Mensajes (Yikon (admin, logística, FAS)): elegir cliente y escribir.
    El mensaje va a la conversación general de ese cliente."""
    cliente_id = SelectField(_l("Cliente"), coerce=int,
                             validators=[DataRequired(message=_l("Elige el cliente."))])
