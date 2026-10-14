"""
Documentos internos de Yikon: logos, plantillas, protocolos, fichas técnicas, formación...

- Los ve el equipo de Yikon (admin, logística, FAS y soporte). El cliente, NUNCA (permiso documentos.ver).
- Cada documento tiene versiones: al subir un archivo nuevo, el anterior se queda en el
  historial y se puede seguir descargando. Se descarga siempre la vigente (la última).
- Los archivos van a la carpeta privada DOCUMENTOS_FOLDER con nombre aleatorio (app/archivos.py),
  y solo se sirven desde aquí, comprobando el permiso.
"""
from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_from_directory, url_for
from flask_babel import gettext as _
from flask_login import current_user
from sqlalchemy import or_
from sqlalchemy.orm import selectinload

from app import archivos
from app.auditoria import registrar
from app.documentos.forms import DocumentoForm, EditarDocumentoForm, VersionForm
from app.extensions import db
from app.models import (CATEGORIAS_DOCUMENTO, ICONOS_CATEGORIA_DOCUMENTO, DocumentoInterno, VersionDocumento,
                        ahora)
from app.pedidos.documentos import EXTENSIONES_PERMITIDAS, carpeta
from app.permisos import requiere_permiso

bp = Blueprint("documentos", __name__)


@bp.before_request
def _solo_si_esta_activo():
    """Documentos internos en pausa (nadie los tiene activados en Ajustes → Qué ve cada rol): sus páginas no existen."""
    from app.permisos import documentos_activos
    if not documentos_activos():
        abort(404)

# Además de lo normal (PDF, Office, imágenes, ZIP...): formatos de diseño para los logos
# (SVG, AI, EPS, PSD), presentaciones, fuentes de la marca y vídeos cortos de formación.
EXTENSIONES_DOCUMENTO = EXTENSIONES_PERMITIDAS | {
    "svg", "ai", "eps", "psd", "gif", "webp", "tif", "tiff",
    "ppt", "pptx", "odp", "ttf", "otf", "woff", "woff2", "mp4",
}
# Las imágenes que se enseñan en miniatura: se comprueba que de verdad lo son al subirlas
FIRMAS_IMAGEN = {"png": (b"\x89PNG",), "jpg": (b"\xff\xd8",), "jpeg": (b"\xff\xd8",),
                 "gif": (b"GIF87a", b"GIF89a"), "webp": (b"RIFF",)}
TIPOS_IMAGEN = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "gif": "image/gif",
                "webp": "image/webp"}
# Icono de Font Awesome según el tipo de archivo
ICONOS_EXTENSION = {
    "pdf": "fa-file-pdf", "doc": "fa-file-word", "docx": "fa-file-word", "odt": "fa-file-word", "rtf": "fa-file-word",
    "xls": "fa-file-excel", "xlsx": "fa-file-excel", "ods": "fa-file-excel", "csv": "fa-file-csv",
    "ppt": "fa-file-powerpoint", "pptx": "fa-file-powerpoint", "odp": "fa-file-powerpoint",
    "zip": "fa-file-archive", "mp4": "fa-file-video", "txt": "fa-file-alt",
    "svg": "fa-bezier-curve", "ai": "fa-bezier-curve", "eps": "fa-bezier-curve", "psd": "fa-file-image",
    "ttf": "fa-font", "otf": "fa-font", "woff": "fa-font", "woff2": "fa-font",
}


def _icono(ext):
    return ICONOS_EXTENSION.get(ext, "fa-file-image" if ext in TIPOS_IMAGEN or ext in ("tif", "tiff") else "fa-file")


@bp.record_once
def _ayudantes(estado):
    estado.app.jinja_env.globals["icono_archivo"] = _icono


def _leer_archivo(campo):
    """(nombre, ext, bytes) ya comprobados, o lanza archivos.ArchivoNoValido."""
    f = campo.data
    if not f or not getattr(f, "filename", ""):
        raise archivos.ArchivoNoValido(_("Elige un archivo."))
    nombre, ext, datos = archivos.leer_y_validar(f, EXTENSIONES_DOCUMENTO,
                                                limite_mb=current_app.config["MAX_DOCUMENTO_INTERNO_MB"])
    if ext in FIRMAS_IMAGEN and (not datos.startswith(FIRMAS_IMAGEN[ext]) or (ext == "webp" and datos[8:12] != b"WEBP")):
        raise archivos.ArchivoNoValido(_("«%(nombre)s» no es una imagen %(ext)s válida.", nombre=nombre, ext=ext.upper()))
    return nombre, ext, datos


def _nueva_version(documento, nombre, ext, datos, nota=None):
    numero = (documento.vigente.numero if documento.vigente else 0) + 1
    version = VersionDocumento(documento=documento, numero=numero, nombre_original=nombre, extension=ext,
                               tamano=len(datos), nota=nota or None, subido_por=current_user,
                               archivo=archivos.escribir(datos, "interno", ext))
    documento.actualizado = ahora()
    db.session.add(version)
    return version


@bp.route("/")
@requiere_permiso("documentos.ver")
def lista():
    return _pagina_lista()


def _pagina_lista(form=None, abrir_modal=False):
    carpeta_actual = request.args.get("carpeta") or None
    if carpeta_actual not in CATEGORIAS_DOCUMENTO:
        carpeta_actual = None
    q = (request.args.get("q") or "").strip()[:100]
    select = db.select(DocumentoInterno).options(selectinload(DocumentoInterno.versiones)
                                                 .selectinload(VersionDocumento.subido_por))
    if carpeta_actual:
        select = select.filter_by(categoria=carpeta_actual)
    if q:
        patron = f"%{q}%"
        select = select.where(or_(DocumentoInterno.titulo.ilike(patron), DocumentoInterno.descripcion.ilike(patron),
                                  DocumentoInterno.versiones.any(VersionDocumento.nombre_original.ilike(patron))))
    documentos = db.session.scalars(select.order_by(DocumentoInterno.categoria, DocumentoInterno.titulo)).all()
    cuentas = dict(db.session.execute(db.select(DocumentoInterno.categoria, db.func.count(DocumentoInterno.id))
                                      .group_by(DocumentoInterno.categoria)).all())
    if form is None and current_user.puede("documentos.subir"):
        form = DocumentoForm(formdata=None, categoria=carpeta_actual or "marca")
    return render_template("documentos/lista.html", title=_("Documentos internos"), documentos=documentos,
                           carpetas=CATEGORIAS_DOCUMENTO, iconos=ICONOS_CATEGORIA_DOCUMENTO, cuentas=cuentas,
                           carpeta=carpeta_actual, q=q, form=form, abrir_modal=abrir_modal)


@bp.route("/nuevo", methods=["POST"])
@requiere_permiso("documentos.subir")
def nuevo():
    form = DocumentoForm()
    if form.validate_on_submit():
        try:
            nombre, ext, datos = _leer_archivo(form.archivo)
        except archivos.ArchivoNoValido as e:
            form.archivo.errors = [str(e)]
        else:
            documento = DocumentoInterno(categoria=form.categoria.data, titulo=form.titulo.data.strip(),
                                         descripcion=(form.descripcion.data or "").strip() or None)
            db.session.add(documento)
            _nueva_version(documento, nombre, ext, datos)
            db.session.flush()
            registrar("crear", documento, f"{documento.titulo} ({nombre})")
            db.session.commit()
            flash(_("Documento «%(titulo)s» subido.", titulo=documento.titulo), "success")
            return redirect(url_for("documentos.lista", carpeta=documento.categoria))
    # Con errores: la lista con la ventana abierta y lo que había escrito
    return _pagina_lista(form, abrir_modal=True), 400


def _documento_o_404(id):
    return db.get_or_404(DocumentoInterno, id)


@bp.route("/<int:id>")
@requiere_permiso("documentos.ver")
def detalle(id, editar_form=None, version_form=None):
    documento = _documento_o_404(id)
    puede_subir = current_user.puede("documentos.subir")
    if puede_subir:
        editar_form = editar_form or EditarDocumentoForm(formdata=None, obj=documento)
        version_form = version_form or VersionForm(formdata=None)
    return render_template("documentos/detalle.html", title=documento.titulo, documento=documento,
                           editar_form=editar_form, version_form=version_form,
                           iconos=ICONOS_CATEGORIA_DOCUMENTO)


@bp.route("/<int:id>/editar", methods=["POST"])
@requiere_permiso("documentos.subir")
def editar(id):
    documento = _documento_o_404(id)
    form = EditarDocumentoForm()
    if not form.validate_on_submit():
        return detalle(id, editar_form=form), 400
    antes = (documento.titulo, documento.categoria)
    documento.titulo = form.titulo.data.strip()
    documento.categoria = form.categoria.data
    documento.descripcion = (form.descripcion.data or "").strip() or None
    registrar("editar", documento, f"{antes} → {(documento.titulo, documento.categoria)}")
    db.session.commit()
    flash(_("Datos del documento guardados."), "success")
    return redirect(url_for("documentos.detalle", id=id))


@bp.route("/<int:id>/version", methods=["POST"])
@requiere_permiso("documentos.subir")
def subir_version(id):
    documento = _documento_o_404(id)
    form = VersionForm()
    if form.validate_on_submit():
        try:
            nombre, ext, datos = _leer_archivo(form.archivo)
        except archivos.ArchivoNoValido as e:
            form.archivo.errors = [str(e)]
        else:
            version = _nueva_version(documento, nombre, ext, datos, (form.nota.data or "").strip())
            registrar("editar", documento, f"versión {version.numero}: {nombre}")
            db.session.commit()
            flash(_("Versión %(n)s subida. La anterior queda en el historial.", n=version.numero), "success")
            return redirect(url_for("documentos.detalle", id=id))
    return detalle(id, version_form=form), 400


@bp.route("/<int:id>/borrar", methods=["POST"])
@requiere_permiso("documentos.borrar")
def borrar(id):
    documento = _documento_o_404(id)
    en_disco = [v.archivo for v in documento.versiones]
    registrar("borrar", documento, f"{documento.titulo} ({len(en_disco)} versiones)")
    categoria = documento.categoria
    db.session.delete(documento)
    db.session.commit()
    for a in en_disco:                       # los archivos, cuando ya está confirmado en la base de datos
        archivos.borrar(a)
    flash(_("Documento borrado."), "success")
    return redirect(url_for("documentos.lista", carpeta=categoria))


@bp.route("/archivo/<int:version_id>")
@requiere_permiso("documentos.ver")
def descargar(version_id):
    version = db.get_or_404(VersionDocumento, version_id)
    return archivos.descargar(version.archivo, version.nombre_original)


@bp.route("/archivo/<int:version_id>/vista")
@requiere_permiso("documentos.ver")
def vista(version_id):
    """Miniatura de las imágenes (PNG, JPG, GIF, WEBP) para ver los logos sin descargarlos.
    Solo esos tipos (comprobados al subir); SVG y demás se descargan siempre."""
    version = db.get_or_404(VersionDocumento, version_id)
    if not version.es_imagen:
        abort(404)
    respuesta = send_from_directory(carpeta(), version.archivo, mimetype=TIPOS_IMAGEN[version.extension])
    respuesta.headers["X-Content-Type-Options"] = "nosniff"
    respuesta.headers["Content-Security-Policy"] = "default-src 'none'"
    respuesta.headers["Cache-Control"] = "private, max-age=3600"
    return respuesta
