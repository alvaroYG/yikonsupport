"""
Guardar y servir las fotos de preparación de los pedidos.

Seguridad:
- Nunca usamos el nombre que manda el navegador para guardar: generamos uno aleatorio.
- Comprobamos que el archivo ES una imagen mirando sus primeros bytes ("firma"),
  no solo la extensión (un .jpg podría ser cualquier cosa renombrada).
- La carpeta no es pública: solo se sirven a través de una vista con permisos.

No usamos Pillow (tiene DLL que el Windows de desarrollo bloquea): guardamos la
imagen tal cual y las miniaturas se hacen con CSS.
"""
import os
import uuid

from flask import current_app
from flask_babel import gettext as _
from flask_login import current_user

from app.models import FotoPedido

# firma (primeros bytes) → extensión
FIRMAS = {
    b"\xff\xd8\xff": "jpg",
    b"\x89PNG\r\n\x1a\n": "png",
}


class FotoNoValida(ValueError):
    pass


def _extension_por_firma(cabecera: bytes):
    for firma, ext in FIRMAS.items():
        if cabecera.startswith(firma):
            return ext
    if cabecera[:4] == b"RIFF" and cabecera[8:12] == b"WEBP":
        return "webp"
    return None


def carpeta():
    ruta = current_app.config["UPLOAD_FOLDER"]
    os.makedirs(ruta, exist_ok=True)
    return ruta


def guardar_foto(archivo, pedido) -> FotoPedido:
    """`archivo` es el FileStorage que llega del formulario. Lanza FotoNoValida si no sirve."""
    datos = archivo.read()
    if not datos:
        raise FotoNoValida(_("«%(nombre)s» está vacío.", nombre=archivo.filename))
    limite = current_app.config["MAX_FOTO_MB"] * 1024 * 1024
    if len(datos) > limite:
        raise FotoNoValida(_("«%(nombre)s» pesa más de %(mb)s MB.", nombre=archivo.filename,
                               mb=current_app.config["MAX_FOTO_MB"]))
    ext = _extension_por_firma(datos[:16])
    if ext is None:
        raise FotoNoValida(_("«%(nombre)s» no es una imagen JPG, PNG o WEBP.", nombre=archivo.filename))

    nombre = f"pedido{pedido.id}_{uuid.uuid4().hex}.{ext}"
    with open(os.path.join(carpeta(), nombre), "wb") as f:
        f.write(datos)
    return FotoPedido(pedido=pedido, archivo=nombre,
                      nombre_original=(archivo.filename or "")[:200],
                      subida_por_id=current_user.id)


def borrar_archivo(foto):
    try:
        os.remove(os.path.join(carpeta(), foto.archivo))
    except FileNotFoundError:
        pass
