"""
Aviso para clientes (Administración → Ajustes → General): una franja arriba del inicio de los
clientes, para avisar de algo que les afecta a todos (cierre por vacaciones, retrasos de un
transportista, un cambio de horario…).

  - Uno solo a la vez, con texto en español y en inglés (cada cliente lo lee en su idioma; si
    falta uno, sale el otro).
  - Fechas desde/hasta opcionales: fuera de ellas no sale (sin fechas, sale hasta que se quite).
  - El cliente lo puede cerrar. Se apunta en su usuario la "huella" del texto: si admin lo cambia,
    la huella cambia y le vuelve a salir.

Se guarda en la tabla "ajustes": aviso_clientes.es, aviso_clientes.en, aviso_clientes.desde y
aviso_clientes.hasta (fechas AAAA-MM-DD).
"""
import hashlib
from datetime import date

from app.extensions import db
from app.models import Ajuste

IDIOMAS = ("es", "en")
CLAVES = [f"aviso_clientes.{i}" for i in IDIOMAS] + ["aviso_clientes.desde", "aviso_clientes.hasta"]
MAX_TEXTO = 600


def _fecha(texto):
    try:
        return date.fromisoformat(texto) if texto else None
    except ValueError:
        return None


def datos() -> dict:
    """{"texto": {"es", "en"}, "desde": date|None, "hasta": date|None}"""
    filas = {a.clave: a.valor for a in db.session.scalars(db.select(Ajuste).where(Ajuste.clave.in_(CLAVES)))}
    return {"texto": {i: filas.get(f"aviso_clientes.{i}", "") for i in IDIOMAS},
            "desde": _fecha(filas.get("aviso_clientes.desde")), "hasta": _fecha(filas.get("aviso_clientes.hasta"))}


def errores(textos: dict, desde, hasta) -> list:
    lista = []
    if any(len((t or "").strip()) > MAX_TEXTO for t in textos.values()):
        lista.append(("texto", MAX_TEXTO))
    if desde and hasta and hasta < desde:
        lista.append(("fechas", None))
    return lista


def guardar(textos: dict, desde, hasta) -> str:
    """Sin commit. Devuelve el texto para la auditoría ("" si no cambia nada)."""
    antes = datos()
    nuevos = {f"aviso_clientes.{i}": (textos.get(i) or "").replace("\r\n", "\n").strip()[:MAX_TEXTO]
              for i in IDIOMAS}
    nuevos["aviso_clientes.desde"] = desde.isoformat() if desde else ""
    nuevos["aviso_clientes.hasta"] = hasta.isoformat() if hasta else ""
    for clave, valor in nuevos.items():
        fila = db.session.get(Ajuste, clave)
        if not valor:
            if fila is not None:
                db.session.delete(fila)
        elif fila is None:
            db.session.add(Ajuste(clave=clave, valor=valor))
        else:
            fila.valor = valor
    despues = {"texto": {i: nuevos[f"aviso_clientes.{i}"] for i in IDIOMAS}, "desde": desde, "hasta": hasta}
    if despues == antes:
        return ""
    if not any(despues["texto"].values()):
        return "aviso para clientes quitado"
    fechas = f" ({desde or '…'} → {hasta or '…'})" if desde or hasta else ""
    return "aviso para clientes: " + " / ".join(t for t in despues["texto"].values() if t)[:200] + fechas


def quitar() -> str:
    return guardar({}, None, None)


def huella(texto) -> str:
    return hashlib.sha256(texto.encode()).hexdigest()[:16]


def estado(hoy=None) -> str:
    """Para la página de ajustes: "sin_aviso", "programado" (empieza más adelante), "caducado" o "visible"."""
    d, hoy = datos(), hoy or date.today()
    if not any(d["texto"].values()):
        return "sin_aviso"
    if d["desde"] and hoy < d["desde"]:
        return "programado"
    if d["hasta"] and hoy > d["hasta"]:
        return "caducado"
    return "visible"


def para(usuario, idioma, hoy=None):
    """El aviso que tiene que ver este usuario ahora: {"texto", "huella"} o None (no hay aviso, no
    está en fechas, no es un cliente o ya lo cerró)."""
    if usuario.rol != "cliente":
        return None
    d, hoy = datos(), hoy or date.today()
    if (d["desde"] and hoy < d["desde"]) or (d["hasta"] and hoy > d["hasta"]):
        return None
    otro = "en" if idioma == "es" else "es"
    texto = d["texto"].get(idioma) or d["texto"].get(otro)
    if not texto:
        return None
    marca = huella(texto)
    if usuario.aviso_cerrado == marca:
        return None
    return {"texto": texto, "huella": marca}
