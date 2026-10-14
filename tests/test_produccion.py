"""Lo que solo se activa en producción (app/produccion.py) y la comprobación /salud."""
import pytest

from app import produccion


def test_salud_responde_sin_login(app, client):
    r = client.get("/salud")
    assert r.status_code == 200 and r.get_data(as_text=True) == "ok\n"


def test_detras_de_nginx_se_ve_la_ip_real_y_el_https(app, client):
    from flask import request, url_for

    @app.route("/_prueba_proxy")
    def _prueba():
        return f"{request.remote_addr}|{url_for('auth.login', _external=True)}"

    cabeceras = {"X-Forwarded-For": "203.0.113.7", "X-Forwarded-Proto": "https", "X-Forwarded-Host": "yikonsupport.com"}
    # sin proxy configurado, las cabeceras se ignoran (cualquiera podría falsearlas)
    assert client.get("/_prueba_proxy", headers=cabeceras).get_data(as_text=True) == "127.0.0.1|http://localhost/auth/login"
    produccion.detras_de_proxy(app, 1)
    assert (client.get("/_prueba_proxy", headers=cabeceras).get_data(as_text=True)
            == "203.0.113.7|https://yikonsupport.com/auth/login")


def test_el_limite_de_login_cuenta_por_visitante_y_no_por_nginx(app, client):
    from app.models import IntentoLogin
    from app.extensions import db
    produccion.detras_de_proxy(app, 1)
    client.post("/auth/login", data={"email": "admin@ejemplo.com", "password": "mala"},
                headers={"X-Forwarded-For": "203.0.113.7"})
    client.post("/auth/login", data={"email": "admin@ejemplo.com", "password": "mala"},
                headers={"X-Forwarded-For": "198.51.100.9"})
    assert {i.ip for i in db.session.scalars(db.select(IntentoLogin))} == {"203.0.113.7", "198.51.100.9"}


def test_en_produccion_no_arranca_sin_base_de_datos_ni_con_clave_corta(app, monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    with pytest.raises(RuntimeError, match="Falta DATABASE_URL"):
        produccion.comprobar(app)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:c@localhost/plataforma")
    monkeypatch.setitem(app.config, "SECRET_KEY", "corta")
    with pytest.raises(RuntimeError, match="SECRET_KEY es demasiado corta"):
        produccion.comprobar(app)


def test_en_produccion_avisa_de_lo_que_falta_sin_impedir_arrancar(app, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:c@localhost/plataforma")
    monkeypatch.setitem(app.config, "SECRET_KEY", "x" * 64)
    monkeypatch.setitem(app.config, "SQLALCHEMY_DATABASE_URI", "postgresql+psycopg://u:c@localhost/plataforma")
    monkeypatch.setitem(app.config, "MAIL_SERVER", None)
    avisos = " ".join(produccion.comprobar(app))
    assert "Falta MAIL_SERVER" in avisos and "Falta ADMIN_EMAILS" in avisos
