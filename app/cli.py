import getpass
from datetime import date, timedelta
from decimal import Decimal

import click

from app.extensions import db
from app.models import Cliente, Factura, LineaPedido, Pedido, Producto, User, ahora


def registrar_comandos(app):

    @app.cli.command("crear-admin")
    @click.option("--email", prompt="Email del administrador")
    @click.option("--nombre", prompt="Nombre")
    def crear_admin(email, nombre):
        """Crea el primer usuario administrador."""
        email = email.strip().lower()
        if db.session.scalar(db.select(User).filter_by(email=email)):
            click.echo("Ya existe un usuario con ese email.")
            return
        password = getpass.getpass("Contraseña (mín. 10 caracteres): ")
        if len(password) < 10:
            click.echo("Demasiado corta.")
            return
        if password != getpass.getpass("Repite la contraseña: "):
            click.echo("No coinciden.")
            return
        user = User(email=email, nombre=nombre, rol="admin")
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        click.echo(f"Administrador {email} creado.")

    @app.cli.command("reiniciar-datos")
    @click.option("--si", is_flag=True, help="No preguntar (para scripts).")
    def reiniciar_datos(si):
        """Deja la plataforma a cero: borra clientes, usuarios (menos los admin), pedidos,
        proformas, facturas, productos, kits, inventario, mensajes, auditoría y los archivos
        subidos (fotos, documentos, PDFs, SDS). Los admin se quedan con su contraseña."""
        import os
        import shutil
        admins = db.session.scalars(db.select(User).filter_by(rol="admin")).all()
        if not admins:
            click.echo("No hay ningún admin: no borro nada (te quedarías sin poder entrar). "
                       "Crea uno antes con: flask crear-admin")
            return
        click.echo(f"Base de datos: {db.engine.url.render_as_string(hide_password=True)}")
        click.echo("Se conservan estos admin: " + ", ".join(u.email for u in admins))
        if not si and not click.confirm("Se borrará TODO lo demás y no se puede deshacer. ¿Seguro?"):
            click.echo("Cancelado: no se ha borrado nada.")
            return
        # Tablas de la más "hija" a la más "madre" (para no romper las claves ajenas: PostgreSQL
        # las comprueba siempre). Al llegar a "usuarios" se borran los que no son admin y los admin
        # se sueltan de su empresa; así, cuando después toca "clientes", ya nadie apunta a ellos.
        for tabla in reversed(db.metadata.sorted_tables):
            if tabla.name == "usuarios":
                db.session.execute(db.delete(User).where(User.rol != "admin"))
                db.session.execute(db.update(User).values(cliente_id=None))
                continue
            db.session.execute(tabla.delete())
        db.session.commit()
        # Archivos subidos: ya no los usa nadie
        for clave in ("UPLOAD_FOLDER", "DOCUMENTOS_FOLDER"):
            carpeta = app.config.get(clave)
            if carpeta and os.path.isdir(carpeta):
                for nombre in os.listdir(carpeta):
                    ruta = os.path.join(carpeta, nombre)
                    shutil.rmtree(ruta) if os.path.isdir(ruta) else os.remove(ruta)
        click.echo("Hecho: la plataforma está a cero (solo quedan los admin).")

    # ------------------------------------------------------------------ #
    # Borrar de verdad (app/limpieza.py). Siempre enseñan antes lo que van a borrar.
    # ------------------------------------------------------------------ #
    def _confirmar(borrado, si, palabra):
        click.echo("Se va a borrar (filas por tabla):\n" + borrado.resumen())
        if borrado.archivos:
            click.echo(f"  y {len(set(borrado.archivos))} archivo(s) del disco (fotos, documentos, PDFs, adjuntos).")
        click.echo(f"Base de datos: {db.engine.url.render_as_string(hide_password=True)}")
        click.echo("⚠ No se puede deshacer. ¿Tienes copia de seguridad? (DESPLIEGUE.md, «Copias de seguridad»)")
        if si:
            return True
        return click.prompt(f"Para borrar, escribe {palabra}", default="", show_default=False).strip() == palabra

    def _terminar(borrado, ok):
        if not ok:
            db.session.rollback()
            click.echo("Cancelado: no se ha borrado nada.")
            return
        db.session.commit()
        n = borrado.borrar_archivos()
        click.echo(f"Hecho. Archivos borrados del disco: {n}.")

    @app.cli.command("borrar-pedido")
    @click.argument("referencia")
    @click.option("--con-facturas", is_flag=True, help="Borrar también sus facturas registradas.")
    @click.option("--si", is_flag=True, help="No preguntar (para scripts).")
    def borrar_pedido_cmd(referencia, con_facturas, si):
        """Borra un pedido con todo lo suyo (proformas, fotos, documentos, mensajes, lotes reservados,
        salidas de stock…). Si era el último número de su cliente, ese número se reutiliza."""
        from app import limpieza
        from app.models import Factura, Pedido
        pedido = db.session.scalar(db.select(Pedido).filter(db.func.lower(Pedido.referencia_interna) == referencia.lower()))
        if pedido is None and referencia.isdigit():
            pedido = db.session.get(Pedido, int(referencia))
        if pedido is None:
            click.echo(f"No hay ningún pedido {referencia}.")
            return
        facturas = db.session.scalars(db.select(Factura.numero).filter_by(pedido_id=pedido.id)).all()
        if facturas and not con_facturas:
            click.echo(f"{pedido.referencia_interna} tiene facturas registradas ({', '.join(facturas)}): no lo borro. "
                       "Una factura emitida no debería desaparecer. Si es una prueba, usa --con-facturas.")
            return
        click.echo(f"Pedido {pedido.referencia_interna} · {pedido.cliente.nombre} · {pedido.estado_nombre}")
        borrado = limpieza.Borrado()
        ref, cliente = pedido.referencia_interna, pedido.cliente.nombre
        atras = limpieza.borrar_pedido(pedido, borrado)
        if atras:
            click.echo(f"Era el último pedido de {cliente}: el siguiente volverá a ser {ref}.")
        limpieza.anotar("borrar", "Pedido", pedido.id, ref, f"pedido de {cliente} borrado con todo lo suyo")
        _terminar(borrado, _confirmar(borrado, si, ref))

    @app.cli.command("borrar-cliente")
    @click.argument("cliente_id", type=int)
    @click.option("--con-facturas", is_flag=True, help="Borrar también sus facturas registradas.")
    @click.option("--si", is_flag=True, help="No preguntar (para scripts).")
    def borrar_cliente_cmd(cliente_id, con_facturas, si):
        """Borra un cliente (el nº de la dirección de su ficha: /clientes/12) con sus usuarios, pedidos,
        mensajes, tickets, precios especiales y catálogo. Mejor desactivarlo, si no es una prueba."""
        from app import limpieza
        from app.models import Cliente, Factura
        cliente = db.session.get(Cliente, cliente_id)
        if cliente is None:
            click.echo(f"No hay ningún cliente con id {cliente_id}.")
            return
        n_facturas = db.session.scalar(db.select(db.func.count()).select_from(Factura).filter_by(cliente_id=cliente.id))
        if n_facturas and not con_facturas:
            click.echo(f"{cliente.nombre} tiene {n_facturas} factura(s) registrada(s): no lo borro. Desactívalo en su "
                       "ficha o, si es una prueba, usa --con-facturas.")
            return
        click.echo(f"Cliente {cliente.nombre} ({cliente.cif or 'sin CIF'}) · usuarios: "
                   + (", ".join(u.email for u in cliente.usuarios) or "ninguno"))
        borrado, nombre = limpieza.Borrado(), cliente.nombre
        borrado.borrar("clientes", [cliente.id])
        limpieza.anotar("borrar", "Cliente", cliente_id, nombre, "cliente borrado con sus usuarios, pedidos y mensajes")
        _terminar(borrado, _confirmar(borrado, si, nombre))

    @app.cli.command("limpiar-pruebas")
    @click.option("--con-inventario", is_flag=True, help="Borrar también los lotes y todas las entradas de stock.")
    @click.option("--si", is_flag=True, help="No preguntar (para scripts).")
    def limpiar_pruebas_cmd(con_inventario, si):
        """Deja la plataforma lista para empezar de verdad: borra pedidos, proformas, facturas, mensajes,
        tickets, correos y auditoría, y la numeración de pedidos vuelve a 1. Se quedan clientes, usuarios,
        productos, kits, precios, catálogos, ajustes y (sin --con-inventario) los lotes y entradas de stock."""
        from app import limpieza
        borrado = limpieza.Borrado()
        limpieza.limpiar_pruebas(borrado, con_inventario)
        click.echo("Se quedan: clientes, usuarios, productos, kits, precios, catálogos y ajustes"
                   + ("." if con_inventario else ", y los lotes y entradas de stock (sin las salidas de los pedidos)."))
        click.echo("La numeración de pedidos de todos los clientes vuelve a empezar (…-001).")
        ok = _confirmar(borrado, si, "BORRAR")
        if ok:
            limpieza.anotar("borrar", "-", None, "limpieza de pruebas",
                            "pedidos, facturas, mensajes y auditoría borrados; numeración a 1"
                            + (" · también el inventario" if con_inventario else ""))
        _terminar(borrado, ok)

    @app.cli.command("importar-datos")
    @click.argument("archivo", type=click.Path(exists=True, dir_okay=False))
    @click.option("--guardar", is_flag=True, help="Guardar de verdad (sin esto, solo se comprueba).")
    def importar_datos(archivo, guardar):
        """Carga productos, kits y empresas desde la plantilla Excel (ver app/importar.py).
        Sin --guardar es una prueba: dice qué haría y no guarda nada. Solo crea: lo que ya
        existe no se toca. Si hay algún error, no se guarda nada."""
        from app.importar import importar
        click.echo(f"Base de datos: {db.engine.url.render_as_string(hide_password=True)}")
        informe = importar(archivo, guardar=guardar)
        for texto in informe.avisos:
            click.echo(f"  · {texto}")
        for texto in informe.errores:
            click.echo(f"  ✗ {texto}")
        c, e, s = informe.creados, informe.existentes, informe.sin_precio
        click.echo(f"Productos: {c['Productos']} nuevos ({s['Productos']} sin precio), {e['Productos']} ya existían")
        click.echo(f"Kits: {c['Kits']} nuevos ({s['Kits']} sin precio, {c['Componentes']} componentes), {e['Kits']} ya existían")
        click.echo(f"Empresas: {c['Empresas']} nuevas, {e['Empresas']} ya existían")
        if informe.errores:
            click.echo(f"{len(informe.errores)} error(es): NO se ha guardado nada. Corrige el Excel y repite.")
            raise SystemExit(1)
        if guardar:
            click.echo("Guardado.")
        else:
            click.echo("Era una PRUEBA: no se ha guardado nada. Si está bien, repite con --guardar.")

    @app.cli.command("reservar-pendientes")
    def reservar_pendientes():
        """Reserva lotes (los que caducan antes) para los pedidos abiertos que aún no tienen.

        Para ejecutarlo UNA vez al instalar la reserva de lotes: los pedidos que ya estaban en
        marcha no tienen lotes reservados y sin ellos no se pueden enviar. No toca los pedidos
        que ya tienen todo reservado ni las proformas que aún se están preparando."""
        from app.inventario import reservas
        from app.models import Pedido
        from app.proformas.servicio import proforma_aceptada, reservar_como_la_proforma
        estados = [e for e in reservas.ESTADOS_CON_RESERVA if e not in ("proforma_solicitada", "cambios_solicitados")]
        pedidos = db.session.scalars(db.select(Pedido).where(Pedido.estado.in_(estados)).order_by(Pedido.fecha, Pedido.id)).all()
        # Primero los que tienen una proforma aceptada: eligen antes, para poder quedarse con el
        # lote de la caducidad que aprobó el cliente
        pedidos.sort(key=lambda p: not (p.con_proforma and proforma_aceptada(p) is not None))
        hechos = con_aviso = 0
        for pedido in pedidos:
            antes = sum(r.cantidad for r in pedido.reservas)
            if pedido.con_proforma and proforma_aceptada(pedido) is not None:
                reservar_como_la_proforma(pedido)
            else:
                reservas.reservar_automatico(pedido)
            _plan, problemas = reservas.plan_reservado(pedido)
            despues = sum(r.cantidad for r in pedido.reservas)
            if despues != antes or problemas:
                hechos += despues != antes
                con_aviso += bool(problemas)
                lotes = ", ".join(f"{r.lote.codigo}×{r.cantidad}" for r in pedido.reservas) or "nada"
                click.echo(f"  {pedido.referencia_interna} ({pedido.estado}): {lotes}"
                           + (f"  ⚠ {'; '.join(problemas)}" if problemas else ""))
        db.session.commit()
        click.echo(f"Pedidos con lotes reservados ahora: {hechos}")
        if con_aviso:
            click.echo("Los marcados con ⚠ no se podrán enviar hasta resolverlo en su ficha (tarjeta «Lotes de este pedido»).")

    @app.cli.command("recordar-recepcion")
    def recordar_recepcion_cmd():
        """Recordatorio «¿Ha recibido su pedido?» a los clientes (cada día a las 9:00 de España: deploy/yikonpo-recordatorios.timer).

        Sale el día después de la fecha estimada de entrega si el pedido sigue «Enviado», una vez.
        En el servidor lo lanza deploy/recordatorios.sh (DESPLIEGUE.md)."""
        from app.notificaciones import recordar_recepcion
        # Sin nadie navegando: los enlaces de los correos salen con URL_PLATAFORMA
        with app.test_request_context(base_url=app.config["URL_PLATAFORMA"]):
            avisados = recordar_recepcion()
        click.echo(f"Recordatorios de recepción: {len(avisados)}"
                   + (" (" + ", ".join(p.referencia_interna or f"#{p.id}" for p in avisados) + ")" if avisados else ""))

    @app.cli.command("situar-clientes")
    @click.option("--todos", is_flag=True, help="También los que ya están en el mapa (vuelve a buscarlos).")
    def situar_clientes_cmd(todos):
        """Sitúa en el mapa de clientes a los que aún no salen (busca su ciudad en OpenStreetMap).

        Para los clientes que ya existían antes del mapa (15/10/2026): una vez basta. Espera un segundo
        entre cliente y cliente (norma de uso de Nominatim). Los que no encuentre, se sitúan a mano en
        «Editar» haciendo clic en el mapa."""
        import time

        from app import geocodificar
        from app.models import Cliente
        if not app.config.get("GEOCODIFICAR"):
            click.echo("GEOCODIFICAR=0 en el .env: no se busca nada.")
            return
        consulta = db.select(Cliente).order_by(Cliente.nombre)
        if not todos:
            consulta = consulta.where(Cliente.latitud.is_(None))
        encontrados, sin = 0, []
        for cliente in db.session.scalars(consulta).all():
            if not (cliente.ciudad or cliente.codigo_postal):
                sin.append(f"{cliente.nombre} (sin ciudad)")
                continue
            if geocodificar.situar(cliente):
                encontrados += 1
                click.echo(f"  ✓ {cliente.nombre}: {cliente.ciudad} ({cliente.latitud:.3f}, {cliente.longitud:.3f})")
            else:
                sin.append(f"{cliente.nombre} ({cliente.ciudad})")
            db.session.commit()
            time.sleep(1.1)
        click.echo(f"Situados: {encontrados}")
        if sin:
            click.echo("Sin situar (hazlo a mano en «Editar»): " + "; ".join(sin))

    @app.cli.command("datos-demo")
    def datos_demo():
        """Rellena la base de datos con datos FICTICIOS para probar (solo desarrollo)."""
        if app.config["ENTORNO"] != "dev":
            click.echo("Solo en desarrollo (FLASK_CONFIG=dev).")
            return
        if db.session.scalar(db.select(Cliente).limit(1)):
            click.echo("La base de datos ya tiene datos; no hago nada.")
            return

        def crear_usuario(nombre, email, rol, **extra):
            u = User(nombre=nombre, email=email, rol=rol, **extra)
            u.set_password("demo123456")
            db.session.add(u)
            return u

        crear_usuario("Admin Demo", "admin@ejemplo.com", "admin")
        crear_usuario("Lucía Almacén", "almacen@ejemplo.com", "logistica")   # el almacén (rol "logistica")
        crear_usuario("Fernando Facturación", "facturacion@ejemplo.com", "facturacion")
        laura = crear_usuario("Laura FAS", "laura@ejemplo.com", "fas")
        pablo = crear_usuario("Pablo FAS", "pablo@ejemplo.com", "fas")

        productos = [
            ("KIT-PGTA-24", "Kit PGT-A 24 muestras", "PGT-A", "1850.00"),
            ("KIT-PGTM-01", "Kit PGT-M (por caso)", "PGT-M", "2400.00"),
            ("REA-WGA-96", "Reactivo amplificación genoma completo (96 rx)", "Reactivos", "960.00"),
            ("CONS-TUBOS", "Tubos PCR 0,2 ml (caja 1000)", "Consumibles", "85.00"),
            ("SERV-ANAL", "Servicio de análisis bioinformático", "Servicios", "150.00"),
        ]
        for ref, nombre, cat, precio in productos:
            db.session.add(Producto(referencia=ref, nombre=nombre, categoria=cat,
                                    precio=Decimal(precio), stock_minimo=5,
                                    controlar_stock=(cat != "Servicios")))

        clientes = [
            Cliente(nombre="Clínica Ficticia Norte", cif="B00000001", ciudad="Bilbao", pais="ES", latitud=43.263, longitud=-2.935, prefijo="NORTE",
                    logisticos=[laura]),
            Cliente(nombre="Centro Reproducción Ejemplo", cif="B00000002", ciudad="Valencia", pais="ES",
                    latitud=39.47, longitud=-0.376, prefijo="CRE",
                    logisticos=[laura, pablo]),  # un cliente con dos FAS
            Cliente(nombre="Instituto Demo de Fertilidad", cif="B00000003", ciudad="Madrid", pais="ES",
                    latitud=40.417, longitud=-3.704, prefijo="IDF",
                    logisticos=[pablo]),
        ]
        db.session.add_all(clientes)
        db.session.flush()
        # Un usuario por empresa cliente
        crear_usuario("Usuario Clínica Norte", "norte@ejemplo.com", "cliente", empresa=clientes[0])
        crear_usuario("Usuario Centro Ejemplo", "centro@ejemplo.com", "cliente", empresa=clientes[1])
        crear_usuario("Usuario Instituto Demo", "instituto@ejemplo.com", "cliente", empresa=clientes[2])

        prods = db.session.scalars(db.select(Producto)).all()
        hoy = date.today()
        for i, cliente in enumerate(db.session.scalars(db.select(Cliente)).all()):
            pedido = Pedido(cliente=cliente, fecha=hoy - timedelta(days=30 - i * 7),
                            estado="entregado", creado_por=cliente.logisticos[0],
                            referencia=f"PO-{hoy.year}-{i + 10}",
                            referencia_interna=cliente.siguiente_referencia_interna())
            for p in prods[i:i + 2]:
                pedido.lineas.append(LineaPedido(producto=p, cantidad=i + 1,
                                                 precio_unitario=p.precio, iva_pct=p.iva_pct))
            db.session.add(pedido)
            db.session.flush()
            db.session.add(Factura(
                numero=f"DEMO-{hoy.year}-{i + 1:04d}", cliente=cliente, pedido=pedido,
                fecha_emision=pedido.fecha, fecha_vencimiento=pedido.fecha + timedelta(days=30),
                base_imponible=pedido.base_imponible, iva=pedido.total_iva, total=pedido.total,
                estado="pagada" if i == 0 else "pendiente",
                fecha_pago=pedido.fecha + timedelta(days=20) if i == 0 else None,
                enviada_el=ahora(),                    # el cliente ya la tiene
            ))
        # Kits: agrupaciones de productos, con su precio estándar
        from app.models import ComponenteKit, Kit, PrecioCliente
        por_ref = {p.referencia: p for p in prods}
        kits = [
            ("KIT-PGTA-COMP", "PGT-A completo", "Kit PGT-A con reactivos, consumibles y análisis.", "2950.00",
             [("KIT-PGTA-24", 1), ("REA-WGA-96", 1), ("CONS-TUBOS", 2), ("SERV-ANAL", 1)]),
            ("KIT-PGTM-COMP", "PGT-M completo", "Estudio PGT-M por caso con consumibles y análisis.", "2600.00",
             [("KIT-PGTM-01", 1), ("CONS-TUBOS", 1), ("SERV-ANAL", 1)]),
            ("KIT-REPO", "Reposición de laboratorio", None, "1000.00",
             [("REA-WGA-96", 1), ("CONS-TUBOS", 1)]),
        ]
        for ref, nombre, desc, precio, componentes in kits:
            db.session.add(Kit(referencia=ref, nombre=nombre, descripcion=desc, precio=Decimal(precio),
                               # los kits llegan cerrados; la reposición se monta en la oficina (ejemplo)
                               cerrado=(ref != "KIT-REPO"), stock_minimo=2 if ref != "KIT-REPO" else 0,
                               componentes=[ComponenteKit(producto=por_ref[r], cantidad=n) for r, n in componentes]))
        db.session.flush()
        # Un precio especial pactado con la Clínica Norte
        norte = db.session.scalar(db.select(Cliente).filter_by(prefijo="NORTE"))
        pgta = db.session.scalar(db.select(Kit).filter_by(referencia="KIT-PGTA-COMP"))
        db.session.add(PrecioCliente(cliente=norte, kit=pgta, precio=Decimal("2750.00")))

        # Stock inicial de la oficina por lotes (uno a punto de caducar y otro caducado,
        # para ver los avisos) y salidas de los pedidos que ya salieron de la oficina
        from app.models import Lote, MovimientoInventario
        hoy = date.today()
        iniciales = {  # referencia: [(lote, caducidad, unidades), ...]
            "KIT-PGTA-24": [("PA2409-01", hoy + timedelta(days=5), 6), ("PA2410-07", hoy + timedelta(days=240), 14)],
            "KIT-PGTM-01": [("PM2407-02", hoy + timedelta(days=180), 6)],
            "REA-WGA-96": [("WG2403-11", hoy - timedelta(days=10), 2), ("WG2409-04", hoy + timedelta(days=300), 10)],
            "CONS-TUBOS": [("TB-5561", hoy + timedelta(days=720), 40)],
        }
        lotes_de = {}
        for p in prods:
            for codigo, caducidad, unidades in iniciales.get(p.referencia, []):
                lote = Lote(producto=p, codigo=codigo, caducidad=caducidad)
                lotes_de.setdefault(p.id, []).append(lote)
                db.session.add(MovimientoInventario(producto=p, lote=lote, cantidad=unidades,
                                                    tipo="entrada", nota="Stock inicial (demo)"))
        # Kits cerrados: su propio lote y caducidad (los de la etiqueta del paquete)
        for ref, codigo, dias, unidades in [("KIT-PGTA-COMP", "YK2409-A1", 6, 3), ("KIT-PGTA-COMP", "YK2411-B2", 300, 8),
                                            ("KIT-PGTM-COMP", "YK2410-M1", 200, 4)]:
            kit = db.session.scalar(db.select(Kit).filter_by(referencia=ref))
            lote = Lote(kit=kit, codigo=codigo, caducidad=hoy + timedelta(days=dias))
            db.session.add(MovimientoInventario(kit=kit, lote=lote, cantidad=unidades,
                                                tipo="entrada", nota="Stock inicial (demo)"))
        for pedido in db.session.scalars(db.select(Pedido).where(Pedido.estado.in_(["enviado", "entregado"]))):
            # Igual que un envío de verdad: un kit cerrado sale entero de su lote…
            for kp in pedido.kits:
                if kp.kit.cerrado:
                    lote = db.session.scalar(db.select(Lote).filter_by(kit_id=kp.kit_id).order_by(Lote.caducidad.desc()))
                    db.session.add(MovimientoInventario(
                        kit=kp.kit, lote=lote, cantidad=-kp.cantidad, tipo="salida_pedido",
                        pedido=pedido, nota=f"Envío {pedido.referencia_interna}"))
            # …y los productos de kits montados o sueltos, de su propio stock
            for l in pedido.lineas:
                if l.kit_pedido is not None and l.kit_pedido.kit.cerrado:
                    continue
                if l.producto.controlar_stock:
                    lote = lotes_de.get(l.producto_id, [None])[-1]     # del lote de caducidad más lejana
                    db.session.add(MovimientoInventario(
                        producto=l.producto, lote=lote, cantidad=-l.cantidad, tipo="salida_pedido",
                        pedido=pedido, nota=f"Envío {pedido.referencia_interna}"))
        _demo_soporte_y_documentos(crear_usuario)
        db.session.commit()
        click.echo(
            "Datos demo creados (contraseña de todos: demo123456)\n"
            "  admin@ejemplo.com                      → admin\n"
            "  facturacion@ejemplo.com                → Facturación (proformas y facturas)\n"
            "  almacen@ejemplo.com                    → Almacén (preparar, enviar, inventario)\n"
            "  laura@ejemplo.com, pablo@ejemplo.com   → Soporte de cliente (rol fas)\n"
            "  norte@, centro@, instituto@ejemplo.com → clientes (norte@ e instituto@ con Soporte ChromGo)\n"
            "  soporte@ejemplo.com                    → Soporte ChromGo\n"
            "  chromgo@ejemplo.com                    → Cliente ChromGo (Clínica Ficticia Norte)"
        )

    @app.cli.command("datos-prueba")
    @click.option("--si", is_flag=True, help="No preguntar.")
    @click.option("--sobre-mis-datos", is_flag=True,
                  help="No borra nada: añade los casos con tus clientes y kits.")
    def datos_prueba(si, sobre_mis_datos):
        """Un caso de cada para probar a mano (pedidos en todos los estados, facturas en todas
        sus fases, mensajes sin leer...). Sin opciones BORRA la base de datos local y parte de los
        datos demo; con --sobre-mis-datos los añade a lo que ya tienes. Solo en desarrollo y solo
        con SQLite: nunca toca la base de datos de producción."""
        from flask_migrate import stamp
        from app.datos_prueba import CONTRASENA, crear_escenarios, quien_es_quien
        if app.config["ENTORNO"] != "dev" or db.engine.url.get_backend_name() != "sqlite":
            click.echo("Solo en desarrollo y con SQLite (FLASK_CONFIG=dev). No he tocado nada.")
            return
        click.echo(f"Base de datos: {db.engine.url.render_as_string(hide_password=True)}")
        if sobre_mis_datos:
            aviso = ("Se AÑADEN pedidos, facturas y mensajes de prueba (y los usuarios que falten) a lo que hay. "
                     "Mejor sobre una copia. ¿Seguimos?")
        else:
            aviso = "Se BORRA todo lo que hay en ella. ¿Seguro?"
        if not si and not click.confirm(aviso):
            click.echo("Cancelado.")
            return
        if not sobre_mis_datos:
            db.drop_all()
            db.create_all()
            stamp()                               # al día con las migraciones (flask db upgrade no hará nada)
            click.echo("Datos demo…")
            datos_demo.callback()
        # Mientras se crean: sin CSRF (es un navegador de pruebas), sin emails de verdad y sin esperar
        # los segundos de "deshacer"
        antes = {k: app.config.get(k) for k in ("WTF_CSRF_ENABLED", "MAIL_BACKEND", "MENSAJES_DESHACER_SEGUNDOS")}
        app.config.update(WTF_CSRF_ENABLED=False, MAIL_BACKEND="memoria", MENSAJES_DESHACER_SEGUNDOS=0)
        try:
            click.echo("Casos de prueba:")
            casos = crear_escenarios(app, avisar=click.echo)
        finally:
            app.config.update(antes)
        click.echo("\nQuién es quién (en la barra «Entrar como» de la web):")
        for linea in quien_es_quien():
            click.echo(linea)
        click.echo(f"(los usuarios creados para las pruebas tienen la contraseña {CONTRASENA})")
        click.echo("\nLos casos (búscalos por su referencia o por «PRUEBA»):")
        for caso, ref in casos:
            click.echo(f"  {ref:<26} {caso}")

    def _demo_soporte_y_documentos(crear_usuario):
        """Soporte ChromGo (usuarios y tickets de ejemplo) y documentos internos (los logos de Yikon)."""
        import os
        from datetime import datetime, timezone
        from app import archivos
        from app.models import DocumentoInterno, Ticket, TicketMensaje, VersionDocumento
        admin = db.session.scalar(db.select(User).filter_by(email="admin@ejemplo.com"))
        laura = db.session.scalar(db.select(User).filter_by(email="laura@ejemplo.com"))
        norte = db.session.scalar(db.select(Cliente).filter_by(prefijo="NORTE"))
        idf = db.session.scalar(db.select(Cliente).filter_by(prefijo="IDF"))
        for email in ("norte@ejemplo.com", "instituto@ejemplo.com"):     # clientes con acceso a Soporte
            db.session.scalar(db.select(User).filter_by(email=email)).acceso_chromgo = True
        soporte = crear_usuario("Álvaro Soporte", "soporte@ejemplo.com", "soporte")
        chromgo = crear_usuario("Marta (bioinformática Norte)", "chromgo@ejemplo.com", "cliente_chromgo", empresa=norte)
        instituto = db.session.scalar(db.select(User).filter_by(email="instituto@ejemplo.com"))
        db.session.flush()
        anio = date.today().year
        ahora = datetime.now(timezone.utc)
        ejemplos = [  # (cliente, autor, asunto, categoría, prioridad, estado, referencia, conversación)
            (norte, chromgo, "El informe CNV de la muestra no se genera", "cnv", "alta", "en_curso", "S-2026-0142",
             [(chromgo, False, "Al pulsar «Generar informe» sale «Error 500». Pasa con todas las muestras del run de ayer."),
              (soporte, True, "Mirado en logs: falla el paso de normalización. Lo hablo con bioinfo."),
              (soporte, False, "Gracias, Marta. Lo estamos revisando; le decimos algo hoy.")]),
            (norte, chromgo, "No puedo entrar: «usuario bloqueado»", "acceso", "urgente", "abierto", None,
             [(chromgo, False, "Desde esta mañana me sale «usuario bloqueado» al entrar en ChromGo.")]),
            (idf, instituto, "¿Cómo exporto los resultados a Excel?", "consulta", "baja", "esperando_cliente", None,
             [(instituto, False, "Queremos exportar el resumen de un run a Excel. ¿Se puede?"),
              (soporte, False, "Sí: en el run, botón «Exportar» → «Resumen (.xlsx)». ¿Le ha funcionado?")]),
            (norte, chromgo, "Haplotipado lento en runs grandes", "snp", "normal", "resuelto", "RUN-0907",
             [(chromgo, False, "El haplotipado de un run de 96 tarda más de 3 horas."),
              (soporte, False, "Hemos ampliado los recursos del servidor. Ahora debería tardar unos 40 min.")]),
        ]
        for i, (cliente, autor, asunto, categoria, prioridad, estado, ref, conversacion) in enumerate(ejemplos, 1):
            t = Ticket(numero=f"TK-{anio}-{i:04d}", cliente=cliente, creado_por=autor, asunto=asunto,
                       categoria=categoria, prioridad=prioridad, estado=estado, referencia=ref,
                       asignado_a=soporte if estado != "abierto" else None,
                       creado=ahora - timedelta(days=5 - i), actualizado=ahora - timedelta(hours=10 - i),
                       resuelto=ahora if estado == "resuelto" else None)
            db.session.add(t)
            for quien, interno, texto in conversacion:
                db.session.add(TicketMensaje(ticket=t, autor=quien, texto=texto, interno=interno,
                                             de_cliente=quien.es_cliente))
        # Documentos internos: los logos que ya usa la plataforma, como ejemplo
        estaticos = os.path.join(os.path.dirname(__file__), "static", "img")
        for titulo, archivo, desc in [("Logo Yikon Genomics (horizontal)", "yikon-logo.png", "Logo completo en color, fondo transparente."),
                                      ("Símbolo Yikon", "yikon-simbolo.png", "Solo el símbolo, para iconos y avatares.")]:
            with open(os.path.join(estaticos, archivo), "rb") as f:
                datos = f.read()
            d = DocumentoInterno(categoria="marca", titulo=titulo, descripcion=desc)
            d.versiones.append(VersionDocumento(numero=1, nombre_original=archivo, extension="png", tamano=len(datos),
                                                subido_por=admin, archivo=archivos.escribir(datos, "interno", "png")))
            db.session.add(d)
        db.session.add(DocumentoInterno(categoria="protocolos", titulo="Protocolo de preparación de envíos",
                                        descripcion="Cómo se preparan y fotografían los pedidos antes de enviarlos.",
                                        versiones=[VersionDocumento(numero=1, nombre_original="protocolo_envios.txt",
                                                                    extension="txt", tamano=60, subido_por=laura,
                                                                    archivo=archivos.escribir(b"Protocolo de envios (demo)\n" * 2, "interno", "txt"))]))
