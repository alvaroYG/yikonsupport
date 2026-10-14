"""Idiomas: español por defecto, inglés si el navegador o el usuario lo piden."""
import os
import re

from babel.messages.pofile import read_po

from app.extensions import db
from app.models import Pedido, User
from tests.conftest import confirmar_correos, login, pedido_cliente

PO_EN = os.path.join(os.path.dirname(__file__), "..", "app", "translations", "en",
                     "LC_MESSAGES", "messages.po")


def test_por_defecto_en_espanol(client):
    html = client.get("/auth/login").get_data(as_text=True)
    assert 'lang="es"' in html and "Recordarme" in html


def test_navegador_en_ingles_ve_la_web_en_ingles(client):
    html = client.get("/auth/login", headers={"Accept-Language": "en-GB,en;q=0.9"}).get_data(as_text=True)
    assert 'lang="en"' in html and "Remember me" in html and "Recordarme" not in html


def test_el_usuario_elige_idioma_y_se_guarda_en_su_ficha(app, client):
    login(client, "cliA")
    client.post("/idioma", data={"idioma": "en"})
    assert db.session.scalar(db.select(User).filter_by(email="clia@ejemplo.com")).idioma == "en"
    html = client.get("/").get_data(as_text=True)
    assert "Last activity" in html and "Place an order" in html
    # Aunque el navegador pida español, manda lo que eligió el usuario
    html = client.get("/", headers={"Accept-Language": "es"}).get_data(as_text=True)
    assert "Last activity" in html


def test_idioma_desconocido_se_ignora(app, client):
    login(client, "cliA")
    client.post("/idioma", data={"idioma": "xx"})
    assert db.session.scalar(db.select(User).filter_by(email="clia@ejemplo.com")).idioma is None


def test_los_estados_y_los_importes_cambian_de_formato(app, client):
    login(client, "cliA")
    pedido_cliente(client)
    client.post("/idioma", data={"idioma": "en"})
    html = client.get("/pedidos/").get_data(as_text=True)
    assert "Accepted" in html and "Aceptado" not in html


def test_cada_cliente_recibe_el_correo_en_su_idioma(app, client):
    correos = app.extensions.setdefault("correos_enviados", [])
    db.session.scalar(db.select(User).filter_by(email="clia@ejemplo.com")).idioma = "en"
    db.session.commit()
    login(client, "cliA"); pedido_cliente(client); client.post("/auth/logout")
    p = db.session.scalar(db.select(Pedido).order_by(Pedido.id.desc()))
    correos.clear()
    login(client, "admin")                      # admin trabaja en español...
    client.post(f"/pedidos/{p.id}/preparacion")
    assert confirmar_correos() == 1
    msg = correos[0]                            # ...pero el cliente lo recibe en inglés
    assert "In preparation" in msg["Subject"] and "Your order" in msg["Subject"]
    assert "We're preparing your order" in msg.get_content()


def test_catalogo_ingles_completo_y_con_las_mismas_variables():
    """Si alguien añade un texto nuevo y olvida traducirlo (o rompe un %(x)s), falla aquí."""
    cat = read_po(open(PO_EN, "rb"))
    variables = lambda s: sorted(re.findall(r"%\((\w+)\)s", s))
    for m in cat:
        if not m.id:
            continue
        ids = m.id if isinstance(m.id, tuple) else (m.id,)
        textos = m.string if isinstance(m.string, tuple) else (m.string,)
        for original, traducido in zip(ids, textos):
            assert traducido, f"Falta traducir: {original!r}"
            assert variables(original) == variables(traducido), f"Variables distintas en {original!r}"


def test_todos_los_textos_marcados_estan_en_el_catalogo():
    """Si alguien marca un texto nuevo con _() y olvida actualizar el catálogo (pybabel
    extract/update), aquí falla y dice cuál. Es lo mismo que hace `pybabel extract`."""
    from babel.messages.extract import DEFAULT_KEYWORDS, extract_from_dir
    raiz = os.path.join(os.path.dirname(__file__), "..")
    metodos = [("app/**.py", "python"), ("app/templates/**.html", "jinja2"), ("app/templates/**.txt", "jinja2")]
    palabras = dict(DEFAULT_KEYWORDS, _l=None)
    extraidos = set()
    for _archivo, _linea, mensaje, _comentarios, _contexto in extract_from_dir(raiz, metodos, keywords=palabras):
        extraidos.add(mensaje if isinstance(mensaje, str) else tuple(mensaje))
    catalogo = {m.id for m in read_po(open(PO_EN, "rb")) if m.id}
    faltan = [m for m in extraidos if m not in catalogo]
    assert not faltan, f"Textos sin traducir (ejecuta pybabel extract/update y tradúcelos): {faltan}"
