from flask import request
from flask_babel import gettext as _, lazy_gettext as _l
from flask_wtf import FlaskForm
from wtforms import DateField, IntegerField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Length, NumberRange, Optional, ValidationError

from app.extensions import db
from app.models import Kit, Lote, Producto


class MovimientoForm(FlaskForm):
    # Qué entra o se ajusta: un kit cerrado ("kit-3") o un producto ("producto-5")
    articulo = SelectField(_l("Artículo"), validators=[DataRequired(message=_l("Elige un kit o un producto."))])
    tipo = SelectField(_l("Tipo"), choices=[("entrada", _l("Entrada de mercancía (suma)")),
                                        ("ajuste", _l("Ajuste por recuento (+/−)"))])
    lote = StringField(_l("Lote"), validators=[DataRequired(message=_l("Indica el lote.")), Length(max=60)],
                       description=_l("Tal como viene en la etiqueta. En un ajuste, elige un lote existente."))
    caducidad = DateField(_l("Caducidad"), validators=[Optional()],
                          description=_l("Obligatoria en las entradas."))
    cantidad = IntegerField(_l("Cantidad"), validators=[DataRequired(message=_l("Indica una cantidad.")),
                                                    NumberRange(min=-100000, max=100000)],
                            description=_l("En un ajuste, usa negativo para restar (p. ej. −2 por rotura)."))
    nota = StringField(_l("Nota"), validators=[Optional(), Length(max=250)],
                       description=_l("Albarán del proveedor, motivo del ajuste…"))
    submit = SubmitField(_l("Registrar"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.kits = db.session.scalars(
            db.select(Kit).filter_by(activo=True, cerrado=True).order_by(Kit.nombre)).all()
        self.productos = db.session.scalars(
            db.select(Producto).filter_by(activo=True, controlar_stock=True).order_by(Producto.nombre)).all()
        # Desplegable con dos grupos: primero los kits cerrados (lo normal), luego los productos
        self.articulo.choices = {
            _("Kits cerrados"): [(f"kit-{k.id}", f"{k.referencia} — {k.nombre}") for k in self.kits],
            _("Productos"): [(f"producto-{p.id}", f"{p.referencia} — {p.nombre}") for p in self.productos],
        }
        # Compatibilidad: formularios antiguos que mandan producto_id
        if not self.articulo.data and request and request.form.get("producto_id", "").isdigit():
            self.articulo.data = f"producto-{request.form['producto_id']}"
        self.lote_encontrado = None          # lo usa la vista tras validar

    @property
    def articulo_elegido(self):
        """El Kit o Producto elegido (None si no es válido)."""
        tipo, _sep, id_ = (self.articulo.data or "").partition("-")
        if not id_.isdigit() or tipo not in ("kit", "producto"):
            return None
        return db.session.get(Kit if tipo == "kit" else Producto, int(id_))

    def validate_lote(self, campo):
        campo.data = (campo.data or "").strip()
        articulo = self.articulo_elegido
        if articulo is None:
            return
        existente = db.session.scalar(
            db.select(Lote).where(Lote.codigo == campo.data,
                                  (Lote.kit_id if articulo.tipo_articulo == "kit" else Lote.producto_id) == articulo.id))
        if self.tipo.data == "ajuste":
            if existente is None:
                raise ValidationError(_("Ese lote no existe para este artículo. Los ajustes se hacen sobre un lote que ya tenga movimientos."))
            if self.cantidad.data and self.cantidad.data < 0 and existente.stock + self.cantidad.data < 0:
                raise ValidationError(_("El lote %(lote)s solo tiene %(n)s unidades.",
                                        lote=existente.codigo, n=existente.stock))
            if self.cantidad.data and self.cantidad.data < 0:
                from app.inventario.reservas import error_si_toca_reservas
                if error := error_si_toca_reservas(existente, existente.stock + self.cantidad.data):
                    raise ValidationError(error)
        elif existente is not None and existente.caducidad is None:
            raise ValidationError(_("Ese código es el del stock anterior a los lotes; usa el código real del lote de la caja."))
        elif existente is not None and existente.caducidad and self.caducidad.data \
                and existente.caducidad != self.caducidad.data:
            raise ValidationError(_("El lote %(lote)s ya existe con caducidad %(fecha)s. Revisa el código o la fecha.",
                                    lote=existente.codigo, fecha=existente.caducidad.strftime("%d/%m/%Y")))
        self.lote_encontrado = existente

    def validate(self, extra_validators=None):
        # La caducidad es obligatoria solo en las entradas. No puede ir en un
        # validate_caducidad(): el validador Optional() (necesario para los ajustes,
        # que no la llevan) corta la validación del campo cuando está vacío.
        ok = super().validate(extra_validators)
        if self.tipo.data == "entrada" and not self.caducidad.data:
            self.caducidad.errors = list(self.caducidad.errors) + [_("Indica la fecha de caducidad del lote.")]
            ok = False
        return ok

    def validate_cantidad(self, campo):
        if self.tipo.data == "entrada" and campo.data is not None and campo.data <= 0:
            raise ValidationError(_("Una entrada debe ser positiva. Para restar usa «Ajuste»."))
        if campo.data == 0:
            raise ValidationError(_("La cantidad no puede ser 0."))


class LoteEditForm(FlaskForm):
    """Corregir el código o la caducidad de un lote ya registrado."""
    codigo = StringField(_l("Lote"), validators=[DataRequired(message=_l("Indica el lote.")), Length(max=60)])
    caducidad = DateField(_l("Caducidad"), validators=[Optional()])
    submit = SubmitField(_l("Guardar"))

    def __init__(self, *args, lote=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._lote = lote

    def validate_codigo(self, campo):
        campo.data = (campo.data or "").strip()
        mismo = (Lote.kit_id == self._lote.kit_id) if self._lote.kit_id else (Lote.producto_id == self._lote.producto_id)
        otro = db.session.scalar(db.select(Lote).where(mismo, Lote.codigo == campo.data))
        if otro is not None and otro.id != self._lote.id:
            raise ValidationError(_("Ya hay otro lote %(lote)s de este producto.", lote=campo.data))

    def validate(self, extra_validators=None):
        ok = super().validate(extra_validators)
        # Si el lote ya tenía caducidad no se puede quitar (solo cambiar). Si no la tenía
        # (lotes antiguos "SIN LOTE"), es opcional: se puede añadir o dejarla vacía.
        if self._lote.caducidad is not None and not self.caducidad.data:
            self.caducidad.errors = list(self.caducidad.errors) + [_("Indica la fecha de caducidad del lote.")]
            ok = False
        return ok


class MovimientoEditForm(FlaskForm):
    """Corregir la cantidad o la nota de una entrada o un ajuste manual."""
    cantidad = IntegerField(_l("Cantidad"), validators=[DataRequired(message=_l("Indica una cantidad.")),
                                                    NumberRange(min=-100000, max=100000)])
    nota = StringField(_l("Nota"), validators=[Optional(), Length(max=250)])
    submit = SubmitField(_l("Guardar"))


class AbrirKitForm(FlaskForm):
    """Abrir kits cerrados de un lote: pasan a ser sus productos sueltos."""
    lote_id = SelectField(_l("Lote"), coerce=int, choices=[], validators=[DataRequired()])
    cantidad = IntegerField(_l("Kits que abres"), default=1,
                            validators=[DataRequired(message=_l("Indica cuántos kits abres.")), NumberRange(min=1, max=1000)])
    nota = StringField(_l("Motivo"), validators=[Optional(), Length(max=200)],
                       description=_l("Para qué se abre (p. ej. reponer un reactivo a un cliente)."))
    submit = SubmitField(_l("Abrir kit"))
