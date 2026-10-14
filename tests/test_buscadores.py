"""Buscador y filtros de las listas de Usuarios y Clientes."""
from app.extensions import db
from app.models import Cliente, User
from tests.conftest import login


def _nombres(client, url, candidatos):
    html = client.get(url).get_data(as_text=True)
    cuerpo = html[html.index("<tbody>"):html.index("</tbody>")]          # solo la tabla (no los desplegables)
    return {c for c in candidatos if c in cuerpo}


USUARIOS = ["admin@", "ofi@", "loga@", "logb@", "clia@", "clib@", "sop@", "chra@", "chrb@"]
CLINICAS = ["Clínica A", "Clínica B"]


def test_filtros_de_usuarios(app, client):
    login(client, "admin")
    assert _nombres(client, "/admin/usuarios", USUARIOS) == set(USUARIOS)
    assert _nombres(client, "/admin/usuarios?q=LOG", USUARIOS) == {"loga@", "logb@"}            # nombre o email, sin distinguir mayúsculas
    assert _nombres(client, "/admin/usuarios?rol=fas", USUARIOS) == {"loga@", "logb@"}
    assert _nombres(client, "/admin/usuarios?rol=cliente_chromgo", USUARIOS) == {"chra@", "chrb@"}
    # empresa: sus usuarios y el FAS que la lleva
    assert _nombres(client, "/admin/usuarios?cliente_id=1", USUARIOS) == {"clia@", "chra@", "loga@"}
    assert _nombres(client, "/admin/usuarios?cliente_id=1&rol=fas", USUARIOS) == {"loga@"}      # se combinan
    # estado
    u = db.session.scalar(db.select(User).filter_by(email="clib@ejemplo.com"))
    u.activo = False; db.session.commit()
    assert _nombres(client, "/admin/usuarios?estado=desactivados", USUARIOS) == {"clib@"}
    assert "clib@" not in _nombres(client, "/admin/usuarios?estado=activos", USUARIOS)
    # invitación pendiente = activos que aún no han entrado (admin acaba de entrar)
    pendientes = _nombres(client, "/admin/usuarios?estado=pendientes", USUARIOS)
    assert "admin@" not in pendientes and "clib@" not in pendientes and "loga@" in pendientes
    # valores raros en la URL no rompen nada
    assert client.get("/admin/usuarios?rol=xx&estado=yy&cliente_id=abc&pagina=999").status_code == 200
    assert "No hay usuarios con estos filtros" in client.get("/admin/usuarios?q=zzzz").get_data(as_text=True)


def test_filtros_de_clientes(app, client):
    b = db.session.scalar(db.select(Cliente).filter_by(nombre="Clínica B"))
    b.ver_precios, b.persona_contacto = True, "Marta Soler"
    db.session.add(Cliente(nombre="Clínica C", cif="B33333333", prefijo="CLC", activo=False))   # inactiva y sin FAS
    db.session.commit()
    todas = CLINICAS + ["Clínica C"]
    login(client, "admin")
    assert _nombres(client, "/clientes/", todas) == set(CLINICAS)                              # por defecto, activos
    assert _nombres(client, "/clientes/?estado=inactivos", todas) == {"Clínica C"}
    assert _nombres(client, "/clientes/?estado=todos", todas) == set(todas)
    assert _nombres(client, "/clientes/?inactivos=1", todas) == set(todas)                      # enlace antiguo
    assert _nombres(client, "/clientes/?q=soler", todas) == {"Clínica B"}                        # por contacto
    assert _nombres(client, "/clientes/?q=CLA", todas) == {"Clínica A"}                          # por prefijo
    assert _nombres(client, "/clientes/?precios=si", todas) == {"Clínica B"}
    assert _nombres(client, "/clientes/?precios=no", todas) == {"Clínica A"}
    loga = db.session.scalar(db.select(User).filter_by(email="loga@ejemplo.com"))
    assert _nombres(client, f"/clientes/?fas={loga.id}", todas) == {"Clínica A"}
    assert _nombres(client, "/clientes/?fas=ninguno&estado=todos", todas) == {"Clínica C"}
    assert client.get("/clientes/?fas=xx&precios=zz&estado=qq").status_code == 200
    client.post("/auth/logout")
    # el FAS solo busca entre sus clientes y no puede filtrar por otro FAS
    logb = db.session.scalar(db.select(User).filter_by(email="logb@ejemplo.com"))
    login(client, "loga")
    assert _nombres(client, "/clientes/?estado=todos", todas) == {"Clínica A"}
    assert _nombres(client, f"/clientes/?fas={logb.id}", todas) == {"Clínica A"}                # se ignora
    assert 'name="fas"' not in client.get("/clientes/").get_data(as_text=True)
