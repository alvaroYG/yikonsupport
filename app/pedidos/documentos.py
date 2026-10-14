"""
Documentos adjuntos a los pedidos (orden de compra del cliente, albaranes...).

Seguridad:
- Lista blanca de extensiones: solo documentos habituales. Nada ejecutable ni HTML
  (un .html subido y abierto desde nuestro dominio podría ejecutar código en la sesión
  de quien lo abra).
- Se guardan con nombre aleatorio en una carpeta privada y SIEMPRE se descargan como
  adjunto (no se abren "dentro" de la web), con cabecera nosniff.
- Solo se sirven a través de una vista que comprueba permisos y alcance.
"""
import os
import uuid

from flask import current_app
from flask_babel import gettext as _
from flask_login import current_user

from app.models import DocumentoPedido

EXTENSIONES_PERMITIDAS = {
    "pdf", "doc", "docx", "xls", "xlsx", "csv", "odt", "ods", "rtf", "txt",
    "jpg", "jpeg", "png", "eml", "msg", "zip",
}


class DocumentoNoValido(ValueError):
    pass


def carpeta():
    ruta = current_app.config["DOCUMENTOS_FOLDER"]
    os.makedirs(ruta, exist_ok=True)
    return ruta


def guardar_documento(archivo, pedido) -> DocumentoPedido:
    nombre = (archivo.filename or "").strip()
    ext = nombre.rsplit(".", 1)[-1].lower() if "." in nombre else ""
    if ext not in EXTENSIONES_PERMITIDAS:
        raise DocumentoNoValido(
            _("«%(nombre)s»: tipo no admitido. Usa PDF, Word, Excel, CSV, imagen o similar.",
              nombre=nombre or _("archivo")))
    datos = archivo.read()
    if not datos:
        raise DocumentoNoValido(_("«%(nombre)s» está vacío.", nombre=nombre))
    limite = current_app.config["MAX_DOCUMENTO_MB"]
    if len(datos) > limite * 1024 * 1024:
        raise DocumentoNoValido(_("«%(nombre)s» pesa más de %(mb)s MB.", nombre=nombre, mb=limite))

    en_disco = f"pedido{pedido.id}_{uuid.uuid4().hex}.{ext}"
    with open(os.path.join(carpeta(), en_disco), "wb") as f:
        f.write(datos)
    return DocumentoPedido(pedido=pedido, archivo=en_disco, nombre_original=nombre[:200],
                           tamano=len(datos), subido_por_id=current_user.id)


def borrar_archivo(documento):
    try:
        os.remove(os.path.join(carpeta(), documento.archivo))
    except FileNotFoundError:
        pass
