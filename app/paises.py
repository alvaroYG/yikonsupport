"""
Países de los clientes (facturación y envío). Se guarda el CÓDIGO ISO de 2 letras (ES, MX, AR…) y se
enseña el nombre en el idioma de quien mira (los nombres los da Babel, que ya usamos para traducir):
así «España» y «Spain» son el mismo país en el mapa, en «Por país» y en el albarán.

Los clientes de antes tenían el país escrito a mano: la migración lo pasó a su código cuando lo
reconoció (codigo_de); lo que no, se quedó tal cual y el formulario lo marca «revisar».
"""
import unicodedata

from babel import Locale
from flask_babel import get_locale

# Lo que Babel trae y no es un país al que enviar (regiones, códigos reservados…)
NO_SON_PAISES = {"EU", "EZ", "UN", "QO", "ZZ", "XA", "XB", "AC", "CP", "CQ", "DG", "EA", "IC", "TA"}
CODIGOS = sorted(c for c in Locale("en").territories if len(c) == 2 and c.isalpha() and c not in NO_SON_PAISES)
_VALIDOS = set(CODIGOS)
# Idiomas en los que se reconoce un país escrito a mano (los de los clientes de Europa y Latinoamérica)
IDIOMAS_RECONOCER = ("es", "en", "pt", "fr", "de", "it", "nl", "ca", "pl", "el")


# Los 27 de la Unión Europea (en sus facturas sale el EORI de Yikon y el del cliente)
UE = {"AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR", "HR", "HU", "IE", "IT", "LT", "LU",
      "LV", "MT", "NL", "PL", "PT", "RO", "SE", "SI", "SK"}


def es_ue(valor) -> bool:
    return valor in UE


def es_codigo(valor) -> bool:
    return bool(valor) and valor in _VALIDOS


def _idioma():
    try:
        return str(get_locale() or "es")
    except Exception:             # (fuera de una petición: el comando de la terminal, la migración…)
        return "es"


def nombre(valor, idioma=None) -> str:
    """El nombre del país en el idioma de ahora ("ES" → «España» / «Spain»). Si no es un código (un
    país escrito a mano que no se reconoció), el texto tal cual; vacío → ""."""
    if not valor:
        return ""
    if not es_codigo(valor):
        return valor
    return Locale.parse(idioma or _idioma()).territories.get(valor, valor)


def _sin_tildes(texto):
    return "".join(c for c in unicodedata.normalize("NFKD", texto.strip().lower()) if not unicodedata.combining(c))


def opciones(idioma=None) -> list:
    """[(código, nombre)] ordenados por el nombre en el idioma de ahora (sin que las tildes descoloquen)."""
    nombres = Locale.parse(idioma or _idioma()).territories
    return sorted(((c, nombres.get(c, c)) for c in CODIGOS), key=lambda x: _sin_tildes(x[1]))


_INDICE = None


def codigo_de(texto):
    """El código de un país escrito a mano en cualquiera de IDIOMAS_RECONOCER, o en su propio idioma
    («España», «Spain», «Espagne», «Deutschland», «es»…). None si no se reconoce."""
    global _INDICE
    if not texto:
        return None
    if texto.strip().upper() in _VALIDOS:
        return texto.strip().upper()
    if _INDICE is None:
        _INDICE = {}
        for idioma in IDIOMAS_RECONOCER:
            for c, n in Locale.parse(idioma).territories.items():
                if c in _VALIDOS:
                    _INDICE.setdefault(_sin_tildes(n), c)
        # Abreviaturas y formas habituales que no salen en esas listas
        for extra, c in (("eeuu", "US"), ("ee. uu.", "US"), ("ee.uu.", "US"), ("usa", "US"), ("uk", "GB"), ("holanda", "NL"),
                         ("deutschland", "DE"), ("osterreich", "AT"), ("schweiz", "CH"), ("suisse", "CH"),
                         ("sverige", "SE"), ("norge", "NO"), ("danmark", "DK"), ("suomi", "FI"), ("hellas", "GR")):
            _INDICE.setdefault(_sin_tildes(extra), c)
    return _INDICE.get(_sin_tildes(texto))
