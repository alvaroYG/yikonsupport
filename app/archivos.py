"""
Archivos subidos que no son fotos: PDF de las facturas y adjuntos de los mensajes.
(Los documentos del pedido usan pedidos/documentos.py, con las mismas reglas.)

Mismas medidas de seguridad que los documentos del pedido:
- lista blanca de extensiones (nada ejecutable ni HTML);
- se guardan con nombre aleatorio en la carpeta privada DOCUMENTOS_FOLDER;
- solo se sirven desde vistas que comprueban permisos, SIEMPRE como descarga y con nosniff.

Se hace en dos pasos (leer y validar → escribir) para poder comprobar TODOS los archivos
de un envío antes de guardar nada: si el tercero no vale, no quedan los dos primeros sueltos.
"""
import os
import uuid

from flask import current_app, send_from_directory
from flask_babel import gettext as _

from app.pedidos.documentos import EXTENSIONES_PERMITIDAS, DocumentoNoValido, carpeta


class ArchivoNoValido(DocumentoNoValido):
    pass


def leer_y_validar(archivo, extensiones=EXTENSIONES_PERMITIDAS, firma=None, limite_mb=None):
    """Devuelve (nombre, extension, bytes) o lanza ArchivoNoValido con un mensaje claro.
    firma: bytes con los que debe empezar el archivo (p. ej. b"%PDF" para un PDF de verdad).
    limite_mb: tamaño máximo (por defecto MAX_DOCUMENTO_MB)."""
    nombre = os.path.basename((archivo.filename or "").replace("\\", "/")).strip()
    ext = nombre.rsplit(".", 1)[-1].lower() if "." in nombre else ""
    if ext not in extensiones:
        if extensiones == {"pdf"}:
            raise ArchivoNoValido(_("«%(nombre)s» no es un PDF.", nombre=nombre or _("archivo")))
        if extensiones == EXTENSIONES_PERMITIDAS:
            raise ArchivoNoValido(_("«%(nombre)s»: tipo no admitido. Usa PDF, Word, Excel, CSV, imagen o similar.",
                                    nombre=nombre or _("archivo")))
        raise ArchivoNoValido(_("«%(nombre)s»: tipo no admitido. Usa %(tipos)s.", nombre=nombre or _("archivo"),
                                tipos=", ".join(sorted(extensiones))))
    datos = archivo.read()
    if not datos:
        raise ArchivoNoValido(_("«%(nombre)s» está vacío.", nombre=nombre))
    limite = limite_mb or current_app.config["MAX_DOCUMENTO_MB"]
    if len(datos) > limite * 1024 * 1024:
        raise ArchivoNoValido(_("«%(nombre)s» pesa más de %(mb)s MB.", nombre=nombre, mb=limite))
    if firma and not datos.startswith(firma):
        raise ArchivoNoValido(_("«%(nombre)s» no es un PDF.", nombre=nombre))
    return nombre[:200], ext, datos


def escribir(datos, prefijo, ext) -> str:
    """Guarda los bytes con un nombre aleatorio y devuelve ese nombre (el que va a la base de datos)."""
    en_disco = f"{prefijo}_{uuid.uuid4().hex}.{ext}"
    with open(os.path.join(carpeta(), en_disco), "wb") as f:
        f.write(datos)
    return en_disco


def descargar(en_disco, nombre_original):
    """Respuesta de descarga segura (nunca se abre "dentro" de la web)."""
    respuesta = send_from_directory(carpeta(), en_disco, as_attachment=True, download_name=nombre_original)
    respuesta.headers["X-Content-Type-Options"] = "nosniff"
    respuesta.headers["Cache-Control"] = "private, no-store"
    return respuesta


def borrar(en_disco):
    if not en_disco:
        return
    try:
        os.remove(os.path.join(carpeta(), en_disco))
    except FileNotFoundError:
        pass


def tamano_legible(bytes_):
    kb = (bytes_ or 0) / 1024
    return f"{max(1, round(kb))} KB" if kb < 1024 else f"{kb / 1024:.1f} MB"
