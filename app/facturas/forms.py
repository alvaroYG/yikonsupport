from datetime import date

from flask_babel import gettext as _, lazy_gettext as _l
from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from wtforms import BooleanField, DateField, SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional, ValidationError

from app.extensions import db
from app.models import ESTADOS_FACTURA, ESTADOS_PROFORMA, Factura, Pedido  # ESTADOS_PROFORMA: los del pedido
from app.pedidos.forms import opciones_clientes


class FacturaForm(FlaskForm):
    numero = StringField(_l("Nº de factura (del sistema contable)"),
                         validators=[DataRequired(), Length(max=50)])
    cliente_id = SelectField(_l("Cliente"), coerce=int, validators=[DataRequired()])
    pedido_id = SelectField(_l("Pedido asociado"), coerce=int, validators=[Optional()])
    fecha_emision = DateField(_l("Fecha de emisión"), default=date.today, validators=[DataRequired()])
    fecha_vencimiento = DateField(_l("Fecha de vencimiento"), validators=[Optional()])
    estado = SelectField(_l("Estado"), choices=list(ESTADOS_FACTURA.items()))
    fecha_pago = DateField(_l("Fecha de pago"), validators=[Optional()])
    revisar = BooleanField()      # solo al registrar: que la revise Soporte de cliente antes de enviarla
    notas = TextAreaField(_l("Notas"), validators=[Optional()],
                          description=_l("Internas: el cliente no las ve."))
    pdf = FileField(_l("PDF de la factura"), render_kw={"accept": "application/pdf,.pdf"},
                    description=_l("El PDF oficial del sistema contable (máx. 15 MB). El cliente podrá descargarlo."))
    submit = SubmitField(_l("Guardar"))

    def __init__(self, *args, factura=None, pedido=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._factura = factura
        self.pdf_leido = None          # (nombre, extensión, bytes) si han subido un PDF válido
        # El pedido que ya lleva la factura (al editar) o desde el que se registra (al crear)
        pedido = pedido or (factura.pedido if factura else None)
        cliente = (factura.cliente if factura else None) or (pedido.cliente if pedido else None)
        self.cliente_id.choices = opciones_clientes()
        # Un cliente dado de baja no sale en la lista, pero su factura se tiene que poder guardar
        if cliente and all(v != cliente.id for v, _t in self.cliente_id.choices):
            self.cliente_id.choices.insert(0, (cliente.id, cliente.nombre))
        pedidos = db.session.scalars(
            db.select(Pedido).where(Pedido.estado.notin_(["cancelado", *ESTADOS_PROFORMA]))
            .order_by(Pedido.fecha.desc()).limit(300)
        ).all()
        self.pedido_id.choices = [(0, _("— Ninguno —"))] + [
            (p.id, f"#{p.id} · {p.cliente.nombre} · {p.fecha:%d/%m/%Y}") for p in pedidos
        ]
        # Igual con un pedido cancelado o antiguo (fuera de los 300 últimos)
        if pedido and all(v != pedido.id for v, _t in self.pedido_id.choices):
            self.pedido_id.choices.insert(1, (pedido.id, f"#{pedido.id} · {pedido.cliente.nombre} · {pedido.fecha:%d/%m/%Y}"))

    def validate_numero(self, campo):
        campo.data = campo.data.strip()
        existente = db.session.scalar(db.select(Factura).filter_by(numero=campo.data))
        if existente and existente is not self._factura:
            raise ValidationError(_("Esa factura ya está registrada."))

    def validate_pedido_id(self, campo):
        if campo.data:
            pedido = db.session.get(Pedido, campo.data)
            if pedido and pedido.cliente_id != self.cliente_id.data:
                raise ValidationError(_("Ese pedido es de otro cliente."))

    def validate_pdf(self, campo):
        from app.archivos import ArchivoNoValido, leer_y_validar
        if campo.data and getattr(campo.data, "filename", ""):
            try:
                self.pdf_leido = leer_y_validar(campo.data, {"pdf"}, firma=b"%PDF")
            except ArchivoNoValido as e:
                raise ValidationError(str(e))

    def validate_fecha_pago(self, campo):
        if self.estado.data == "pagada" and not campo.data:
            raise ValidationError(_("Indica la fecha de pago."))


def _leer_pdf(form, campo):
    """Comprueba el PDF subido y lo deja en form.pdf_leido (nombre, extensión, bytes)."""
    from app.archivos import ArchivoNoValido, leer_y_validar
    if campo.data and getattr(campo.data, "filename", ""):
        try:
            form.pdf_leido = leer_y_validar(campo.data, {"pdf"}, firma=b"%PDF")
        except ArchivoNoValido as e:
            raise ValidationError(str(e))


class FacturaPedidoForm(FlaskForm):
    """Registrar la factura desde la ficha del pedido: el PDF, su nº y el vencimiento (sin importes:
    la factura se hace a mano con "Preparar factura")."""
    numero = StringField(_l("Nº de factura"), validators=[DataRequired(), Length(max=50)])
    fecha_emision = DateField(_l("Emisión"), default=date.today, validators=[DataRequired()])
    fecha_vencimiento = DateField(_l("Vencimiento"), validators=[Optional()])
    pdf = FileField(_l("PDF"), render_kw={"accept": "application/pdf,.pdf"})
    # Que la revise Soporte de cliente antes de enviarla (marcada si el cliente lo tiene activado)
    revisar = BooleanField()
    submit = SubmitField(_l("Registrar factura"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pdf_leido = None

    def validate_numero(self, campo):
        campo.data = campo.data.strip()
        if db.session.scalar(db.select(Factura).filter_by(numero=campo.data)):
            raise ValidationError(_("Esa factura ya está registrada."))

    def validate_fecha_vencimiento(self, campo):
        if campo.data and self.fecha_emision.data and campo.data < self.fecha_emision.data:
            raise ValidationError(_("El vencimiento no puede ser anterior a la emisión."))

    def validate_pdf(self, campo):
        _leer_pdf(self, campo)


class FacturaPdfForm(FlaskForm):
    """Subir (o sustituir) el PDF de una factura ya registrada."""
    pdf = FileField(_l("PDF de la factura"), render_kw={"accept": "application/pdf,.pdf"})
    submit = SubmitField(_l("Subir PDF"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.pdf_leido = None

    def validate_pdf(self, campo):
        if not (campo.data and getattr(campo.data, "filename", "")):
            raise ValidationError(_("Elige el PDF."))
        _leer_pdf(self, campo)
