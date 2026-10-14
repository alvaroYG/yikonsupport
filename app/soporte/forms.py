from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from flask_wtf.file import MultipleFileField
from wtforms import RadioField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional, ValidationError

from app.models import CATEGORIAS_TICKET, ESTADOS_TICKET, PRIORIDADES_TICKET
from app.soporte.servicio import MAX_ADJUNTOS, MAX_TEXTO

AYUDA_ADJUNTOS = _l("Hasta %(n)s archivos de 15 MB: capturas de pantalla, PDF, Excel, .log…", n=MAX_ADJUNTOS)


def _limpiar(s):
    return (s or "").strip()


class TicketForm(FlaskForm):
    # Solo lo ve el equipo (al abrir un ticket en nombre de un cliente); se quita para el cliente
    cliente_id = SelectField(_l("Cliente"), coerce=int, validators=[DataRequired(message=_l("Elige el cliente."))])
    asunto = StringField(_l("Asunto"), filters=[_limpiar], validators=[DataRequired(), Length(max=200)],
                         description=_l("En una frase, p. ej. «El informe CNV de la muestra no se genera»."))
    categoria = SelectField(_l("Tipo de problema"), choices=list(CATEGORIAS_TICKET.items()))
    # La explicación de cada opción (AYUDA_PRIORIDAD_TICKET) la pinta la plantilla
    prioridad = RadioField(_l("¿Cuánto le afecta?"), default="normal", choices=list(PRIORIDADES_TICKET.items()))
    referencia = StringField(_l("ID de muestra, análisis o run en ChromGo"), filters=[_limpiar],
                             validators=[Optional(), Length(max=120)],
                             description=_l("Opcional. Solo el identificador interno: nunca nombres ni datos del paciente."))
    texto = TextAreaField(_l("Descripción"), filters=[_limpiar],
                          validators=[DataRequired(message=_l("Cuéntenos qué ocurre.")),
                                      Length(max=MAX_TEXTO, message=_l("Máximo %(max)d caracteres."))],
                          description=_l("Qué intentaba hacer, qué ha pasado y, si sale, el mensaje de error."))
    adjuntos = MultipleFileField(_l("Adjuntar archivos"), render_kw={"multiple": True}, description=AYUDA_ADJUNTOS)
    submit = SubmitField(_l("Enviar ticket"))


class RespuestaForm(FlaskForm):
    texto = TextAreaField(_l("Mensaje"), filters=[_limpiar],
                          validators=[Length(max=MAX_TEXTO, message=_l("Máximo %(max)d caracteres."))])
    adjuntos = MultipleFileField(_l("Adjuntar archivos"), render_kw={"multiple": True}, description=AYUDA_ADJUNTOS)
    # Solo el equipo, en la conversación con el cliente: en qué estado queda el ticket al responder
    dejar_en = SelectField(_l("Dejar el ticket en"), default="esperando_cliente",
                           choices=[(k, ESTADOS_TICKET[k]) for k in ("esperando_cliente", "en_curso", "resuelto")])
    submit = SubmitField(_l("Enviar"))

    def hay_adjuntos(self):
        return any(f and getattr(f, "filename", "") for f in (self.adjuntos.data or []))

    def validate_texto(self, campo):
        if not campo.data and not self.hay_adjuntos():
            raise ValidationError(_l("Escribe un mensaje o adjunta un archivo."))


class GestionForm(FlaskForm):
    """Panel del equipo: estado, prioridad, tipo y quién lo lleva."""
    estado = SelectField(_l("Estado"), choices=list(ESTADOS_TICKET.items()))
    prioridad = SelectField(_l("Prioridad"), choices=list(PRIORIDADES_TICKET.items()))
    categoria = SelectField(_l("Tipo de problema"), choices=list(CATEGORIAS_TICKET.items()))
    asignado_a_id = SelectField(_l("Lo lleva"), coerce=int)
    submit = SubmitField(_l("Guardar cambios"))
