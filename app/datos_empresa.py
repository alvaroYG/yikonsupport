"""
Datos de Yikon (Administración → Ajustes → Datos de Yikon): se escriben una vez y salen en
  - el bloque "Seller." del Excel de "Preparar factura"   → lineas_vendedor()
  - la cabecera y el pie del modelo de proforma            → nombre(), lineas_cabecera()
  - la firma de los correos al cliente, mientras nadie la haya cambiado a mano (correos_cliente)

Se guardan en la tabla "ajustes" (empresa.<campo>). Lo que no se ha tocado nunca sale de
config.py (EMPRESA_NOMBRE y VENDEDOR_FACTURA): así, sin tocar nada, todo sale como antes.
"""
from flask import current_app
from flask_babel import lazy_gettext as _l

from app.extensions import db
from app.models import Ajuste

CAMPOS = {
    "nombre": _l("Nombre comercial"),
    "razon_social": _l("Razón social"),
    "cif": _l("CIF"),
    "telefono": _l("Teléfono"),
    "direccion": _l("Dirección"),
    "cp_ciudad": _l("Código postal y ciudad"),
    "pais": _l("País"),
    "email": _l("Email de contacto"),
    "web": _l("Web"),
    # Para la factura en Excel («Preparar factura»: app/facturas/datos.py)
    "eori": _l("EORI (sale en las facturas a clientes de la UE)"),
    "banco": _l("Banco (transferencias)"),
    "iban": _l("IBAN"),
    "swift": _l("SWIFT / BIC"),
    "incoterm": _l("Incoterm"),
    "entrega": _l("Plazo de entrega (en la factura)"),
}
LARGO = {"direccion": 300}       # (el resto, 150)
# Los de la factura vienen como en la plantilla de factura de Yikon (se cambian aquí)
FABRICA_FACTURA = {"eori": "", "banco": "CaixaBank, S.A.", "iban": "ES47 2100 1152 7002 0032 6054",
                   "swift": "CAIXESBBXXX", "incoterm": "CPT", "entrega": "TWO WEEKS AFTER FULL PAYMENT."}


def _de_fabrica():
    """Lo de config.py, repartido en los campos: VENDEDOR_FACTURA es [razón social, dirección…, "CIF: …"]."""
    cfg = current_app.config
    vendedor = list(cfg.get("VENDEDOR_FACTURA") or [])
    cif = ""
    if vendedor and vendedor[-1].upper().startswith("CIF"):
        cif = vendedor.pop().split(":", 1)[-1].strip()
    return {"nombre": cfg.get("EMPRESA_NOMBRE") or "Yikon Genomics España",
            "razon_social": vendedor[0] if vendedor else "", "cif": cif, "telefono": "",
            "direccion": "\n".join(vendedor[1:]), "cp_ciudad": "", "pais": "", "email": "", "web": "",
            **FABRICA_FACTURA}


def datos() -> dict:
    """{campo: valor}: lo guardado por admin o, si no, lo de fábrica."""
    guardados = {a.clave: a.valor for a in db.session.scalars(
        db.select(Ajuste).where(Ajuste.clave.like("empresa.%")))}
    fabrica = _de_fabrica()
    return {c: guardados.get(f"empresa.{c}", fabrica[c]) for c in CAMPOS}


def guardar(nuevos: dict) -> list:
    """Guarda (sin commit) y devuelve los campos que han cambiado, para la auditoría."""
    actuales, fabrica, cambios = datos(), _de_fabrica(), []
    for campo in CAMPOS:
        valor = "\n".join(l.strip() for l in (nuevos.get(campo) or "").strip().splitlines() if l.strip())
        valor = valor[:LARGO.get(campo, 150)]
        if valor == actuales[campo]:
            continue
        fila = db.session.get(Ajuste, f"empresa.{campo}")
        if valor == fabrica[campo]:
            if fila is not None:
                db.session.delete(fila)
        elif fila is None:
            db.session.add(Ajuste(clave=f"empresa.{campo}", valor=valor))
        else:
            fila.valor = valor
        cambios.append(campo)
    return cambios


def nombre() -> str:
    return datos()["nombre"]


def _lugar(d):
    return ", ".join(x for x in (d["cp_ciudad"], d["pais"]) if x)


def lineas_vendedor() -> list:
    """El bloque "Seller." del Excel: razón social, dirección, CP/ciudad/país y CIF."""
    d = datos()
    lineas = [d["razon_social"]] + d["direccion"].splitlines() + [_lugar(d)]
    if d["cif"]:
        lineas.append(f"CIF: {d['cif']}")
    return [l for l in lineas if l]


def lineas_cabecera() -> list:
    """Debajo del nombre, en la cabecera del modelo de proforma."""
    d = datos()
    direccion = ", ".join(d["direccion"].splitlines())
    lineas = [direccion, _lugar(d), f"CIF {d['cif']}" if d["cif"] else "",
              " · ".join(x for x in (d["telefono"], d["email"], d["web"]) if x)]
    return [l for l in lineas if l]


def lineas_firma() -> list:
    """Para la firma de fábrica de los correos: nombre, dirección y contacto."""
    d = datos()
    direccion = ", ".join(d["direccion"].splitlines() + ([_lugar(d)] if _lugar(d) else []))
    lineas = [d["nombre"], direccion, " · ".join(x for x in (d["telefono"], d["email"]) if x), d["web"]]
    return [l for l in lineas if l]
