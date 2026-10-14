"""Los archivos estáticos llevan ?v=<fecha del archivo>: tras una actualización, el navegador descarga
el JavaScript nuevo aunque nginx le deje guardar el viejo 7 días (antes hacía falta Ctrl+F5)."""
import os
import re

from flask import url_for

from tests.conftest import login


def test_los_estaticos_llevan_version_y_cambia_con_el_archivo(app, client):
    with app.test_request_context():
        url = url_for("static", filename="js/pedido.js")
        ruta = os.path.join(app.static_folder, "js/pedido.js")
        assert url == f"/static/js/pedido.js?v={int(os.stat(ruta).st_mtime)}"
        antes = os.stat(ruta)
        try:
            os.utime(ruta, (antes.st_atime, antes.st_mtime + 100))
            assert url_for("static", filename="js/pedido.js") != url          # cambia el archivo → cambia la dirección
        finally:
            os.utime(ruta, (antes.st_atime, antes.st_mtime))
        assert url_for("static", filename="no/existe.js") == "/static/no/existe.js"   # sin archivo, sin versión
    login(client, "admin")
    html = client.get("/pedidos/").get_data(as_text=True)
    assert re.search(r'src="/static/js/selectores_buscables\.js\?v=\d+"', html)
    assert client.get(re.search(r'src="(/static/js/pedido\.js\?v=\d+)"', html).group(1)).status_code == 200
