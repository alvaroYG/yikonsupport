"""
Ajustes que admin cambia desde la plataforma (Administración → Ajustes). Se guardan en la
tabla "ajustes" (clave → valor); lo que no se haya tocado nunca usa el valor de fábrica.

Aquí están los PLAZOS (cuántos días puede llevar un pedido en cada situación antes de marcarse
con el reloj en "Pendientes"; 0 = no avisar nunca) y los VALORES POR DEFECTO DE LAS PROFORMAS.
Otros ajustes tienen su propio archivo: correos_cliente.py, apartados.py, avisos_internos.py y
datos_empresa.py.
"""
from flask_babel import lazy_gettext as _l

from app.extensions import db
from app.models import Ajuste

# estado del pedido → (días de fábrica, cómo se le explica a admin en la página de ajustes)
PLAZOS = {
    "proforma_solicitada": (3, _l("Proforma solicitada, sin preparar")),
    "cambios_solicitados": (3, _l("Cambios pedidos por el cliente, sin atender")),
    "aceptado": (3, _l("Aceptado, sin empezar")),
    "en_preparacion": (5, _l("En preparación")),
    "en_validacion": (3, _l("Pendiente de validación")),
    "validado": (3, _l("Listo para enviar, sin enviar")),
    "proforma_enviada": (7, _l("Proforma enviada, sin respuesta del cliente")),
    "enviado": (7, _l("Enviado, sin confirmar la recepción")),
}
MAXIMO_DIAS = 365


def _clave(estado):
    return f"plazo.{estado}"


def plazos() -> dict:
    """{estado: días} con lo guardado por admin y, para lo demás, el valor de fábrica."""
    guardados = {a.clave: a.valor for a in db.session.scalars(
        db.select(Ajuste).where(Ajuste.clave.like("plazo.%")))}
    resultado = {}
    for estado, (de_fabrica, _texto) in PLAZOS.items():
        valor = guardados.get(_clave(estado))
        resultado[estado] = int(valor) if valor is not None and valor.isdigit() else de_fabrica
    return resultado


def guardar_plazos(nuevos: dict) -> list:
    """Guarda {estado: días} (sin commit). Devuelve los cambios como texto, para la auditoría:
    ["aceptado 3→5", ...]. Los estados que no existen se ignoran."""
    actuales, cambios = plazos(), []
    for estado, dias in nuevos.items():
        if estado not in PLAZOS or dias == actuales[estado]:
            continue
        ajuste = db.session.get(Ajuste, _clave(estado))
        if ajuste is None:
            db.session.add(Ajuste(clave=_clave(estado), valor=str(dias)))
        else:
            ajuste.valor = str(dias)
        cambios.append(f"{estado} {actuales[estado]}→{dias}")
    return cambios


# --------------------------------------------------------------------------- #
# Proformas: lo que sale ya relleno al enviar una (se puede cambiar en cada una)
# --------------------------------------------------------------------------- #
VALIDEZ_DE_FABRICA = 30
IDIOMAS_PROFORMA = ("es", "en")


def proformas() -> dict:
    """{"validez": días, "plazo": {idioma: texto}, "notas": {idioma: texto}}"""
    guardados = {a.clave: a.valor for a in db.session.scalars(
        db.select(Ajuste).where(Ajuste.clave.like("proforma.%")))}
    validez = guardados.get("proforma.validez", "")
    return {"validez": int(validez) if validez.isdigit() else VALIDEZ_DE_FABRICA,
            "plazo": {i: guardados.get(f"proforma.plazo.{i}", "") for i in IDIOMAS_PROFORMA},
            "notas": {i: guardados.get(f"proforma.notas.{i}", "") for i in IDIOMAS_PROFORMA}}


def guardar_proformas(validez: int, plazo: dict, notas: dict) -> list:
    """Guarda (sin commit) y devuelve lo que ha cambiado, para la auditoría."""
    actuales, cambios = proformas(), []
    nuevos = {"proforma.validez": "" if validez == VALIDEZ_DE_FABRICA else str(validez)}
    for i in IDIOMAS_PROFORMA:
        nuevos[f"proforma.plazo.{i}"] = (plazo.get(i) or "").strip()[:120]
        nuevos[f"proforma.notas.{i}"] = (notas.get(i) or "").replace("\r\n", "\n").strip()[:2000]
    antes = {"proforma.validez": "" if actuales["validez"] == VALIDEZ_DE_FABRICA else str(actuales["validez"])}
    antes.update({f"proforma.plazo.{i}": actuales["plazo"][i] for i in IDIOMAS_PROFORMA})
    antes.update({f"proforma.notas.{i}": actuales["notas"][i] for i in IDIOMAS_PROFORMA})
    for clave, valor in nuevos.items():
        if valor == antes[clave]:
            continue
        fila = db.session.get(Ajuste, clave)
        if not valor:
            if fila is not None:
                db.session.delete(fila)
        elif fila is None:
            db.session.add(Ajuste(clave=clave, valor=valor))
        else:
            fila.valor = valor
        cambios.append(clave.removeprefix("proforma."))
    return cambios


def idioma_del_cliente(cliente) -> str:
    """El idioma en el que lee un cliente: el que más usan sus usuarios activos ("es" si no hay)."""
    from collections import Counter
    idiomas = Counter((u.idioma or "es") for u in cliente.usuarios if u.activo and u.rol == "cliente")
    idioma = idiomas.most_common(1)[0][0] if idiomas else "es"
    return idioma if idioma in IDIOMAS_PROFORMA else "es"
