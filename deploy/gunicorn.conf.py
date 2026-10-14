# Configuración de gunicorn (el servidor que ejecuta la plataforma en producción).
# Lo arranca systemd con:  gunicorn -c deploy/gunicorn.conf.py run:app   (ver deploy/yikonpo.service)

# Solo escucha en el propio servidor: desde fuera se entra por nginx, que pone el HTTPS.
bind = "127.0.0.1:8000"

# Procesos que atienden visitas a la vez. Regla habitual: (2 × núcleos) + 1. Con 2 núcleos, 5;
# 3 es de sobra para empezar y gasta menos memoria.
workers = 3

# Segundos máximos por petición (subir varias fotos desde el móvil con mala cobertura tarda).
timeout = 120

# Cada proceso se renueva tras este número de peticiones (por si alguno fuera acumulando memoria).
max_requests = 1000
max_requests_jitter = 100

# Registro: a la salida estándar, que systemd guarda (se lee con: journalctl -u yikonpo)
accesslog = "-"
errorlog = "-"
