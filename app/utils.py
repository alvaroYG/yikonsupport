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
