import json
from datetime import date

from flask_babel import gettext as _, lazy_gettext as _l
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, MultipleFileField
from wtforms import (DateField, DecimalField, FieldList, Form, FormField, HiddenField, IntegerField, SelectField,
                     StringField, SubmitField, TextAreaField)
from wtforms.validators import DataRequired, Length, NumberRange, Optional, ValidationError

from app.alcance import filtrar_clientes
from app.extensions import db
from app.models import ESTADOS_PEDIDO, Cliente, Kit, Pedido, Producto


def opciones_clientes():
    """Clientes activos que el usuario actual puede ver (FAS: solo los suyos)."""
    select = filtrar_clientes(db.select(Cliente).filter_by(activo=True).order_by(Cliente.nombre))
    return [(c.id, c.nombre) for c in db.session.scalars(select)]


def opciones_productos():
    return [(p.id, f"{p.referencia} — {p.nombre}") for p in db.session.scalars(
        db.select(Producto).filter_by(activo=True).order_by(Producto.nombre))]


def comprobar_documento(campo):
    """Valida el adjunto ANTES de crear el pedido, para no dejar un pedido a medias."""
    from flask import current_app

    from app.pedidos.documentos import EXTENSIONES_PERMITIDAS
    archivo = campo.data
    if not archivo or not getattr(archivo, "filename", ""):
        return
    ext = archivo.filename.rsplit(".", 1)[-1].lower() if "." in archivo.filename else ""
    if ext not in EXTENSIONES_PERMITIDAS:
        raise ValidationError(_("Tipo de archivo no admitido. Usa PDF, Word, Excel, CSV, imagen o similar."))
    archivo.stream.seek(0, 2)                      # ir al final para saber el tamaño
    tamano = archivo.stream.tell()
    archivo.stream.seek(0)                         # y volver al principio para guardarlo luego
    if tamano == 0:
        raise ValidationError(_("El archivo está vacío."))
    if tamano > current_app.config["MAX_DOCUMENTO_MB"] * 1024 * 1024:
        raise ValidationError(_("El archivo pesa más de %(mb)s MB.", mb=current_app.config["MAX_DOCUMENTO_MB"]))


TEXTO_DOCUMENTO = _l("PDF, Word, Excel, CSV, imagen… (máx. 15 MB)")


def comprobar_referencia_unica(campo, cliente_id, pedido_actual=None):
    """La referencia de la empresa no puede repetirse DENTRO del mismo cliente."""
    if not campo.data:
        campo.data = None
        return
    campo.data = campo.data.strip()
    existente = db.session.scalar(
        db.select(Pedido).filter_by(cliente_id=cliente_id, referencia=campo.data))
    if existente and existente is not pedido_actual:
        raise ValidationError(
            _("Ya hay un pedido con esa referencia (%(ref)s).", ref=existente.referencia_interna))


def con_ids_propios(form, prefijo):
    """Cambia los id HTML de los campos (no sus nombres): la ventana emergente de nuevo
    pedido está en páginas que tienen otros formularios con campos que se llaman igual
    ("documento", "notas", "cliente_id"...) y dos id iguales en una página confunden al
    navegador (al pulsar una etiqueta se va al campo del otro formulario)."""
    for campo in form:
        if campo.type in ("CSRFTokenField", "FieldList"):
            continue
        campo.id = f"{prefijo}-{campo.id}"
        campo.label.field_id = campo.id
    return form


def catalogo_kits(cliente=None):
    """Kits activos con sus productos, para la ventana de pedido (JavaScript los pinta). Con un
    cliente: solo los de su catálogo (app/catalogo_cliente.py)."""
    from app.catalogo_cliente import kits_para
    return [{"id": k.id, "referencia": k.referencia, "nombre": k.nombre, "descripcion": k.descripcion or "",
             "componentes": [{"producto_id": c.producto_id, "nombre": c.producto.nombre,
                              "referencia": c.producto.referencia, "cantidad": c.cantidad}
                             for c in k.componentes_activos]}
            for k in kits_para(cliente)]


MAX_CONTENIDO = 50_000        # caracteres del JSON: de sobra para 20 kits y 40 productos sueltos
MAX_UNIDADES = 100_000        # unidades de un mismo producto en un kit o como suelto


def _entero(valor, minimo, maximo):
    """int de verdad dentro de [minimo, maximo] o ValueError (lo que llega del navegador no
    es de fiar: "3", 2.5, true o 1e400 no valen, solo números enteros)."""
    if type(valor) is not int or not minimo <= valor <= maximo:
        raise ValueError
    return valor


def _sin_constantes(nombre):
    """json.loads acepta NaN e Infinity por defecto; aquí no."""
    raise ValueError(nombre)


class _PedidoConLineasForm(FlaskForm):
    """
    Lo común a los dos formularios de pedido (el del cliente y el de Yikon (admin, logística, FAS)).

    El contenido (kits, productos de cada kit y productos sueltos) cambia en el navegador
    y viaja en UN campo oculto con este JSON (lo arma static/js/pedido.js):
        {"kits":    [{"kit_id": 3, "cantidad": 2,
                      "productos": [{"producto_id": 7, "cantidad": 4}, ...]}, ...],
         "sueltos": [{"producto_id": 9, "cantidad": 1}, ...]}
    Aquí se valida TODO: que los kits existan, que cada producto sea de su kit, las
    cantidades... y que el cliente solo pida kits y productos sueltos de su catálogo.
    El documento del pedido es obligatorio para todos (cliente y Yikon).
    """
    contenido = HiddenField()
    fecha = DateField(_l("Fecha del pedido"), default=date.today, validators=[DataRequired()])
    admite_sueltos = True             # productos sueltos (fuera de un kit): Yikon y también el cliente
    kits_permitidos = None            # ids de kits que se pueden pedir (None = todos): el cliente, su catálogo
    productos_permitidos = None       # ids de productos sueltos que se pueden pedir (None = todos los activos)
    documento_obligatorio = True      # sin documento no se crea el pedido (cliente y Yikon)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.kits_validos = []        # [{"kit": Kit, "cantidad": 2, "productos": {producto_id: cantidad}}]
        self.sueltos_validos = {}     # {producto_id: cantidad}
        self.catalogo_json = json.dumps(catalogo_kits())
        self.productos_json = json.dumps(
            [{"id": pid, "texto": texto} for pid, texto in opciones_productos()]) if self.admite_sueltos else "[]"

    def validate_documento(self, campo):
        # La regla la pone el formulario, no algo que llegue del navegador
        if self.documento_obligatorio and not (campo.data and getattr(campo.data, "filename", "")):
            raise ValidationError(_("El documento de pedido es obligatorio."))
        comprobar_documento(campo)

    def validate_contenido(self, campo):
        try:
            texto = campo.data or "{}"
            if len(texto) > MAX_CONTENIDO:
                raise ValueError
            datos = json.loads(texto, parse_constant=_sin_constantes)
            if not isinstance(datos, dict):
                raise ValueError
            kits = datos.get("kits") or []
            sueltos = datos.get("sueltos") or []
            if not isinstance(kits, list) or not isinstance(sueltos, list) or len(kits) > 20 or len(sueltos) > 40:
                raise ValueError
            for bloque in kits:
                kit = db.session.get(Kit, _entero(bloque.get("kit_id"), 1, 10**9))
                if kit is None or not kit.activo:
                    raise ValidationError(_("Uno de los kits ya no está disponible. Revisa el pedido."))
                if self.kits_permitidos is not None and kit.id not in self.kits_permitidos:
                    raise ValidationError(_("El kit %(kit)s no está en su catálogo. Pídaselo a su contacto en Yikon.",
                                            kit=kit.nombre))
                de_este_kit = {c.producto_id for c in kit.componentes_activos}
                productos = {}
                for fila in bloque.get("productos") or []:
                    pid = _entero(fila.get("producto_id"), 1, 10**9)
                    if pid not in de_este_kit:            # solo se pueden quitar o cambiar, no añadir otros
                        raise ValueError
                    cantidad = _entero(fila.get("cantidad"), 0, MAX_UNIDADES)
                    if cantidad:
                        productos[pid] = productos.get(pid, 0) + cantidad
                        if productos[pid] > MAX_UNIDADES:        # la misma fila repetida muchas veces
                            raise ValueError
                if not productos:
                    raise ValidationError(_("El kit %(kit)s no tiene ningún producto. Quítalo o marca al menos uno.",
                                            kit=kit.nombre))
                self.kits_validos.append({"kit": kit, "cantidad": _entero(bloque.get("cantidad", 1), 1, 1000),
                                          "productos": productos})
            if sueltos and not self.admite_sueltos:
                raise ValueError
            for fila in sueltos:
                producto = db.session.get(Producto, _entero(fila.get("producto_id"), 1, 10**9))
                if producto is None or not producto.activo:
                    raise ValidationError(_("Uno de los productos ya no está disponible. Revisa el pedido."))
                if self.productos_permitidos is not None and producto.id not in self.productos_permitidos:
                    raise ValidationError(_("El producto %(producto)s no está en su catálogo. Pídaselo a su contacto en Yikon.",
                                            producto=producto.nombre))
                self.sueltos_validos[producto.id] = (self.sueltos_validos.get(producto.id, 0)
                                                     + _entero(fila.get("cantidad"), 1, MAX_UNIDADES))
                if self.sueltos_validos[producto.id] > MAX_UNIDADES:
                    raise ValueError
        except ValidationError:
            raise
        except (ValueError, TypeError, AttributeError, RecursionError):
            raise ValidationError(_("No se ha podido leer el contenido del pedido. Vuelve a intentarlo."))
        if not self.kits_validos and not self.sueltos_validos:
            raise ValidationError(_("Añade al menos un kit o un producto.") if self.admite_sueltos
                                  else _("Añade al menos un kit."))


class PedidoClienteForm(_PedidoConLineasForm):
    """Formulario del usuario cliente: el cliente es SU empresa, no se elige."""
    referencia = StringField(_l("Nº de pedido de empresa"),
                             validators=[DataRequired(message=_l("El nº de pedido interno es obligatorio.")),
                                         Length(max=50)],
                             description=_l("Su número de pedido interno de la empresa."))
    documento = FileField(_l("Documento de su pedido interno"),
                          description=_l("La orden de compra o registro interno. %(formatos)s", formatos=TEXTO_DOCUMENTO))
    submit = SubmitField(_l("Solicitar proforma"))   # el pedido empieza pidiendo proforma

    def __init__(self, *args, cliente_id=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._cliente_id = cliente_id
        # Solo los kits de su catálogo (app/catalogo_cliente.py)
        from app.catalogo_cliente import kits_permitidos
        cliente = db.session.get(Cliente, cliente_id) if cliente_id else None
        self.kits_permitidos = kits_permitidos(cliente)
        if self.kits_permitidos is not None:
            self.catalogo_json = json.dumps(catalogo_kits(cliente))
        # Productos sueltos: los de su catálogo (si tiene uno propio; si no, todos los activos)
        if cliente is not None and cliente.catalogo_propio:
            from app.catalogo_cliente import productos_para
            visibles = productos_para(cliente)
            self.productos_permitidos = {p.id for p in visibles}
            self.productos_json = json.dumps([{"id": p.id, "texto": f"{p.referencia} — {p.nombre}"} for p in visibles])

    def validate_referencia(self, campo):
        comprobar_referencia_unica(campo, self._cliente_id)


class PedidoModificarClienteForm(PedidoClienteForm):
    """«Modificar pedido» del cliente (mientras no lo ha aceptado): la misma ventana que al pedir,
    con lo que lleva ya puesto. El documento aquí es opcional: el del pedido ya está; si sube otro,
    se añade a los documentos del pedido."""
    documento_obligatorio = False
    documento = FileField(_l("Otro documento (opcional)"),
                          description=_l("Si ha cambiado su orden de compra, adjunte la nueva. %(formatos)s",
                                         formatos=TEXTO_DOCUMENTO))
    submit = SubmitField(_l("Guardar cambios"))

    def __init__(self, *args, pedido=None, **kwargs):
        self._pedido = pedido
        super().__init__(*args, cliente_id=pedido.cliente_id if pedido else None, **kwargs)

    def validate_referencia(self, campo):
        comprobar_referencia_unica(campo, self._cliente_id, pedido_actual=self._pedido)


class PedidoInternoForm(_PedidoConLineasForm):
    """Formulario de Yikon (admin, logística, FAS): eligen el cliente (FAS, solo los suyos)
    y meten todos los productos de una vez. Los precios salen del catálogo y se
    pueden retocar después en la ficha (descuentos, quitar/añadir líneas)."""
    cliente_id = SelectField(_l("Cliente"), coerce=int, validators=[DataRequired(message=_l("Elige el cliente."))])
    # filters: se aplica ANTES de validar (Optional() cortaría el strip del validador)
    referencia = StringField(_l("Nº de pedido de empresa"), filters=[lambda s: (s or "").strip() or None],
                             validators=[Optional(), Length(max=50)],
                             description=_l("Opcional: el nº de pedido del cliente, si lo tiene."))
    documento = FileField(_l("Documento del pedido"), description=TEXTO_DOCUMENTO)
    notas = TextAreaField(_l("Notas internas"), validators=[Optional()],
                          description=_l("Solo las ve el equipo de Yikon."))
    submit = SubmitField(_l("Crear pedido"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.clientes = db.session.scalars(filtrar_clientes(
            db.select(Cliente).filter_by(activo=True).order_by(Cliente.nombre))).all()
        self.cliente_id.choices = [(0, _("— Elige un cliente —"))] + [(c.id, c.nombre) for c in self.clientes]
        # Para la insignia de la ventana: qué referencia interna le tocaría a cada cliente
        # (texto JSON normal: WTForms lo escapa al ponerlo como atributo HTML)
        self.proximas_json = json.dumps({c.id: c.proxima_referencia_interna for c in self.clientes})

    def validate_referencia(self, campo):
        comprobar_referencia_unica(campo, self.cliente_id.data)


class DocumentoForm(FlaskForm):
    documento = FileField(_l("Adjuntar documento"), description=TEXTO_DOCUMENTO)
    submit = SubmitField(_l("Subir"))

    def validate_documento(self, campo):
        if not campo.data or not getattr(campo.data, "filename", ""):
            raise ValidationError(_("Elige un archivo."))
        comprobar_documento(campo)


class LineaForm(FlaskForm):
    """Añadir un producto suelto a un pedido ya creado (Yikon (admin, logística, FAS))."""
    producto_id = SelectField(_l("Producto suelto"), coerce=int)
    cantidad = IntegerField(_l("Cantidad"), default=1, validators=[DataRequired(), NumberRange(min=1, max=100000)])
    precio = DecimalField(_l("Precio (€)"), places=2, validators=[Optional(), NumberRange(min=0, max=99999999.99)],
                          description=_l("Vacío = el del catálogo."))
    submit = SubmitField(_l("Añadir"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.producto_id.choices = opciones_productos()


class AnadirKitForm(FlaskForm):
    """Añadir un kit completo (composición estándar) a un pedido ya creado."""
    kit_id = SelectField(_l("Kit"), coerce=int)
    cantidad = IntegerField(_l("Nº de kits"), default=1, validators=[DataRequired(), NumberRange(min=1, max=1000)])
    submit = SubmitField(_l("Añadir kit"))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.kit_id.choices = [(k.id, f"{k.nombre} · {k.referencia}") for k in db.session.scalars(
            db.select(Kit).filter_by(activo=True).order_by(Kit.nombre))]


TRANSPORTISTAS_HABITUALES = ["SEUR", "MRW", "DHL", "UPS", "FedEx", "GLS", "Correos Express", "Nacex",
                              "TNT", "World Courier", "Marken"]


def comprobar_enlace(campo):
    """Solo enlaces web normales: un "javascript:..." en un enlace sería un agujero (XSS)."""
    if campo.data:
        campo.data = campo.data.strip()
        if not campo.data.lower().startswith(("http://", "https://")):
            raise ValidationError(_("El enlace debe empezar por https:// (cópialo de la web del transportista)."))


class _CamposEnvio:
    """Datos del envío: se piden al pasar a "Enviado" y se pueden corregir después."""
    fecha_entrega_estimada = DateField(_l("Fecha estimada de entrega"), validators=[Optional()],
                                       description=_l("La verá el cliente."))
    transportista = StringField(_l("Transportista"), validators=[Optional(), Length(max=60)])
    numero_seguimiento = StringField(_l("Nº de seguimiento"), validators=[Optional(), Length(max=100)])
    enlace_seguimiento = StringField(_l("Enlace de seguimiento"), validators=[Optional(), Length(max=500)],
                                     description=_l("Opcional: el enlace que da el transportista para seguir el envío."))

    def validate_enlace_seguimiento(self, campo):
        comprobar_enlace(campo)


class EstadoPedidoForm(_CamposEnvio, FlaskForm):
    # Las opciones las pone la vista: solo los estados a los que ESTE usuario puede pasar
    estado = SelectField(_l("Estado"), choices=[])
    submit = SubmitField(_l("Cambiar estado"))


class DatosEnvioForm(_CamposEnvio, FlaskForm):
    submit = SubmitField(_l("Guardar datos de envío"))


class FotosForm(FlaskForm):
    fotos = MultipleFileField(_l("Fotos del pedido preparado"),
                              render_kw={"accept": "image/jpeg,image/png,image/webp", "multiple": True})
    submit = SubmitField(_l("Subir fotos"))


class ValidacionForm(FlaskForm):
    comentario = TextAreaField(_l("Comentario"),
                               description=_l("Obligatorio si lo rechazas: explica qué hay que revisar."))
    aprobar = SubmitField(_l("✓ Validar y dar permiso para enviar"))
    rechazar = SubmitField(_l("✕ Rechazar · Revisar urgente"))

    def validate_comentario(self, campo):
        if self.rechazar.data and not (campo.data or "").strip():
            raise ValidationError(_("Para rechazar tienes que explicar qué hay que revisar."))
