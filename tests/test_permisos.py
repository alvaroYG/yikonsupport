"""Capa 1: qué PANTALLAS puede abrir cada rol."""
import pytest

from tests.conftest import login

# Usuarios del escenario (conftest): admin · fac = Facturación · ofi = Almacén (rol "logistica") ·
# loga = FAS · sop = Soporte ChromGo · cliA = Cliente · chrA = Cliente ChromGo
USUARIOS = ["admin", "fac", "ofi", "loga", "sop", "cliA", "chrA"]
MATRIZ = [
    ("/clientes/", {"admin", "fac", "loga"}),               # Almacén no ve fichas de clientes
    ("/clientes/nuevo", {"admin", "loga"}),                # Soporte de cliente da de alta los suyos; Facturación no (15/10)
    ("/productos/", {"admin", "fac", "ofi", "loga"}),
    ("/productos/nuevo", {"admin", "fac"}),                 # Almacén: solo el mínimo, desde Inventario
    ("/productos/catalogo", {"cliA"}),
    ("/pedidos/", {"admin", "fac", "ofi", "loga", "cliA"}),
    ("/pedidos/nuevo", {"admin", "fac", "loga", "cliA"}),   # Almacén no crea pedidos
    ("/pedidos/preparar", {"admin", "ofi"}),                # prepara y hace fotos Almacén
    ("/mensajes/", {"admin", "fac", "ofi", "loga", "cliA"}),
    ("/facturas/", {"admin", "fac", "loga"}),               # FAS: consulta (las de sus clientes)
    ("/facturas/nueva", {"admin", "fac"}),
    ("/facturas/mias", {"cliA"}),
    ("/inventario/", {"admin", "fac", "ofi"}),              # Facturación: consulta
    ("/soporte/", {"admin", "loga", "sop", "chrA"}),        # cliA: solo si se le da acceso
    ("/soporte/nuevo", {"admin", "sop", "chrA"}),
    ("/documentos/", {"admin", "fac", "ofi", "loga", "sop"}),   # todos menos los clientes
    ("/admin/usuarios", {"admin"}),
    ("/admin/auditoria", {"admin"}),
    ("/estadisticas", {"admin", "fac"}),
]


@pytest.mark.parametrize("usuario", USUARIOS)
@pytest.mark.parametrize("ruta,permitidos", MATRIZ)
def test_matriz_de_permisos(client, usuario, ruta, permitidos):
    login(client, usuario)
    r = client.get(ruta)
    esperado = 200 if usuario in permitidos else 403
    # (el inicio de Soporte/Cliente ChromGo es la lista de tickets: / redirige, las demás son 200/403)
    assert r.status_code == esperado, f"{usuario} en {ruta}: {r.status_code}"


def test_cliente_con_acceso_a_soporte(app, client):
    """El acceso a Soporte ChromGo del rol Cliente se da por USUARIO (no por empresa)."""
    from app.extensions import db
    from app.models import User
    login(client, "cliA")
    assert client.get("/soporte/").status_code == 403
    u = db.session.scalar(db.select(User).filter_by(email="clia@ejemplo.com"))
    u.acceso_chromgo = True; db.session.commit()
    assert client.get("/soporte/").status_code == 200 and client.get("/soporte/nuevo").status_code == 200
    client.post("/auth/logout")
    login(client, "cliB")                                   # su compañera de otra empresa no, claro
    assert client.get("/soporte/").status_code == 403


def test_admin_da_el_acceso_a_soporte_desde_la_ficha_del_usuario(app, client):
    from app.extensions import db
    from app.models import User
    login(client, "admin")
    u = db.session.scalar(db.select(User).filter_by(email="clia@ejemplo.com"))
    datos = {"nombre": u.nombre, "email": u.email, "rol": "cliente", "cliente_id": u.cliente_id,
             "idioma": "", "activo": "y", "acceso_chromgo": "y"}
    client.post(f"/admin/usuarios/{u.id}", data=datos)
    db.session.refresh(u)
    assert u.acceso_chromgo
    # si deja de ser Cliente, la casilla no se queda puesta
    client.post(f"/admin/usuarios/{u.id}", data={**datos, "rol": "cliente_chromgo"})
    db.session.refresh(u)
    assert not u.acceso_chromgo


def test_usuario_cliente_necesita_empresa(client):
    login(client, "admin")
    r = client.post("/admin/usuarios/nuevo", data={
        "nombre": "X", "email": "x@ejemplo.com", "rol": "cliente", "cliente_id": 0,
        "activo": "y", "password": "password123"})
    assert "debe pertenecer a una empresa" in r.get_data(as_text=True)
