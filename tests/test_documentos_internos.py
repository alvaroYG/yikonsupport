"""Documentos internos de Yikon: solo el equipo, con versiones."""
from io import BytesIO

from app.extensions import db
from app.models import DocumentoInterno, VersionDocumento
from tests.conftest import login

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 50
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


def _subir(client, titulo="Logo Yikon", nombre="logo.png", datos=PNG, categoria="marca", **extra):
    return client.post("/documentos/nuevo", content_type="multipart/form-data",
                       data={"titulo": titulo, "categoria": categoria, "descripcion": "Color, fondo transparente",
                             "archivo": (BytesIO(datos), nombre), **extra})


def test_quien_ve_la_seccion(app, client):
    for usuario, esperado in [("admin", 200), ("ofi", 200), ("loga", 200), ("sop", 200), ("cliA", 403), ("chrA", 403)]:
        login(client, usuario)
        assert client.get("/documentos/").status_code == esperado, usuario
        client.post("/auth/logout")


def test_subir_buscar_y_descargar(app, client):
    login(client, "admin")                                   # solo admin sube
    assert _subir(client, titulo="Logo Yikon color").status_code == 302
    _subir(client, titulo="Plantilla de oferta", nombre="oferta.docx", datos=b"PK docx", categoria="plantillas")
    client.get("/documentos/")                               # (se lleva el aviso "subido")
    doc = db.session.scalar(db.select(DocumentoInterno).filter_by(titulo="Logo Yikon color"))
    assert doc.vigente.numero == 1 and doc.vigente.subido_por.email == "admin@ejemplo.com"
    html = client.get("/documentos/?carpeta=marca").get_data(as_text=True)
    assert "Logo Yikon color" in html and "Plantilla de oferta" not in html
    html = client.get("/documentos/?q=oferta").get_data(as_text=True)           # busca también por archivo
    assert "Plantilla de oferta" in html and "Logo Yikon color" not in html
    r = client.get(f"/documentos/archivo/{doc.vigente.id}")
    assert r.data == PNG and "attachment" in r.headers["Content-Disposition"]
    r = client.get(f"/documentos/archivo/{doc.vigente.id}/vista")               # miniatura del logo
    assert r.status_code == 200 and r.mimetype == "image/png"


def test_nueva_version_guarda_el_historial(app, client):
    login(client, "admin")
    _subir(client, titulo="Logo Yikon color")
    doc = db.session.scalar(db.select(DocumentoInterno))
    primera = doc.vigente
    client.post(f"/documentos/{doc.id}/version", content_type="multipart/form-data",
                data={"archivo": (BytesIO(PNG + b"v2"), "logo_2026.png"), "nota": "Nuevo color"})
    db.session.refresh(doc)
    assert [v.numero for v in doc.versiones] == [2, 1]
    assert doc.vigente.nombre_original == "logo_2026.png" and doc.vigente.nota == "Nuevo color"
    assert client.get(f"/documentos/archivo/{primera.id}").data == PNG          # la antigua sigue ahí
    assert "Historial de versiones" in client.get(f"/documentos/{doc.id}").get_data(as_text=True)


def test_formatos_de_diseno_y_seguridad(app, client):
    login(client, "admin")
    assert _subir(client, titulo="Logo vectorial", nombre="logo.svg", datos=SVG).status_code == 302
    v = db.session.scalar(db.select(VersionDocumento).filter_by(extension="svg"))
    # un SVG puede llevar código: nunca se enseña dentro de la web, solo se descarga
    assert client.get(f"/documentos/archivo/{v.id}/vista").status_code == 404
    assert "attachment" in client.get(f"/documentos/archivo/{v.id}").headers["Content-Disposition"]
    for nombre in ("logo.ai", "logo.eps", "fuente.otf", "presentacion.pptx"):
        assert _subir(client, titulo=nombre, nombre=nombre, datos=b"datos").status_code == 302, nombre
    # ejecutables fuera; y un "png" que no es una imagen tampoco entra
    r = _subir(client, titulo="virus", nombre="virus.exe", datos=b"MZ")
    assert r.status_code == 400 and "no admitido" in r.get_data(as_text=True)
    r = _subir(client, titulo="falso", nombre="falso.png", datos=b"<html>")
    assert r.status_code == 400 and "no es una imagen" in r.get_data(as_text=True)
    assert db.session.scalar(db.select(db.func.count(DocumentoInterno.id)).filter_by(titulo="falso")) == 0


def test_permisos_de_escritura(app, client):
    login(client, "admin"); _subir(client); client.post("/auth/logout")
    doc = db.session.scalar(db.select(DocumentoInterno))
    login(client, "sop")                                         # soporte: solo consulta
    assert _subir(client, titulo="otro").status_code == 403
    assert client.post(f"/documentos/{doc.id}/borrar").status_code == 403
    client.post("/auth/logout")
    for usuario in ("loga", "ofi"):                              # FAS y Logística: solo consulta
        login(client, usuario)
        assert _subir(client, titulo="otro").status_code == 403
        assert client.post(f"/documentos/{doc.id}/borrar").status_code == 403
        assert client.get(f"/documentos/archivo/{doc.vigente.id}").status_code == 200
        client.post("/auth/logout")
    client.post("/auth/logout")
    login(client, "cliA")                                        # el cliente: nada, ni descargar
    assert client.get(f"/documentos/archivo/{doc.vigente.id}").status_code == 403
    client.post("/auth/logout")
    login(client, "admin")
    client.post(f"/documentos/{doc.id}/borrar")
    assert db.session.scalar(db.select(db.func.count(VersionDocumento.id))) == 0


def test_webp_falso_no_entra(app, client):
    login(client, "admin")
    r = _subir(client, titulo="falso webp", nombre="w.webp", datos=b"RIFF<html><script>")
    assert r.status_code == 400
    assert _subir(client, titulo="webp bueno", nombre="b.webp", datos=b"RIFF\x00\x00\x00\x00WEBPVP8 ").status_code == 302
