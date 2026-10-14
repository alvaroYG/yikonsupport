"""
Idiomas de la plataforma (Flask-Babel).

Cómo funciona la traducción:
  1. En el código, cada texto visible se marca: _('Pedidos')  (en Python y en las plantillas).
  2. `pybabel extract` recorre el código y saca todos esos textos a messages.pot.
  3. Cada idioma tiene su catálogo: app/translations/en/LC_MESSAGES/messages.po,
     con pares  msgid "Pedidos"  →  msgstr "Orders".
  4. `pybabel compile` lo convierte a messages.mo (lo que lee la app).
  Los textos originales (msgid) están en español: si falta una traducción, se ve en español.
  Comandos exactos en el README (sección "Traducciones").
"""
from flask import has_request_context, request, session

IDIOMAS = {"es": "Español", "en": "English"}
IDIOMA_POR_DEFECTO = "es"


def elegir_idioma():
    """
    Flask-Babel llama a esta función en cada petición para saber en qué idioma pintar.
    Prioridad: 1) lo que el usuario eligió en su cuenta · 2) lo elegido en esta sesión
    (p. ej. en la pantalla de login) · 3) el idioma del navegador · 4) español.
    """
    if not has_request_context():
        return IDIOMA_POR_DEFECTO
    from flask_login import current_user
    if current_user and current_user.is_authenticated and current_user.idioma in IDIOMAS:
        return current_user.idioma
    if session.get("idioma") in IDIOMAS:
        return session["idioma"]
    return request.accept_languages.best_match(list(IDIOMAS)) or IDIOMA_POR_DEFECTO
