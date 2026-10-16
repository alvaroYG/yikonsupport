import secrets

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_babel import gettext as _
from flask_login import current_user

from app.admin.forms import UsuarioForm
from app.auditoria import registrar
from app.extensions import db
from app.models import RegistroAuditoria, User
from app.permisos import ROLES, chromgo_para_clientes, requiere_permiso, roles_disponibles, soporte_activo
from app.utils import paginar

bp = Blueprint("admin", __name__)


@bp.route("/usuarios")
@requiere_permiso("usuarios.gestionar")
def usuarios():
    """Lista con buscador y filtros (?q=&rol=&cliente_id=&estado=), paginada."""
    from app.models import Cliente
    q = request.args.get("q", "").strip()[:100]
    select = db.select(User).order_by(User.nombre)
    if q:
        patron = f"%{q}%"
        select = select.where(User.nombre.ilike(patron) | User.email.ilike(patron))
    rol = request.args.get("rol") or ""
    if rol in ROLES:
        select = select.filter_by(rol=rol)
    else:
        rol = ""
    # Empresa: sus usuarios (Cliente / Cliente ChromGo) y los FAS que la llevan
    cliente_id = request.args.get("cliente_id", type=int)
    if cliente_id:
        select = select.where((User.cliente_id == cliente_id)
                              | User.clientes_asignados.any(Cliente.id == cliente_id))
    # Estado: activos, desactivados o con la invitación pendiente (activos que aún no han entrado)
    estado = request.args.get("estado") or ""
    if estado == "activos":
        select = select.filter_by(activo=True)
    elif estado == "desactivados":
        select = select.filter_by(activo=False)
    elif estado == "inactivos":
        from datetime import timedelta
        from app.control_admin import numero
        from app.models import ahora
        select = select.where(User.activo.is_(True), User.ultimo_acceso < ahora() - timedelta(days=numero('inactivos')))
    elif estado == "pendientes":
        select = select.where(User.activo.is_(True), User.ultimo_acceso.is_(None))
    else:
        estado = ""
    clientes = db.session.scalars(db.select(Cliente).order_by(Cliente.nombre)).all()
    return render_template("admin/usuarios.html", title=_("Usuarios"), pagina=paginar(select), q=q, rol=rol,
                           cliente_id=cliente_id, estado=estado, roles=roles_disponibles(), clientes=clientes,
                           soporte_activo=soporte_activo(),
                           hay_filtros=bool(q or rol or cliente_id or estado))


@bp.route("/usuarios/nuevo", methods=["GET", "POST"])
@requiere_permiso("usuarios.gestionar")
def nuevo_usuario():
    form = UsuarioForm()
    if form.validate_on_submit():
        user = User(nombre=form.nombre.data, email=form.email.data,
                    rol=form.rol.data, activo=form.activo.data, idioma=form.idioma.data or None,
                    cliente_id=form.cliente_id.data or None,
                    acceso_chromgo=bool(chromgo_para_clientes() and form.acceso_chromgo.data and form.rol.data == "cliente"))
        # Sin contraseña: le ponemos una aleatoria que nadie conoce; la cambiará él
        # desde el enlace de la invitación
        user.set_password(form.password.data or secrets.token_urlsafe(32))
        db.session.add(user)
        db.session.flush()  # para tener user.id en la auditoría
        invitar = form.invitar.data and user.activo      # a un usuario desactivado no le serviría
        registrar("crear", user, f"rol={user.rol}" + (" · invitación preparada" if invitar else ""))
        if invitar:
            _invitar(user)
        db.session.commit()
        flash(_("Usuario %(email)s creado. La invitación está pendiente de revisar y enviar.", email=user.email)
              if invitar else _("Usuario %(email)s creado.", email=user.email), "success")
        return redirect(url_for("admin.usuarios"))
    return render_template("admin/usuario_form.html", title=_("Nuevo usuario"), form=form)


@bp.route("/usuarios/<int:id>", methods=["GET", "POST"])
@requiere_permiso("usuarios.gestionar")
def editar_usuario(id):
    user = db.get_or_404(User, id)
    form = UsuarioForm(obj=user, usuario=user)
    del form.invitar                     # al editar no se invita (hay un botón aparte)
    if request.method == "GET":
        form.cliente_id.data = user.cliente_id or 0
        form.idioma.data = user.idioma or ""
    if form.validate_on_submit():
        if user.id == current_user.id and (form.rol.data != "admin" or not form.activo.data):
            flash(_("No puedes quitarte el rol de admin ni desactivarte a ti mismo."), "danger")
            return redirect(url_for("admin.editar_usuario", id=id))
        detalle = f"rol {user.rol}→{form.rol.data}, activo {user.activo}→{form.activo.data}"
        user.nombre, user.email = form.nombre.data, form.email.data
        user.rol, user.activo = form.rol.data, form.activo.data
        user.cliente_id = form.cliente_id.data or None
        user.idioma = form.idioma.data or None
        # Con los tickets quitados a los clientes la casilla no sale en el formulario: no se toca lo
        # que hubiera guardado (si no, al editar a un cliente se le quitaría el acceso sin querer).
        if chromgo_para_clientes():
            if user.acceso_chromgo != (form.acceso_chromgo.data and user.rol == "cliente"):
                detalle += f", acceso ChromGo {user.acceso_chromgo}→{not user.acceso_chromgo}"
            user.acceso_chromgo = bool(form.acceso_chromgo.data and user.rol == "cliente")   # solo tiene sentido en Cliente
        if user.rol != "fas":
            user.clientes_asignados = []  # si deja de ser FAS, pierde sus clientes
        if form.password.data:
            user.set_password(form.password.data)
            detalle += ", contraseña restablecida"
        registrar("editar", user, detalle)
        db.session.commit()
        flash(_("Usuario actualizado."), "success")
        return redirect(url_for("admin.usuarios"))
    return render_template("admin/usuario_form.html", title=_("Editar %(nombre)s", nombre=user.nombre), form=form,
                           usuario=user)


def _invitar(user):
    from app.auth.routes import crear_token_invitacion
    from app.notificaciones import enviar_invitacion
    enlace = url_for("auth.invitacion", token=crear_token_invitacion(user), _external=True)
    from app import seguridad
    enviar_invitacion(user, enlace, seguridad.valor("invitacion_dias"), current_user.nombre)


@bp.route("/usuarios/<int:id>/invitar", methods=["POST"])
@requiere_permiso("usuarios.gestionar")
def reenviar_invitacion(id):
    """Para quien aún no ha entrado nunca: perdió el email, caducó el enlace..."""
    user = db.get_or_404(User, id)
    if user.activo and user.ultimo_acceso is None:
        _invitar(user)
        registrar("editar", user, "invitación reenviada")
        db.session.commit()
        flash(_("Invitación preparada para %(email)s. Revisa el correo antes de enviarlo.", email=user.email), "success")
    else:
        flash(_("No se envía: el usuario ya ha entrado alguna vez o está desactivado."), "warning")
    return redirect(url_for("admin.usuarios"))


@bp.route("/usuarios/<int:id>/ver-como", methods=["POST"])
@requiere_permiso("usuarios.ver_como")
def ver_como(id):
    """Ver la plataforma como este usuario, en solo lectura (app/ver_como.py). No vale con otro admin."""
    from app import ver_como as vc
    user = db.get_or_404(User, id)
    vc.comprobar_admin(user)
    vc.empezar(current_user._get_current_object(), user)
    return redirect(url_for("main.inicio"))          # (la franja de arriba ya dice a quién estás viendo)


@bp.route("/auditoria")
@requiere_permiso("auditoria.ver")
def auditoria():
    """Todo lo que ha pasado, con filtros (?tipo=&usuario_id=&accion=&q=) y el historial de un
    objeto concreto (?tipo=Pedido&id=23: lo que enlaza el icono de cada fila)."""
    from app import auditoria as aud
    from app.utils import limpiar_busqueda, paginar
    select = db.select(RegistroAuditoria).order_by(RegistroAuditoria.fecha.desc(), RegistroAuditoria.id.desc())
    tipo = request.args.get("tipo") or ""
    tipo = tipo if tipo in aud.TIPOS else ""
    objeto_id = request.args.get("id", type=int) if tipo else None
    usuario_id = request.args.get("usuario_id", type=int)
    accion = request.args.get("accion") or ""
    accion = accion if accion in aud.ACCIONES else ""
    q = limpiar_busqueda(request.args.get("q"), 100)
    if tipo:
        select = select.filter_by(entidad=tipo)
    if objeto_id:
        select = select.filter_by(entidad_id=objeto_id)
    if usuario_id:
        select = select.filter_by(usuario_id=usuario_id)
    if accion:
        select = select.filter_by(accion=accion)
    if q:
        patron = f"%{q}%"
        select = select.where(RegistroAuditoria.objeto.ilike(patron) | RegistroAuditoria.detalle.ilike(patron))
    from datetime import date, datetime, time, timedelta, timezone
    from zoneinfo import ZoneInfo
    desde, hasta = request.args.get('desde', ''), request.args.get('hasta', '')
    try:
        inicio = date.fromisoformat(desde) if desde else None
        fin = date.fromisoformat(hasta) if hasta else None
        if inicio and fin and inicio > fin:
            raise ValueError
    except ValueError:
        from flask import abort
        abort(400)
    if inicio:
        select = select.where(RegistroAuditoria.fecha >= datetime.combine(inicio, time.min, ZoneInfo('Europe/Madrid')).astimezone(timezone.utc))
    if fin:
        select = select.where(RegistroAuditoria.fecha < datetime.combine(fin + timedelta(days=1), time.min, ZoneInfo('Europe/Madrid')).astimezone(timezone.utc))
    if request.args.get('exportar') == '1':
        from flask import Response
        from app.excel import generar_excel, Columna, MIMETYPE_XLSX
        from app.utils import hora_local
        registros = db.session.scalars(select).all()
        filas = [[hora_local(r.fecha).strftime('%d/%m/%Y %H:%M'), r.usuario.nombre if r.usuario else '',
                  r.accion, r.objeto or r.entidad, r.detalle, r.valor_anterior, r.valor_nuevo] for r in registros]
        datos = generar_excel(_('Auditoría'), [Columna(x, 30) for x in
            (_('Fecha'), _('Usuario'), _('Acción'), _('Objeto'), _('Detalle'), _('Valor anterior'), _('Valor nuevo'))], filas)
        return Response(datos, mimetype=MIMETYPE_XLSX, headers={'Content-Disposition': 'attachment; filename="auditoria.xlsx"'})
    pagina = paginar(select)
    objetos = aud.describir(pagina.items)
    historial_de = None
    if objeto_id:                         # el nombre del objeto cuyo historial se está viendo
        primero = db.session.scalar(db.select(RegistroAuditoria).filter_by(entidad=tipo, entidad_id=objeto_id).limit(1))
        historial_de = aud.describir([primero])[primero.id] if primero else None
    # (en el desplegable, solo quien sale en la auditoría)
    usuarios = db.session.scalars(db.select(User).where(User.id.in_(
        db.select(RegistroAuditoria.usuario_id).distinct())).order_by(User.nombre)).all()
    return render_template("admin/auditoria.html", title=_("Auditoría"), pagina=pagina, objetos=objetos,
                           detalle_legible=aud.detalle_legible,
                           tipos=aud.TIPOS, acciones=aud.ACCIONES, usuarios=usuarios, tipo=tipo, objeto_id=objeto_id,
                           usuario_id=usuario_id, accion=accion, q=q, historial_de=historial_de,
                           desde=desde, hasta=hasta, hay_filtros=bool(tipo or usuario_id or accion or q or desde or hasta))


@bp.route("/ajustes", methods=["GET", "POST"])
@requiere_permiso("ajustes.editar")
def ajustes():
    """Los plazos de aviso: a partir de cuántos días un pedido se marca con el reloj en "Pendientes"."""
    from flask_wtf import FlaskForm

    from app import ajustes as ajustes_
    actuales = ajustes_.plazos()
    form = FlaskForm()                    # solo para el token CSRF: los campos son los de PLAZOS
    errores = {}
    if form.validate_on_submit():
        nuevos = {}
        for estado in ajustes_.PLAZOS:
            dias = request.form.get(f"plazo_{estado}", type=int)
            if dias is None or not 0 <= dias <= ajustes_.MAXIMO_DIAS:
                errores[estado] = _("Escribe un número de días entre 0 y %(max)s.", max=ajustes_.MAXIMO_DIAS)
            else:
                nuevos[estado] = dias
        if not errores:
            cambios = ajustes_.guardar_plazos(nuevos)
            if cambios:
                db.session.add(RegistroAuditoria(usuario_id=current_user.id, accion="editar", entidad="Ajuste",
                                                 detalle="plazos: " + ", ".join(cambios)))
                db.session.commit()
                flash(_("Plazos guardados."), "success")
            else:
                flash(_("No has cambiado nada."), "info")
            return redirect(url_for("admin.ajustes"))
        actuales = {e: request.form.get(f"plazo_{e}", "") for e in ajustes_.PLAZOS}
    from app import aviso_clientes, mantenimiento
    return render_template("admin/ajustes.html", title=_("Ajustes"), form=form, plazos=ajustes_.PLAZOS,
                           actuales=actuales, errores=errores, mantenimiento=mantenimiento.estado(),
                           aviso=aviso_clientes.datos(), estado_aviso=aviso_clientes.estado(),
                           max_aviso=aviso_clientes.MAX_TEXTO)


@bp.route("/ajustes/mantenimiento", methods=["POST"])
@requiere_permiso("ajustes.editar")
def ajustes_mantenimiento():
    from flask_wtf import FlaskForm

    from app import mantenimiento
    if FlaskForm().validate_on_submit():
        cambio = mantenimiento.guardar(request.form.get("activado") == "1", request.form.get("mensaje"))
        if cambio:
            db.session.add(RegistroAuditoria(usuario_id=current_user.id, accion="editar", entidad="Ajuste",
                                             objeto=_("Ajustes"), detalle=cambio))
        db.session.commit()
        activado, _mensaje = mantenimiento.estado()
        flash(_("Modo mantenimiento activado: solo entra admin.") if activado
              else _("Modo mantenimiento desactivado: ya entra todo el mundo."), "warning" if activado else "success")
    return redirect(url_for("admin.ajustes_panel", tema="sistema", seccion="mantenimiento") + "#mantenimiento")


# Las demás páginas de Ajustes van en sus propios archivos (mismo blueprint)
from app.admin import ajustes_apartados, ajustes_correos, ajustes_mas, correos_estado, panel  # noqa: E402,F401
