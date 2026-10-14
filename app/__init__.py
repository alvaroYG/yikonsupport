import os
from decimal import Decimal

from flask import Flask, render_template

from app.extensions import babel, csrf, db, login_manager, migrate
from config import configs


def create_app(nombre_config: str = None):
    """Application factory: crea y configura la app."""
    nombre_config = nombre_config or os.environ.get("FLASK_CONFIG", "dev")
    app = Flask(__name__)
    app.config.from_object(configs[nombre_config])
    app.config["ENTORNO"] = nombre_config

    if not app.config.get("SECRET_KEY"):
        raise RuntimeError(
            "Falta SECRET_KEY. Copia .env.example a .env y genera una con:\n"
            "  python -c \"import secrets; print(secrets.token_hex(32))\""
        )

    db.init_app(app)
    migrate.init_app(app, db)
    csrf.init_app(app)
    login_manager.init_app(app)
    from app.idioma import elegir_idioma
    babel.init_app(app, locale_selector=elegir_idioma)

    from app import models  # noqa: F401  (registra los modelos para Flask-Migrate)
    from app.admin.routes import bp as admin_bp
    from app.auth.routes import bp as auth_bp
    from app.clientes.routes import bp as clientes_bp
    from app.facturas.routes import bp as facturas_bp
    from app.inventario.routes import bp as inventario_bp
    from app.main.routes import bp as main_bp
    from app.mensajes.routes import bp as mensajes_bp
    from app.pedidos.routes import bp as pedidos_bp
    from app.productos.routes import bp as productos_bp
    from app.proformas.routes import bp as proformas_bp
    from app.documentos.routes import bp as documentos_bp
    from app.soporte.routes import bp as soporte_bp

    from app.revision_correo import bp as revision_correo_bp
    app.register_blueprint(revision_correo_bp, url_prefix="/correos-revision")
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(clientes_bp, url_prefix="/clientes")
    app.register_blueprint(productos_bp, url_prefix="/productos")
    app.register_blueprint(pedidos_bp, url_prefix="/pedidos")
    app.register_blueprint(proformas_bp, url_prefix="/pedidos")
    app.register_blueprint(facturas_bp, url_prefix="/facturas")
    app.register_blueprint(inventario_bp, url_prefix="/inventario")
    app.register_blueprint(mensajes_bp, url_prefix="/mensajes")
    app.register_blueprint(documentos_bp, url_prefix="/documentos")
    app.register_blueprint(soporte_bp, url_prefix="/soporte")
    if app.config["ENTORNO"] == "dev":
        # "Entrar como…" (barra de pruebas): solo en desarrollo, nunca en producción
        from app.pruebas import bp as pruebas_bp, usuarios_para_probar
        app.register_blueprint(pruebas_bp, url_prefix="/pruebas")
        app.jinja_env.globals["usuarios_para_probar"] = usuarios_para_probar

    # "Ver como un usuario" (solo lectura) va el PRIMERO: cambia la sesión de base de datos de la
    # petición antes de que nadie la use. Después, el cierre de sesión por inactividad.
    from app import seguridad, ver_como
    ver_como.registrar(app)
    seguridad.registrar(app)

    _registrar_filtros(app)
    _registrar_contexto(app)
    _registrar_seguridad(app)
    _configurar_logs(app)
    _registrar_errores(app)

    from app.cli import registrar_comandos
    registrar_comandos(app)

    if nombre_config == "prod":
        from app import produccion
        for aviso in produccion.comprobar(app):       # (si falta algo grave, no arranca y lo dice)
            app.logger.warning("Configuración: %s", aviso)
        produccion.detras_de_proxy(app, app.config["NUM_PROXIES"])

    return app


def _registrar_seguridad(app):
    from flask import Response

    @app.after_request
    def cabeceras(respuesta):
        # Que ningún buscador indexe la plataforma (es privada, con login)
        respuesta.headers.setdefault("X-Robots-Tag", "noindex, nofollow")
        # Que otra web no pueda meter la plataforma dentro de un iframe (clickjacking)
        respuesta.headers.setdefault("X-Frame-Options", "DENY")
        respuesta.headers.setdefault("X-Content-Type-Options", "nosniff")
        return respuesta

    @app.route("/salud")
    def salud():
        """Para comprobar desde fuera que la plataforma responde y llega a la base de datos
        (monitorización, o un curl tras actualizar). No enseña ningún dato."""
        db.session.execute(db.text("SELECT 1"))
        return Response("ok\n", mimetype="text/plain", headers={"Cache-Control": "no-store"})

    @app.route("/robots.txt")
    def robots():
        return Response("User-agent: *\nDisallow: /\n", mimetype="text/plain")


def _registrar_contexto(app):
    from flask_login import current_user

    # Disponible también dentro de las macros de _macros.html
    app.jinja_env.globals["current_user"] = current_user
    # Año actual para el pie de página (función: así cambia solo el 1 de enero)
    from datetime import date
    app.jinja_env.globals["anio_actual"] = lambda: date.today().year
    app.jinja_env.globals["hoy_fecha"] = date.today
    # Idioma: el actual (para <html lang> y el selector) y la lista de disponibles
    from flask_babel import get_locale
    from app.idioma import IDIOMAS
    app.jinja_env.globals["idioma_actual"] = lambda: str(get_locale() or "es")
    app.jinja_env.globals["IDIOMAS"] = IDIOMAS

    def args_url(**cambios):
        """Los filtros de la URL actual (?estado=...&q=...), listos para url_for().
        Se descartan los nombres que url_for trata de forma especial ('endpoint',
        '_external', '_scheme'...): si alguien los mete a mano en la URL darían error 500."""
        from flask import request
        args = {k: v for k, v in request.args.items() if k != "endpoint" and not k.startswith("_")}
        args.update(cambios)
        return args
    app.jinja_env.globals["args_url"] = args_url

    # Archivos estáticos con versión: url_for('static', filename='js/pedido.js') → /static/js/pedido.js?v=1760430000
    # (la fecha del archivo). nginx deja que el navegador los guarde 7 días; con esto, cuando un archivo
    # cambia (una actualización), su dirección cambia y el navegador descarga el nuevo sin Ctrl+F5.
    @app.url_defaults
    def _version_de_estaticos(endpoint, valores):
        if endpoint == "static" and "filename" in valores and "v" not in valores:
            try:
                valores["v"] = int(os.stat(os.path.join(app.static_folder, valores["filename"])).st_mtime)
            except (OSError, TypeError):
                pass
    from app.utils import TAMANOS_DE_PAGINA
    app.jinja_env.globals["tamanos_de_pagina"] = TAMANOS_DE_PAGINA     # (10, 25, 50): pie de las listas
    from app.models import ICONOS_ESTADO
    app.jinja_env.globals["iconos_estado"] = ICONOS_ESTADO
    from app.navegacion import menu_lateral
    app.jinja_env.globals["menu_lateral"] = menu_lateral      # secciones del menú lateral

    from app import mantenimiento
    mantenimiento.registrar(app)              # modo mantenimiento: solo entra admin

    @app.before_request
    def _idioma_de_esta_peticion():
        # Flask-Babel recuerda el idioma en `g`. En producción cada petición tiene su `g`,
        # pero en los tests (y si algún día se reutiliza el contexto) se arrastraría el de
        # la petición anterior: así se vuelve a calcular siempre.
        from flask_babel import refresh
        refresh()

    # El nombre visible del rol "fas" para las plantillas: {{ rol_fas }} (ver app/permisos.py)
    from app.permisos import NOMBRE_FAS
    app.jinja_env.globals["rol_fas"] = NOMBRE_FAS

    @app.context_processor
    def avisos():
        """Contadores para el menú: lo que requiere tu atención ahora mismo."""
        if not current_user.is_authenticated:
            return {}
        from app.alcance import filtrar_pedidos
        from app.models import Pedido

        def contar(estado):
            return db.session.scalar(filtrar_pedidos(
                db.select(db.func.count(Pedido.id)).filter_by(estado=estado)))

        extra = {}
        # Para la ventana emergente "Nuevo pedido" (el formulario se crea solo si la plantilla la usa)
        if current_user.rol == "cliente" and current_user.empresa:
            from app.pedidos.forms import PedidoClienteForm, con_ids_propios
            extra["nuevo_pedido_form"] = lambda: con_ids_propios(PedidoClienteForm(
                formdata=None, cliente_id=current_user.cliente_id), "modal")
        elif current_user.rol != "cliente" and current_user.puede("pedidos.crear"):
            from app.pedidos.forms import PedidoInternoForm, con_ids_propios
            extra["nuevo_pedido_form"] = lambda: con_ids_propios(PedidoInternoForm(formdata=None), "modal")

        avisos = {}
        if current_user.puede("mensajes.ver"):
            from app.mensajes.servicio import no_leidos_total
            if current_user.puede("mensajes.internos"):
                # Yikon: por separado lo que escribe el cliente y las notas internas entre compañeros
                avisos["mensajes"] = no_leidos_total(current_user, interno=False)
                avisos["internos"] = no_leidos_total(current_user, interno=True)
            else:
                avisos["mensajes"] = no_leidos_total(current_user)
                if current_user.rol == "cliente" and avisos["mensajes"]:
                    # El cliente: una línea por conversación con algo nuevo (la campana le lleva
                    # a ese pedido o a la conversación con su responsable)
                    from app.mensajes.servicio import avisos_del_cliente
                    extra["avisos_mensajes"] = avisos_del_cliente(current_user)
        if current_user.puede("pedidos.proforma.enviar"):
            # Yikon: proformas por preparar (nuevas o con cambios pedidos por el cliente)
            avisos["proformas"] = contar("proforma_solicitada") + contar("cambios_solicitados")
        if current_user.puede("pedidos.proforma.responder"):
            avisos["proformas"] = contar("proforma_enviada")        # cliente: proformas por responder
        if current_user.rol == "cliente":
            # ...y sus envíos por confirmar. La campana del cliente cuenta lo mismo que las líneas
            # con punto de "Tus pedidos en curso" (app/main/inicio_cliente.py) y lleva hasta ellas.
            avisos["recibir"] = contar("enviado")
        if current_user.puede("pedidos.fotos.subir"):
            # admin: devueltos por el FAS (en preparación con la última validación rechazada)
            en_prep = db.session.scalars(filtrar_pedidos(db.select(Pedido).filter_by(estado="en_preparacion"))).all()
            avisos["revisar"] = sum(1 for p in en_prep if p.devuelto)
            avisos["preparar"] = contar("aceptado") + len(en_prep)   # menú "Preparar" (móvil)
        if current_user.puede("pedidos.validar"):
            avisos["validar"] = contar("en_validacion")    # FAS: esperando su visto bueno
        if current_user.puede("facturas.revisar") or current_user.puede("facturas.editar"):
            # Facturas antes de llegar al cliente: por revisar (admin, FAS) y devueltas (admin, Logística)
            from app.alcance import filtrar_facturas
            from app.facturas.routes import FASES
            from app.models import Factura

            def facturas(fase):
                return db.session.scalar(filtrar_facturas(
                    db.select(db.func.count(Factura.id)).where(*FASES[fase])))
            if current_user.puede("facturas.revisar"):
                avisos["facturas_revisar"] = facturas("en_revision")
            if current_user.puede("facturas.editar"):
                avisos["facturas_devueltas"] = facturas("devueltas")
        if current_user.puede("pedidos.incidencias.resolver"):
            # Yikon: problemas que han avisado los clientes y siguen abiertos (una línea por cada uno)
            from app.incidencias import abiertas
            extra["avisos_incidencias"] = abiertas()
            avisos["incidencias"] = len(extra["avisos_incidencias"])
        if current_user.puede("soporte.ver"):
            # Soporte ChromGo: tickets con algo nuevo (mensajes del otro lado, notas de compañeros...)
            from app.soporte.servicio import tickets_con_novedades
            avisos["soporte"] = tickets_con_novedades(current_user)
        if current_user.puede("inventario.ver"):
            # Iconos de la barra superior (admin): stock bajo y lotes caducados o a punto de caducar
            from app.inventario.stock import articulos_con_stock_bajo, avisos_caducidad
            extra["aviso_stock"] = articulos_con_stock_bajo()   # kits cerrados y productos
            extra["aviso_caducidades"] = avisos_caducidad()
        return {"avisos": avisos, **extra}


def _registrar_filtros(app):
    @app.template_filter("euros")
    def euros(valor):
        if valor is None:
            return "—"
        from flask_babel import get_locale
        valor = Decimal(valor).quantize(Decimal("0.01"))
        if str(get_locale() or "es") == "en":
            return f"€{valor:,.2f}"                   # formato inglés: €1,234.56
        # Formato español: 1.234,56 €
        texto = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
        return f"{texto} €"

    @app.template_filter("euros_corto")
    def euros_corto(valor):
        """Para etiquetas de gráficos, donde no cabe la cifra entera: 12.345 € → 12,3k €."""
        from flask_babel import get_locale
        valor = Decimal(valor or 0)
        texto = f"{valor / 1000:.1f}k" if abs(valor) >= 1000 else f"{valor:.0f}"
        if str(get_locale() or "es") == "en":
            return f"€{texto}"
        return texto.replace(".", ",") + " €"

    @app.template_filter("fecha")
    def fecha(valor):
        return valor.strftime("%d/%m/%Y") if valor else "—"

    @app.template_filter("fecha_hora")
    def fecha_hora(valor, formato="%d/%m/%Y %H:%M"):
        """Fecha y hora en hora de Madrid (se guardan en UTC)."""
        from app.utils import hora_local
        return hora_local(valor).strftime(formato) if valor else "—"


def _configurar_logs(app):
    """
    Registro de errores en archivo (instance/logs/plataforma.log, rota a los 5 MB).
    En producción, además, cada error 500 se envía por email a ADMIN_EMAILS (si hay SMTP).
    """
    import logging
    from logging.handlers import RotatingFileHandler, SMTPHandler

    if app.testing:
        return
    carpeta = os.path.join(app.instance_path, "logs")
    os.makedirs(carpeta, exist_ok=True)
    archivo = RotatingFileHandler(os.path.join(carpeta, "plataforma.log"),
                                  maxBytes=5 * 1024 * 1024, backupCount=10, encoding="utf-8")
    archivo.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s"))
    archivo.setLevel(logging.INFO)
    app.logger.addHandler(archivo)
    app.logger.setLevel(logging.INFO)

    destinatarios = app.config.get("ADMIN_EMAILS") or []
    if not app.debug and app.config.get("MAIL_SERVER") and destinatarios:
        credenciales = None
        if app.config.get("MAIL_USERNAME"):
            credenciales = (app.config["MAIL_USERNAME"], app.config["MAIL_PASSWORD"])
        por_email = SMTPHandler(
            mailhost=(app.config["MAIL_SERVER"], app.config["MAIL_PORT"]),
            fromaddr=app.config["MAIL_FROM"], toaddrs=destinatarios,
            subject="[Plataforma Yikon] Error en producción", credentials=credenciales,
            secure=() if app.config.get("MAIL_USE_TLS") else None)
        por_email.setLevel(logging.ERROR)
        app.logger.addHandler(por_email)


def _registrar_errores(app):
    from flask_babel import gettext as _

    @app.errorhandler(403)
    def prohibido(e):
        return render_template("errors/error.html", codigo=403,
                               mensaje=_("No tienes permiso para ver esta página.")), 403

    @app.errorhandler(404)
    def no_encontrado(e):
        return render_template("errors/error.html", codigo=404,
                               mensaje=_("La página que buscas no existe.")), 404

    @app.errorhandler(500)
    def error_interno(e):
        from flask import request
        from flask_login import current_user
        db.session.rollback()
        quien = current_user.email if current_user.is_authenticated else "anónimo"
        original = getattr(e, "original_exception", e)
        app.logger.error("Error 500 en %s %s (usuario: %s)", request.method, request.path, quien,
                         exc_info=original)
        from app.estado import apuntar_error           # para Administración → Estado
        apuntar_error(f"{request.method} {request.path}", quien, original)
        return render_template("errors/error.html", codigo=500,
                               mensaje=_("Algo ha fallado. Inténtalo de nuevo.")), 500
