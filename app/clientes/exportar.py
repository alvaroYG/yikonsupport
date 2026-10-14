"""
Exportar TODO lo de un cliente en un ZIP (ficha del cliente → «Exportar todo», solo admin).
Para dárselo al cliente si lo pide (RGPD, auditoría de la clínica…) o para guardarlo si se va.

Dentro del ZIP:
  pedidos.xlsx                      todos sus pedidos (con importes y su contenido)
  facturas/<número>.pdf             el PDF de cada factura (las que lo tienen)
  proformas/<pedido>/<número>.pdf   cada versión de cada proforma (el PDF que se envió o, en las
                                    antiguas sin PDF, el modelo de la plataforma)
  documentos/<pedido>/<archivo>     los documentos adjuntos a sus pedidos
  LEEME.txt                         qué es, cuándo y quién lo sacó, y si faltó algún archivo

Se arma en un archivo temporal (no en memoria): un cliente con muchos PDF puede pesar bastante.
Queda en la auditoría (acción "Exportar", sobre el cliente).
"""
import os
import re
import tempfile
import unicodedata
import zipfile
from datetime import date

from flask import current_app
from flask_babel import force_locale, gettext as _

from app.extensions import db
from app.models import Factura, Pedido, ahora


def nombre_seguro(texto, por_defecto="archivo"):
    """Un nombre de archivo que vale en Windows, Mac y Linux (sin tildes raras ni / \\ : * ? " < > |)."""
    texto = unicodedata.normalize("NFC", str(texto or "")).strip()
    texto = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", texto).strip(" .")
    return texto[:120] or por_defecto


class _Zip:
    """Un ZipFile que no repite nombres (añade (2), (3)…) y apunta lo que falta."""

    def __init__(self, archivo):
        self.zip = zipfile.ZipFile(archivo, "w", zipfile.ZIP_DEFLATED)
        self.usados, self.faltan = set(), []

    def _libre(self, ruta):
        base, ext = os.path.splitext(ruta)
        n, candidata = 2, ruta
        while candidata.lower() in self.usados:
            candidata, n = f"{base} ({n}){ext}", n + 1
        self.usados.add(candidata.lower())
        return candidata

    def datos(self, ruta, contenido):
        self.zip.writestr(self._libre(ruta), contenido)

    def fichero(self, ruta, en_disco, carpeta):
        origen = os.path.join(carpeta, en_disco or "")
        if not en_disco or not os.path.isfile(origen):
            self.faltan.append(ruta)
            return False
        self.zip.write(origen, self._libre(ruta))
        return True


def _excel_pedidos(pedidos):
    from app.excel import Columna, generar_excel
    columnas = [Columna(_("Ref. interna"), 18), Columna(_("Fecha"), 12, "fecha"), Columna(_("Ref. empresa"), 16),
                Columna(_("Productos"), 50), Columna(_("Estado"), 18), Columna(_("Entrega estimada"), 14, "fecha"),
                Columna(_("Transportista"), 16), Columna(_("Nº de seguimiento"), 20),
                Columna(_("Base imponible"), 14, "euros"), Columna(_("IVA"), 12, "euros"), Columna(_("Total"), 14, "euros"),
                Columna(_("Facturas"), 20), Columna(_("Incidencias"), 30)]
    filas = []
    for p in pedidos:
        filas.append([p.referencia_interna or f"#{p.id}", p.fecha, p.referencia or "", p.resumen_contenido("\n"),
                      str(p.estado_nombre), p.fecha_entrega_estimada, p.transportista or "", p.numero_seguimiento or "",
                      p.base_imponible, p.total_iva, p.total, ", ".join(f.numero for f in p.facturas),
                      "\n".join(f"{i.motivo_nombre} ({'abierta' if i.abierta else 'resuelta'})" for i in p.incidencias)])
    return generar_excel(_("Pedidos"), columnas, filas, subtitulo=_("%(n)s pedidos", n=len(pedidos)))


def generar_zip(cliente, usuario):
    """Arma el ZIP y devuelve (ruta del archivo temporal, resumen para la auditoría). Quien llama
    lo envía y lo borra después."""
    from app import archivos
    from app.pedidos import documentos as docs
    from app.proformas.pdf import generar_pdf_proforma

    pedidos = db.session.scalars(db.select(Pedido).filter_by(cliente_id=cliente.id)
                                 .order_by(Pedido.fecha, Pedido.id)).all()
    facturas = db.session.scalars(db.select(Factura).filter_by(cliente_id=cliente.id)
                                  .order_by(Factura.fecha_emision, Factura.id)).all()
    descriptor, ruta = tempfile.mkstemp(prefix="exportar_cliente_", suffix=".zip")
    os.close(descriptor)
    cuenta = {"facturas": 0, "proformas": 0, "documentos": 0}
    with force_locale("es"):                      # (los nombres de las columnas y del LEEME, en español)
        z = _Zip(ruta)
        z.datos("pedidos.xlsx", _excel_pedidos(pedidos))
        for f in facturas:
            if f.pdf_archivo:
                cuenta["facturas"] += z.fichero(f"facturas/{nombre_seguro(f.numero)}.pdf", f.pdf_archivo, archivos.carpeta())
        for p in pedidos:
            carpeta_pedido = nombre_seguro(p.referencia_interna or f"pedido-{p.id}")
            for pf in p.proformas:
                destino = f"proformas/{carpeta_pedido}/{nombre_seguro(pf.numero)}.pdf"
                if pf.pdf_archivo:
                    cuenta["proformas"] += z.fichero(destino, pf.pdf_archivo, archivos.carpeta())
                else:
                    z.datos(destino, generar_pdf_proforma(pf))
                    cuenta["proformas"] += 1
            for d in p.documentos:
                cuenta["documentos"] += z.fichero(f"documentos/{carpeta_pedido}/{nombre_seguro(d.nombre_original)}",
                                                  d.archivo, docs.carpeta())
        from app.utils import hora_local
        leeme = [f"{cliente.nombre} · {cliente.razon_social or ''} {cliente.cif or ''}".strip(),
                 f"Exportado el {hora_local(ahora()):%d/%m/%Y %H:%M} por {usuario.nombre} ({usuario.email})",
                 "", f"{len(pedidos)} pedidos (pedidos.xlsx)",
                 f"{cuenta['facturas']} facturas en PDF (de {len(facturas)} registradas)",
                 f"{cuenta['proformas']} proformas", f"{cuenta['documentos']} documentos de pedidos"]
        if z.faltan:
            leeme += ["", "No se han encontrado en el servidor (no van en el ZIP):"] + [f"  - {f}" for f in z.faltan]
        z.datos("LEEME.txt", "\r\n".join(leeme) + "\r\n")
        z.zip.close()
    resumen = (f"exportado en ZIP: {len(pedidos)} pedidos, {cuenta['facturas']} facturas, "
               f"{cuenta['proformas']} proformas, {cuenta['documentos']} documentos"
               + (f" · faltan {len(z.faltan)} archivos" if z.faltan else ""))
    if z.faltan:
        current_app.logger.warning("Exportar %s: faltan archivos %s", cliente.nombre, z.faltan)
    return ruta, resumen


def nombre_del_zip(cliente):
    return f"{nombre_seguro(cliente.prefijo or cliente.nombre, 'cliente')}_{date.today():%Y%m%d}.zip"
