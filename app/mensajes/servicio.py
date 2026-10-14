"""
Lógica de los mensajes: enviar, marcar como leído, contar los no leídos y avisar por email.

Las vistas (routes.py) solo llaman a estas funciones. Así la ficha del pedido y la
página de Mensajes usan exactamente las mismas reglas.

"No leído" = un mensaje del OTRO lado (para Yikon, los que escribe el cliente; para el
cliente, los que escribe Yikon) posterior al último que ese usuario vio en esa conversación.
Lo que escribe un compañero de tu mismo lado no cuenta como pendiente.
En las conversaciones INTERNAS (Yikon: admin, logística y FAS) todos son del mismo lado: ahí cuenta
como pendiente lo que ha escrito cualquier otra persona.
"""
from datetime import timedelta

from flask import current_app, has_request_context, request, url_for
from flask_babel import force_locale, gettext as _
from sqlalchemy import and_, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased, selectinload

from app import archivos
from app.alcance import filtrar_mensajes, mensaje_ya_visible
from app.correo import enviar_al_cliente_tras_guardar, enviar_tras_guardar
from app.extensions import db
from app.models import AdjuntoMensaje, LecturaHilo, Mensaje, User, ahora, hilo_de

MAX_TEXTO = 5000          # caracteres por mensaje
MAX_EN_PANTALLA = 300     # mensajes que se cargan al abrir una conversación (los más recientes)
MAX_ADJUNTOS = 5          # archivos por mensaje


def _es_cliente(usuario):
    return usuario.es_cliente


def _pendientes(usuario, *columnas, interno=None):
    """SELECT de los mensajes que este usuario (el conectado) tiene sin leer.
    interno=True/False: solo los de conversaciones internas / con el cliente."""
    lectura = aliased(LecturaHilo)
    select = (db.select(*columnas).select_from(Mensaje)
              .outerjoin(lectura, (lectura.hilo == Mensaje.hilo) & (lectura.usuario_id == usuario.id))
              .where(or_(and_(Mensaje.interno.is_(False), Mensaje.de_cliente.is_(not _es_cliente(usuario))),
                         and_(Mensaje.interno.is_(True), Mensaje.autor_id != usuario.id)))
              .where(Mensaje.id > db.func.coalesce(lectura.ultimo_mensaje_id, 0)))
    if interno is not None:
        select = select.where(Mensaje.interno.is_(interno))
    if usuario.creado:
        # A un usuario nuevo no le aparecen como pendientes las conversaciones de antes de existir
        select = select.where(Mensaje.fecha >= usuario.creado)
    return filtrar_mensajes(select)


def no_leidos_total(usuario, interno=None) -> int:
    return db.session.scalar(_pendientes(usuario, db.func.count(Mensaje.id), interno=interno)) or 0


def no_leidos_por_hilo(usuario, hilos=None) -> dict:
    """{"pedido-12": 3, "cliente-4": 1, ...} (solo los que tienen alguno)."""
    select = _pendientes(usuario, Mensaje.hilo, db.func.count(Mensaje.id)).group_by(Mensaje.hilo)
    if hilos is not None:
        if not hilos:
            return {}
        select = select.where(Mensaje.hilo.in_(list(hilos)))
    return dict(db.session.execute(select).all())


def mensajes_de(hilo, despues=0):
    """Los mensajes de una conversación, del más antiguo al más reciente. El cliente no ve los
    que Yikon aún puede deshacer."""
    from flask_login import current_user
    select = (db.select(Mensaje).filter_by(hilo=hilo).where(Mensaje.id > despues)
              .options(selectinload(Mensaje.autor), selectinload(Mensaje.adjuntos))
              .order_by(Mensaje.id.desc()).limit(MAX_EN_PANTALLA))
    if has_request_context() and current_user.is_authenticated:
        select = filtrar_mensajes(select)      # (el cliente: sin lo que aún se puede deshacer; Logística: lo compartido)
    return list(reversed(db.session.scalars(select).all()))


def _lectura(usuario_id, hilo):
    """La fila "hasta dónde ha leído" de este usuario en esta conversación; la crea si no existe.
    Si dos pestañas la crean a la vez, la segunda choca con la restricción UNIQUE: en ese
    caso se deshace solo ese intento (savepoint) y se usa la que creó la otra pestaña."""
    lectura = db.session.scalar(db.select(LecturaHilo).filter_by(usuario_id=usuario_id, hilo=hilo))
    if lectura is None:
        try:
            with db.session.begin_nested():
                lectura = LecturaHilo(usuario_id=usuario_id, hilo=hilo, ultimo_mensaje_id=0)
                db.session.add(lectura)
        except IntegrityError:
            lectura = db.session.scalar(db.select(LecturaHilo).filter_by(usuario_id=usuario_id, hilo=hilo))
    return lectura


def marcar_leido(usuario, hilo):
    """Apunta que el usuario ha visto hasta el último mensaje de la conversación (sin commit)."""
    ultimo = db.session.scalar(db.select(db.func.max(Mensaje.id)).filter_by(hilo=hilo))
    if not ultimo:
        return
    lectura = _lectura(usuario.id, hilo)
    if ultimo > lectura.ultimo_mensaje_id:
        lectura.ultimo_mensaje_id = ultimo
    lectura.avisado = False           # lo ha leído: el próximo mensaje vuelve a avisarle


def conversaciones(usuario, cliente_id=None, limite=200, interno=None):
    """
    Las conversaciones que ve el usuario, la de actividad más reciente primero:
    [{"hilo", "cliente", "pedido", "ultimo" (Mensaje), "total", "no_leidos"}]
    """
    resumen = filtrar_mensajes(
        db.select(Mensaje.hilo, db.func.max(Mensaje.id).label("ultimo_id"),
                  db.func.count(Mensaje.id).label("total")).group_by(Mensaje.hilo))
    if cliente_id:
        resumen = resumen.where(Mensaje.cliente_id == cliente_id)
    if interno is not None:
        resumen = resumen.where(Mensaje.interno.is_(interno))
    resumen = resumen.subquery()
    filas = db.session.execute(
        db.select(Mensaje, resumen.c.total).join(resumen, Mensaje.id == resumen.c.ultimo_id)
        .options(selectinload(Mensaje.cliente), selectinload(Mensaje.pedido), selectinload(Mensaje.autor),
                 selectinload(Mensaje.adjuntos))
        .order_by(Mensaje.id.desc()).limit(limite)).all()
    pendientes = no_leidos_por_hilo(usuario, [m.hilo for m, _t in filas])
    return [{"hilo": m.hilo, "cliente": m.cliente, "pedido": m.pedido, "ultimo": m, "total": total,
             "no_leidos": pendientes.get(m.hilo, 0), "interno": m.interno} for m, total in filas]


def leer_adjuntos(ficheros):
    """Comprueba TODOS los archivos antes de guardar nada. Devuelve [(nombre, ext, bytes)]
    o lanza archivos.ArchivoNoValido (con el motivo, para enseñarlo al usuario)."""
    ficheros = [f for f in ficheros if f and getattr(f, "filename", "")]
    if len(ficheros) > MAX_ADJUNTOS:
        raise archivos.ArchivoNoValido(_("Como máximo %(n)s archivos por mensaje.", n=MAX_ADJUNTOS))
    return [archivos.leer_y_validar(f) for f in ficheros]


def enviar(autor, cliente, texto, pedido=None, adjuntos=(), avisar=True, interno=False) -> Mensaje:
    """Guarda el mensaje (sin commit) y deja preparado el aviso por email a la otra parte.
    adjuntos: lo que devuelve leer_adjuntos() (ya comprobado).
    avisar=False: sin email (cuando quien llama ya manda su propio aviso, p. ej. "recibido")."""
    if interno and (pedido is None or _es_cliente(autor)):
        raise ValueError("Las conversaciones internas son de un pedido y solo para Yikon")
    mensaje = Mensaje(hilo=hilo_de(cliente.id, pedido.id if pedido else None, interno=interno), cliente=cliente,
                      pedido=pedido, autor=autor, de_cliente=_es_cliente(autor), texto=texto or "",
                      interno=interno)
    segundos = deshacer_segundos(mensaje)
    if segundos:
        mensaje.visible_desde = ahora() + timedelta(seconds=segundos)
    db.session.add(mensaje)
    db.session.flush()                         # para tener mensaje.id
    for nombre, ext, datos in adjuntos:
        db.session.add(AdjuntoMensaje(mensaje=mensaje, archivo=archivos.escribir(datos, f"mensaje{mensaje.id}", ext),
                                      nombre_original=nombre, tamano=len(datos)))
    marcar_leido(autor, mensaje.hilo)          # lo que escribes tú, lo has leído
    if avisar and segundos:
        programar_aviso(mensaje.id, segundos)  # el email, cuando ya no se pueda deshacer
    elif avisar:
        _avisar(mensaje)
    return mensaje


# --------------------------------------------------------------------------- #
# Deshacer: un mensaje de Yikon al cliente queda unos segundos sin enseñarse al cliente y sin
# email, por si era una nota interna escrita en el chat equivocado.
# --------------------------------------------------------------------------- #
def deshacer_segundos(mensaje) -> int:
    """Segundos para deshacer: solo lo que Yikon escribe al cliente (no lo interno ni lo del cliente)."""
    if mensaje.interno or mensaje.de_cliente:
        return 0
    return int(current_app.config.get("MENSAJES_DESHACER_SEGUNDOS", 0) or 0)


def se_puede_deshacer(mensaje, usuario) -> bool:
    return (mensaje.autor_id == usuario.id and mensaje.visible_desde is not None
            and _con_zona(mensaje.visible_desde) > ahora())


def _con_zona(momento):
    from datetime import timezone
    return momento if momento.tzinfo else momento.replace(tzinfo=timezone.utc)   # SQLite las devuelve sin zona


def deshacer(mensaje):
    """Borra el mensaje (y sus archivos) antes de que lo vea el cliente. Sin commit."""
    ficheros = [a.archivo for a in mensaje.adjuntos]
    for adjunto in mensaje.adjuntos:
        db.session.delete(adjunto)
    db.session.delete(mensaje)
    return ficheros                           # quien llama los borra tras el commit


def avisar_si_sigue(mensaje_id):
    """El email del mensaje, si nadie lo ha deshecho. Lo llama programar_aviso() pasado el plazo."""
    mensaje = db.session.get(Mensaje, mensaje_id)
    if mensaje is not None:
        _avisar(mensaje)
        db.session.commit()


def programar_aviso(mensaje_id, segundos):
    """Manda el email dentro de `segundos`, en segundo plano (un hilo que espera), con la misma
    dirección web que la petición actual para que los enlaces del email salgan bien."""
    import threading
    app = current_app._get_current_object()
    base = request.host_url if has_request_context() else None

    def tarea():
        with app.test_request_context(base_url=base or "http://localhost/"):
            try:
                avisar_si_sigue(mensaje_id)
            except Exception:                 # un email que falla no debe tumbar nada
                app.logger.exception("No se pudo avisar del mensaje %s", mensaje_id)
            finally:
                db.session.remove()

    temporizador = threading.Timer(segundos + 1, tarea)
    temporizador.daemon = True
    temporizador.start()


# --------------------------------------------------------------------------- #
# Aviso por email
# --------------------------------------------------------------------------- #
def _destinatarios(mensaje):
    """Quién debe enterarse: si escribe Yikon, los usuarios de la empresa cliente; si escribe el
    cliente, o es una nota interna, quien diga Ajustes → Avisos internos (de fábrica: su Soporte de
    cliente, o admin si no tiene; en las internas, admin y su Soporte de cliente)."""
    from app.avisos_internos import destinatarios      # (Ajustes → Avisos internos)
    if mensaje.interno:
        return destinatarios("nota_interna", mensaje.cliente)
    if mensaje.de_cliente:
        usuarios = destinatarios("mensaje_cliente", mensaje.cliente)
        if mensaje.pedido_id is None:      # la general es privada con su Soporte: Logística no
            usuarios = [u for u in usuarios if u.puede("mensajes.general")]
        return usuarios
    # Yikon escribe al cliente: sus usuarios con el aviso «Mensajes» marcado (ficha del cliente)
    from app.avisos_cliente import destinatarios as del_cliente
    return del_cliente(mensaje.cliente_id, "mensajes")


def _avisar(mensaje):
    por_idioma = {}
    for u in _destinatarios(mensaje):
        if u.id == mensaje.autor_id:
            continue
        # Un solo email hasta que entre a leer: si ya le avisamos y no lo ha leído, no
        # le mandamos otro por cada mensaje (evita llenarle el buzón)
        lectura = _lectura(u.id, mensaje.hilo)
        if lectura.avisado:
            continue
        lectura.avisado = True
        # (el cliente recibe el correo con el texto que admin puede cambiar: correos_cliente)
        por_idioma.setdefault((u.idioma or "es", u.es_cliente), []).append(u.email)
    if not mensaje.interno and not mensaje.de_cliente:
        # Emails en copia del cliente (sin usuario, ficha del cliente): como no pueden "leer" en la
        # plataforma, les llega un correo por cada mensaje de Yikon
        from app.ajustes import idioma_del_cliente
        from app.avisos_cliente import copias
        ya = {u.email for u in mensaje.cliente.usuarios}      # (los que ya tienen usuario van por su casilla)
        extra = [e for e in copias(mensaje.cliente_id, "mensajes") if e not in ya]
        if extra:
            por_idioma.setdefault((idioma_del_cliente(mensaje.cliente), True), []).extend(extra)
    if not por_idioma:
        return
    cliente, pedido, autor = mensaje.cliente, mensaje.pedido, mensaje.autor
    if pedido:
        enlace = url_for("pedidos.detalle", id=pedido.id, _external=True) + ("#interno" if mensaje.interno else "#mensajes")
    else:
        enlace = url_for("mensajes.conversacion", cliente_id=cliente.id, _external=True)
    for (idioma, es_cliente), emails in por_idioma.items():
        with force_locale(idioma):
            quien = (f"{autor.nombre} ({cliente.nombre})" if mensaje.de_cliente
                     else f"{autor.nombre} (Yikon Genomics)")
            if pedido and mensaje.interno:
                sobre = _("el pedido %(ref)s (conversación interna)", ref=pedido.referencia_interna or f"#{pedido.id}")
            elif pedido:
                sobre = _("el pedido %(ref)s", ref=pedido.referencia_interna or f"#{pedido.id}")
            else:
                sobre = _("la conversación general de %(cliente)s", cliente=cliente.nombre)
            if es_cliente:
                adjuntos = "\n".join(f"  - {a.nombre_original}" for a in mensaje.adjuntos)
                enviar_al_cliente_tras_guardar(emails, "mensaje_nuevo", idioma, {
                    "quien": quien, "sobre": sobre, "texto": mensaje.texto, "adjuntos": adjuntos,
                    "enlace": enlace, "cliente": cliente.nombre},
                    {"revision_autor_id": autor.id, "revision_equipo": not mensaje.de_cliente, "cliente_id": cliente.id, "pedido_id": pedido.id if pedido else None})
                continue
            enviar_tras_guardar(emails, _("Nuevo mensaje sobre %(sobre)s", sobre=sobre), "mensaje_nuevo",
                                meta={"tipo": "interno.nota_interna" if mensaje.interno else "interno.mensaje_cliente",
                                      "revision_autor_id": autor.id, "revision_equipo": not mensaje.de_cliente, "cliente_id": cliente.id, "pedido_id": pedido.id if pedido else None},
                                quien=quien, sobre=sobre, texto=mensaje.texto, enlace=enlace,
                                adjuntos=[a.nombre_original for a in mensaje.adjuntos])


def resumen_texto(mensaje, largo=90):
    """Primera parte del mensaje, en una línea, para las listas (o sus archivos, si no lleva texto)."""
    linea = " ".join((mensaje.texto or "").split())
    if not linea and mensaje.adjuntos:
        linea = "📎 " + ", ".join(a.nombre_original for a in mensaje.adjuntos)
    return linea if len(linea) <= largo else linea[:largo - 1].rstrip() + "…"



def avisos_del_cliente(usuario, limite=5) -> list:
    """Las conversaciones con mensajes sin leer de un cliente, para su campana:
    [{"titulo", "resumen", "url"}]. De un pedido → a ese pedido; la general → a su conversación."""
    avisos = []
    for c in conversaciones(usuario):
        if not c["no_leidos"]:
            continue
        ultimo = c["ultimo"]
        if c["pedido"]:
            titulo = _("Mensaje nuevo en %(ref)s", ref=c["pedido"].referencia_interna or f"#{c['pedido'].id}")
            url = url_for("pedidos.detalle", id=c["pedido"].id) + "#mensajes"
        else:
            titulo = _("Mensaje nuevo de %(nombre)s", nombre=ultimo.autor.nombre)
            url = url_for("mensajes.conversacion", cliente_id=c["cliente"].id)
        avisos.append({"titulo": titulo, "resumen": f"«{resumen_texto(ultimo, 60)}»", "url": url})
        if len(avisos) == limite:
            break
    return avisos
