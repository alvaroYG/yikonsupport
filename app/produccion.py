"""
Lo que solo hace falta en producción (FLASK_CONFIG=prod). Lo llama create_app().

  - comprobar(app): que no falte nada importante en el .env. Mejor que no arranque y diga
    qué falta, a que arranque mal (p. ej. guardando los datos en un SQLite de pruebas).
  - detras_de_proxy(app, n): la aplicación no recibe las visitas directamente: las recibe
    nginx (que pone el HTTPS) y se las pasa. Sin esto, Flask creería que todas las visitas
    vienen de nginx (misma IP para todos: el límite de intentos de login bloquearía a todo
    el mundo a la vez) y que llegan por http (los enlaces de los emails saldrían con http://).
"""
from werkzeug.middleware.proxy_fix import ProxyFix


def comprobar(app):
    """Devuelve la lista de avisos (no impiden arrancar). Lo que SÍ lo impide lanza RuntimeError."""
    import os
    errores, avisos = [], []
    if not os.environ.get("DATABASE_URL"):
        errores.append("Falta DATABASE_URL (la base de datos PostgreSQL).")
    elif app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite"):
        avisos.append("DATABASE_URL es SQLite: en producción usa PostgreSQL.")
    if len(app.config.get("SECRET_KEY") or "") < 32:
        errores.append("SECRET_KEY es demasiado corta: genera una con "
                       "python -c \"import secrets; print(secrets.token_hex(32))\"")
    for clave in ("UPLOAD_FOLDER", "DOCUMENTOS_FOLDER"):
        if not os.environ.get(clave):
            avisos.append(f"{clave} no está definida: los archivos subidos irán a instance/. "
                          "Mejor una carpeta fuera del código, incluida en las copias de seguridad.")
    if not app.config.get("MAIL_SERVER"):
        avisos.append("Falta MAIL_SERVER: los emails NO se envían (se guardan en instance/correos/).")
    if "ejemplo.com" in (app.config.get("MAIL_FROM") or ""):
        avisos.append("MAIL_FROM sigue con la dirección de ejemplo.")
    if not app.config.get("ADMIN_EMAILS"):
        avisos.append("Falta ADMIN_EMAILS: nadie recibirá por email los errores de la plataforma.")
    if errores:
        raise RuntimeError("Configuración de producción incompleta (.env):\n  - " + "\n  - ".join(errores))
    return avisos


def detras_de_proxy(app, proxies=1):
    """Hace que Flask lea la IP real, el https y el dominio de las cabeceras X-Forwarded-*
    que pone nginx. `proxies` = cuántos hay delante (0 = ninguno: no se toca nada)."""
    if proxies > 0:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxies, x_proto=proxies, x_host=proxies)
    return app
