"""
Administración → Estado de la plataforma: lo que habría que mirar por consola, de un vistazo.
Cada tarjeta devuelve {"estado": "ok" / "aviso" / "sin_datos", ...}. Todo es de solo lectura.
"""
import os
import shutil
from datetime import datetime, timedelta, timezone

from flask import current_app

from app.extensions import db
from app.models import CorreoEnviado, ErrorWeb, IntentoLogin, User, ahora

ARRANCADA = datetime.now(timezone.utc)        # cuándo arrancó este proceso de la plataforma
DIAS_SIN_COPIA = 2
DIAS_INACTIVO = 90


def apuntar_error(ruta, usuario, error):
    """Guarda un error 500 (en una transacción aparte: la de la petición se ha deshecho). Nunca falla."""
    from sqlalchemy.orm import Session as SesionAparte
    try:
        with SesionAparte(db.engine) as sesion:
            sesion.add(ErrorWeb(fecha=ahora(), ruta=ruta[:300], usuario=(usuario or "")[:150],
                                error=f"{type(error).__name__}: {error}"[:500]))
            sesion.execute(db.delete(ErrorWeb).where(ErrorWeb.fecha < ahora() - timedelta(days=90)))
            sesion.commit()
    except Exception:
        current_app.logger.exception("No se pudo apuntar el error en la base de datos")


def _con_zona(fecha):
    return fecha if fecha is None or fecha.tzinfo else fecha.replace(tzinfo=timezone.utc)


def copia():
    """La hora de la última copia: la deja el script del servidor en COPIA_SEGURIDAD_MARCA
    (el contenido, en formato 2026-10-09T03:00, o si no se entiende, la fecha del archivo)."""
    ruta = current_app.config.get("COPIA_SEGURIDAD_MARCA")
    if not ruta or not os.path.exists(ruta):
        return {"estado": "sin_datos"}
    try:
        with open(ruta, encoding="utf-8") as f:
            cuando = datetime.fromisoformat(f.read().strip())
    except (OSError, ValueError):
        cuando = datetime.fromtimestamp(os.path.getmtime(ruta))
    cuando = cuando if cuando.tzinfo else cuando.astimezone()
    vieja = datetime.now(timezone.utc) - cuando > timedelta(days=DIAS_SIN_COPIA)
    return {"estado": "aviso" if vieja else "ok", "cuando": cuando}


def correos():
    desde = ahora() - timedelta(days=7)
    cuenta = dict(db.session.execute(db.select(CorreoEnviado.estado, db.func.count(CorreoEnviado.id))
                                     .where(CorreoEnviado.fecha >= desde).group_by(CorreoEnviado.estado)).all())
    return {"estado": "aviso" if cuenta.get("fallido") else "ok",
            "enviados": cuenta.get("enviado", 0), "fallidos": cuenta.get("fallido", 0)}


def _tamano_carpeta(ruta):
    total = 0
    for raiz, _dirs, archivos in os.walk(ruta or ""):
        for a in archivos:
            try:
                total += os.path.getsize(os.path.join(raiz, a))
            except OSError:
                pass
    return total


def _tamano_base_de_datos():
    url = db.engine.url
    if url.get_backend_name() == "sqlite":
        return os.path.getsize(url.database) if url.database and os.path.exists(url.database) else None
    if url.get_backend_name() == "postgresql":
        return db.session.scalar(db.text("SELECT pg_database_size(current_database())"))
    return None


def espacio():
    cfg = current_app.config
    try:
        disco = shutil.disk_usage(cfg.get("DOCUMENTOS_FOLDER") or current_app.instance_path)
    except OSError:
        disco = None
    usado = disco.used / disco.total if disco else None
    return {"estado": "aviso" if usado is not None and usado > 0.85 else ("ok" if disco else "sin_datos"),
            "base_de_datos": _tamano_base_de_datos(), "fotos": _tamano_carpeta(cfg.get("UPLOAD_FOLDER")),
            "documentos": _tamano_carpeta(cfg.get("DOCUMENTOS_FOLDER")),
            "libre": disco.free if disco else None, "usado": usado}


def usuarios():
    sin_usar = db.session.scalar(db.select(db.func.count(User.id)).where(
        User.activo.is_(True), User.ultimo_acceso.is_(None)))
    inactivos = db.session.scalar(db.select(db.func.count(User.id)).where(
        User.activo.is_(True), User.ultimo_acceso < ahora() - timedelta(days=DIAS_INACTIVO)))
    fallidos = db.session.scalar(db.select(db.func.count(IntentoLogin.id)).where(
        IntentoLogin.exito.is_(False), IntentoLogin.fecha >= ahora() - timedelta(hours=24)))
    return {"estado": "aviso" if (sin_usar or inactivos) else "ok",
            "invitaciones": sin_usar, "inactivos": inactivos, "fallidos": fallidos}


def version():
    try:
        revision = db.session.scalar(db.text("SELECT version_num FROM alembic_version"))
    except Exception:
        db.session.rollback()
        revision = None
    return {"estado": "ok" if revision else "sin_datos", "revision": revision,
            "entorno": current_app.config.get("ENTORNO") or "producción", "arrancada": ARRANCADA}


def errores():
    desde = ahora() - timedelta(hours=24)
    ultimos = db.session.scalars(db.select(ErrorWeb).order_by(ErrorWeb.fecha.desc()).limit(5)).all()
    hoy = db.session.scalar(db.select(db.func.count(ErrorWeb.id)).where(ErrorWeb.fecha >= desde))
    return {"estado": "aviso" if hoy else "ok", "hoy": hoy, "ultimos": ultimos}


def todo():
    return {"copia": copia(), "correos": correos(), "espacio": espacio(), "usuarios": usuarios(),
            "version": version(), "errores": errores()}


def legible(bytes_):
    """1234567 → "1,2 MB" (None → "—")."""
    if bytes_ is None:
        return "—"
    for unidad in ("B", "KB", "MB", "GB", "TB"):
        if bytes_ < 1024 or unidad == "TB":
            texto = f"{bytes_:.0f}" if unidad == "B" else f"{bytes_:.1f}".replace(".", ",")
            return f"{texto} {unidad}"
        bytes_ /= 1024
