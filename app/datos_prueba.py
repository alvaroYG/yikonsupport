"""
`flask datos-prueba`: la base de datos LOCAL con un caso de cada para probar la plataforma a mano.

Parte de los datos demo (`flask datos-demo`: usuarios, productos, kits, lotes, clientes) y añade
pedidos en todos los estados, facturas en todas sus fases y mensajes sin leer. Los pedidos se
crean usando la propia plataforma (como si alguien pulsara los botones, con un navegador de
pruebas), no escribiendo directamente en la base de datos: así pasan por las mismas reglas,
reservas de lotes, proformas y auditoría que los de verdad.

Cada pedido lleva en "Ref. empresa" qué caso es (p. ej. "PRUEBA · devuelto por Soporte"), para
encontrarlos rápido con el buscador. El guion de pruebas sigue estos mismos casos.

Dos maneras (solo en desarrollo):
  - flask datos-prueba                    → BORRA la base de datos y parte de los datos demo
  - flask datos-prueba --sobre-mis-datos  → no borra nada: añade los casos con TUS clientes y kits
    (crea los usuarios de prueba que falten, con contraseña demo123456, y algo de stock de prueba)
"""
import json
from datetime import date, timedelta
from io import BytesIO

from app.extensions import db
from app.proformas.pdf import generar_pdf_proforma
from app.proformas.servicio import modelo_previo
from app.models import Cliente, Factura, Kit, Lote, MovimientoInventario, Pedido, RegistroAuditoria, User, ahora

CONTRASENA = "demo123456"
PDF = b"%PDF-1.4\n% factura de prueba\n" + b"0" * 400
FOTO = b"\xff\xd8\xff\xe0" + b"\x00" * 400


class Navegador:
    """Un navegador de pruebas: entra como un usuario y pulsa botones (peticiones a la plataforma).
    Entra sin contraseña (pone el usuario en la sesión, como hace Flask-Login), así sirve también con
    tus usuarios, cuya contraseña no sabemos. Si algo no sale como debe, para con un error que dice
    qué paso ha fallado."""

    def __init__(self, app):
        self.cliente = app.test_client()
        self.usuario = None

    def como(self, usuario):
        if self.usuario != usuario.id:
            with self.cliente.session_transaction() as sesion:
                sesion.clear()
                sesion["_user_id"] = str(usuario.id)
                sesion["_fresh"] = True
            # Las peticiones de prueba comparten el contexto de la app del comando, y Flask-Login
            # guarda ahí el usuario cargado: hay que olvidarlo para que cargue el nuevo
            from flask import g
            g.pop("_login_user", None)
            self.usuario = usuario.id
        return self

    def post(self, url, paso, **datos):
        archivos = any(isinstance(v, tuple) for v in datos.values())
        r = self.cliente.post(url, data=datos, content_type="multipart/form-data" if archivos else None)
        if r.status_code not in (200, 302):
            raise RuntimeError(f"Falló «{paso}» ({url} → {r.status_code})")
        return r


def _contenido(kit, n=1):
    """El JSON del formulario de pedido (como lo arma pedido.js): n kits con sus productos estándar."""
    return json.dumps({"kits": [{"kit_id": kit.id, "cantidad": n, "productos": [
        {"producto_id": c.producto_id, "cantidad": c.cantidad * n} for c in kit.componentes_activos]}], "sueltos": []})


def _ultimo_pedido():
    return db.session.scalar(db.select(Pedido).order_by(Pedido.id.desc()))


def _envejecer(pedido, dias):
    """Como si lo apuntado de este pedido hubiera pasado hace `dias` días (para ver los retrasos)."""
    for r in db.session.scalars(db.select(RegistroAuditoria).filter_by(entidad="Pedido", entidad_id=pedido.id)):
        r.fecha = ahora() - timedelta(days=dias)
    pedido.fecha = date.today() - timedelta(days=dias)
    db.session.commit()


# --------------------------------------------------------------------------- #
# Quién hace de quién: tres clientes (A, B y C), cada uno con su usuario y su Soporte de cliente
# --------------------------------------------------------------------------- #
def _usuario(rol, nombre, email, **extra):
    """Un usuario de prueba nuevo (contraseña demo123456)."""
    if db.session.scalar(db.select(User).filter_by(email=email)):
        email = email.replace("@", f".{db.session.scalar(db.select(db.func.count(User.id)))}@")
    u = User(nombre=nombre, email=email, rol=rol, **extra)
    u.set_password(CONTRASENA)
    db.session.add(u)
    db.session.flush()
    return u


def _primero(select):
    return db.session.scalar(select.limit(1))


def reparto(avisar=print):
    """{"admin", "facturacion", "logistica" (Almacén), "clientes": [(cliente, su usuario, su Soporte), ×3], "kits": [kit, kit]}
    con lo que haya en la base de datos; lo que falte, se crea (y se avisa)."""
    activos = db.select(User).filter_by(activo=True).order_by(User.id)
    admin = _primero(activos.filter_by(rol="admin")) or _usuario("admin", "Admin de prueba", "prueba.admin@ejemplo.com")
    logistica = _primero(activos.filter_by(rol="logistica"))
    if logistica is None:
        logistica = _usuario("logistica", "Almacén de prueba", "prueba.almacen@ejemplo.com")
        avisar(f"    creado {logistica.email} (Almacén)")
    facturacion = _primero(activos.filter_by(rol="facturacion"))
    if facturacion is None:
        facturacion = _usuario("facturacion", "Facturación de prueba", "prueba.facturacion@ejemplo.com")
        avisar(f"    creado {facturacion.email} (Facturación)")
    clientes = db.session.scalars(db.select(Cliente).filter_by(activo=True).order_by(Cliente.id).limit(3)).all()
    if not clientes:
        raise RuntimeError("No hay ningún cliente activo: crea al menos uno (o usa flask datos-prueba sin --sobre-mis-datos)")
    trios = []
    for i in range(3):
        cliente = clientes[i % len(clientes)]
        usuario = _primero(activos.filter_by(rol="cliente", cliente_id=cliente.id))
        if usuario is None:
            usuario = _usuario("cliente", f"Usuario de prueba {cliente.nombre}",
                               f"prueba.{(cliente.prefijo or str(cliente.id)).lower()}@ejemplo.com", empresa=cliente)
            avisar(f"    creado {usuario.email} (cliente de {cliente.nombre})")
        fas = next((u for u in cliente.logisticos if u.activo), None)
        if fas is None:
            fas = _primero(activos.filter_by(rol="fas")) or _usuario("fas", "Soporte de prueba", "prueba.soporte@ejemplo.com")
            cliente.logisticos.append(fas)
            avisar(f"    {fas.nombre} pasa a llevar a {cliente.nombre} (no tenía Soporte de cliente)")
        trios.append((cliente, usuario, fas))
    kits = db.session.scalars(db.select(Kit).filter_by(activo=True).order_by(Kit.id).limit(2)).all()
    if not kits:
        raise RuntimeError("No hay ningún kit activo: crea al menos uno")
    db.session.commit()
    return {"admin": admin, "facturacion": facturacion, "logistica": logistica, "clientes": trios, "kits": kits if len(kits) == 2 else kits * 2}


def _lote_de_prueba(**articulo):
    """El lote "PRUEBA-…" de ese kit o producto: el que ya hay (si el comando ya se ejecutó antes) o uno nuevo."""
    clave = articulo.get("kit") or articulo.get("producto")
    codigo = f"PRUEBA-{clave.referencia}"[:60]
    filtro = {"kit_id": clave.id} if "kit" in articulo else {"producto_id": clave.id}
    return (db.session.scalar(db.select(Lote).filter_by(codigo=codigo, **filtro))
            or Lote(codigo=codigo, caducidad=date.today() + timedelta(days=400), **articulo))


def _mas_stock(kits):
    """Stock de prueba para que salgan todos los pedidos (lote "PRUEBA-…", caduca en 400 días).
    Si el comando ya se ejecutó antes, suma al mismo lote en vez de crear otro."""
    with db.session.no_autoflush:
        for kit in kits:
            if kit.cerrado:
                db.session.add(MovimientoInventario(kit=kit, lote=_lote_de_prueba(kit=kit), cantidad=40,
                                                    tipo="entrada", nota="Stock para las pruebas"))
            else:
                for c in kit.componentes_activos:
                    if c.producto.controlar_stock:
                        db.session.add(MovimientoInventario(producto=c.producto, lote=_lote_de_prueba(producto=c.producto),
                                                            cantidad=40 * c.cantidad, tipo="entrada",
                                                            nota="Stock para las pruebas"))
    db.session.commit()


def crear_escenarios(app, avisar=print):
    """Añade los casos de prueba a lo que haya en la base de datos. Devuelve [(caso, referencia), ...]."""
    nav = Navegador(app)
    r = reparto(avisar)
    admin, logistica, facturacion = r["admin"], r["logistica"], r["facturacion"]
    (cli_a, usu_a, fas_a), (cli_b, usu_b, fas_b), (cli_c, usu_c, fas_c) = r["clientes"]
    kit1, kit2 = r["kits"]
    usuario_de = {cli_a.id: usu_a, cli_b.id: usu_b, cli_c.id: usu_c}
    soporte_de = {cli_a.id: fas_a, cli_b.id: fas_b, cli_c.id: fas_c}
    casos = []
    _mas_stock({kit1, kit2})

    # Facturación: si un cliente no la tiene configurada, un formato, un IVA y un envío distintos en cada uno
    nav.como(admin)
    for cliente, formato, regimen, envio in [(cli_a, "B", "ue", "150"), (cli_b, "C", "export", ""), (cli_c, "A", "es", "")]:
        if not cliente.formato_factura:
            nav.post(f"/facturas/cliente/{cliente.id}/facturacion", "facturación del cliente",
                     formato_factura=formato, regimen_iva=regimen, gastos_envio=envio)

    # --- Los pasos de un pedido, como los haría cada persona ---
    def comprobar(p, estado, paso):
        db.session.refresh(p)
        if p.estado != estado:
            raise RuntimeError(f"«{paso}» no ha dejado {p.referencia_interna} en {estado} (está en {p.estado})")

    def pedir(cliente, caso, kit=kit2):
        antes = _ultimo_pedido()
        # La referencia del cliente no se puede repetir: si el comando ya se ejecutó, "(2)", "(3)"...
        referencia = f"PRUEBA · {caso}"
        ya = db.session.scalar(db.select(db.func.count(Pedido.id)).where(
            Pedido.cliente_id == cliente.id, Pedido.referencia.like(f"{referencia}%")))
        if ya:
            referencia += f" ({ya + 1})"
        nav.como(usuario_de[cliente.id])
        r = nav.post("/pedidos/nuevo", "el cliente hace un pedido", contenido=_contenido(kit),
                     fecha=date.today().isoformat(), referencia=referencia,
                     documento=(BytesIO(b"%PDF-1.4 orden de compra de prueba"), "orden_de_compra_prueba.pdf"))  # obligatorio
        p = _ultimo_pedido()
        if p is None or p is antes:
            import re
            errores = re.findall(r'(?:invalid-feedback[^>]*>|class="alert alert-[a-z]+[^>]*>|text-danger[^>]*>)\s*([^<]{3,300})',
                                 r.get_data(as_text=True))
            raise RuntimeError(f"«{caso}»: no se ha creado el pedido. La plataforma dice: {errores or r.status_code}")
        comprobar(p, "proforma_solicitada", "el cliente hace un pedido")
        casos.append((caso, p.referencia_interna))
        return p

    def proforma(p):
        # El PDF es obligatorio: de prueba adjuntamos el modelo que genera la propia plataforma
        valida = date.today() + timedelta(days=30)
        with app.test_request_context():         # (el PDF lleva enlaces: necesita una petición)
            pdf = generar_pdf_proforma(modelo_previo(p, valida, "5-7 días laborables"))
        nav.como(facturacion).post(f"/pedidos/{p.id}/proforma/enviar", "enviar la proforma",
                                 valida_hasta=valida.isoformat(), plazo_entrega="5-7 días laborables",
                                 pdf=(BytesIO(pdf), "Proforma.pdf"))
        comprobar(p, "proforma_enviada", "enviar la proforma")

    def aceptar(p):
        proforma(p)
        nav.como(usuario_de[p.cliente_id]).post(f"/pedidos/{p.id}/proforma/responder", "aceptar la proforma", aceptar="1")
        comprobar(p, "aceptado", "aceptar la proforma")

    def preparar(p):
        aceptar(p)
        nav.como(logistica).post(f"/pedidos/{p.id}/preparacion", "empezar la preparación")
        comprobar(p, "en_preparacion", "empezar la preparación")

    def a_validar(p):
        preparar(p)
        nav.post(f"/pedidos/{p.id}/fotos", "subir fotos", fotos=(BytesIO(FOTO), "caja.jpg"))
        nav.post(f"/pedidos/{p.id}/enviar-validacion", "enviar a validación")
        comprobar(p, "en_validacion", "enviar a validación")

    def validado(p):
        a_validar(p)
        nav.como(soporte_de[p.cliente_id]).post(f"/pedidos/{p.id}/validar", "validar las fotos", aprobar="1")
        comprobar(p, "validado", "validar las fotos")

    def enviado(p):
        validado(p)
        nav.como(logistica).post(f"/pedidos/{p.id}/estado", "marcar enviado", estado="enviado",
                                 transportista="DHL", numero_seguimiento="4471229018",
                                 fecha_entrega_estimada=(date.today() + timedelta(days=2)).isoformat(),
                                 confirmar_stock="1")
        comprobar(p, "enviado", "marcar enviado")

    def recibido(p):
        enviado(p)
        nav.como(usuario_de[p.cliente_id]).post(f"/pedidos/{p.id}/recibido", "marcar recibido")
        comprobar(p, "entregado", "marcar recibido")

    def factura(p, revisar):
        nav.como(facturacion)
        datos = {"numero": p.referencia_interna, "fecha_emision": date.today().isoformat(),
                 "fecha_vencimiento": (date.today() + timedelta(days=30)).isoformat(),
                 "pdf": (BytesIO(PDF), f"{p.referencia_interna}.pdf")}
        if revisar:
            datos["revisar"] = "y"
        nav.post(f"/facturas/pedido/{p.id}", "registrar la factura", **datos)
        f = db.session.scalar(db.select(Factura).filter_by(pedido_id=p.id))
        if f is None:
            raise RuntimeError(f"No se registró la factura de {p.referencia_interna}")
        return f

    # --- Pedidos en cada estado ---
    avisar("  pedidos en cada estado…")
    pedir(cli_a, "proforma pedida")
    proforma(pedir(cli_b, "proforma enviada, sin respuesta"))
    p = pedir(cli_c, "el cliente pide cambios")
    proforma(p)
    nav.como(usu_c).post(f"/pedidos/{p.id}/proforma/responder", "pedir cambios", cambios="1",
                         comentario="¿Podéis cambiar los índices por otros?")
    comprobar(p, "cambios_solicitados", "pedir cambios")
    aceptar(pedir(cli_a, "aceptado, sin empezar", kit=kit1))
    p = pedir(cli_b, "aceptado sin lote")
    aceptar(p)
    for reserva in list(p.reservas):           # como si al aceptarlo no hubiera habido stock
        db.session.delete(reserva)
    db.session.commit()
    preparar(pedir(cli_c, "en preparación"))
    p = pedir(cli_a, "devuelto por Soporte de cliente")
    a_validar(p)
    nav.como(fas_a).post(f"/pedidos/{p.id}/validar", "devolver", rechazar="1",
                         comentario="Falta la etiqueta del lote en la caja 2")
    comprobar(p, "en_preparacion", "devolver")
    a_validar(pedir(cli_b, "fotos por validar"))
    validado(pedir(cli_c, "listo para enviar"))
    enviado(pedir(cli_a, "enviado, por facturar", kit=kit1))
    recibido(pedir(cli_b, "recibido, por facturar"))
    p = pedir(cli_c, "cancelado")
    nav.como(admin).post(f"/pedidos/{p.id}/estado", "cancelar", estado="cancelado")
    comprobar(p, "cancelado", "cancelar")

    # --- Facturas en cada fase ---
    avisar("  facturas en cada fase…")
    p = pedir(cli_a, "factura en revisión")
    recibido(p)
    factura(p, revisar=True)
    p = pedir(cli_a, "factura devuelta por Soporte")
    recibido(p)
    f = factura(p, revisar=True)
    nav.como(fas_a).post(f"/facturas/{f.id}/devolver", "devolver la factura",
                         comentario="Falta el descuento del 10 % pactado en septiembre")
    p = pedir(cli_b, "factura aprobada, por enviar")
    recibido(p)
    f = factura(p, revisar=True)
    nav.como(fas_b).post(f"/facturas/{f.id}/aprobar", "aprobar la factura")
    p = pedir(cli_c, "factura enviada y pagada")
    recibido(p)
    f = factura(p, revisar=False)
    nav.como(facturacion).post(f"/facturas/{f.id}/enviada", "enviar la factura")
    nav.post(f"/facturas/{f.id}/pagada", "marcar pagada")
    p = pedir(cli_c, "factura vencida")
    recibido(p)
    f = factura(p, revisar=False)
    nav.como(facturacion).post(f"/facturas/{f.id}/enviada", "enviar la factura")
    f.fecha_emision, f.fecha_vencimiento = date.today() - timedelta(days=45), date.today() - timedelta(days=15)
    db.session.commit()

    # --- Mensajes sin leer ---
    avisar("  mensajes…")
    por_caso = {caso: ref for caso, ref in casos}

    def pedido_de(caso):
        return db.session.scalar(db.select(Pedido).filter_by(referencia_interna=por_caso[caso]))

    nav.como(usu_a).post(f"/mensajes/pedido/{pedido_de('aceptado, sin empezar').id}", "mensaje del cliente",
                         texto="Hola, ¿podéis adelantar el envío al lunes? Tenemos casos el martes.")
    nav.como(logistica).post(f"/mensajes/pedido/{pedido_de('en preparación').id}/interno", "nota interna",
                             texto=f"{fas_c.nombre}, ¿el cliente quería las cajas por separado?")
    nav.como(usu_c).post(f"/mensajes/cliente/{cli_c.id}", "conversación general",
                         texto="Buenos días, ¿tenéis ya las tarifas de 2027?")
    nav.como(fas_a).post(f"/mensajes/pedido/{pedido_de('enviado, por facturar').id}", "mensaje al cliente",
                         texto="Os lo hemos enviado hoy con DHL. Nº de seguimiento: 4471229018.")

    # --- Que se vea el paso del tiempo: retrasos ---
    for caso, dias in [("proforma enviada, sin respuesta", 12), ("aceptado, sin empezar", 6), ("listo para enviar", 4)]:
        _envejecer(pedido_de(caso), dias)
    return casos


def quien_es_quien():
    """Para el final del comando: con qué usuario hace cada papel (los de reparto())."""
    r = reparto(avisar=lambda _t: None)
    lineas = [f"  admin:      {r['admin'].nombre} <{r['admin'].email}>",
              f"  facturación: {r['facturacion'].nombre} <{r['facturacion'].email}>",
              f"  almacén:    {r['logistica'].nombre} <{r['logistica'].email}>"]
    for letra, (cliente, usuario, fas) in zip("ABC", r["clientes"]):
        lineas.append(f"  cliente {letra}:  {cliente.nombre} → {usuario.nombre} <{usuario.email}>; "
                      f"su Soporte: {fas.nombre}")
    return lineas
