import re
import unicodedata
from datetime import date, datetime, timezone
from decimal import Decimal

from flask import current_app
from flask_babel import lazy_gettext as _l
from flask_login import UserMixin
from sqlalchemy.orm import validates

from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db, login_manager
from app import apartados
from app.permisos import (PERMISOS_SEGUN_EMPRESA, PERMISOS_SEGUN_USUARIO, ROLES, ROLES_CLIENTE,
                          tiene_permiso)


def _dec(valor) -> Decimal:
    """Convierte a Decimal de forma segura (None → 0; float vía str para no arrastrar decimales raros)."""
    if valor is None:
        return Decimal("0")
    return valor if isinstance(valor, Decimal) else Decimal(str(valor))


def ahora():
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Usuarios
# --------------------------------------------------------------------------- #
class User(db.Model, UserMixin):
    __tablename__ = "usuarios"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    rol = db.Column(db.String(20), nullable=False, default="cliente")
    activo = db.Column(db.Boolean, nullable=False, default=True)
    creado = db.Column(db.DateTime(timezone=True), default=ahora)
    ultimo_acceso = db.Column(db.DateTime(timezone=True))
    # Idioma de la interfaz y de sus correos ("es" / "en"). Vacío = el del navegador.
    idioma = db.Column(db.String(5))

    # Solo rol "cliente": ¿puede abrir y ver tickets de Soporte ChromGo? (lo decide admin en su ficha)
    acceso_chromgo = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    # Solo usuarios de clientes: los avisos por email que NO quiere recibir ("proformas,mensajes"...).
    # Vacío = todos (como hasta ahora). Lo deciden admin y su Soporte en la ficha del cliente
    # (app/avisos_cliente.py).
    avisos_desactivados = db.Column(db.String(200), nullable=False, default="", server_default="")
    # El aviso para clientes (Ajustes → General) que cerró, por su "huella": si admin cambia el
    # texto, la huella cambia y le vuelve a salir (app/aviso_clientes.py).
    aviso_cerrado = db.Column(db.String(20))

    # Solo para usuarios de clientes: la empresa a la que pertenece el usuario
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"))
    empresa = db.relationship("Cliente", back_populates="usuarios")

    # Solo para rol "fas": empresas que tiene asignadas (muchos a muchos)
    clientes_asignados = db.relationship(
        "Cliente", secondary="cliente_logistica", back_populates="logisticos"
    )

    @validates("email")
    def _normalizar_email(self, clave, valor):
        # Siempre en minúsculas, lo cree quien lo cree (formulario, consola, tests...)
        return valor.strip().lower() if valor else valor

    def set_password(self, password: str):
        # scrypt de la librería estándar (hashlib): sin DLL externas
        self.password_hash = generate_password_hash(
            password, method=current_app.config.get("PASSWORD_HASH_METHOD", "scrypt"))

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def puede(self, permiso: str) -> bool:
        if not self.activo:
            return False
        if tiene_permiso(self.rol, permiso):
            return True
        # Permisos que un usuario cliente tiene solo si su empresa lo tiene activado
        # (p. ej. ver precios): ver PERMISOS_SEGUN_EMPRESA en permisos.py
        if self.rol != "cliente":
            return False
        campo = PERMISOS_SEGUN_EMPRESA.get(permiso)
        if campo and self.empresa is not None and getattr(self.empresa, campo, False):
            return True
        # ...o si se lo han activado a él (p. ej. acceso a Soporte ChromGo): PERMISOS_SEGUN_USUARIO
        if not apartados.permite("cliente", permiso):    # apartado quitado (p. ej. Tickets ChromGo)
            return False
        campo = PERMISOS_SEGUN_USUARIO.get(permiso)
        return bool(campo and getattr(self, campo, False))

    @property
    def es_cliente(self) -> bool:
        """¿Es de una empresa cliente? (rol Cliente o Cliente ChromGo: tienen empresa y solo ven lo suyo)"""
        return self.rol in ROLES_CLIENTE

    @property
    def is_active(self):  # Flask-Login: los usuarios desactivados no pueden entrar
        return self.activo

    @property
    def rol_nombre(self):
        return ROLES.get(self.rol, self.rol)

    def __repr__(self):
        return f"<User {self.email} ({self.rol})>"


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


# --------------------------------------------------------------------------- #
# Clientes (clínicas / centros)
# --------------------------------------------------------------------------- #

# Tabla intermedia muchos-a-muchos: qué usuarios FAS llevan qué clientes.
# No es una clase porque solo guarda la pareja (cliente, usuario), nada más.
cliente_logistica = db.Table(
    "cliente_logistica",
    db.Column("cliente_id", db.Integer, db.ForeignKey("clientes.id"), primary_key=True),
    db.Column("usuario_id", db.Integer, db.ForeignKey("usuarios.id"), primary_key=True),
)


# Catálogo propio de cada cliente (ficha del cliente → «Su catálogo»): qué kits puede pedir y qué
# productos ve. Solo cuenta si Cliente.catalogo_propio está activado (si no, ve todo lo activo).
catalogo_kits = db.Table(
    "catalogo_kits",
    db.Column("cliente_id", db.Integer, db.ForeignKey("clientes.id"), primary_key=True),
    db.Column("kit_id", db.Integer, db.ForeignKey("kits.id"), primary_key=True),
)
catalogo_productos = db.Table(
    "catalogo_productos",
    db.Column("cliente_id", db.Integer, db.ForeignKey("clientes.id"), primary_key=True),
    db.Column("producto_id", db.Integer, db.ForeignKey("productos.id"), primary_key=True),
)


class Cliente(db.Model):
    __tablename__ = "clientes"

    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(150), nullable=False, index=True)
    razon_social = db.Column(db.String(200))
    cif = db.Column(db.String(20), unique=True)
    email = db.Column(db.String(120))
    telefono = db.Column(db.String(30))
    direccion = db.Column(db.String(250))
    ciudad = db.Column(db.String(100))
    persona_contacto = db.Column(db.String(120))
    notas = db.Column(db.Text)
    activo = db.Column(db.Boolean, nullable=False, default=True)
    creado = db.Column(db.DateTime(timezone=True), default=ahora)

    # Referencias internas de pedido: YK-<año>-<prefijo>-<número>, p. ej. YK-2026-DiNA-1.
    # El número es de cada cliente y vuelve a 1 cada año: contador_pedidos cuenta los pedidos
    # del año anio_contador (si cambia el año, se empieza de nuevo).
    prefijo = db.Column(db.String(10), unique=True)
    contador_pedidos = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    anio_contador = db.Column(db.Integer)
    # ¿Sus usuarios ven precios (sus tarifas, totales de pedidos, importes de facturas)?
    # Lo activan admin o su FAS desde Clientes. Por defecto, no.
    ver_precios = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    # Facturación (solo Yikon): cómo le hace Aina la factura en la plantilla de Excel.
    # Vacíos = sin configurar ("Preparar factura" usa A, España y sin envío, y lo avisa).
    formato_factura = db.Column(db.String(1))          # clave de FORMATOS_FACTURA
    regimen_iva = db.Column(db.String(10))             # clave de REGIMENES_IVA
    gastos_envio = db.Column(db.Numeric(10, 2))        # pactado por el comercial; vacío = no se cobran
    # Sus facturas las revisa Soporte de cliente antes de enviarlas (marca por defecto la casilla al registrar)
    revisar_facturas = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    # Catálogo propio: False = todo lo activo (como siempre); True = solo los kits y productos marcados
    # (app/catalogo_cliente.py). Lo cambian admin y su Soporte de cliente.
    catalogo_propio = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    kits_catalogo = db.relationship("Kit", secondary=catalogo_kits)
    productos_catalogo = db.relationship("Producto", secondary=catalogo_productos)

    # Usuarios de Yikon (rol FAS) que llevan este cliente
    logisticos = db.relationship(
        "User", secondary=cliente_logistica, back_populates="clientes_asignados"
    )
    # Usuarios de la propia empresa cliente (rol cliente)
    usuarios = db.relationship("User", back_populates="empresa")

    pedidos = db.relationship("Pedido", back_populates="cliente", lazy="dynamic")
    facturas = db.relationship("Factura", back_populates="cliente", lazy="dynamic")

    def _proximo_numero(self, anio) -> int:
        """El número que le toca al próximo pedido en ese año (vuelve a 1 al cambiar de año)."""
        return (self.contador_pedidos or 0) + 1 if self.anio_contador == anio else 1

    @property
    def proxima_referencia_interna(self) -> str:
        """La referencia que tendrá el PRÓXIMO pedido, sin reservarla (para enseñarla)."""
        anio = anio_actual()
        return referencia_pedido(anio, self.prefijo or prefijo_desde_nombre(self.nombre), self._proximo_numero(anio))

    def siguiente_referencia_interna(self) -> str:
        """
        Reserva el siguiente número de pedido de este cliente y devuelve la referencia.
        Usamos un contador guardado (y no "contar los pedidos que tiene") para que un
        número nunca se reutilice aunque se borre o cancele un pedido.
        """
        anio = anio_actual()
        referencia = self.proxima_referencia_interna
        self.contador_pedidos, self.anio_contador = self._proximo_numero(anio), anio
        return referencia

    def __repr__(self):
        return f"<Cliente {self.nombre}>"


def referencia_pedido(anio: int, prefijo: str, numero: int) -> str:
    """El formato de la referencia interna de un pedido: YK-2026-DiNA-001. Para cambiarlo, aquí."""
    return f"YK-{anio}-{prefijo}-{numero:03d}"


def anio_actual() -> int:
    """El año en Madrid (no en UTC: el 31 de diciembre a las 23:30 sigue siendo ese año)."""
    from app.utils import hora_local
    return hora_local(ahora()).year


def prefijo_desde_nombre(nombre: str) -> str:
    """'DiNA Science S.L.' → 'DiNA'. Primera palabra, solo letras y números, máx. 10."""
    palabras = (nombre or "").split()
    if not palabras:
        return "CLI"
    # quita tildes (Clínica → Clinica) y todo lo que no sea letra o número
    sin_tildes = unicodedata.normalize("NFKD", palabras[0]).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]", "", sin_tildes)[:10] or "CLI"


# --------------------------------------------------------------------------- #
# Catálogo de productos
# --------------------------------------------------------------------------- #
class Producto(db.Model):
    __tablename__ = "productos"

    id = db.Column(db.Integer, primary_key=True)
    def precio_para(self, cliente) -> Decimal:
        """Precio automático de un producto suelto para este cliente: el especial si lo tiene, si no el estándar."""
        if cliente is not None:
            especial = db.session.scalar(db.select(PrecioProductoCliente.precio).filter_by(
                producto_id=self.id, cliente_id=cliente.id))
            if especial is not None:
                return especial
        return self.precio

    referencia = db.Column(db.String(50), unique=True, nullable=False)
    nombre = db.Column(db.String(200), nullable=False)
    categoria = db.Column(db.String(80))
    precio = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    iva_pct = db.Column(db.Numeric(5, 2), nullable=False, default=Decimal("21.00"))
    activo = db.Column(db.Boolean, nullable=False, default=True)
    # Los servicios (p. ej. análisis bioinformático) no son mercancía: no llevan stock
    controlar_stock = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    # Por debajo de esta cantidad, el inventario lo marca como "stock bajo"
    stock_minimo = db.Column(db.Integer, nullable=False, default=0, server_default="0")

    # Ficha de datos de seguridad (SDS) en PDF. La sube admin y la descargan los clientes
    # desde su apartado de Productos. Nombre aleatorio en la carpeta privada.
    sds_archivo = db.Column(db.String(100), unique=True)
    sds_nombre = db.Column(db.String(200))
    sds_tamano = db.Column(db.Integer)
    sds_fecha = db.Column(db.DateTime(timezone=True))      # cuándo se subió la versión actual


    movimientos = db.relationship("MovimientoInventario", back_populates="producto",
                                  lazy="dynamic")
    lotes = db.relationship("Lote", back_populates="producto", order_by="Lote.caducidad")

    @property
    def stock(self) -> int:
        """Unidades en la oficina = suma de todos sus movimientos (+ entradas, − salidas)."""
        return db.session.scalar(
            db.select(db.func.coalesce(db.func.sum(MovimientoInventario.cantidad), 0))
            .filter_by(producto_id=self.id)
        )

    # Producto y Kit comparten lo que usa el inventario ("artículo": lo que tiene lotes y stock)
    tipo_articulo = "producto"

    @property
    def clave(self):
        return ("producto", self.id)

    @property
    def lleva_stock(self) -> bool:
        return self.controlar_stock

    def __repr__(self):
        return f"<Producto {self.referencia}>"


# --------------------------------------------------------------------------- #
# Kits: agrupaciones de productos que se venden juntas
# --------------------------------------------------------------------------- #
class Kit(db.Model):
    """
    Un kit del catálogo (p. ej. "PGT-A completo") con su lista de productos y la
    cantidad de cada uno POR KIT.

    Dos formas de tenerlo en el almacén:
      - CERRADO (lo normal): llega del fabricante como un paquete con UNA etiqueta de
        lote y caducidad, aunque venga en varias cajas (1/2, 2/2). El stock, los lotes
        y la caducidad son del kit; sus productos no se tocan al enviarlo.
      - MONTADO (cerrado=False): se junta en la oficina con productos sueltos; el stock
        y los lotes son de esos productos (como los productos que se venden sueltos).
    """

    __tablename__ = "kits"

    id = db.Column(db.Integer, primary_key=True)
    referencia = db.Column(db.String(50), unique=True, nullable=False)
    nombre = db.Column(db.String(200), nullable=False)
    descripcion = db.Column(db.Text)
    # Precio estándar de UN kit (sin IVA). Cada cliente puede tener uno especial (PrecioCliente)
    precio = db.Column(db.Numeric(10, 2), nullable=False, default=0)
    iva_pct = db.Column(db.Numeric(5, 2), nullable=False, default=Decimal("21.00"))
    activo = db.Column(db.Boolean, nullable=False, default=True)
    cerrado = db.Column(db.Boolean, nullable=False, default=True, server_default=db.true())
    stock_minimo = db.Column(db.Integer, nullable=False, default=0, server_default="0")   # solo kits cerrados

    # En el orden que se elige a mano en el formulario del kit (flechas ↑↓)
    componentes = db.relationship("ComponenteKit", back_populates="kit", cascade="all, delete-orphan",
                                  order_by="(ComponenteKit.orden, ComponenteKit.id)")

    def precio_para(self, cliente) -> Decimal:
        """Precio automático de un kit para este cliente: el especial si lo tiene, si no el estándar."""
        if cliente is not None:
            especial = db.session.scalar(db.select(PrecioCliente.precio).filter_by(
                kit_id=self.id, cliente_id=cliente.id))
            if especial is not None:
                return especial
        return self.precio

    lotes = db.relationship("Lote", back_populates="kit", order_by="Lote.caducidad")

    @property
    def componentes_activos(self):
        """Componentes cuyo producto sigue activo (un producto dado de baja ya no se sirve)."""
        return [c for c in self.componentes if c.producto.activo]

    tipo_articulo = "kit"

    @property
    def clave(self):
        return ("kit", self.id)

    @property
    def lleva_stock(self) -> bool:
        """Solo los kits cerrados tienen stock propio."""
        return self.cerrado

    @property
    def stock(self) -> int:
        return db.session.scalar(
            db.select(db.func.coalesce(db.func.sum(MovimientoInventario.cantidad), 0)).filter_by(kit_id=self.id))

    def __repr__(self):
        return f"<Kit {self.referencia}>"


class ComponenteKit(db.Model):
    """Un producto dentro de un kit, con cuántas unidades lleva cada kit."""

    __tablename__ = "componentes_kit"
    __table_args__ = (db.UniqueConstraint("kit_id", "producto_id"),)

    id = db.Column(db.Integer, primary_key=True)
    kit_id = db.Column(db.Integer, db.ForeignKey("kits.id"), nullable=False, index=True)
    kit = db.relationship("Kit", back_populates="componentes")
    producto_id = db.Column(db.Integer, db.ForeignKey("productos.id"), nullable=False)
    producto = db.relationship("Producto")
    cantidad = db.Column(db.Integer, nullable=False, default=1)
    orden = db.Column(db.Integer, nullable=False, default=0, server_default="0")   # posición dentro del kit


class PrecioCliente(db.Model):
    """Precio especial de un kit para un cliente concreto (tarifa pactada)."""

    __tablename__ = "precios_cliente"
    __table_args__ = (db.UniqueConstraint("cliente_id", "kit_id"),)

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=False, index=True)
    cliente = db.relationship("Cliente")
    kit_id = db.Column(db.Integer, db.ForeignKey("kits.id"), nullable=False)
    kit = db.relationship("Kit")
    precio = db.Column(db.Numeric(10, 2), nullable=False)


class PrecioProductoCliente(db.Model):
    """Precio especial de un producto suelto para un cliente concreto (tarifa pactada)."""

    __tablename__ = "precios_producto_cliente"
    __table_args__ = (db.UniqueConstraint("cliente_id", "producto_id"),)

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=False, index=True)
    cliente = db.relationship("Cliente")
    producto_id = db.Column(db.Integer, db.ForeignKey("productos.id"), nullable=False)
    producto = db.relationship("Producto")
    precio = db.Column(db.Numeric(10, 2), nullable=False)


# --------------------------------------------------------------------------- #
# Pedidos (compras de los clientes)
# --------------------------------------------------------------------------- #
ESTADOS_PEDIDO = {
    # 1-3. Proforma: el cliente la pide, Yikon la revisa y se la envía; el cliente la
    #      acepta o pide cambios (y Yikon le envía otra)
    "proforma_solicitada": _l("Proforma solicitada"),
    "proforma_enviada": _l("Proforma enviada"),
    "cambios_solicitados": _l("Cambios solicitados"),
    # 4-7. Pedido: aceptado → Almacén lo prepara y hace las fotos → el FAS del cliente las valida
    #      (o lo devuelve a preparación) → listo para enviar
    "aceptado": _l("Aceptado"),
    "en_preparacion": _l("En preparación"),
    "en_validacion": _l("Pendiente de validación"),
    "validado": _l("Listo para enviar"),
    # 8-9. Enviado (con su nº de seguimiento) → el cliente marca que lo ha recibido
    "enviado": _l("Enviado"),
    "entregado": _l("Recibido"),
    "cancelado": _l("Cancelado"),
}

# El cliente no ve el proceso interno de preparación: todos estos le salen como uno solo
ESTADOS_PREPARACION = {"en_preparacion", "en_validacion", "validado"}
ESTADOS_PROFORMA = ("proforma_solicitada", "proforma_enviada", "cambios_solicitados")
ESTADOS_PEDIDO_CLIENTE = {
    "proforma_solicitada": _l("Proforma solicitada"),
    "proforma_enviada": _l("Proforma recibida"),
    "cambios_solicitados": _l("Cambios solicitados"),
    "aceptado": _l("Aceptado"),
    "preparacion": _l("En preparación"),
    "enviado": _l("Enviado"),
    "entregado": _l("Recibido"),
    "cancelado": _l("Cancelado"),
}

# Icono (Font Awesome) de cada estado: sale siempre junto al nombre y al color, para que el
# estado se reconozca sin depender del color (daltonismo). Los colores están en main.css
# (clases .est-<estado>, paleta Okabe-Ito, pensada para que se distingan con daltonismo).
ICONOS_ESTADO = {
    "proforma_solicitada": "fa-file-alt",
    "proforma_enviada": "fa-paper-plane",
    "cambios_solicitados": "fa-undo",
    "aceptado": "fa-check",
    "en_preparacion": "fa-box-open",
    "preparacion": "fa-box-open",        # (vista del cliente)
    "en_validacion": "fa-eye",
    "validado": "fa-check-double",
    "enviado": "fa-truck",
    "entregado": "fa-flag-checkered",
    "cancelado": "fa-times",
}

# Flujo: desde cada estado, a qué estados se puede pasar y con qué permiso (o permisos:
# basta con tener uno). Cualquier cambio de estado pasa por aquí; lo que no está, no se
# puede hacer (salvo admin forzándolo, que queda marcado en la auditoría).
_CANCELAR_PROFORMA = ("pedidos.editar", "pedidos.proforma.cancelar")   # Yikon o el propio cliente
TRANSICIONES = {
    "proforma_solicitada": {"proforma_enviada": "pedidos.proforma.enviar", "cancelado": _CANCELAR_PROFORMA},
    "proforma_enviada":    {"aceptado": "pedidos.proforma.responder",
                            "cambios_solicitados": "pedidos.proforma.responder",
                            "proforma_solicitada": "pedidos.proforma.enviar",    # Yikon la retira para corregirla
                            "cancelado": _CANCELAR_PROFORMA},
    "cambios_solicitados": {"proforma_enviada": "pedidos.proforma.enviar", "cancelado": _CANCELAR_PROFORMA},
    "aceptado":            {"en_preparacion": "pedidos.preparar", "cancelado": "pedidos.editar",
                            # para cambiar lo aceptado hay que mandar otra proforma (solo si iba por proforma)
                            "proforma_solicitada": "pedidos.proforma.enviar"},
    "en_preparacion":      {"en_validacion": "pedidos.fotos.subir", "cancelado": "pedidos.editar"},
    "en_validacion":       {"validado": "pedidos.validar", "en_preparacion": "pedidos.validar",   # OK o devolverlo
                            "cancelado": "pedidos.editar"},
    "validado":            {"enviado": "pedidos.enviar", "en_preparacion": "pedidos.preparar",
                            "cancelado": "pedidos.editar"},
    "enviado":             {"entregado": ("pedidos.recibir", "pedidos.enviar"),   # el cliente (o admin por él)
                            "validado": "pedidos.enviar"},                        # = anular el envío
    "entregado":           {"enviado": "pedidos.enviar"},
    # Reabrir: a "proforma solicitada" si va por proforma, si no a "aceptado" (ver Pedido.transicion_valida)
    "cancelado":           {"proforma_solicitada": "pedidos.editar", "aceptado": "pedidos.editar"},
}


def puede_alguno(usuario, permiso) -> bool:
    """Un permiso de TRANSICIONES puede ser uno ("pedidos.editar") o varios (tupla: basta uno)."""
    if isinstance(permiso, tuple):
        return any(usuario.puede(p) for p in permiso)
    return usuario.puede(permiso)


class Pedido(db.Model):
    __tablename__ = "pedidos"
    __table_args__ = (db.UniqueConstraint("cliente_id", "referencia"),)

    id = db.Column(db.Integer, primary_key=True)
    # Referencia interna de Yikon, generada automáticamente (DiNA_001)
    referencia_interna = db.Column(db.String(30), unique=True)
    # Referencia que pone la empresa cliente (su nº de pedido). Única por cliente,
    # no global: dos clínicas distintas pueden usar ambas "PO-001".
    referencia = db.Column(db.String(50))
    fecha = db.Column(db.Date, nullable=False, default=date.today)
    fecha_entrega_estimada = db.Column(db.Date)   # la pone admin al enviar; la ve el cliente
    # Datos del envío (los pone admin al enviar; el cliente los ve y le llegan por email)
    transportista = db.Column(db.String(60))
    numero_seguimiento = db.Column(db.String(100))
    enlace_seguimiento = db.Column(db.String(500))
    estado = db.Column(db.String(20), nullable=False, default="aceptado")
    notas = db.Column(db.Text)
    creado = db.Column(db.DateTime(timezone=True), default=ahora)
    # ¿Va por proforma? (los pedidos que hace el cliente). Si se cancela y se reabre, o hay
    # que cambiarlo después de aceptar la proforma, vuelve a "proforma solicitada".
    con_proforma = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())

    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=False)
    cliente = db.relationship("Cliente", back_populates="pedidos")
    creado_por_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"))
    creado_por = db.relationship("User")

    lineas = db.relationship(
        "LineaPedido", back_populates="pedido", cascade="all, delete-orphan"
    )
    # Kits del pedido (cada uno con sus productos, que son LineaPedido con kit_pedido_id)
    kits = db.relationship("KitPedido", back_populates="pedido", cascade="all, delete-orphan",
                           order_by="KitPedido.id")
    facturas = db.relationship("Factura", back_populates="pedido")

    @property
    def lineas_sueltas(self):
        """Productos pedidos fuera de un kit (y todas las líneas de los pedidos antiguos)."""
        return [l for l in self.lineas if l.kit_pedido_id is None]

    # Importes: los kits cuentan por su precio de kit; sus productos no llevan precio
    # propio (ver LineaPedido.subtotal). Los productos sueltos, por su precio.
    @property
    def base_imponible(self):
        return (sum((l.subtotal for l in self.lineas_sueltas), Decimal("0"))
                + sum((k.subtotal for k in self.kits), Decimal("0")))

    @property
    def total_iva(self):
        return (sum((l.iva for l in self.lineas_sueltas), Decimal("0"))
                + sum((k.iva for k in self.kits), Decimal("0")))

    def resumen_contenido(self, separador="\n"):
        """Texto con lo que lleva el pedido, para listas, PDF, Excel y emails:
        '2 × PGT-A completo (1 × Reactivo, 2 × Tubos)' y '1 × Tubos' para los sueltos."""
        partes = []
        for k in self.kits:
            productos = ", ".join(f"{l.cantidad} × {l.producto.nombre}" for l in k.lineas)
            partes.append(f"{k.cantidad} × {k.kit.nombre} ({productos})")
        partes += [f"{l.cantidad} × {l.producto.nombre}" for l in self.lineas_sueltas]
        return separador.join(partes)

    @property
    def total(self):
        return self.base_imponible + self.total_iva

    documentos = db.relationship("DocumentoPedido", back_populates="pedido",
                                 cascade="all, delete-orphan", order_by="DocumentoPedido.id")
    fotos = db.relationship("FotoPedido", back_populates="pedido",
                            cascade="all, delete-orphan", order_by="FotoPedido.id")
    revisiones = db.relationship("RevisionPedido", back_populates="pedido",
                                 cascade="all, delete-orphan", order_by="RevisionPedido.fecha.desc()")
    # La más reciente primero (proforma_actual = la primera)
    proformas = db.relationship("Proforma", back_populates="pedido", order_by="Proforma.id.desc()")

    @property
    def estado_nombre(self):
        return ESTADOS_PEDIDO.get(self.estado, self.estado)

    @property
    def estado_cliente(self):
        """Clave del estado tal como lo ve el cliente (sin el detalle interno)."""
        return "preparacion" if self.estado in ESTADOS_PREPARACION else self.estado

    def estado_nombre_para(self, usuario):
        if usuario.rol == "cliente":
            return ESTADOS_PEDIDO_CLIENTE.get(self.estado_cliente, self.estado_nombre)
        return self.estado_nombre

    def transicion_valida(self, destino):
        """Reglas que dependen del pedido (además de TRANSICIONES y los permisos):
        - "proforma enviada" solo con una proforma pendiente (la crea el botón "Enviar proforma");
        - un pedido cancelado se reabre a "proforma solicitada" si iba por proforma, y si no
          (pedido creado por Yikon) a "aceptado";
        - de "aceptado" se vuelve a "proforma solicitada" (para mandar otra) solo si iba por proforma."""
        if destino == "proforma_enviada":
            return any(p.estado == "enviada" for p in self.proformas)
        if self.estado == "cancelado" and destino in ("aceptado", "proforma_solicitada"):
            return destino == ("proforma_solicitada" if self.con_proforma else "aceptado")
        if self.estado == "aceptado" and destino == "proforma_solicitada":
            return self.con_proforma
        return True

    def transiciones_para(self, usuario):
        """Estados a los que ESTE usuario puede mover el pedido ahora mismo."""
        if usuario.puede("pedidos.forzar_estado"):   # admin: cualquier estado (menos "proforma enviada" sin proforma)
            return [e for e in ESTADOS_PEDIDO if e != self.estado
                    and (e != "proforma_enviada" or self.transicion_valida(e))]
        return [destino for destino, permiso in TRANSICIONES.get(self.estado, {}).items()
                if puede_alguno(usuario, permiso) and self.transicion_valida(destino)]

    def es_transicion_normal(self, destino):
        return destino in TRANSICIONES.get(self.estado, {})

    @property
    def ultima_revision(self):
        return self.revisiones[0] if self.revisiones else None

    @property
    def devuelto(self):
        """En preparación porque el FAS lo ha devuelto (su última revisión fue un rechazo)."""
        r = self.ultima_revision
        return self.estado == "en_preparacion" and r is not None and not r.aprobado

    @property
    def editable(self):
        # Mientras Yikon prepara la proforma (o la corrige) se puede ajustar lo que lleva.
        # Después de aceptada ya no: para cambiarlo hay que volver a "proforma solicitada" y
        # enviar otra. Un pedido creado por Yikon (sin proforma) se ajusta hasta prepararlo.
        if self.estado in ("proforma_solicitada", "cambios_solicitados"):
            return True
        return self.estado == "aceptado" and not self.con_proforma

    @property
    def proforma_actual(self):
        """La última proforma enviada (la que el cliente tiene que aceptar), o None."""
        return self.proformas[0] if self.proformas else None


class LineaPedido(db.Model):
    __tablename__ = "lineas_pedido"

    id = db.Column(db.Integer, primary_key=True)
    pedido_id = db.Column(db.Integer, db.ForeignKey("pedidos.id"), nullable=False)
    pedido = db.relationship("Pedido", back_populates="lineas")
    producto_id = db.Column(db.Integer, db.ForeignKey("productos.id"), nullable=False)
    producto = db.relationship("Producto")
    # Si es un producto de un kit del pedido: su kit. Vacío = producto suelto.
    kit_pedido_id = db.Column(db.Integer, db.ForeignKey("kits_pedido.id"), index=True)
    kit_pedido = db.relationship("KitPedido", back_populates="lineas")

    cantidad = db.Column(db.Integer, nullable=False, default=1)
    # Precio e IVA se copian del producto al crear la línea: si mañana cambia
    # el precio del catálogo, los pedidos antiguos no se alteran.
    # (Los productos de un kit van a 0 €: el precio lo lleva el kit.)
    precio_unitario = db.Column(db.Numeric(10, 2), nullable=False)
    iva_pct = db.Column(db.Numeric(5, 2), nullable=False)
    descuento_pct = db.Column(db.Numeric(5, 2), nullable=False, default=0)

    @property
    def subtotal(self):
        if self.kit_pedido_id is not None or self.kit_pedido is not None:
            return Decimal("0.00")                 # lo paga el kit
        bruto = Decimal(self.cantidad or 0) * _dec(self.precio_unitario)
        return (bruto * (1 - _dec(self.descuento_pct) / 100)).quantize(Decimal("0.01"))

    @property
    def iva(self):
        return (self.subtotal * _dec(self.iva_pct) / 100).quantize(Decimal("0.01"))


class KitPedido(db.Model):
    """
    Un kit dentro de un pedido: qué kit, cuántos y a qué precio (por kit). Sus productos
    son LineaPedido con kit_pedido_id: son los que mueven stock y lotes.
    El precio se copia al crear el pedido (el especial del cliente o el estándar) y
    Yikon (admin, logística, FAS) lo pueden cambiar a mano en la ficha.
    """

    __tablename__ = "kits_pedido"

    id = db.Column(db.Integer, primary_key=True)
    pedido_id = db.Column(db.Integer, db.ForeignKey("pedidos.id"), nullable=False, index=True)
    pedido = db.relationship("Pedido", back_populates="kits")
    kit_id = db.Column(db.Integer, db.ForeignKey("kits.id"), nullable=False)
    kit = db.relationship("Kit")
    cantidad = db.Column(db.Integer, nullable=False, default=1)      # nº de kits
    precio_unitario = db.Column(db.Numeric(10, 2), nullable=False)   # precio de UN kit
    iva_pct = db.Column(db.Numeric(5, 2), nullable=False)
    # True si el cliente quitó productos o cambió cantidades respecto al kit estándar
    modificado = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())

    # cascade "all": al quitar un kit del pedido se borran también sus productos
    lineas = db.relationship("LineaPedido", back_populates="kit_pedido", order_by="LineaPedido.id",
                             cascade="all")

    @property
    def subtotal(self):
        return (Decimal(self.cantidad or 0) * _dec(self.precio_unitario)).quantize(Decimal("0.01"))

    @property
    def iva(self):
        return (self.subtotal * _dec(self.iva_pct) / 100).quantize(Decimal("0.01"))

    def es_estandar(self) -> bool:
        """¿Lleva exactamente los productos y cantidades del kit del catálogo × nº de kits?"""
        estandar = {c.producto_id: c.cantidad * self.cantidad for c in self.kit.componentes_activos}
        actual = {}
        for l in self.lineas:
            actual[l.producto_id] = actual.get(l.producto_id, 0) + l.cantidad
        return estandar == actual


# --------------------------------------------------------------------------- #
# Proformas (presupuesto sin precios que el cliente acepta antes del pedido)
# --------------------------------------------------------------------------- #
ESTADOS_DE_PROFORMA = {
    "enviada": _l("Pendiente de respuesta"),
    "aceptada": _l("Aceptada"),
    "cambios": _l("El cliente pidió cambios"),
    "retirada": _l("Retirada por Yikon"),
}


class CopiaAviso(db.Model):
    """Un email SIN usuario en la plataforma que recibe en copia avisos de un cliente (p. ej. el
    almacén o contabilidad de la clínica). tipos: los avisos que recibe, separados por comas
    (claves de app/avisos_cliente.TIPOS). Lo deciden admin y su Soporte en la ficha del cliente."""

    __tablename__ = "copias_aviso"
    __table_args__ = (db.UniqueConstraint("cliente_id", "email"),)

    id = db.Column(db.Integer, primary_key=True)
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=False, index=True)
    cliente = db.relationship("Cliente", backref=db.backref("copias_aviso", order_by="CopiaAviso.email",
                                                            cascade="all, delete-orphan"))
    email = db.Column(db.String(120), nullable=False)
    tipos = db.Column(db.String(200), nullable=False, default="")

    @validates("email")
    def _normalizar_email(self, clave, valor):
        return valor.strip().lower() if valor else valor


# --------------------------------------------------------------------------- #
# Incidencias: "Hay un problema con este pedido" (lo abre el cliente cuando ya lo tiene)
# --------------------------------------------------------------------------- #
MOTIVOS_INCIDENCIA = {
    "danado": _l("Llegó dañado"),
    "falta": _l("Falta algo"),
    "temperatura": _l("Temperatura"),
    "otro": _l("Otro"),
}
ICONOS_MOTIVO_INCIDENCIA = {"danado": "fa-box", "falta": "fa-search-minus", "temperatura": "fa-thermometer-half",
                            "otro": "fa-question"}
ESTADOS_CON_INCIDENCIAS = ("enviado", "entregado")      # se pueden abrir en pedidos que ya han salido


class Incidencia(db.Model):
    """Un problema con un pedido que ya tiene el cliente (llegó dañado, falta algo...). Lo que
    escribe el cliente y sus fotos van también al chat del pedido (las fotos son los adjuntos de
    ese mensaje): allí se habla. Yikon la cierra con «Resuelta» y una nota. Lógica: app/incidencias.py"""

    __tablename__ = "incidencias"

    id = db.Column(db.Integer, primary_key=True)
    pedido_id = db.Column(db.Integer, db.ForeignKey("pedidos.id"), nullable=False, index=True)
    pedido = db.relationship("Pedido", backref=db.backref("incidencias", order_by="Incidencia.id.desc()",
                                                          cascade="all, delete-orphan"))
    motivo = db.Column(db.String(20), nullable=False, default="otro")
    texto = db.Column(db.Text, nullable=False)
    creada = db.Column(db.DateTime(timezone=True), default=ahora, index=True)
    creada_por_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"))
    creada_por = db.relationship("User", foreign_keys=[creada_por_id])
    # El mensaje del chat del pedido con el texto y las fotos (sus adjuntos)
    mensaje_id = db.Column(db.Integer, db.ForeignKey("mensajes.id"))
    mensaje = db.relationship("Mensaje")
    # "abierta" / "resuelta"
    estado = db.Column(db.String(10), nullable=False, default="abierta", index=True)
    resuelta_el = db.Column(db.DateTime(timezone=True))
    resuelta_por_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"))
    resuelta_por = db.relationship("User", foreign_keys=[resuelta_por_id])
    nota_resolucion = db.Column(db.Text)

    @property
    def abierta(self):
        return self.estado == "abierta"

    @property
    def motivo_nombre(self):
        return MOTIVOS_INCIDENCIA.get(self.motivo, self.motivo)

    @property
    def fotos(self):
        return list(self.mensaje.adjuntos) if self.mensaje is not None else []


class Proforma(db.Model):
    """
    Una proforma enviada al cliente. Es una FOTO FIJA: guarda cómo estaba el pedido
    (productos, cantidades, caducidad prevista) al enviarla, aunque luego cambien el
    pedido o el stock. Si el cliente pide cambios, se envía otra (versión 2, 3...).
    """

    __tablename__ = "proformas"

    id = db.Column(db.Integer, primary_key=True)
    # PF-{referencia del pedido}, y PF-…-v2, -v3 en las siguientes (las antiguas: PF-2026-0001)
    numero = db.Column(db.String(60), unique=True, nullable=False)
    pedido_id = db.Column(db.Integer, db.ForeignKey("pedidos.id"), nullable=False, index=True)
    pedido = db.relationship("Pedido", back_populates="proformas")
    version = db.Column(db.Integer, nullable=False, default=1)
    fecha = db.Column(db.DateTime(timezone=True), default=ahora)
    valida_hasta = db.Column(db.Date, nullable=False)
    plazo_entrega = db.Column(db.String(120))
    notas = db.Column(db.Text)                     # para el cliente: salen en la proforma
    estado = db.Column(db.String(20), nullable=False, default="enviada")
    creada_por_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"))
    creada_por = db.relationship("User", foreign_keys=[creada_por_id])
    respondida_por_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"))
    respondida_por = db.relationship("User", foreign_keys=[respondida_por_id])
    respondida_fecha = db.Column(db.DateTime(timezone=True))
    # Lo que pidió cambiar el cliente (también va al chat del pedido)
    comentario_cambios = db.Column(db.Text)
    # El PDF que hace Yikon y adjunta al enviarla: es el que descarga el cliente. Las proformas
    # antiguas no lo tienen y se descargan con el modelo que genera la plataforma.
    pdf_archivo = db.Column(db.String(100), unique=True)
    pdf_nombre = db.Column(db.String(200))
    pdf_tamano = db.Column(db.Integer)
    lineas = db.relationship("ProformaLinea", back_populates="proforma", order_by="ProformaLinea.orden",
                             cascade="all, delete-orphan")

    @property
    def estado_nombre(self):
        return ESTADOS_DE_PROFORMA.get(self.estado, self.estado)

    @property
    def caducada(self):
        return self.estado == "enviada" and self.valida_hasta < date.today()

    @property
    def numero_y_version(self):
        """El número tal cual; en las antiguas (PF-2026-0001) la versión no va en el número: se añade."""
        if self.version > 1 and not self.numero.endswith(f"-v{self.version}"):
            return f"{self.numero} (v{self.version})"
        return self.numero


class ProformaLinea(db.Model):
    """Un producto de la proforma, copiado tal cual estaba al enviarla."""

    __tablename__ = "proforma_lineas"

    id = db.Column(db.Integer, primary_key=True)
    proforma_id = db.Column(db.Integer, db.ForeignKey("proformas.id"), nullable=False, index=True)
    proforma = db.relationship("Proforma", back_populates="lineas")
    orden = db.Column(db.Integer, nullable=False, default=0)
    grupo = db.Column(db.String(250))              # "2 × PGT-A completo" o vacío = producto suelto
    referencia = db.Column(db.String(50), nullable=False)
    nombre = db.Column(db.String(200), nullable=False)
    marca = db.Column(db.String(80))
    cantidad = db.Column(db.Integer, nullable=False)
    # Caducidad del primer lote que saldría (FEFO) al preparar la proforma. Vacía si el
    # producto no lleva stock (servicios) o si en ese momento no había suficiente.
    caducidad = db.Column(db.Date)
    sin_stock = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())


# --------------------------------------------------------------------------- #
# Facturas (REGISTRO de facturas emitidas por el sistema contable)
# --------------------------------------------------------------------------- #
# "Vencida" no se guarda: se calcula (pendiente + fecha de vencimiento pasada).
# Formatos de la tabla de productos de la factura (ver app/facturas/datos.py)
FORMATOS_FACTURA = {
    "A": _l("A · Kits sin precio"),
    "B": _l("B · Kits con precio por línea"),
    "C": _l("C · Lista con precio unitario"),
}
REGIMENES_IVA = {
    "es": _l("España (IVA)"),
    "ue": _l("UE · sin IVA"),
    "export": _l("Exportación · sin IVA"),
}

ESTADOS_FACTURA = {
    "pendiente": _l("Pendiente"),
    "pagada": _l("Pagada"),
    "anulada": _l("Anulada"),
}


class Factura(db.Model):
    """
    Esta tabla REGISTRA facturas que se emiten en otro sistema (ERP/contabilidad).
    No genera facturas legales: el número lo pone el sistema de facturación oficial.
    """

    __tablename__ = "facturas"

    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(50), unique=True, nullable=False, index=True)
    fecha_emision = db.Column(db.Date, nullable=False, default=date.today)
    fecha_vencimiento = db.Column(db.Date)
    fecha_pago = db.Column(db.Date)
    # Importes: solo los de las facturas antiguas. Las nuevas no los llevan: la factura se hace
    # a mano (con "Preparar factura" del pedido) y aquí se registra el PDF, el nº y el vencimiento.
    base_imponible = db.Column(db.Numeric(12, 2))
    iva = db.Column(db.Numeric(12, 2))
    total = db.Column(db.Numeric(12, 2))
    estado = db.Column(db.String(20), nullable=False, default="pendiente")
    notas = db.Column(db.Text)
    creado = db.Column(db.DateTime(timezone=True), default=ahora)

    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=False)
    cliente = db.relationship("Cliente", back_populates="facturas")
    pedido_id = db.Column(db.Integer, db.ForeignKey("pedidos.id"))
    pedido = db.relationship("Pedido", back_populates="facturas")

    # PDF oficial de la factura (el que sale del sistema contable). Lo sube admin y lo
    # descarga el cliente. Se guarda con nombre aleatorio en la carpeta privada.
    pdf_archivo = db.Column(db.String(100), unique=True)
    pdf_nombre = db.Column(db.String(200))
    pdf_tamano = db.Column(db.Integer)

    @property
    def pdf_tamano_legible(self):
        from app.archivos import tamano_legible
        return tamano_legible(self.pdf_tamano)

    @property
    def estado_nombre(self):
        return ESTADOS_FACTURA.get(self.estado, self.estado)

    # Revisión por Soporte de cliente (opcional) y envío al cliente. El cliente solo la ve cuando
    # está enviada (enviada_el): Aina la manda por email y lo marca aquí, así los dos caminos van a la vez.
    #   revision: None (no se pidió) · "pendiente" (en revisión) · "cambios" (devuelta) · "aprobada"
    revision = db.Column(db.String(20))
    revision_comentario = db.Column(db.Text)            # lo que pidió cambiar quien la devolvió
    revisado_por_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"))
    revisado_por = db.relationship("User")
    revisado_el = db.Column(db.DateTime(timezone=True))
    enviada_el = db.Column(db.DateTime(timezone=True))

    @property
    def enviada(self):
        return self.enviada_el is not None

    @property
    def fase(self):
        """En qué punto está antes de llegar al cliente: "revision", "cambios", "por_enviar" o
        "enviada" (a partir de ahí manda el estado de pago)."""
        if self.enviada:
            return "enviada"
        if self.revision in ("pendiente", "cambios"):
            return "revision" if self.revision == "pendiente" else "cambios"
        return "por_enviar"

    @property
    def esta_vencida(self):
        # Solo cuenta desde que el cliente la tiene
        return (
            self.enviada
            and self.estado == "pendiente"
            and self.fecha_vencimiento is not None
            and self.fecha_vencimiento < date.today()
        )


# --------------------------------------------------------------------------- #
# Auditoría: quién hizo qué y cuándo
# --------------------------------------------------------------------------- #
class RegistroAuditoria(db.Model):
    __tablename__ = "auditoria"

    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime(timezone=True), default=ahora, index=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"))
    usuario = db.relationship("User")
    accion = db.Column(db.String(20), nullable=False)  # crear / editar / borrar / login
    entidad = db.Column(db.String(50), nullable=False)  # "Factura", "Cliente"...
    entidad_id = db.Column(db.Integer)
    # Cómo se llamaba el objeto al registrarlo ("YK-2026-DiNA-010 · DiNA Genomics"): así se reconoce
    # a simple vista y se sigue leyendo aunque luego lo renombren o lo borren (app/auditoria.py)
    objeto = db.Column(db.String(250))
    detalle = db.Column(db.Text)


# --------------------------------------------------------------------------- #
# Inventario de la oficina
# --------------------------------------------------------------------------- #
TIPOS_MOVIMIENTO = {
    "entrada": _l("Entrada de mercancía"),
    "salida_pedido": _l("Salida por envío de pedido"),
    "devolucion_pedido": _l("Anulación de envío"),
    "ajuste": _l("Ajuste manual"),
    "apertura_kit": _l("Apertura de kit"),     # −1 kit cerrado y + sus productos sueltos
}


class MovimientoInventario(db.Model):
    """
    Cada fila es un cambio de stock: +10 (llegan 10 kits), −3 (se envía un pedido)...
    El stock NUNCA se edita directamente: se añade un movimiento. Así siempre se
    puede reconstruir por qué hay las unidades que hay, y quién lo hizo.
    """

    __tablename__ = "movimientos_inventario"

    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime(timezone=True), default=ahora, index=True)
    # De QUÉ es el movimiento: de un producto o de un kit cerrado (uno de los dos)
    producto_id = db.Column(db.Integer, db.ForeignKey("productos.id"), index=True)
    producto = db.relationship("Producto", back_populates="movimientos")
    kit_id = db.Column(db.Integer, db.ForeignKey("kits.id"), index=True)
    kit = db.relationship("Kit")
    cantidad = db.Column(db.Integer, nullable=False)  # positiva = entra, negativa = sale
    tipo = db.Column(db.String(20), nullable=False)
    nota = db.Column(db.String(250))
    pedido_id = db.Column(db.Integer, db.ForeignKey("pedidos.id"))
    pedido = db.relationship("Pedido")
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"))
    usuario = db.relationship("User")
    # De qué lote entra o sale. Así sabemos qué lote se envió en cada pedido (trazabilidad).
    lote_id = db.Column(db.Integer, db.ForeignKey("lotes.id"), index=True)
    lote = db.relationship("Lote", back_populates="movimientos")

    @property
    def tipo_nombre(self):
        return TIPOS_MOVIMIENTO.get(self.tipo, self.tipo)

    @property
    def articulo(self):
        return self.kit if self.kit_id is not None or self.kit is not None else self.producto


class Lote(db.Model):
    """
    Un lote de fabricación de un producto o de un kit cerrado, con su caducidad.
    El stock de cada lote es la suma de sus movimientos (igual que el del producto).
    Los envíos sacan primero el lote que caduca antes (FEFO) y nunca uno caducado.
    """

    __tablename__ = "lotes"
    __table_args__ = (db.UniqueConstraint("producto_id", "codigo"),   # mismo código en otro producto: vale
                      db.UniqueConstraint("kit_id", "codigo"),
                      db.CheckConstraint("(producto_id IS NULL) <> (kit_id IS NULL)", name="lote_de_producto_o_kit"))

    id = db.Column(db.Integer, primary_key=True)
    producto_id = db.Column(db.Integer, db.ForeignKey("productos.id"), index=True)
    producto = db.relationship("Producto", back_populates="lotes")
    kit_id = db.Column(db.Integer, db.ForeignKey("kits.id"), index=True)
    kit = db.relationship("Kit", back_populates="lotes")
    codigo = db.Column(db.String(60), nullable=False)
    # Vacía solo en el lote "SIN LOTE" que agrupa el stock anterior a esta función
    caducidad = db.Column(db.Date)
    creado = db.Column(db.DateTime(timezone=True), default=ahora)
    movimientos = db.relationship("MovimientoInventario", back_populates="lote")

    @property
    def stock(self) -> int:
        return db.session.scalar(
            db.select(db.func.coalesce(db.func.sum(MovimientoInventario.cantidad), 0))
            .where(MovimientoInventario.lote_id == self.id))

    @property
    def articulo(self):
        """El producto o el kit de este lote."""
        return self.kit if self.kit_id is not None or self.kit is not None else self.producto

    def caducado(self, hoy=None) -> bool:
        return self.caducidad is not None and self.caducidad < (hoy or date.today())

    def dias_para_caducar(self, hoy=None):
        return None if self.caducidad is None else (self.caducidad - (hoy or date.today())).days

    def __repr__(self):
        return f"<Lote {self.codigo} ({self.articulo!r})>"


class ReservaLote(db.Model):
    """
    Unidades de un lote APARTADAS para un pedido que todavía no ha salido.
    La caducidad que el cliente aprueba en la proforma es la de estos lotes: por eso quedan
    reservados (otro pedido no puede llevárselos) y al enviar salen exactamente estos.
    No es un movimiento: la mercancía sigue en la oficina. Al enviar, la reserva se convierte
    en la salida de stock y desaparece; al cancelar, se libera. Lógica: inventario/reservas.py
    """

    __tablename__ = "reservas_lote"
    __table_args__ = (db.UniqueConstraint("pedido_id", "lote_id"),
                      db.CheckConstraint("cantidad > 0", name="reserva_positiva"))

    id = db.Column(db.Integer, primary_key=True)
    pedido_id = db.Column(db.Integer, db.ForeignKey("pedidos.id"), nullable=False, index=True)
    pedido = db.relationship("Pedido", backref=db.backref("reservas", cascade="all, delete-orphan"))
    lote_id = db.Column(db.Integer, db.ForeignKey("lotes.id"), nullable=False, index=True)
    lote = db.relationship("Lote")
    cantidad = db.Column(db.Integer, nullable=False)
    fecha = db.Column(db.DateTime(timezone=True), default=ahora)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"))
    usuario = db.relationship("User")


class Ajuste(db.Model):
    """Un ajuste de la plataforma que admin cambia desde Administración → Ajustes (clave → valor):
    plazos, proformas, datos de Yikon, apartados por rol, avisos internos, logo de los correos…"""

    __tablename__ = "ajustes"

    clave = db.Column(db.String(60), primary_key=True)
    valor = db.Column(db.Text, nullable=False)        # (Text: las notas por defecto de la proforma son largas)


class PlantillaCorreo(db.Model):
    """Texto de un correo al cliente cambiado por admin (Administración → Ajustes → Correos al
    cliente), en un idioma. Si un caso no tiene fila, se usa el texto de fábrica (app/correos_cliente.py).
    La clave "firma" guarda la firma con los datos de contacto que va al final de todos."""

    __tablename__ = "plantillas_correo"
    __table_args__ = (db.UniqueConstraint("clave", "idioma"),)

    id = db.Column(db.Integer, primary_key=True)
    clave = db.Column(db.String(40), nullable=False)
    idioma = db.Column(db.String(5), nullable=False)
    asunto = db.Column(db.String(200))
    cuerpo = db.Column(db.Text, nullable=False)
    actualizado_por_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"))
    actualizado_por = db.relationship("User")
    actualizado_el = db.Column(db.DateTime(timezone=True), default=ahora, onupdate=ahora)


class VistaPedido(db.Model):
    """Cuándo abrió cada usuario la ficha de cada pedido por última vez. Con esto se sabe qué
    es "nuevo" para esa persona (ver app/pedidos/novedades.py)."""

    __tablename__ = "vistas_pedido"
    __table_args__ = (db.UniqueConstraint("usuario_id", "pedido_id"),)

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False, index=True)
    pedido_id = db.Column(db.Integer, db.ForeignKey("pedidos.id"), nullable=False, index=True)
    pedido = db.relationship("Pedido", backref=db.backref("vistas", cascade="all, delete-orphan"))
    fecha = db.Column(db.DateTime(timezone=True), nullable=False, default=ahora)


# --------------------------------------------------------------------------- #
# Fotos de preparación y validación del pedido
# --------------------------------------------------------------------------- #
class FotoPedido(db.Model):
    """
    Foto del pedido preparado. El archivo NO está en /static: se guarda en una
    carpeta privada y solo se sirve a través de una vista que comprueba permisos
    y alcance (el cliente nunca las ve).
    """

    __tablename__ = "fotos_pedido"

    id = db.Column(db.Integer, primary_key=True)
    pedido_id = db.Column(db.Integer, db.ForeignKey("pedidos.id"), nullable=False, index=True)
    pedido = db.relationship("Pedido", back_populates="fotos")
    archivo = db.Column(db.String(100), nullable=False, unique=True)  # nombre en disco (aleatorio)
    nombre_original = db.Column(db.String(200))
    subida_por_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"))
    subida_por = db.relationship("User")
    fecha = db.Column(db.DateTime(timezone=True), default=ahora)


class RevisionPedido(db.Model):
    """Cada vez que el FAS valida o rechaza las fotos de un pedido."""

    __tablename__ = "revisiones_pedido"

    id = db.Column(db.Integer, primary_key=True)
    pedido_id = db.Column(db.Integer, db.ForeignKey("pedidos.id"), nullable=False, index=True)
    pedido = db.relationship("Pedido", back_populates="revisiones")
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"))
    usuario = db.relationship("User")
    aprobado = db.Column(db.Boolean, nullable=False)
    comentario = db.Column(db.Text)
    fecha = db.Column(db.DateTime(timezone=True), default=ahora)


# --------------------------------------------------------------------------- #
# Documentos del pedido (p. ej. la orden de compra interna del cliente)
# --------------------------------------------------------------------------- #
class DocumentoPedido(db.Model):
    """Archivo adjunto al pedido. Lo ven el cliente de ese pedido, sus FAS, logística y admin."""

    __tablename__ = "documentos_pedido"

    id = db.Column(db.Integer, primary_key=True)
    pedido_id = db.Column(db.Integer, db.ForeignKey("pedidos.id"), nullable=False, index=True)
    pedido = db.relationship("Pedido", back_populates="documentos")
    archivo = db.Column(db.String(100), nullable=False, unique=True)  # nombre en disco (aleatorio)
    nombre_original = db.Column(db.String(200), nullable=False)
    tamano = db.Column(db.Integer, nullable=False)                    # bytes
    subido_por_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"))
    subido_por = db.relationship("User")
    fecha = db.Column(db.DateTime(timezone=True), default=ahora)

    @property
    def tamano_legible(self):
        kb = self.tamano / 1024
        return f"{max(1, round(kb))} KB" if kb < 1024 else f"{kb / 1024:.1f} MB"

    @property
    def extension(self):
        return self.nombre_original.rsplit(".", 1)[-1].lower() if "." in self.nombre_original else ""


# --------------------------------------------------------------------------- #
# Mensajes entre el cliente y Yikon (Yikon (admin, logística, FAS))
# --------------------------------------------------------------------------- #
# Hay dos tipos de conversación ("hilo"):
#   - la general de cada cliente   → hilo "cliente-<id>"  (pedido_id vacío)
#   - la de cada pedido            → hilo "pedido-<id>"
# El hilo se guarda como texto para poder usarlo tal cual en la tabla de lecturas
# (una restricción UNIQUE con un pedido_id vacío no funcionaría: NULL ≠ NULL).
def hilo_de(cliente_id=None, pedido_id=None, interno=False) -> str:
    """Clave de una conversación: "cliente-4" (general), "pedido-12" (del pedido, con el
    cliente) o "interno-12" (interna del pedido: solo admin, logística y FAS)."""
    if interno:
        return f"interno-{pedido_id}"
    return f"pedido-{pedido_id}" if pedido_id else f"cliente-{cliente_id}"


class Mensaje(db.Model):
    """
    Un mensaje de una conversación. NO se edita ni se borra: es el registro de lo
    que se ha hablado. Lo ve el cliente, SALVO los internos (interno=True: conversación
    interna de un pedido entre admin, logística y FAS), que alcance.filtrar_mensajes le oculta.
    """

    __tablename__ = "mensajes"

    id = db.Column(db.Integer, primary_key=True)
    hilo = db.Column(db.String(30), nullable=False, index=True)
    # Siempre se guarda el cliente (también en los de pedido): así el filtro de
    # "qué puede ver cada uno" es el mismo para las dos conversaciones.
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=False, index=True)
    cliente = db.relationship("Cliente")
    pedido_id = db.Column(db.Integer, db.ForeignKey("pedidos.id"), index=True)
    pedido = db.relationship("Pedido")
    autor_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    autor = db.relationship("User", foreign_keys=[autor_id])
    # ¿Lo escribió alguien de la empresa cliente? (se guarda: si al autor le cambian el
    # rol más adelante, el mensaje sigue en el lado en que se escribió)
    de_cliente = db.Column(db.Boolean, nullable=False, default=False)
    texto = db.Column(db.Text, nullable=False)   # puede ir vacío si el mensaje solo lleva archivos
    # Mensaje de Yikon al cliente: el cliente no lo ve (ni le llega el email) hasta esta hora, para
    # que quien lo escribió pueda deshacerlo unos segundos (MENSAJES_DESHACER_SEGUNDOS). Vacío = ya.
    visible_desde = db.Column(db.DateTime(timezone=True))
    interno = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    # La conversación general es privada entre el cliente y su Soporte de cliente: Almacén y
    # Facturación solo ven los mensajes que el Soporte les comparte («Compartir con…»), con una nota
    # opcional. compartido_con: a qué roles, separados por comas ("logistica", "facturacion" o los dos).
    compartido_el = db.Column(db.DateTime(timezone=True))
    compartido_con = db.Column(db.String(40))
    compartido_por_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"))
    compartido_por = db.relationship("User", foreign_keys=[compartido_por_id])
    compartido_nota = db.Column(db.String(500))

    @property
    def compartido_roles(self):
        """Los roles con los que se ha compartido (["logistica"], ["facturacion"], los dos o [])."""
        return [r for r in (self.compartido_con or "").split(",") if r]
    fecha = db.Column(db.DateTime(timezone=True), default=ahora, index=True)
    adjuntos = db.relationship("AdjuntoMensaje", back_populates="mensaje", order_by="AdjuntoMensaje.id")

    # Para contar rápido los "no leídos" (filtran por conversación, lado y número de mensaje)
    __table_args__ = (db.Index("ix_mensajes_hilo_lado_id", "hilo", "de_cliente", "id"),)


class AdjuntoMensaje(db.Model):
    """Un archivo adjunto a un mensaje. Lo ve quien ve el mensaje (y tampoco se borra)."""

    __tablename__ = "adjuntos_mensaje"

    id = db.Column(db.Integer, primary_key=True)
    mensaje_id = db.Column(db.Integer, db.ForeignKey("mensajes.id"), nullable=False, index=True)
    mensaje = db.relationship("Mensaje", back_populates="adjuntos")
    archivo = db.Column(db.String(100), nullable=False, unique=True)   # nombre en disco (aleatorio)
    nombre_original = db.Column(db.String(200), nullable=False)
    tamano = db.Column(db.Integer, nullable=False)                      # bytes

    @property
    def tamano_legible(self):
        from app.archivos import tamano_legible
        return tamano_legible(self.tamano)


class LecturaHilo(db.Model):
    """Hasta qué mensaje ha leído cada usuario en cada conversación (para los "no leídos")."""

    __tablename__ = "lecturas_hilo"
    __table_args__ = (db.UniqueConstraint("usuario_id", "hilo"),)

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False, index=True)
    hilo = db.Column(db.String(30), nullable=False)
    ultimo_mensaje_id = db.Column(db.Integer, nullable=False, default=0)
    # ¿Ya le avisamos por email de mensajes que aún no ha leído? Así solo recibe UN email
    # hasta que entra a leerlos (se vuelve a poner a False al leer).
    avisado = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())


# --------------------------------------------------------------------------- #
# Intentos de login (para frenar a quien pruebe contraseñas a lo bruto)
# --------------------------------------------------------------------------- #
class CorreoEnviado(db.Model):
    """Cada email que sale de la plataforma (Administración → Correos enviados), para saber si le
    llegó a alguien y reenviarlo si falló. Se guarda el texto y el HTML (sin imágenes: el logo se
    vuelve a poner al reenviar). Los de más de CORREOS_REGISTRO_DIAS se borran solos (app/correo.py)."""

    __tablename__ = "correos_enviados"

    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime(timezone=True), default=ahora, index=True)
    para = db.Column(db.Text, nullable=False)
    asunto = db.Column(db.String(300), nullable=False)
    tipo = db.Column(db.String(60), index=True)            # "cliente.enviado", "interno.proforma_pedida", "invitacion"...
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), index=True)
    cliente = db.relationship("Cliente")
    pedido_id = db.Column(db.Integer, db.ForeignKey("pedidos.id"), index=True)
    pedido = db.relationship("Pedido")
    estado = db.Column(db.String(10), nullable=False)      # "enviado" / "fallido"
    error = db.Column(db.Text)
    texto = db.Column(db.Text)
    html = db.Column(db.Text)
    reenvio_de_id = db.Column(db.Integer, db.ForeignKey("correos_enviados.id"))


class ErrorWeb(db.Model):
    """Una página que falló por un error nuestro (500), para la página de Estado. Se guardan los últimos 90 días."""

    __tablename__ = "errores_web"

    id = db.Column(db.Integer, primary_key=True)
    fecha = db.Column(db.DateTime(timezone=True), default=ahora, index=True)
    ruta = db.Column(db.String(300))
    usuario = db.Column(db.String(150))
    error = db.Column(db.String(500))


class IntentoLogin(db.Model):
    __tablename__ = "intentos_login"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), index=True)
    ip = db.Column(db.String(45), index=True)
    exito = db.Column(db.Boolean, nullable=False, default=False)
    fecha = db.Column(db.DateTime(timezone=True), default=ahora, index=True)


# --------------------------------------------------------------------------- #
# Documentos internos de Yikon (logos, plantillas, protocolos...): solo el equipo
# --------------------------------------------------------------------------- #
CATEGORIAS_DOCUMENTO = {
    "marca": _l("Logos y marca"),
    "plantillas": _l("Plantillas"),
    "protocolos": _l("Protocolos"),
    "fichas": _l("Fichas técnicas"),
    "formacion": _l("Formación"),
    "otros": _l("Otros"),
}
ICONOS_CATEGORIA_DOCUMENTO = {"marca": "fa-palette", "plantillas": "fa-file-alt", "protocolos": "fa-clipboard-check",
                              "fichas": "fa-flask", "formacion": "fa-graduation-cap", "otros": "fa-folder"}


class DocumentoInterno(db.Model):
    """Un documento del equipo. Sus archivos son VERSIONES: al subir uno nuevo, el anterior
    se queda en el historial (se puede seguir descargando). La vigente es la última."""

    __tablename__ = "documentos_internos"

    id = db.Column(db.Integer, primary_key=True)
    categoria = db.Column(db.String(20), nullable=False, index=True, default="otros")
    titulo = db.Column(db.String(150), nullable=False)
    descripcion = db.Column(db.Text)
    creado = db.Column(db.DateTime(timezone=True), default=ahora)
    actualizado = db.Column(db.DateTime(timezone=True), default=ahora, index=True)   # última versión subida
    versiones = db.relationship("VersionDocumento", back_populates="documento", cascade="all, delete-orphan",
                                order_by="VersionDocumento.numero.desc()")

    @property
    def vigente(self):
        return self.versiones[0] if self.versiones else None

    @property
    def categoria_nombre(self):
        return CATEGORIAS_DOCUMENTO.get(self.categoria, self.categoria)


class VersionDocumento(db.Model):
    __tablename__ = "versiones_documento"
    __table_args__ = (db.UniqueConstraint("documento_id", "numero"),)

    id = db.Column(db.Integer, primary_key=True)
    documento_id = db.Column(db.Integer, db.ForeignKey("documentos_internos.id"), nullable=False, index=True)
    documento = db.relationship("DocumentoInterno", back_populates="versiones")
    numero = db.Column(db.Integer, nullable=False)                      # 1, 2, 3...
    archivo = db.Column(db.String(100), nullable=False, unique=True)   # nombre en disco (aleatorio)
    nombre_original = db.Column(db.String(200), nullable=False)
    extension = db.Column(db.String(10), nullable=False)
    tamano = db.Column(db.Integer, nullable=False)
    nota = db.Column(db.String(300))                                    # "qué cambia en esta versión"
    subido_por_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"))
    subido_por = db.relationship("User")
    fecha = db.Column(db.DateTime(timezone=True), default=ahora)

    @property
    def tamano_legible(self):
        from app.archivos import tamano_legible
        return tamano_legible(self.tamano)

    @property
    def es_imagen(self):
        """Se puede enseñar en miniatura (SVG no: podría llevar código; se descarga)."""
        return self.extension in {"png", "jpg", "jpeg", "gif", "webp"}


# --------------------------------------------------------------------------- #
# Soporte ChromGo: tickets de incidencias de los clientes con la plataforma ChromGo
# --------------------------------------------------------------------------- #
CATEGORIAS_TICKET = {
    "acceso": _l("Acceso / inicio de sesión"),
    "carga": _l("Carga de datos / muestras"),
    "cnv": _l("Análisis CNV / aneuploidías"),
    "snp": _l("SNP / haplotipado"),
    "informes": _l("Informes y resultados"),
    "rendimiento": _l("Lentitud o errores de la web"),
    "consulta": _l("Consulta / cómo se hace"),
    "otro": _l("Otro"),
}
PRIORIDADES_TICKET = {
    "baja": _l("Baja"),
    "normal": _l("Normal"),
    "alta": _l("Alta"),
    "urgente": _l("Urgente"),
}
# Lo que explica cada prioridad al cliente cuando la elige
AYUDA_PRIORIDAD_TICKET = {
    "baja": _l("Una duda o mejora; no me bloquea."),
    "normal": _l("Algo no funciona, pero puedo seguir trabajando."),
    "alta": _l("No puedo terminar un análisis o un informe."),
    "urgente": _l("No puedo trabajar con ChromGo / resultados urgentes de paciente."),
}
ESTADOS_TICKET = {
    "abierto": _l("Abierto"),
    "en_curso": _l("En curso"),
    "esperando_cliente": _l("Esperando al cliente"),
    "resuelto": _l("Resuelto"),
    "cerrado": _l("Cerrado"),
}
ICONOS_ESTADO_TICKET = {"abierto": "fa-inbox", "en_curso": "fa-cogs", "esperando_cliente": "fa-hourglass-half",
                        "resuelto": "fa-check", "cerrado": "fa-lock"}
ICONOS_PRIORIDAD_TICKET = {"baja": "fa-angle-down", "normal": "fa-minus", "alta": "fa-angle-up",
                           "urgente": "fa-angle-double-up"}
ESTADOS_TICKET_ACTIVOS = ("abierto", "en_curso", "esperando_cliente")


class Ticket(db.Model):
    """Una incidencia de un cliente con ChromGo. La conversación va en TicketMensaje:
    la del cliente y, aparte, las notas internas del equipo de soporte (el cliente no las ve)."""

    __tablename__ = "tickets"

    id = db.Column(db.Integer, primary_key=True)
    numero = db.Column(db.String(20), nullable=False, unique=True)     # TK-2026-0001
    cliente_id = db.Column(db.Integer, db.ForeignKey("clientes.id"), nullable=False, index=True)
    cliente = db.relationship("Cliente")
    creado_por_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    creado_por = db.relationship("User", foreign_keys=[creado_por_id])
    asunto = db.Column(db.String(200), nullable=False)
    categoria = db.Column(db.String(20), nullable=False, default="otro")
    prioridad = db.Column(db.String(10), nullable=False, default="normal", index=True)
    estado = db.Column(db.String(20), nullable=False, default="abierto", index=True)
    # ID de la muestra, del análisis o del run en ChromGo (nunca datos personales del paciente)
    referencia = db.Column(db.String(120))
    asignado_a_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), index=True)
    asignado_a = db.relationship("User", foreign_keys=[asignado_a_id])
    creado = db.Column(db.DateTime(timezone=True), default=ahora, index=True)
    actualizado = db.Column(db.DateTime(timezone=True), default=ahora, index=True)   # último mensaje o cambio
    resuelto = db.Column(db.DateTime(timezone=True))
    mensajes = db.relationship("TicketMensaje", back_populates="ticket", order_by="TicketMensaje.id")

    @property
    def estado_nombre(self):
        return ESTADOS_TICKET.get(self.estado, self.estado)

    @property
    def prioridad_nombre(self):
        return PRIORIDADES_TICKET.get(self.prioridad, self.prioridad)

    @property
    def categoria_nombre(self):
        return CATEGORIAS_TICKET.get(self.categoria, self.categoria)

    @property
    def activo(self):
        return self.estado in ESTADOS_TICKET_ACTIVOS


class TicketMensaje(db.Model):
    """Un mensaje de un ticket (no se edita ni se borra). interno=True: nota del equipo de
    soporte que el cliente NO ve (se filtra en soporte/servicio.py, el único sitio que los lee).
    de_sistema=True: línea automática ("Estado: Abierto → Resuelto")."""

    __tablename__ = "ticket_mensajes"

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=False, index=True)
    ticket = db.relationship("Ticket", back_populates="mensajes")
    autor_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    autor = db.relationship("User")
    de_cliente = db.Column(db.Boolean, nullable=False, default=False)
    interno = db.Column(db.Boolean, nullable=False, default=False)
    de_sistema = db.Column(db.Boolean, nullable=False, default=False)
    texto = db.Column(db.Text, nullable=False)
    fecha = db.Column(db.DateTime(timezone=True), default=ahora)
    adjuntos = db.relationship("AdjuntoTicket", back_populates="mensaje", order_by="AdjuntoTicket.id")


class AdjuntoTicket(db.Model):
    __tablename__ = "adjuntos_ticket"

    id = db.Column(db.Integer, primary_key=True)
    mensaje_id = db.Column(db.Integer, db.ForeignKey("ticket_mensajes.id"), nullable=False, index=True)
    mensaje = db.relationship("TicketMensaje", back_populates="adjuntos")
    archivo = db.Column(db.String(100), nullable=False, unique=True)
    nombre_original = db.Column(db.String(200), nullable=False)
    tamano = db.Column(db.Integer, nullable=False)

    @property
    def tamano_legible(self):
        from app.archivos import tamano_legible
        return tamano_legible(self.tamano)


class LecturaTicket(db.Model):
    """Hasta qué mensaje ha leído cada usuario cada ticket (para los "sin leer" y no repetir emails)."""

    __tablename__ = "lecturas_ticket"
    __table_args__ = (db.UniqueConstraint("usuario_id", "ticket_id"),)

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False, index=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey("tickets.id"), nullable=False, index=True)
    # Dos conversaciones por ticket, cada una con su "hasta dónde he leído" y su aviso por email:
    # la del cliente y (solo el equipo) las notas internas. Así leer una no marca la otra.
    ultimo_mensaje_id = db.Column(db.Integer, nullable=False, default=0)
    ultimo_interno_id = db.Column(db.Integer, nullable=False, default=0, server_default="0")
    avisado = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())
    avisado_interno = db.Column(db.Boolean, nullable=False, default=False, server_default=db.false())


class CorreoBorrador(db.Model):
    """Correo del equipo que no puede entregarse sin confirmación de su autor."""
    __tablename__ = "correos_borrador"
    id = db.Column(db.Integer, primary_key=True)
    autor_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False, index=True)
    fecha = db.Column(db.DateTime(timezone=True), nullable=False, default=ahora)
    caduca = db.Column(db.DateTime(timezone=True), nullable=False)
    estado = db.Column(db.String(20), nullable=False, default="pendiente", index=True)
    mensaje = db.Column(db.LargeBinary, nullable=True)
    meta = db.Column(db.JSON, nullable=False, default=dict)
    reenvio_de_id = db.Column(db.Integer, nullable=True)
    version = db.Column(db.Integer, nullable=False, default=1)
