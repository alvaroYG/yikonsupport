import pytest

from app import create_app
from app.extensions import db
import json
from io import BytesIO

from app.models import Cliente, ComponenteKit, Kit, Producto, User


@pytest.fixture
def app():
    """
    Escenario de prueba:
      Clínica A  ← FAS "loga"   ← usuario cliente "cliA"
      Clínica B  ← FAS "logb"   ← usuario cliente "cliB"
      Almacén: "ofi" (rol "logistica") · Facturación: "fac"
      Soporte ChromGo: "sop" (Yikon) · Cliente ChromGo: "chrA" (Clínica A) y "chrB" (Clínica B)
    """
    app = create_app("test")
    with app.app_context():
        db.create_all()
        a = Cliente(nombre="Clínica A", cif="B11111111", prefijo="CLA")
        b = Cliente(nombre="Clínica B", cif="B22222222", prefijo="CLB")
        p1 = Producto(referencia="P1", nombre="Kit 1", precio=100)
        # Kit "K1" = 1 × P1, a 100 € (mismo importe que P1 suelto: así los importes de los
        # tests de antes siguen cuadrando). Es un kit MONTADO (su stock es el de P1); los kits
        # cerrados, con stock propio, se prueban en test_kits_cerrados.py
        k1 = Kit(referencia="K1", nombre="Kit uno", precio=100, cerrado=False,
                 componentes=[ComponenteKit(producto=p1, cantidad=1)])
        db.session.add_all([a, b, p1, k1])

        def usuario(email, rol, **extra):
            u = User(nombre=email, email=f"{email}@ejemplo.com", rol=rol, **extra)
            u.set_password("password123")
            db.session.add(u)
            return u

        usuario("admin", "admin")
        # "loga" y "logb" son FAS (antes "logistics"): cada uno lleva una clínica
        usuario("loga", "fas", clientes_asignados=[a])
        usuario("logb", "fas", clientes_asignados=[b])
        usuario("ofi", "logistica")          # Almacén (rol "logistica"): los pedidos desde «aceptado»
        usuario("fac", "facturacion")        # Facturación: proformas, facturas, clientes, precios
        usuario("cliA", "cliente", empresa=a)
        usuario("cliB", "cliente", empresa=b)
        # Soporte ChromGo: "sop" (equipo de Yikon) y un usuario Cliente ChromGo por clínica
        usuario("sop", "soporte")
        usuario("chrA", "cliente_chromgo", empresa=a)
        usuario("chrB", "cliente_chromgo", empresa=b)
        db.session.commit()
        yield app
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


def login(client, usuario):
    return client.post("/auth/login", data={"email": f"{usuario}@ejemplo.com",
                                            "password": "password123"})


def confirmar_correos():
    """Revisión de correos (app/revision_correo.py): lo que genera el equipo de Yikon no sale
    hasta que su autor pulsa «Enviar» en la ventana de revisión. Esto hace lo mismo, sin cambiar
    el texto, para cada autor con correos pendientes (con su propio navegador de pruebas, para no
    tocar la sesión del test). Devuelve cuántos ha confirmado: así el test comprueba de paso que
    ese correo pasaba por la revisión. Solo los pendientes: los que ya fallaron no se repiten."""
    from flask import current_app, g

    from app.models import CorreoBorrador, User
    db.session.expire_all()
    autores = db.session.scalars(db.select(CorreoBorrador.autor_id).where(
        CorreoBorrador.estado == "pendiente").distinct()).all()
    confirmados = 0
    for autor in autores:
        # En los tests todas las peticiones comparten el contexto de la app (y su `g`), donde
        # Flask-Login guarda el usuario de la última petición: se quita para que cada navegador
        # use el suyo (si no, el login de aquí vería al usuario del test y no entraría).
        g.pop("_login_user", None)
        navegador = current_app.test_client()
        navegador.post("/auth/login", data={"email": db.session.get(User, autor).email,
                                            "password": "password123"})
        for c in navegador.get("/correos-revision/pendientes").get_json()["correos"]:
            if c["estado"] != "pendiente":
                continue
            r = navegador.post(f"/correos-revision/{c['id']}", json={
                "version": c["version"], "accion": "enviar", "asunto": c["asunto"], "texto": c["texto"]})
            assert r.status_code in (200, 502), r.get_json()      # 502: falló la entrega (se registra)
            confirmados += 1
    g.pop("_login_user", None)                    # el test sigue con su propio usuario
    db.session.expire_all()
    return confirmados


def contenido(kits=(), sueltos=None):
    """El JSON que arma pedido.js. kits: [(kit_id, nº de kits, {producto_id: cantidad}), ...]
    · sueltos: {producto_id: cantidad} (solo admin/logistics)."""
    return json.dumps({
        "kits": [{"kit_id": k, "cantidad": n, "productos": [{"producto_id": p, "cantidad": c} for p, c in prods.items()]}
                 for k, n, prods in kits],
        "sueltos": [{"producto_id": p, "cantidad": c} for p, c in (sueltos or {}).items()],
    })


def doc_pedido(nombre="pedido.pdf"):
    """El documento del pedido (orden de compra), obligatorio al crear cualquier pedido."""
    return (BytesIO(b"%PDF-1.4 orden de compra"), nombre)


def pedido_cliente(client, referencia=None, cantidad=1, con_proforma=False):
    """El usuario cliente logueado pide `cantidad` kits K1 (= `cantidad` × P1).
    La referencia de su empresa es obligatoria: si no se indica, se inventa una única.

    Los pedidos del cliente empiezan como "proforma solicitada". Para los tests que no van
    de la proforma, se deja directamente en "aceptado" (como si ya la hubiera aceptado);
    con_proforma=True lo deja en la fase de proforma (tests de test_proformas.py)."""
    import uuid
    datos = {"contenido": contenido([(1, cantidad, {1: cantidad})]), "fecha": "2026-09-25",
             "referencia": referencia or f"OC-{uuid.uuid4().hex[:8]}", "documento": doc_pedido()}
    r = client.post("/pedidos/nuevo", data=datos)
    if not con_proforma:
        proforma_aceptada()
    return r


def proforma_aceptada():
    """Atajo de los tests: los pedidos en "proforma solicitada" pasan a "aceptado"."""
    from app.inventario import reservas
    from app.models import Pedido
    for p in db.session.scalars(db.select(Pedido).filter_by(estado="proforma_solicitada")):
        p.estado, p.con_proforma = "aceptado", False   # como un pedido creado por Yikon (sin proforma)
        # ...y, como ellos, reserva al nacer los lotes libres que caducan antes (FEFO). Si en
        # ese momento no hay stock no reserva nada: lo que entre DESPUÉS no se asigna solo
        # (para eso está reservar_lotes)
        reservas.reservar_automatico(p)
    db.session.commit()


def reservar_lotes(client, pedido_id):
    """Botón "Reparto automático" de la tarjeta "Lotes de este pedido": reserva para el pedido
    los lotes libres que caducan antes (FEFO). Hace falta cuando el stock se registra DESPUÉS
    de crear el pedido: sin lotes reservados no se puede enviar.
    Quien llama tiene que estar logueado con un usuario con permiso pedidos.editar
    (admin, "ofi" o el FAS del cliente)."""
    return client.post(f"/pedidos/{pedido_id}/lotes", data={"accion": "automatico"})


# Bytes mínimos que empiezan como un JPEG real (la app comprueba la "firma" del archivo)
FOTO_JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 200


def subir_foto(client, pedido_id, contenido=FOTO_JPG, nombre="foto.jpg"):
    from io import BytesIO
    return client.post(f"/pedidos/{pedido_id}/fotos",
                       data={"fotos": (BytesIO(contenido), nombre)},
                       content_type="multipart/form-data")


def llevar_a_validado(client, pedido_id, logistics="loga"):
    """Desde "en preparación": admin sube foto y lo manda a validar; logistics lo valida."""
    login(client, "admin")
    subir_foto(client, pedido_id)
    client.post(f"/pedidos/{pedido_id}/enviar-validacion")
    client.post("/auth/logout")
    login(client, logistics)
    client.post(f"/pedidos/{pedido_id}/validar", data={"aprobar": "1"})
    client.post("/auth/logout")


def ref(prefijo, numero):
    """La referencia interna que recibe el pedido nº `numero` de este año de un cliente: YK-2026-CLA-1."""
    from app.models import anio_actual, referencia_pedido
    return referencia_pedido(anio_actual(), prefijo, numero)


def pdf_proforma():
    """El PDF que adjunta Yikon al enviar una proforma (obligatorio)."""
    return (BytesIO(b"%PDF-1.4 proforma de Yikon"), "Proforma Yikon.pdf")
