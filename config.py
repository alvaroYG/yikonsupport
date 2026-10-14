import os
from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))


class Config:
    # La clave secreta NUNCA va en el código: se lee del entorno (.env en desarrollo).
    SECRET_KEY = os.environ.get("SECRET_KEY")
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///" + os.path.join(BASE_DIR, "dev.db")
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Cookies de sesión más seguras
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    REMEMBER_COOKIE_HTTPONLY = True

    ELEMENTOS_POR_PAGINA = 10      # filas por página en todas las listas largas (se puede elegir 25 o 50)

    # Inventario: avisar de los lotes que caducan en los próximos N días
    DIAS_AVISO_CADUCIDAD = 7

    # Invitaciones a usuarios nuevos: días que vale el enlace para elegir contraseña
    INVITACION_DIAS = 7

    # Idiomas (Flask-Babel). Los catálogos están en app/translations/
    BABEL_DEFAULT_LOCALE = "es"
    # Las horas se guardan en UTC y se muestran en esta zona horaria
    ZONA_HORARIA = "Europe/Madrid"
    BABEL_TRANSLATION_DIRECTORIES = os.path.join(BASE_DIR, "app", "translations")

    # Fotos de los pedidos: carpeta PRIVADA (fuera de /static). En producción debe
    # ser un disco persistente incluido en las copias de seguridad.
    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER",
                                   os.path.join(BASE_DIR, "instance", "fotos_pedidos"))
    MAX_CONTENT_LENGTH = 80 * 1024 * 1024   # 80 MB por envío (varias fotos, 5 adjuntos de 15 MB, un documento de 40 MB...)
    MAX_FOTO_MB = 10                        # por foto
    DOCUMENTOS_FOLDER = os.environ.get("DOCUMENTOS_FOLDER",
                                       os.path.join(BASE_DIR, "instance", "documentos_pedidos"))
    MAX_DOCUMENTO_MB = 15
    MAX_DOCUMENTO_INTERNO_MB = 40           # documentos internos de Yikon (zips de logos, vídeos cortos...)

    # Tickets ChromGo y Documentos internos: hechos pero EN PAUSA. Se activan por rol desde la web
    # (Administración → Ajustes → Qué ve cada rol). Esto solo es cómo vienen de fábrica (0 = quitados
    # para todos); lo que marque admin en la web manda. Ver app/apartados.py.
    SOPORTE_CHROMGO = os.environ.get("SOPORTE_CHROMGO", "0") == "1"
    DOCUMENTOS_INTERNOS = os.environ.get("DOCUMENTOS_INTERNOS", "0") == "1"

    # Vendedor (bloque "Seller." del Excel de "Preparar factura"): una línea por fila
    VENDEDOR_FACTURA = [
        "YIKON GENOMICS, SOCIEDAD LIMITADA",
        "RONDA GENERAL MITRE, 49",
        "PLANTA 1, PUERTA 1, 08017",
        "BARCELONA, ESPAÑA",
        "CIF: B44777787",
    ]

    # Segundos para deshacer un mensaje de Yikon al cliente (el cliente no lo ve ni recibe el
    # email hasta entonces). 0 = sin deshacer.
    MENSAJES_DESHACER_SEGUNDOS = 10

    # Registro de correos enviados (Administración → Correos enviados): días que se guardan
    CORREOS_REGISTRO_DIAS = 183
    # Página de Estado: archivo que deja el script de copias de seguridad del servidor con la fecha de
    # la última copia (vacío = aún no configurado). Ver README, "Producción".
    COPIA_SEGURIDAD_MARCA = os.environ.get("COPIA_SEGURIDAD_MARCA", "")

    # Límite de intentos de login
    LOGIN_MAX_FALLOS_EMAIL = 5      # fallos seguidos con un mismo email...
    LOGIN_MAX_FALLOS_IP = 20        # ...o desde una misma IP...
    LOGIN_VENTANA_MINUTOS = 15      # ...dentro de esta ventana → bloqueo temporal
    PASSWORD_RESET_HORAS = 2        # validez del enlace de "he olvidado mi contraseña"
    SESION_INACTIVIDAD_HORAS = 8    # sin usar la plataforma este tiempo, se cierra la sesión (0 = nunca)
    # (INVITACION_DIAS, PASSWORD_RESET_HORAS, LOGIN_MAX_FALLOS_EMAIL, LOGIN_VENTANA_MINUTOS y
    #  SESION_INACTIVIDAD_HORAS son los valores de fábrica: admin los cambia en Ajustes → Seguridad)

    # Correo. Sin MAIL_SERVER, en desarrollo los emails se guardan como .eml en
    # instance/correos/ (los puedes abrir con Outlook/Thunderbird) en vez de enviarse.
    MAIL_SERVER = os.environ.get("MAIL_SERVER")
    MAIL_PORT = int(os.environ.get("MAIL_PORT", "587"))
    MAIL_USE_TLS = os.environ.get("MAIL_USE_TLS", "1") == "1"
    MAIL_USERNAME = os.environ.get("MAIL_USERNAME")
    MAIL_PASSWORD = os.environ.get("MAIL_PASSWORD")
    # Datos de la empresa que salen en la cabecera de las proformas. EMPRESA_DATOS admite
    # varias líneas separadas por "|" (p. ej. "C/ Ejemplo 1, Barcelona|CIF B00000000|info@...")
    EMPRESA_NOMBRE = os.environ.get("EMPRESA_NOMBRE", "Yikon Genomics España")
    EMPRESA_DATOS = os.environ.get("EMPRESA_DATOS", "")
    MAIL_FROM = os.environ.get("MAIL_FROM", "Yikon Genomics PO <no-responder@ejemplo.com>")
    # Si alguien responde a un aviso, la respuesta va aquí (un buzón que se lea). Vacío: al remitente.
    MAIL_REPLY_TO = os.environ.get("MAIL_REPLY_TO", "")
    ADMIN_EMAILS = [e.strip() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()]
    PASSWORD_HASH_METHOD = "scrypt"


class DevConfig(Config):
    DEBUG = True


class ProdConfig(Config):
    """Producción (FLASK_CONFIG=prod). Guía de instalación: DESPLIEGUE.md"""
    DEBUG = False
    SESSION_COOKIE_SECURE = True   # solo por HTTPS
    REMEMBER_COOKIE_SECURE = True
    PREFERRED_URL_SCHEME = "https"  # los enlaces de los emails salen con https://
    # Si PostgreSQL cierra una conexión que llevaba rato sin usarse, se abre otra sin dar error
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    # Cuántos proxies hay delante de la aplicación (nginx = 1). Con esto Flask se fía de las
    # cabeceras que pone nginx (IP real del visitante, https, dominio): ver app/produccion.py.
    # Si no hubiera ningún proxy delante, pon NUM_PROXIES=0 (si no, cualquiera podría falsear su IP).
    NUM_PROXIES = int(os.environ.get("NUM_PROXIES", "1"))


class TestConfig(Config):
    TESTING = True
    MENSAJES_DESHACER_SEGUNDOS = 0      # los tests de "deshacer" lo activan ellos (test_mensajes_deshacer.py)
    SECRET_KEY = "clave-solo-para-tests"
    # Por defecto, SQLite en memoria (rápido). Para pasar los tests contra PostgreSQL, como en
    # producción:  TEST_DATABASE_URL=postgresql+psycopg://usuario@localhost/pruebas python -m pytest
    # (una base de datos VACÍA y solo para esto: los tests crean y borran todas las tablas)
    SQLALCHEMY_DATABASE_URI = os.environ.get("TEST_DATABASE_URL", "sqlite:///:memory:")
    WTF_CSRF_ENABLED = False
    SOPORTE_CHROMGO = True          # los tests lo prueban activado (y test_soporte_en_pausa.py, apagado)
    DOCUMENTOS_INTERNOS = True      # igual (apagado: test_documentos_en_pausa.py)
    UPLOAD_FOLDER = os.path.join(__import__("tempfile").gettempdir(), "tests_fotos_pedidos")
    DOCUMENTOS_FOLDER = os.path.join(__import__("tempfile").gettempdir(), "tests_documentos_pedidos")
    MAIL_BACKEND = "memoria"        # los tests miran los emails en una lista, no se envía nada
    PASSWORD_HASH_METHOD = "pbkdf2:sha256:1000"  # rápido, SOLO para tests


configs = {"dev": DevConfig, "prod": ProdConfig, "test": TestConfig}
