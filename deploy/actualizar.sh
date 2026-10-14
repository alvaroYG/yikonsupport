#!/usr/bin/env bash
# Poner en producción una versión nueva de la plataforma. Ejecutar en el servidor como yikonpo:
#     cd /srv/yikonpo/app && ./deploy/actualizar.sh
# Hace: copia de seguridad → descarga el código → dependencias → migraciones → reinicia → comprueba.
set -euo pipefail

BASE=/srv/yikonpo
cd "$BASE/app"

echo "1/6 Copia de seguridad (por si hay que volver atrás)…"
./deploy/copia_seguridad.sh

echo "2/6 Descargando el código…"
git pull --ff-only

echo "3/6 Dependencias…"
"$BASE/venv/bin/pip" install --quiet -r requirements.txt

echo "4/6 Migraciones de la base de datos…"
"$BASE/venv/bin/flask" db upgrade

echo "5/6 Reiniciando la plataforma…"
sudo systemctl restart yikonpo

echo "6/6 Comprobando que responde…"
sleep 3
curl --fail --silent http://127.0.0.1:8000/salud && echo "Actualizada y funcionando."
