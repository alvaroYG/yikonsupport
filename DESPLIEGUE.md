# Poner la plataforma en producción

Guía paso a paso para instalar **Yikon Genomics PO** en un servidor alquilado (VPS) con el
dominio `yikonsupport.com`. Está pensada para **Ubuntu Server LTS** (22.04 o 24.04).

Cómo queda montado:

```
 Internet ──HTTPS──► nginx ──► gunicorn (la plataforma, Flask) ──► PostgreSQL
                     (puerto 443)   (127.0.0.1:8000, 3 procesos)      (base de datos)
                                           │
                                           └──► /srv/yikonpo/datos  (fotos, documentos, facturas)
```

Y dónde está cada cosa en el servidor:

| Ruta | Qué hay |
|---|---|
| `/srv/yikonpo/app` | El código (descargado de Git) y el `.env` |
| `/srv/yikonpo/venv` | Python y sus librerías |
| `/srv/yikonpo/datos` | Archivos subidos (fotos, documentos, PDF de facturas, SDS) |
| `/srv/yikonpo/copias` | Copias de seguridad diarias |

Los archivos de configuración ya están preparados en la carpeta [`deploy/`](deploy/):
`env.produccion.ejemplo`, `gunicorn.conf.py`, `yikonpo.service`, `nginx.conf`,
`copia_seguridad.sh` y `actualizar.sh`.

> **Qué está probado y qué no.** La plataforma se ha probado con PostgreSQL 16 (todas las
> migraciones desde cero y la batería de tests completa), arrancada con gunicorn en modo
> producción, y la copia de seguridad se ha restaurado en una base de datos nueva. Los pasos
> de sistema de esta guía (apt, nginx, certbot, systemd, cortafuegos) son los habituales en
> Ubuntu pero **no se han ejecutado en vuestro servidor**: síguelos con calma la primera vez
> y, si un comando da un error, no sigas al siguiente paso.


## Nuestro servidor (instalado el 13/10/2026)

| | |
|---|---|
| Web | https://yikonsupport.com (y `www`), HTTPS de Let's Encrypt que se renueva solo |
| Servidor | Hetzner Cloud **CAX11** (Arm64, 2 núcleos, 4 GB), Ubuntu 26.04 |
| IP | `2.31.22.223` |
| Entrar | Desde PowerShell: **`ssh alvaro@2.31.22.223`** (con tu clave SSH; te pide su frase de paso). `sudo` pide la contraseña de `alvaro`. **root no puede entrar** y no se entra con contraseña |
| Versiones | Python 3.14, PostgreSQL 18 |
| Correo saliente | Brevo (`smtp-relay.brevo.com`, puerto 587), remitente `avisos@yikonsupport.com`; dominio verificado en Brevo (registros en la zona DNS de dondominio) |
| DNS / dominio | dondominio |
| Copias | Cada noche a las 3:15 (hora del servidor, UTC) en `/srv/yikonpo/copias` (14 días) + **Backups de Hetzner** (diarios, 7). Administración → Estado avisa si falla (`COPIA_SEGURIDAD_MARCA`) |
| Actualizar | `sudo -u yikonpo -H bash -c "cd /srv/yikonpo/app && ./deploy/actualizar.sh"` |

Diferencias con la guía de abajo: el código se subió la primera vez con un `.tar.gz` (no había Git) y
después se convirtió en copia de Git; `copia_seguridad.sh` hace `cd "$BASE"` (si no, falla al
lanzarlo a mano desde la carpeta de otro usuario).

Código: GitHub privado `alvaroYG/yikonsupport`; el servidor lo descarga con una *deploy key* de solo
lectura (`/srv/yikonpo/.ssh/id_ed25519`). **Ojo con los scripts nuevos** (`.sh`): Git en Windows no
guarda el permiso de ejecución; al crear uno, márcalo una vez en tu PC con
`git update-index --chmod=+x deploy/nuevo.sh` antes del commit.

---

## 0. Antes de empezar (sin tocar el servidor)

- [ ] **Dominio** `yikonsupport.com` comprado, con una cuenta a nombre de la empresa y
      renovación automática. (Opcional: `yikonsupport.es`, para redirigirlo al `.com`.)
- [ ] **Servidor** contratado: Ubuntu LTS, 2 núcleos, 4 GB de memoria, 40–80 GB de disco,
      centro de datos en la UE, copias automáticas del proveedor activadas. Apunta su **IP**.
- [ ] **Correo saliente**: servidor SMTP, usuario y contraseña para una dirección del dominio
      (p. ej. `avisos@yikonsupport.com`). Te lo da quien gestione el correo del dominio.
- [ ] **Código en un repositorio Git privado** (ver `GIT.md`). El servidor lo descarga de ahí.
- [ ] **RGPD**: contrato de encargado del tratamiento con el proveedor y visto bueno interno.

### DNS: que el dominio apunte al servidor

En el panel del registrador del dominio, crea estos registros (cambia `IP_DEL_SERVIDOR`):

| Tipo | Nombre | Valor |
|---|---|---|
| A | `@` | `IP_DEL_SERVIDOR` |
| A | `www` | `IP_DEL_SERVIDOR` |

Tarda de unos minutos a unas horas. Se comprueba desde tu ordenador con
`nslookup yikonsupport.com`: debe devolver la IP del servidor. **El paso 7 (HTTPS) no
funciona hasta que esto responda bien.**

---

## 1. Entrar al servidor y asegurarlo

El proveedor te da un usuario (normalmente `root`) y una forma de entrar por SSH.

```bash
ssh root@IP_DEL_SERVIDOR
```

Actualiza el sistema y crea un usuario para ti (no se trabaja como `root`):

```bash
apt update && apt upgrade -y
adduser alvaro                    # te pide una contraseña: guárdala
usermod -aG sudo alvaro           # puede usar sudo
```

Cortafuegos: solo SSH y web.

```bash
ufw allow OpenSSH
ufw allow 'Nginx Full' 2>/dev/null || (ufw allow 80/tcp && ufw allow 443/tcp)
ufw enable
ufw status
```

A partir de aquí entra siempre con tu usuario: `ssh alvaro@IP_DEL_SERVIDOR`.

> Recomendado cuando todo funcione: entrar por SSH con clave en vez de contraseña y
> desactivar el acceso de `root` por SSH. El proveedor suele tener una guía propia.

## 2. Instalar lo necesario

```bash
sudo apt install -y python3 python3-venv python3-pip git nginx postgresql postgresql-client \
                    certbot python3-certbot-nginx
```

Crea el usuario del sistema que ejecutará la plataforma (sin contraseña: no entra nadie con
él) y sus carpetas:

```bash
sudo adduser --system --group --home /srv/yikonpo yikonpo
sudo mkdir -p /srv/yikonpo/datos/fotos_pedidos /srv/yikonpo/datos/documentos /srv/yikonpo/copias
sudo chown -R yikonpo:yikonpo /srv/yikonpo
sudo chmod 750 /srv/yikonpo
```

## 3. Base de datos (PostgreSQL)

Inventa una contraseña larga para la base de datos y guárdala (irá en el `.env`).
Usa solo letras y números: los símbolos como `@ : / #` rompen la dirección de conexión.

```bash
sudo -u postgres psql
```

Dentro de `psql` (cambia la contraseña):

```sql
CREATE USER yikonpo WITH PASSWORD 'CONTRASEÑA_DE_LA_BASE_DE_DATOS';
CREATE DATABASE yikonpo OWNER yikonpo;
\q
```

## 4. Descargar el código e instalar las librerías

```bash
sudo -u yikonpo -H bash          # a partir de aquí eres el usuario yikonpo
cd /srv/yikonpo
git clone URL_DE_TU_REPOSITORIO app
python3 -m venv venv
venv/bin/pip install --upgrade pip
venv/bin/pip install -r app/requirements.txt
```

> Si el repositorio es privado, `git clone` pedirá credenciales. Lo más limpio es una
> *deploy key* (clave SSH solo de lectura para ese repositorio): se crea con
> `ssh-keygen -t ed25519` y se pega la parte pública en la configuración del repositorio.

## 5. Configuración (`.env`)

```bash
cd /srv/yikonpo/app
cp deploy/env.produccion.ejemplo .env
chmod 600 .env
python3 -c "import secrets; print(secrets.token_hex(32))"     # copia el resultado
nano .env
```

Rellena al menos:

- `SECRET_KEY`: el texto que acabas de generar. **Nueva**, no la de tu ordenador.
- `DATABASE_URL`: cambia `CONTRASEÑA_DE_LA_BASE_DE_DATOS` por la del paso 3.
- `MAIL_SERVER`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_FROM`: el correo saliente.
- `ADMIN_EMAILS`: tu correo (recibirás los errores de la plataforma).
- `EMPRESA_DATOS`: dirección y CIF para la cabecera de las proformas.

Si falta `DATABASE_URL` o la `SECRET_KEY` es corta, la plataforma **no arranca** y dice qué
falta. Lo demás (correo, etc.) solo avisa en el registro.

## 6. Crear las tablas, el primer admin y arrancar

Todavía como `yikonpo`, en `/srv/yikonpo/app`:

```bash
../venv/bin/flask db upgrade                                  # crea todas las tablas
../venv/bin/flask crear-admin                                 # te pide email, nombre y contraseña
exit                                                          # vuelves a tu usuario
```

Instala el servicio para que arranque sola (también tras reiniciar el servidor):

```bash
sudo cp /srv/yikonpo/app/deploy/yikonpo.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now yikonpo
sudo systemctl status yikonpo          # debe decir "active (running)"
curl http://127.0.0.1:8000/salud       # debe responder: ok
```

Si no arranca: `sudo journalctl -u yikonpo -n 50` enseña el motivo (casi siempre, el `.env`).

## 7. nginx y HTTPS

```bash
sudo cp /srv/yikonpo/app/deploy/nginx.conf /etc/nginx/sites-available/yikonpo
sudo ln -s /etc/nginx/sites-available/yikonpo /etc/nginx/sites-enabled/
sudo rm -f /etc/nginx/sites-enabled/default
sudo usermod -aG yikonpo www-data      # nginx puede leer la carpeta static
sudo nginx -t && sudo systemctl reload nginx
```

Certificado HTTPS gratuito (Let's Encrypt). Necesita que el DNS del paso 0 ya funcione:

```bash
sudo certbot --nginx -d yikonsupport.com -d www.yikonsupport.com --redirect
```

Te pide un correo y aceptar las condiciones. Certbot edita la configuración de nginx, activa
la redirección de http a https y **renueva el certificado solo**. Comprueba la renovación con
`sudo certbot renew --dry-run`.

Abre **https://yikonsupport.com** en el navegador: debe salir la pantalla de login, con el
candado. Entra con el admin del paso 6.

## 8. Comprobar el correo

Entra como admin, crea un usuario de prueba con tu propio correo e invítalo: debe llegarte el
email con el enlace (que empieza por `https://yikonsupport.com/`).

Para que los avisos no acaben en spam, en el DNS del dominio hay que añadir los registros
**SPF** y **DKIM** que te indique tu proveedor de correo (son específicos de cada uno), y
conviene un registro **DMARC**. Sin ellos, muchos servidores de correo marcan los mensajes
como sospechosos.

## 9. Copias de seguridad

La copia diaria guarda la base de datos y los archivos subidos en `/srv/yikonpo/copias`
(últimos 14 días). Pruébala a mano una vez:

```bash
sudo -u yikonpo /srv/yikonpo/app/deploy/copia_seguridad.sh
```

Y prográmala cada noche a las 3:15:

```bash
sudo -u yikonpo crontab -e
```

Añade esta línea al final:

```
15 3 * * * /srv/yikonpo/app/deploy/copia_seguridad.sh >> /srv/yikonpo/copias/copias.log 2>&1
```

**Dos cosas que no son opcionales:**

1. **Una copia fuera del servidor.** Estas copias están en la misma máquina: si se pierde el
   servidor, se pierden con él. Activa las copias automáticas del proveedor y, además, baja
   periódicamente la carpeta `copias` a otro sitio (otro servidor, almacenamiento de la
   empresa…), por ejemplo desde tu ordenador:
   `scp -r alvaro@IP_DEL_SERVIDOR:/srv/yikonpo/copias/AAAA-MM-DD_HHMM ./`
2. **Probar a restaurar** una copia antes de dar acceso a clientes (siguiente apartado). Una
   copia que nunca se ha restaurado no es una copia.

### Recordatorio de recepción (aviso automático diario)

El día después de la fecha estimada de entrega, si un pedido sigue «Enviado», la plataforma manda al
cliente el correo «¿Ha recibido su pedido?» (una vez por pedido; el texto se cambia y se activa o
desactiva en Ajustes → Correos al cliente). Sale cada día a las **9:00 de España** (también en horario de
verano): lo lanza un temporizador de systemd. Pruébalo a mano:

```bash
sudo -u yikonpo bash /srv/yikonpo/app/deploy/recordatorios.sh
```

Y prográmalo (una sola vez; luego `actualizar.sh` no lo toca):

```bash
cd /srv/yikonpo/app
sudo cp deploy/yikonpo-recordatorios.service deploy/yikonpo-recordatorios.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now yikonpo-recordatorios.timer
systemctl list-timers yikonpo-recordatorios      # «NEXT»: mañana a las 9:00 (hora de España)
```

Lo que ha hecho cada día: `sudo journalctl -u yikonpo-recordatorios`. Si el servidor estaba apagado a las
9:00, se lanza al arrancar.

Los enlaces de esos correos salen con `URL_PLATAFORMA` del `.env` (si no está, `https://yikonsupport.com`).

### Restaurar una copia

En una base de datos de prueba (no toca la real):

```bash
sudo -u postgres createdb prueba_restauracion -O yikonpo
sudo -u yikonpo pg_restore --no-owner -d prueba_restauracion /srv/yikonpo/copias/AAAA-MM-DD_HHMM/base_de_datos.dump
sudo -u yikonpo psql prueba_restauracion -c "select count(*) from pedidos"
sudo -u postgres dropdb prueba_restauracion
```

Restaurar de verdad (sustituye lo que hay; solo tras un desastre):

```bash
sudo systemctl stop yikonpo
sudo -u postgres dropdb yikonpo && sudo -u postgres createdb yikonpo -O yikonpo
sudo -u yikonpo pg_restore --no-owner -d yikonpo /srv/yikonpo/copias/AAAA-MM-DD_HHMM/base_de_datos.dump
sudo -u yikonpo tar -xzf /srv/yikonpo/copias/AAAA-MM-DD_HHMM/archivos.tar.gz -C /srv/yikonpo
sudo systemctl start yikonpo
```

## 10. Actualizar la plataforma (cada versión nueva)

Primero, que `yikonpo` pueda reiniciar su propio servicio sin contraseña (solo una vez):

```bash
echo 'yikonpo ALL=(root) NOPASSWD: /usr/bin/systemctl restart yikonpo' | sudo tee /etc/sudoers.d/yikonpo
sudo chmod 440 /etc/sudoers.d/yikonpo
```

Y cada vez que haya una versión nueva en Git:

```bash
sudo -u yikonpo -H bash -c "cd /srv/yikonpo/app && ./deploy/actualizar.sh"
```

Hace, en este orden: copia de seguridad, `git pull`, librerías, migraciones, reinicia y
comprueba que responde. Si algo falla, se para y no sigue.

**Antes de la primera actualización con pedidos abiertos**, recuerda los comandos de una sola
vez de cada versión (están en `PENDIENTES.md`), por ejemplo `flask reservar-pendientes`.

---

## El día a día

| Quiero… | Comando |
|---|---|
| Ver si está arrancada | `sudo systemctl status yikonpo` |
| Ver el registro en directo | `sudo journalctl -u yikonpo -f` |
| Reiniciarla | `sudo systemctl restart yikonpo` |
| Ver errores de la aplicación | `sudo less /srv/yikonpo/app/instance/logs/plataforma.log` |
| Ver errores de nginx | `sudo tail -50 /var/log/nginx/error.log` |
| Comprobar que responde | `curl https://yikonsupport.com/salud` |
| Espacio en disco | `df -h /srv` |
| Actualizar el sistema | `sudo apt update && sudo apt upgrade` (una vez al mes) |

## Antes de dar acceso al primer cliente

- [ ] `https://yikonsupport.com` abre con candado y `http://` redirige a `https://`.
- [ ] El registro al arrancar (`journalctl -u yikonpo`) no tiene avisos de «Configuración:».
- [ ] Llega el email de invitación y su enlace funciona.
- [ ] Se puede subir una foto y un documento, y descargarlos.
- [ ] Se ha hecho una copia y se ha restaurado en una base de datos de prueba.
- [ ] Hay una copia fuera del servidor.
- [ ] Una semana de uso interno (admin, Logística, FAS) sin errores en el registro.
- [ ] Datos de prueba borrados: `flask reiniciar-datos` deja solo los admin.

## Si cambia el dominio

Hay que cambiarlo en tres sitios: `server_name` en `/etc/nginx/sites-available/yikonpo`,
`MAIL_FROM` en el `.env`, y pedir un certificado nuevo con `certbot`. El código no lleva el
dominio escrito: lo toma de cada visita.
