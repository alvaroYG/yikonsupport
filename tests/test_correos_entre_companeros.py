"""Revisión de correos: los avisos ENTRE COMPAÑEROS del equipo salen solos (decidido el 14/10/2026).
Se siguen revisando los que llevan a alguien de fuera, las invitaciones y los reenvíos."""
import pytest
from flask import request

from app.correo import _a_la_cola, construir_compuesto
from app.extensions import db
from app.models import CorreoBorrador, CorreoEnviado, User
from app.revision_correo import solo_para_el_equipo
from tests.conftest import confirmar_correos, login


@pytest.fixture
def generar(app, client):
    """Una ruta de prueba que prepara un correo, como hace la plataforma, para los destinatarios
    y el tipo que se le digan (lo genera admin: alguien del equipo)."""
    @app.post("/prueba-companeros")
    def _generar():
        msg = construir_compuesto(request.args["para"].split(","), {
            "asunto": "Aviso", "texto": "Texto del aviso", "html": "<p>Texto del aviso</p>", "logo": None})
        _a_la_cola(msg, {"tipo": request.args.get("tipo", "interno.prueba")})
        db.session.commit()
        return "", 204
    login(client, "admin")
    app.extensions["correos_enviados"] = []

    def lanzar(para, tipo="interno.prueba"):
        client.post(f"/prueba-companeros?para={para}&tipo={tipo}")
        return app.extensions["correos_enviados"]
    return lanzar


def _borradores():
    return db.session.scalar(db.select(db.func.count(CorreoBorrador.id)))


def test_entre_companeros_sale_solo(app, generar):
    enviados = generar("ofi@ejemplo.com,LOGA@ejemplo.com")          # (da igual mayúsculas)
    assert len(enviados) == 1 and _borradores() == 0
    assert db.session.scalar(db.select(CorreoEnviado)).estado == "enviado"


@pytest.mark.parametrize("para", [
    "ofi@ejemplo.com,clia@ejemplo.com",          # un compañero y un cliente
    "ofi@ejemplo.com,almacen@clinica-a.com",     # un compañero y un email en copia de fuera
    "clia@ejemplo.com",                          # solo el cliente
])
def test_si_va_alguien_de_fuera_se_revisa(app, generar, para):
    assert generar(para) == [] and _borradores() == 1
    assert confirmar_correos() == 1 and len(app.extensions["correos_enviados"]) == 1


def test_un_compañero_dado_de_baja_no_cuenta_como_equipo(app, generar):
    ofi = db.session.scalar(db.select(User).filter_by(email="ofi@ejemplo.com"))
    ofi.activo = False
    db.session.commit()
    assert generar("ofi@ejemplo.com") == [] and _borradores() == 1


def test_la_invitacion_se_revisa_aunque_sea_para_un_compañero(app, generar):
    assert generar("ofi@ejemplo.com", tipo="invitacion") == [] and _borradores() == 1


def test_el_reenvio_de_un_aviso_interno_se_revisa(app, client, generar):
    generar("ofi@ejemplo.com")
    registro = db.session.scalar(db.select(CorreoEnviado))
    app.extensions["correos_enviados"].clear()
    client.post(f"/admin/correos/{registro.id}/reenviar")
    assert app.extensions["correos_enviados"] == [] and _borradores() == 1
    assert confirmar_correos() == 1
    assert [m["To"] for m in app.extensions["correos_enviados"]] == ["ofi@ejemplo.com"]


def test_solo_para_el_equipo(app):
    from email.message import EmailMessage

    def con(para):
        m = EmailMessage()
        if para is not None:
            m["To"] = para
        return solo_para_el_equipo(m)
    assert con("admin@ejemplo.com, sop@ejemplo.com, logb@ejemplo.com")
    assert not con("admin@ejemplo.com, chra@ejemplo.com")      # Cliente ChromGo: de fuera
    assert not con("nadie@ejemplo.com")                          # no es usuario
    assert not con(None) and not con("")
