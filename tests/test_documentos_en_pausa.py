"""
Documentos internos EN PAUSA (config DOCUMENTOS_INTERNOS = False, como va en producción de momento).
No se ven ni se puede entrar; los documentos de cada PEDIDO (otra cosa) siguen funcionando.
"""
import pytest

from app.extensions import db
from app.models import User
from app.navegacion import menu_lateral
from app.permisos import PERMISOS, ROLES, tiene_permiso
from tests.conftest import login


@pytest.fixture
def en_pausa(app):
    app.config["DOCUMENTOS_INTERNOS"] = False
    return app


def _usuario(nombre):
    return db.session.scalar(db.select(User).filter_by(email=f"{nombre.lower()}@ejemplo.com"))


def test_nadie_tiene_permisos_de_documentos_internos(en_pausa):
    permisos = [p for p in PERMISOS if p.startswith("documentos.")]
    assert permisos                                   # si se renombran, este test tiene que enterarse
    for permiso in permisos:
        for rol in ROLES:
            assert tiene_permiso(rol, permiso) is False, (rol, permiso)
    assert _usuario("admin").puede("documentos.ver") is False


def test_los_documentos_de_los_pedidos_no_se_tocan(en_pausa):
    assert _usuario("admin").puede("pedidos.documentos.ver") is True
    assert _usuario("cliA").puede("pedidos.documentos.subir") is True


def test_las_paginas_no_existen(en_pausa, client):
    login(client, "admin")
    assert client.get("/documentos/").status_code == 404
    assert client.post("/documentos/nuevo", data={"titulo": "x"}).status_code == 404


def test_no_salen_en_el_menu_ni_en_el_buscador(en_pausa, client):
    claves = [s["clave"] for s in menu_lateral(_usuario("admin"), "main.inicio", "main", None)]
    assert claves == ["pedidos", "catalogo", "clientes", "soporte", "admin"]      # sin "equipo"
    login(client, "admin")
    assert "/documentos/" not in client.get("/").get_data(as_text=True)
    assert "Documentos internos" not in client.get("/buscar?q=logo&lista=1").get_data(as_text=True)


def test_al_activarlos_vuelven(en_pausa, client):
    en_pausa.config["DOCUMENTOS_INTERNOS"] = True
    login(client, "admin")
    assert client.get("/documentos/").status_code == 200
