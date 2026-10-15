from decimal import Decimal

from flask_babel import gettext as _, lazy_gettext as _l
from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from wtforms import (BooleanField, DecimalField, FieldList, Form, FormField, IntegerField, SelectField,
                     StringField, SubmitField, TextAreaField)
from wtforms.validators import DataRequired, InputRequired, Length, NumberRange, Optional, ValidationError

from app.extensions import db
from app.models import Kit, Producto

TIPOS_IVA = [("21.00", "21 %"), ("10.00", "10 %"), ("4.00", "4 %"), ("0.00", _l("0 % / exento"))]


class ProductoForm(FlaskForm):
    referencia = StringField(_l("Referencia"), validators=[DataRequired(), Length(max=50)])
    nombre = StringField(_l("Nombre"), validators=[DataRequired(), Length(max=200)])
    categoria = StringField(_l("Marca"), validators=[Optional(), Length(max=80)])
    codigo_hs = StringField(_l("HS Code (código arancelario)"), validators=[Optional(), Length(max=20)],
                            default="3822190090", description=_l("Sale en la factura en Excel."))
    # InputRequired y no DataRequired: DataRequired trata el 0 como "vacío" (y 0 € es válido)
    precio = DecimalField(_l("Precio sin IVA (€)"), places=2,
                          validators=[InputRequired(), NumberRange(min=0, max=99999999.99)])
    iva_pct = SelectField(_l("IVA"), choices=TIPOS_IVA, coerce=Decimal)
    controlar_stock = BooleanField(_l("Controlar stock en inventario"), default=True,
                                   description=_l("Desmárcalo para servicios u otros productos que no son mercancía."))
    stock_minimo = IntegerField(_l("Stock mínimo"), default=0, validators=[NumberRange(min=0)],
                                description=_l("Por debajo de esto, el inventario avisa de stock bajo."))
    activo = BooleanField(_l("Activo"), default=True)
    sds_pdf = FileField(_l("Ficha de seguridad (SDS)"), render_kw={"accept": "application/pdf,.pdf"},
                        description=_l("PDF (máx. 15 MB). Los clientes la descargan desde su apartado de Productos."))
    submit = SubmitField(_l("Guardar"))

    def __init__(self, *args, producto=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._producto = producto
        self.sds_leida = None          # (nombre, extensión, bytes) si han subido un PDF válido

    def populate_obj(self, obj):
        # El archivo no es un atributo del producto: lo guarda la vista (_guardar_sds)
        for nombre, campo in self._fields.items():
            if nombre != "sds_pdf":
                campo.populate_obj(obj, nombre)

    def validate_sds_pdf(self, campo):
        from app.archivos import ArchivoNoValido, leer_y_validar
        if campo.data and getattr(campo.data, "filename", ""):
            try:
                self.sds_leida = leer_y_validar(campo.data, {"pdf"}, firma=b"%PDF")
            except ArchivoNoValido as e:
                raise ValidationError(str(e))

    def validate_referencia(self, campo):
        campo.data = campo.data.strip().upper()
        existente = db.session.scalar(db.select(Producto).filter_by(referencia=campo.data))
        if existente and existente is not self._producto:
            raise ValidationError(_("Ya existe un producto con esa referencia."))


class ComponenteForm(Form):
    """Una fila del kit: producto + unidades por kit (va dentro de KitForm)."""
    producto_id = SelectField(_l("Producto"), coerce=int, choices=[])
    cantidad = IntegerField(_l("Unidades por kit"), default=1, validators=[Optional(), NumberRange(min=1, max=10000)])


class KitForm(FlaskForm):
    referencia = StringField(_l("Referencia"), validators=[DataRequired(), Length(max=50)])
    nombre = StringField(_l("Nombre"), validators=[DataRequired(), Length(max=200)])
    descripcion = TextAreaField(_l("Descripción"), validators=[Optional()],
                                description=_l("Opcional. La ve también el cliente al elegir el kit."))
    precio = DecimalField(_l("Precio estándar de un kit, sin IVA (€)"), places=2,
                          validators=[InputRequired(), NumberRange(min=0, max=99999999.99)],
                          description=_l("A cada cliente se le puede poner un precio especial desde su ficha."))
    iva_pct = SelectField(_l("IVA"), choices=TIPOS_IVA, coerce=Decimal)
    componentes = FieldList(FormField(ComponenteForm), min_entries=1, max_entries=40)
    cerrado = BooleanField(_l("Kit cerrado (llega del fabricante con su propio lote y caducidad)"), default=True,
                           description=_l("Lo normal. El stock y los lotes son del kit y al enviarlo sale entero. "
                                          "Desmárcalo solo si el kit se monta en la oficina con productos sueltos."))
    stock_minimo = IntegerField(_l("Stock mínimo del kit"), default=0, validators=[Optional(), NumberRange(min=0, max=100000)],
                                description=_l("Solo kits cerrados: por debajo, el inventario avisa de stock bajo."))
    activo = BooleanField(_l("Activo"), default=True)
    submit = SubmitField(_l("Guardar"))

    def __init__(self, *args, kit=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._kit = kit
        opciones = [(0, _("— Elige un producto —"))] + [
            (p.id, f"{p.referencia} — {p.nombre}") for p in db.session.scalars(
                db.select(Producto).filter_by(activo=True).order_by(Producto.nombre))]
        # un producto que ya estaba en el kit y luego se desactivó sigue saliendo (si no, no se podría guardar)
        if kit:
            for c in kit.componentes:
                if all(v != c.producto_id for v, _t in opciones):
                    opciones.append((c.producto_id, f"{c.producto.referencia} — {c.producto.nombre}"))
        for fila in self.componentes:
            fila.form.producto_id.choices = opciones

    def validate_referencia(self, campo):
        campo.data = campo.data.strip().upper()
        existente = db.session.scalar(db.select(Kit).filter_by(referencia=campo.data))
        if existente and existente is not self._kit:
            raise ValidationError(_("Ya existe un kit con esa referencia."))

    def validate_componentes(self, campo):
        if not self.productos_del_kit():
            raise ValidationError(_("Añade al menos un producto al kit."))

    def productos_del_kit(self) -> dict:
        """{producto_id: unidades por kit}, en el orden de las filas (el orden del kit).
        Ignora filas vacías; si un producto se repite, suma (y cuenta su primera posición)."""
        total = {}
        for fila in self.componentes:
            pid, cant = fila.form.producto_id.data, fila.form.cantidad.data
            if pid and cant:
                total[pid] = total.get(pid, 0) + cant
        return total
