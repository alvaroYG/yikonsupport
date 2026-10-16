"""
Borrar de verdad (desde la terminal del servidor; la web nunca borra pedidos ni clientes):

  flask borrar-pedido YK-2026-CLA-003     un pedido con todo lo suyo
  flask borrar-cliente 12                 un cliente con sus usuarios, pedidos, mensajes, tickets…
  flask limpiar-pruebas                   todos los pedidos, facturas, mensajes… (para empezar de
                                          verdad tras las pruebas); se quedan clientes, usuarios,
                                          productos, kits, precios y ajustes; la numeración vuelve a 1

Cómo borra: busca en la base de datos qué tablas apuntan a lo que se borra (sus claves ajenas) y
borra primero lo de abajo (las líneas, las fotos, los mensajes y sus adjuntos…), sin olvidar nada
aunque mañana se añada una tabla nueva. Lo que solo "menciona" a lo borrado y tiene sentido sin
ello (p. ej. la auditoría o el «creado por» de otro registro) se queda, con ese dato vacío.
  - Stock: los movimientos de salida del pedido se borran, así que el stock vuelve a estar como si
    el pedido no hubiera existido (el stock es la suma de los movimientos).
  - Archivos: las fotos, documentos, PDFs y adjuntos de lo borrado se borran también del disco.
  - Siempre enseña antes lo que va a borrar (cuántas filas de cada tabla) y pide confirmación.

ANTES DE BORRAR EN EL SERVIDOR: copia de seguridad (DESPLIEGUE.md, «Copias de seguridad»).
"""
import os
import re
from collections import Counter

from flask import current_app

from app.extensions import db

# Columnas con el nombre de un archivo en disco (fotos, documentos, PDFs, adjuntos, SDS)
COLUMNAS_ARCHIVO = ("archivo", "pdf_archivo", "sds_archivo")
# Referencias que se pueden quedar vacías pero cuyo registro ES de lo que se borra (y se va con él):
# los mensajes del chat de un pedido, sus movimientos de stock, sus facturas, los correos de ese
# pedido o cliente y los usuarios de la empresa.
SE_VAN_CON_EL = {("mensajes", "pedido_id"), ("movimientos_inventario", "pedido_id"), ("facturas", "pedido_id"),
                 ("correos_enviados", "pedido_id"), ("correos_enviados", "cliente_id"), ("usuarios", "cliente_id")}


class Borrado:
    """Lo que se va borrando (sin commit): cuántas filas de cada tabla y qué archivos."""

    def __init__(self):
        self.filas = Counter()
        self.archivos = []

    def _referencias(self, tabla):
        """[(tabla hija, columna)] de las tablas que apuntan a esta."""
        return [(t, fk.parent) for t in db.metadata.sorted_tables for fk in t.foreign_keys
                if fk.column.table is tabla and t is not tabla]

    def borrar(self, nombre, ids):
        """Borra esas filas de la tabla `nombre` y, antes, todo lo que depende de ellas."""
        ids = [i for i in set(ids) if i is not None]
        if not ids:
            return
        tabla = db.metadata.tables[nombre]
        for hija, columna in self._referencias(tabla):
            condicion = columna.in_(ids)
            if columna.nullable and (hija.name, columna.name) not in SE_VAN_CON_EL:
                db.session.execute(hija.update().where(condicion).values({columna.name: None}))
                continue
            if "id" in hija.c:
                hijos = db.session.scalars(db.select(hija.c.id).where(condicion)).all()
                self.borrar(hija.name, hijos)
            else:                                      # (tablas de unión: catálogo, Soporte asignado…)
                self.filas[hija.name] += db.session.execute(hija.delete().where(condicion)).rowcount
        # Referencias a sí misma (un correo reenviado apunta al original): se sueltan
        for fk in tabla.foreign_keys:
            if fk.column.table is tabla:
                db.session.execute(tabla.update().where(fk.parent.in_(ids)).values({fk.parent.name: None}))
        archivos = [c for c in COLUMNAS_ARCHIVO if c in tabla.c]
        if archivos:
            for fila in db.session.execute(db.select(*[tabla.c[c] for c in archivos]).where(tabla.c.id.in_(ids))):
                self.archivos += [a for a in fila if a]
        self.filas[nombre] += db.session.execute(tabla.delete().where(tabla.c.id.in_(ids))).rowcount

    def todo(self, nombre):
        tabla = db.metadata.tables[nombre]
        self.borrar(nombre, db.session.scalars(db.select(tabla.c.id)).all())

    def resumen(self) -> str:
        return "\n".join(f"  {n:>6}  {tabla}" for tabla, n in sorted(self.filas.items()) if n) or "  (nada)"

    def borrar_archivos(self):
        """Tras el commit: los archivos de lo borrado (estén en la carpeta que estén)."""
        carpetas = {current_app.config.get(c) for c in ("UPLOAD_FOLDER", "DOCUMENTOS_FOLDER")} - {None}
        borrados = 0
        for nombre in set(self.archivos):
            for carpeta in carpetas:
                ruta = os.path.join(carpeta, os.path.basename(nombre))
                if os.path.isfile(ruta):
                    os.remove(ruta)
                    borrados += 1
        return borrados


def anotar(accion, entidad, entidad_id, objeto, detalle):
    """A la auditoría (desde la terminal no hay usuario: queda como «terminal»)."""
    from app.models import RegistroAuditoria
    db.session.add(RegistroAuditoria(accion=accion, entidad=entidad, entidad_id=entidad_id, objeto=objeto[:250],
                                     detalle=f"desde la terminal · {detalle}"))


def numero_de(referencia):
    """YK-2026-CLA-007 → (2026, 7); None si no tiene ese formato."""
    m = re.fullmatch(r"YK-(\d{4})-[A-Za-z0-9]+-(\d+)", referencia or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def borrar_pedido(pedido, borrado):
    """Borra el pedido (sin commit). Si era el último número de su cliente en ese año, el contador
    vuelve atrás: el siguiente pedido reutiliza ese número y no queda un hueco."""
    cliente, numero = pedido.cliente, numero_de(pedido.referencia_interna)
    borrado.borrar("pedidos", [pedido.id])
    if numero and cliente.anio_contador == numero[0] and cliente.contador_pedidos == numero[1]:
        cliente.contador_pedidos -= 1
        return True
    return False


def limpiar_pruebas(borrado, con_inventario=False):
    """Todo lo que se mueve (pedidos, facturas, mensajes, tickets, correos, auditoría…) a cero; se
    quedan clientes, usuarios, productos, kits, precios y ajustes. Numeración de pedidos a 1."""
    from app.models import Cliente
    for tabla in ("pedidos", "facturas", "mensajes", "tickets", "correos_enviados", "correos_borrador",
                  "auditoria", "errores_web"):
        if tabla in db.metadata.tables:
            borrado.todo(tabla)
    if con_inventario:
        for tabla in ("reservas_lote", "movimientos_inventario", "lotes"):
            borrado.todo(tabla)
    db.session.execute(db.update(Cliente).values(contador_pedidos=0, anio_contador=None))
