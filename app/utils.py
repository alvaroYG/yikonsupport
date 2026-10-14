import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from flask import current_app, request

from app.extensions import db


def es_url_segura(destino: str) -> bool:
    """Solo permite redirigir a rutas internas (evita 'open redirect')."""
    if not destino or not destino.startswith("/") or destino.startswith("//") \
            or "\\" in destino:
        return False
    partes = urlsplit(destino)
    return partes.scheme == "" and partes.netloc == ""


TAMANOS_DE_PAGINA = (10, 25, 50)


def paginar(select, parametro="pagina", tamano="por_pagina"):
    """Una página de resultados. ?pagina=N y ?por_pagina=10|25|50 (otro valor: el de siempre, 10).
    Si en una misma página hay dos listas (p. ej. la ficha del cliente: pedidos y facturas), cada una
    usa sus propios nombres (?pagina_pedidos=2&pagina_facturas=1) para no moverse las dos a la vez."""
    por_pagina = request.args.get(tamano, type=int)
    if por_pagina not in TAMANOS_DE_PAGINA:
        por_pagina = current_app.config["ELEMENTOS_POR_PAGINA"]
    return db.paginate(
        select,
        page=request.args.get(parametro, 1, type=int),
        per_page=por_pagina,
        error_out=False,
    )


def leer_orden(claves, parametro="orden"):
    """El orden pedido en la URL: ?orden=nombre (A→Z, menor→mayor) o ?orden=-nombre (al revés).
    Devuelve (clave, descendente), o (None, False) si no hay orden o la clave no es de las permitidas
    (así nadie puede ordenar por una columna que no está en la lista)."""
    valor = request.args.get(parametro, "")
    clave = valor[1:] if valor.startswith("-") else valor
    return (clave, valor.startswith("-")) if clave in claves else (None, False)


def ordenar(select, columnas, desempate=None, antes=(), parametro="orden"):
    """
    Ordena una consulta según la cabecera que se ha pulsado (?orden=clave / ?orden=-clave).
    columnas: {clave: expresión o (expresión, ...)}. Para texto, usar db.func.lower(...) y así
      «a» y «A» van juntas. Los vacíos van siempre al final, en los dos sentidos.
    desempate: columna para que el orden sea siempre el mismo entre páginas (p. ej. Modelo.id).
    antes: lo que va SIEMPRE primero, se ordene por lo que se ordene (p. ej. activos antes que inactivos).
    Sin orden válido en la URL devuelve la consulta tal cual (con su orden de siempre) y "".
    Devuelve (consulta, orden) — orden es el valor de la URL ("nombre", "-precio"...) para las cabeceras.
    """
    clave, desc = leer_orden(columnas, parametro)
    if clave is None:
        return select, ""
    exprs = columnas[clave] if isinstance(columnas[clave], (tuple, list)) else (columnas[clave],)
    orden = [(e.desc() if desc else e.asc()).nulls_last() for e in exprs]
    if desempate is not None:
        orden.append(desempate.desc() if desc else desempate.asc())
    return select.order_by(None).order_by(*antes, *orden), ("-" if desc else "") + clave


def ordenar_lista(filas, claves, parametro="orden"):
    """Lo mismo para listas que se calculan en Python (p. ej. el stock): claves = {clave: función
    que da el valor de una fila}. Los vacíos (None) van al final. Devuelve (filas, orden)."""
    clave, desc = leer_orden(claves, parametro)
    if clave is None:
        return filas, ""
    valor = claves[clave]
    con = [f for f in filas if valor(f) is not None]
    sin = [f for f in filas if valor(f) is None]
    texto = lambda v: v.lower() if isinstance(v, str) else v       # noqa: E731
    return sorted(con, key=lambda f: texto(valor(f)), reverse=desc) + sin, ("-" if desc else "") + clave


PRECIO_MAXIMO = Decimal("99999999.99")      # lo que cabe en las columnas Numeric(10, 2)


def leer_precio(texto):
    """
    Precio escrito a mano → Decimal con 2 decimales, o None si no es válido.
    Acepta '1850', '1850,50', '1.850,50', '1850.50' y '1.850' (punto de miles).
    Rechaza negativos, 'NaN', 'Infinity' y lo que no cabe en la base de datos.
    """
    t = (texto or "").strip().replace(" ", "").replace("€", "")
    if "," in t:
        t = t.replace(".", "").replace(",", ".")            # formato español: 1.850,50
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", t):
        t = t.replace(".", "")                              # 1.850 = mil ochocientos cincuenta
    try:
        valor = Decimal(t)
        if not valor.is_finite():
            return None
        valor = valor.quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None
    return valor if Decimal(0) <= valor <= PRECIO_MAXIMO else None


def hora_local(valor):
    """
    Las horas se guardan en UTC (ver ahora() en models.py). Para mostrarlas se pasan
    a la hora de Madrid (config ZONA_HORARIA), con su cambio de horario de verano.
    SQLite devuelve las fechas sin zona: se entienden como UTC.
    (En Windows, zoneinfo necesita el paquete "tzdata": está en requirements.txt.)
    """
    if valor is None:
        return None
    if valor.tzinfo is None:
        valor = valor.replace(tzinfo=timezone.utc)
    return valor.astimezone(ZoneInfo(current_app.config.get("ZONA_HORARIA", "Europe/Madrid")))


def ahora_local():
    return hora_local(datetime.now(timezone.utc))


# --------------------------------------------------------------------------- #
# Texto que escribe el usuario en un buscador
# --------------------------------------------------------------------------- #
def limpiar_busqueda(texto, largo=80) -> str:
    """Sin caracteres de control (un NUL rompería PostgreSQL o el Excel), sin espacios dobles y
    recortado."""
    texto = "".join(c for c in (texto or "") if c.isprintable() or c == " ")
    return " ".join(texto.split())[:largo]


def patron_like(texto) -> str:
    """"%texto%" para ILIKE, con % y _ escapados: buscar "100%" busca ese texto, no "cualquier
    cosa". Usar con .ilike(patron, escape="\\")."""
    return "%" + texto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def es_entero(texto) -> bool:
    """Solo dígitos 0-9 (str.isdigit() acepta también "²", que luego int() no sabe leer)."""
    return texto.isascii() and texto.isdigit()
