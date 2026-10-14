from app.extensions import db
from app.models import User
from tests.conftest import login


def test_sin_login_redirige_a_login(client):
    r = client.get("/clientes/")
    assert r.status_code == 302 and "/auth/login" in r.headers["Location"]


def test_login_correcto_e_incorrecto(client):
    assert login(client, "admin").status_code == 302
    client.post("/auth/logout")
    r = client.post("/auth/login", data={"email": "admin@ejemplo.com", "password": "mal"})
    assert "incorrectos" in r.get_data(as_text=True)


def test_no_existe_registro_publico(client):
    assert client.get("/auth/register").status_code == 404


def test_open_redirect_bloqueado(client):
    r = client.post("/auth/login?next=https://malicioso.com",
                    data={"email": "admin@ejemplo.com", "password": "password123"})
    assert "malicioso" not in r.headers["Location"]
    r = client.post("/auth/login?next=//malicioso.com",
                    data={"email": "cliA@ejemplo.com", "password": "password123"})
    assert "malicioso" not in r.headers["Location"]


def test_usuario_desactivado_no_entra(app, client):
    u = db.session.scalar(db.select(User).filter_by(rol="cliente"))
    u.activo = False
    db.session.commit()
    r = login(client, "cliA")
    assert r.status_code == 200  # se queda en la página de login


def test_email_duplicado_da_error_de_formulario(client):
    login(client, "admin")
    r = client.post("/admin/usuarios/nuevo", data={
        "nombre": "Otro", "email": "loga@ejemplo.com", "rol": "logistics",
        "cliente_id": 0, "activo": "y", "password": "password123"})
    assert r.status_code == 200 and "Ya existe" in r.get_data(as_text=True)


def test_bloqueo_tras_varios_fallos(client):
    for _ in range(5):
        client.post("/auth/login", data={"email": "admin@ejemplo.com", "password": "mal"})
    # el 6º intento, AUNQUE la contraseña sea buena, se bloquea
    r = client.post("/auth/login", data={"email": "admin@ejemplo.com", "password": "password123"})
    assert r.status_code == 429 and "Demasiados intentos" in r.get_data(as_text=True)
    # otro usuario desde la misma IP todavía puede entrar (límite de IP más alto)
    assert login(client, "loga").status_code == 302


def test_login_correcto_limpia_los_fallos(client):
    for _ in range(4):
        client.post("/auth/login", data={"email": "admin@ejemplo.com", "password": "mal"})
    assert login(client, "admin").status_code == 302
    client.post("/auth/logout")
    for _ in range(4):
        client.post("/auth/login", data={"email": "admin@ejemplo.com", "password": "mal"})
    assert login(client, "admin").status_code == 302   # los 4 anteriores ya no cuentan


def test_noindex(client):
    assert "noindex" in client.get("/auth/login").headers["X-Robots-Tag"]
    assert "Disallow: /" in client.get("/robots.txt").get_data(as_text=True)
