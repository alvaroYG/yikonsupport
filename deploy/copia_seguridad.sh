#!/usr/bin/env bash
# Copia de seguridad diaria: la base de datos y los archivos subidos.
# La lanza cron cada noche con el usuario yikonpo (paso 9 de DESPLIEGUE.md).
#
#   /srv/yikonpo/copias/AAAA-MM-DD_HHMM/
#       base_de_datos.dump     (pg_dump en formato "custom": se restaura con pg_restore)
#       archivos.tar.gz        (fotos, documentos, facturas, SDS)
#
# Guarda las de los últimos DIAS días y borra las más antiguas.
# IMPORTANTE: estas copias están en el MISMO servidor. Sirven si se borra algo por error,
# pero no si se pierde el servidor: copia además la carpeta fuera (ver DESPLIEGUE.md).
set -euo pipefail

BASE=/srv/yikonpo
cd "$BASE"   # carpeta de trabajo propia (si no, falla al lanzarlo desde la carpeta de otro usuario)
DIAS=14
DESTINO="$BASE/copias/$(date +%F_%H%M)"

# La dirección de la base de datos sale del mismo .env que usa la plataforma. Se lee solo esa
# línea (no se ejecuta el archivo: otras líneas llevan espacios o símbolos que bash no entiende).
DATABASE_URL="$(grep -E '^DATABASE_URL=' "$BASE/app/.env" | head -1 | cut -d= -f2-)"
if [ -z "$DATABASE_URL" ]; then echo "No encuentro DATABASE_URL en $BASE/app/.env" >&2; exit 1; fi
# pg_dump no entiende el "+psycopg" que usa SQLAlchemy en la dirección
URL_PG="${DATABASE_URL/postgresql+psycopg:/postgresql:}"

mkdir -p "$DESTINO"
pg_dump --format=custom --file="$DESTINO/base_de_datos.dump" "$URL_PG"
tar -czf "$DESTINO/archivos.tar.gz" -C "$BASE" datos
chmod -R go-rwx "$DESTINO"

# Fuera las de hace más de DIAS días
find "$BASE/copias" -mindepth 1 -maxdepth 1 -type d -mtime +"$DIAS" -exec rm -rf {} +

echo "Copia hecha en $DESTINO ($(du -sh "$DESTINO" | cut -f1))"
