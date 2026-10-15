"""
Dónde está un cliente, para el mapa de clientes (Clientes → Mapa).

Al guardar un cliente se busca su ciudad (con el código postal y el país de facturación, si los hay)
en Nominatim, el buscador libre de OpenStreetMap. Es una sola consulta por cliente y solo cuando
cambia su dirección; si no se encuentra (o no hay internet), el cliente se guarda igual y se sitúa
a mano haciendo clic en el mapa del formulario. Normas de uso de Nominatim: como mucho una consulta
por segundo y con un User-Agent que diga quién somos (lo cumplimos: aquí es una cada vez que alguien
guarda un cliente, y `flask situar-clientes` espera un segundo entre una y otra).

Se apaga con GEOCODIFICAR=0 en el .env (y en los tests, que no salen a internet).
"""
import json
import urllib.parse
import urllib.request

from flask import current_app

URL = "https://nominatim.openstreetmap.org/search"
CAMPOS_LUGAR = ("direccion", "codigo_postal", "ciudad", "provincia", "pais")


def buscar(ciudad=None, pais=None, codigo_postal=None, provincia=None):
    """(latitud, longitud) o None. Busca la CIUDAD (no la calle): para el mapa basta y falla menos."""
    if not current_app.config.get("GEOCODIFICAR") or not (ciudad or codigo_postal):
        return None
    consulta = {"format": "json", "limit": "1"}
    for clave, valor in (("city", ciudad), ("postalcode", codigo_postal), ("state", provincia), ("country", pais)):
        if valor:
            consulta[clave] = valor.strip()
    peticion = urllib.request.Request(URL + "?" + urllib.parse.urlencode(consulta), headers={
        "User-Agent": f"YikonGenomicsPO/1.0 ({current_app.config.get('URL_PLATAFORMA', '')})",
        "Accept-Language": "es,en"})
    try:
        with urllib.request.urlopen(peticion, timeout=6) as respuesta:
            resultados = json.load(respuesta)
    except Exception as e:                     # sin internet, Nominatim caído…: se sitúa a mano
        current_app.logger.warning("Mapa de clientes: no se ha podido buscar %s (%s)", consulta, e)
        return None
    if not resultados:
        # Sin la provincia o el código postal a veces sí aparece
        if codigo_postal or provincia:
            return buscar(ciudad, pais)
        return None
    return float(resultados[0]["lat"]), float(resultados[0]["lon"])


def situar(cliente) -> bool:
    """Busca y pone latitud/longitud del cliente (sin commit). True si lo ha encontrado."""
    lugar = buscar(cliente.ciudad, cliente.pais, cliente.codigo_postal, cliente.provincia)
    if lugar is None:
        return False
    cliente.latitud, cliente.longitud = lugar
    return True
