"""
Administración → Ajustes → Correos al cliente: cambiar el texto de cada aviso que reciben los
clientes, la firma con los datos de contacto y el logo. Solo admin (permiso "ajustes.editar").

La lógica (textos de fábrica, datos entre llaves, cómo se monta el correo) está en
app/correos_cliente.py; aquí solo están las páginas.
"""
import base64

from flask import Response, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_babel import force_locale, gettext as _
from flask_login import current_user
from flask_wtf import FlaskForm

from app import correos_cliente as cc
from app.admin.routes import bp
from app.extensions import db
from app.models import RegistroAuditoria
from app.permisos import requiere_permiso


def _idioma():
    idioma = request.values.get("idioma", "es")
    return idioma if idioma in cc.IDIOMAS else "es"


def _nombre(clave):
    return _("Firma y datos de contacto") if clave == cc.FIRMA else str(cc.CASOS[clave].nombre)


def _caso_o_404(clave):
    if clave != cc.FIRMA and clave not in cc.CASOS:
        abort(404)


def _auditar(detalle):
    db.session.add(RegistroAuditoria(usuario_id=current_user.id, accion="editar", entidad="Ajuste", detalle=detalle))


@bp.route("/ajustes/correos")
@requiere_permiso("ajustes.editar")
def ajustes_correos():
    """Lista de los correos al cliente, con lo que se ha cambiado en cada idioma, y el logo."""
    from app.avisos_cliente import TIPOS
    filas = [{"clave": clave, "caso": caso, "tipo": TIPOS.get(cc.TIPO_DE_CASO.get(clave)),
              "activado": cc.aviso_activado(clave), "idiomas": {i: cc.texto(clave, i)["cambiado"] for i in cc.IDIOMAS}}
             for clave, caso in cc.CASOS.items()]
    # Dos grupos: los avisos de los pedidos (cada usuario del cliente elige cuáles recibe, en la ficha
    # del cliente) y los de acceso a la plataforma (invitación y cambiar la contraseña: llegan siempre)
    grupos = [(_("Avisos de los pedidos"), [f for f in filas if f["clave"] not in cc.CASOS_ACCESO]),
              (_("Acceso a la plataforma (también al equipo de Yikon)"), [f for f in filas if f["clave"] in cc.CASOS_ACCESO])]
    firma = {i: cc.texto(cc.FIRMA, i)["cambiado"] for i in cc.IDIOMAS}
    return render_template("admin/ajustes_correos.html", title=_("Correos al cliente"), grupos=grupos, firma=firma,
                           con_logo=cc.con_logo(), logo_propio=bool(cc.logo_propio()), form=FlaskForm())


@bp.route("/ajustes/correos/<clave>", methods=["GET", "POST"])
@requiere_permiso("ajustes.editar")
def ajustes_correo(clave):
    """Editar un correo (o la firma) en un idioma: guardar, volver al original o enviarse una prueba."""
    _caso_o_404(clave)
    idioma = _idioma()
    form = FlaskForm()
    actual = cc.texto(clave, idioma)
    asunto, cuerpo, errores = actual["asunto"], actual["cuerpo"], []
    if form.validate_on_submit():
        accion = request.form.get("accion")
        asunto, cuerpo = request.form.get("asunto", ""), request.form.get("cuerpo", "")
        if accion == "original":
            cc.volver_al_original(clave, idioma)
            _auditar(f"correo al cliente «{_nombre(clave)}» ({idioma}): vuelve al texto original")
            db.session.commit()
            flash(_("Vuelve a salir el texto original."), "success")
            return redirect(url_for("admin.ajustes_correo", clave=clave, idioma=idioma))
        errores = cc.errores(clave, asunto, cuerpo)
        if not errores and accion == "prueba":
            _enviar_prueba(clave, idioma, asunto, cuerpo)
            flash(_("Prueba preparada para %(email)s, pendiente de revisar y enviar. (La plantilla aún no está guardada.)",
                    email=current_user.email), "info")
        elif not errores:
            cc.guardar(clave, idioma, asunto, cuerpo, current_user)
            _auditar(f"correo al cliente «{_nombre(clave)}» ({idioma})")
            db.session.commit()
            flash(_("Guardado. Los próximos correos saldrán con este texto."), "success")
            return redirect(url_for("admin.ajustes_correo", clave=clave, idioma=idioma))
    datos = [] if clave == cc.FIRMA else [(d, cc.DATOS[d]) for d in cc.CASOS[clave].datos]
    otros = {i: cc.texto(clave, i)["cambiado"] for i in cc.IDIOMAS}
    return render_template("admin/ajustes_correo.html", title=_nombre(clave), clave=clave, nombre=_nombre(clave),
                           caso=cc.CASOS.get(clave), idioma=idioma, idiomas=cc.IDIOMAS, otros=otros, actual=actual,
                           asunto=asunto, cuerpo=cuerpo, errores=errores, datos=datos, form=form,
                           vista=_vista_previa(clave, idioma, asunto, cuerpo))


@bp.route("/ajustes/correos/<clave>/vista-previa", methods=["POST"])
@requiere_permiso("ajustes.editar")
def ajustes_correo_vista_previa(clave):
    """La vista previa mientras se escribe (la pide el navegador; no guarda nada)."""
    _caso_o_404(clave)
    if not FlaskForm().validate_on_submit():
        abort(400)
    idioma = _idioma()
    asunto, cuerpo = request.form.get("asunto", ""), request.form.get("cuerpo", "")
    return jsonify(errores=cc.errores(clave, asunto, cuerpo), **_vista_previa(clave, idioma, asunto, cuerpo))


def _montar(clave, idioma, asunto, cuerpo, src_logo=None):
    """El correo con datos de ejemplo. Editando la firma, se ve debajo del correo «Enviado»."""
    with force_locale(idioma):
        if clave == cc.FIRMA:
            ejemplo = cc.texto("enviado", idioma)
            return cc.montar(ejemplo["asunto"], ejemplo["cuerpo"], cuerpo, cc.valores_de_ejemplo("enviado"), src_logo)
        return cc.montar(asunto, cuerpo, cc.texto(cc.FIRMA, idioma)["cuerpo"], cc.valores_de_ejemplo(clave), src_logo)


def _vista_previa(clave, idioma, asunto, cuerpo):
    # El logo va metido en la página (data:): la vista previa está en un iframe aislado (sandbox),
    # que no lleva la sesión y no podría pedirlo a la plataforma
    imagen = cc.logo()
    src = f"data:{imagen[1]}/{imagen[2]};base64," + base64.b64encode(imagen[0]).decode() if imagen else None
    compuesto = _montar(clave, idioma, asunto, cuerpo, src_logo=src)
    return {"asunto": compuesto["asunto"], "html": compuesto["html"]}


def _enviar_prueba(clave, idioma, asunto, cuerpo):
    from app.correo import _entregar, construir_compuesto
    compuesto = _montar(clave, idioma, asunto, cuerpo)
    compuesto["asunto"] = "[" + _("Prueba") + "] " + compuesto["asunto"]
    msg = construir_compuesto([current_user.email], compuesto)
    if msg is not None:
        msg.meta = {"tipo": "prueba"}
        _entregar(msg)


@bp.route("/ajustes/correos/logo.img")
@requiere_permiso("ajustes.editar")
def ajustes_correo_logo():
    """El logo de los correos, para verlo en estas páginas (aunque esté desactivado)."""
    imagen = cc.logo(aunque_este_desactivado=True)
    if imagen is None:
        abort(404)
    datos, tipo, subtipo = imagen
    return Response(datos, mimetype=f"{tipo}/{subtipo}", headers={"Cache-Control": "private, max-age=300"})


@bp.route("/ajustes/correos/logo", methods=["POST"])
@requiere_permiso("ajustes.editar")
def ajustes_correo_guardar_logo():
    """Con o sin logo, subir otro o volver al de la plataforma."""
    from app import archivos
    form = FlaskForm()
    if not form.validate_on_submit():
        abort(400)
    nuevo = None
    subido = request.files.get("logo")
    if subido and subido.filename:
        try:
            nuevo = archivos.leer_y_validar(subido, {"png", "jpg", "jpeg"}, limite_mb=1)
        except archivos.ArchivoNoValido as e:
            flash(str(e), "danger")
            return redirect(url_for("admin.ajustes_correos"))
        if not (nuevo[2].startswith(b"\x89PNG") or nuevo[2].startswith(b"\xff\xd8")):
            flash(_("Eso no parece una imagen PNG o JPG."), "danger")
            return redirect(url_for("admin.ajustes_correos"))
    activado = request.form.get("con_logo") == "1"
    sobra = cc.guardar_logo(activado, nuevo, quitar_propio=request.form.get("accion") == "quitar_propio")
    _auditar("correos al cliente: " + (("logo propio" if nuevo or cc.logo_propio() else "logo de la plataforma")
                                       if activado else "sin logo"))
    db.session.commit()
    if sobra:
        archivos.borrar(sobra)
    flash(_("Logo guardado."), "success")
    return redirect(url_for("admin.ajustes_correos"))


@bp.route("/ajustes/correos/avisos-activos", methods=["POST"])
@requiere_permiso("ajustes.editar")
def guardar_avisos_activos():
    if not FlaskForm().validate_on_submit():
        abort(400)
    activados = set(request.form.getlist("avisos"))
    if not activados.issubset(set(cc.CASOS) - set(cc.CASOS_ACCESO)):
        abort(400)
    cc.configurar_avisos(activados)
    _auditar("avisos por correo activados: " + ", ".join(sorted(activados)))
    db.session.commit()
    flash(_("Avisos actualizados. Los desactivados no se enviarán a ningún cliente."), "success")
    return redirect(url_for("admin.ajustes_correos"))
