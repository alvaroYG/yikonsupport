#!/usr/bin/env bash
# Avisos automáticos diarios a los clientes. La lanza el temporizador yikonpo-recordatorios.timer cada día
# a las 9:00 de España, con el usuario yikonpo (DESPLIEGUE.md, «Recordatorio de recepción»):
#   - «¿Ha recibido su pedido?»: el día después de la fecha estimada de entrega, si sigue «Enviado».
set -euo pipefail
cd /srv/yikonpo/app
date "+%F %T"
/srv/yikonpo/venv/bin/flask recordar-recepcion
