# Yikon Genomics PO

Plataforma de pedidos de **Yikon Genomics España** con sus clientes (clínicas y laboratorios):
proformas, pedidos, preparación con fotos, envío, inventario por lotes, mensajes y registro de
facturas, con usuarios por roles. En producción en **https://yikonsupport.com**.

Flask (application factory, blueprints) + SQLAlchemy 2 + Alembic, Flask-Login, Flask-WTF,
Flask-Babel (es/en), Bootstrap 5.3. SQLite en desarrollo, PostgreSQL en producción. Tests con pytest.

> ⚠ La plataforma **no genera facturas**. Facturación las hace a mano en contabilidad; la
> plataforma solo le da los datos («Preparar factura», en Excel) y **registra** el PDF oficial.
> Nº de factura = referencia interna del pedido.

Para trabajar en ella con Claude: **COMO_TRABAJAMOS.md** (reglas) y **PENDIENTES.md** (qué hay hecho y qué falta).

## Puesta en marcha (desarrollo)

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env                 # Windows: copy .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"   # pega el resultado en SECRET_KEY del .env

flask db upgrade                     # crea la base de datos (dev.db, SQLite)
flask datos-demo                     # opcional: datos FICTICIOS para probar
flask datos-prueba                   # BORRA la base local y crea un caso de cada (pedidos en todos los
                                     # estados, facturas en todas sus fases, mensajes...). Solo dev + SQLite
flask crear-admin                    # o crea tu propio usuario administrador
flask run --debug                    # http://127.0.0.1:5000
```

Usuarios de `flask datos-demo` (contraseña `demo123456`): `admin@ejemplo.com` (admin),
`facturacion@ejemplo.com` (Facturación), `almacen@ejemplo.com` (Almacén), `laura@ejemplo.com` y `pablo@ejemplo.com` (Soporte de cliente),
`norte@`, `centro@` e `instituto@ejemplo.com` (clientes). Al terminar, el comando lista todos.

En desarrollo (`ENTORNO=dev`) hay además una barra «Entrar como» para cambiar de usuario al probar.

Tests: `python -m pytest -q` (todos deben pasar antes de entregar un cambio).

## Si Windows bloquea librerías ("Una directiva de Control de aplicaciones bloqueó este archivo")

El equipo tiene una política que bloquea DLL (.pyd) no firmadas instaladas por pip. SQLAlchemy y
fonttools (que usa fpdf2 para los PDF) funcionan igual sin sus piezas compiladas. Con el entorno
activado, después de cada `pip install`:

```powershell
python scripts/limpiar_pyd.py
```

Solo borra los .pyd que tienen versión en Python puro. La solución definitiva es desactivar Smart App
Control o que IT excluya la carpeta del entorno virtual.

## Estructura

```
config.py              Configuración por entorno (dev / prod / test). Secretos desde .env
run.py                 Punto de entrada
app/
  __init__.py          create_app(): registra extensiones, blueprints, filtros y errores
  extensions.py        db, migrate, csrf, babel, login_manager
  models.py            todas las tablas (usuarios, clientes, kits, pedidos, proformas, lotes, facturas…)
  permisos.py          ROLES + PERMISOS + decorador @requiere_permiso  ← quién puede qué
  apartados.py         lo que admin quita/pone a cada rol desde Ajustes
  alcance.py           qué registros ve cada uno (filtrar_pedidos, filtrar_mensajes…)
  auditoria.py         registrar(): deja rastro de cada cambio
  correo.py            envío de correos (tras el commit), registro de enviados, reenviar
  revision_correo.py   los correos del equipo esperan a que su autor los revise y envíe
  correos_cliente.py   textos editables de los correos al cliente · avisos_internos.py: los internos
  cli.py               flask crear-admin / datos-demo / datos-prueba / reservar-pendientes…
  auth/ admin/ main/ clientes/ productos/ pedidos/ facturas/ mensajes/ inventario/
  soporte/ documentos/   (un blueprint por área; soporte y documentos están en pausa)
  templates/           Jinja + Bootstrap 5 (incluido en static/vendor, sin CDN)
                       layout.html = estructura tipo "SB Admin 2": menú lateral + barra superior
  static/main.css      todos los estilos propios (colores, menú, tarjetas, tablas)
  static/js/menu.js    plegar/desplegar el menú lateral
  translations/        catálogos de idiomas (en/LC_MESSAGES/messages.po → .mo)
  static/img/          logotipo, símbolo, favicon y fondo del login (imagen corporativa)
  static/vendor/       Bootstrap 5.3, Font Awesome 5 (iconos) y fuente Nunito, todo local
  excel.py             exportación a Excel (openpyxl) reutilizable
  static/js/pedido.js  ventana de pedido: kits, productos, sueltos → JSON en el campo "contenido"
  inventario/stock.py  lógica de stock, lotes (FEFO) y caducidades
  inventario/reservas.py  lotes reservados para cada pedido (se eligen antes de la proforma)
  pedidos/historial.py línea de tiempo del pedido (a partir de la auditoría)
migrations/            Flask-Migrate (Alembic)
tests/                 pytest: login, seguridad, matriz de permisos, flujo pedido→factura
```

## Roles y permisos

Todo se define en `app/permisos.py`. Las vistas usan `@requiere_permiso("facturas.editar")` y las
plantillas `current_user.puede("facturas.editar")`; **nunca se pregunta por el rol directamente**,
así que cambiar lo que puede hacer un rol es tocar una sola línea.

Roles: **Administrador** · **Facturación** (proformas, facturas, clientes, precios y catálogo) ·
**Almacén** (rol `logistica` por dentro: los pedidos desde que el cliente acepta, fotos, envío e
inventario) · **Soporte de cliente** (rol `fas`: FAS y business developers, cada uno con sus clientes
asignados; el nombre visible está en `permisos.NOMBRE_FAS`) · **Cliente** · y, en pausa,
**Soporte ChromGo** y **Cliente ChromGo**. Admin es un perfil interno: el cliente nunca lo ve nombrado.

| Permiso | Admin | Facturación | Almacén | Soporte de cliente | Cliente |
|---|:-:|:-:|:-:|:-:|:-:|
| Ver clientes / darlos de alta y cambiar sus datos | ✓ / ✓ | ✓ / ✓ | — | sus clientes / ✓ (quedan suyos) | — |
| Usuarios de cada empresa cliente (alta con invitación, editar, desactivar) | ✓ | | | sus clientes | |
| Precios especiales del cliente | ✓ | ✓ | | | |
| Asignar el Soporte de cliente de una empresa | ✓ | | | | |
| Catálogo de cada cliente, avisos por email, «Ve precios» | ✓ | ✓ | | sus clientes | |
| Productos: ver / editar | ✓ / ✓ | ✓ / ✓ | ✓ / solo el mínimo (Inventario) | ✓ / — | catálogo sin precios + SDS |
| Pedidos: ver | todos | todos | desde «aceptado» | de sus clientes | de su empresa |
| Pedidos: crear | ✓ | ✓ | — | sus clientes | vía proforma; kits y sueltos de su catálogo |
| Enviar proformas / aceptarlas o pedir cambios | ✓ / — | ✓ / — | — | sus clientes / — | — / ✓ |
| Cambiar líneas y precios, cancelar, reabrir | ✓ | ✓ | — | sus clientes | |
| Modificar o cancelar su pedido hasta aceptar la proforma | | | | | ✓ |
| Indicar el uso del pedido (RUO / IVD / indiferente) y observaciones | opcional | opcional | — | opcional | ✓ (uso obligatorio) |
| Reservar lotes | ✓ | ✓ | ✓ (aceptados) | sus clientes | |
| Preparar, hacer fotos y enviar | ✓ | | ✓ | | |
| Albarán (PDF) para el paquete | ✓ | | ✓ | | |
| Datos de facturación y envío de la empresa | editar | editar | | editar (sus clientes) | ver los suyos («Mi empresa») |
| Validar las fotos (o devolver a preparación) | ✓ (suple) | | | sus clientes | |
| Marcar recibido | ✓ | | ✓ (en su nombre) | | ✓ |
| Saltarse el flujo (queda en auditoría) | ✓ | | | | |
| Importes (precios, IVA, totales) | ✓ | ✓ | — | ✓ | si su empresa «Ve precios» |
| Conversación general del cliente | ✓ | lo que le comparten | lo que le comparten | sus clientes | ✓ |
| Chat del pedido / chat interno | ✓ / ✓ | ✓ / ✓ | ✓ / ✓ | ✓ / ✓ | ✓ / — |
| Incidencias de un pedido: abrir / resolver | — / ✓ | — / ✓ | — / ✓ | — / ✓ | ✓ / — |
| Inventario | ✓ | consulta | ✓ | | |
| Facturas: registrar y enviar / revisar antes de enviar | ✓ / ✓ | ✓ / — | — | — / sus clientes | ver las suyas y el PDF |
| Correos enviados | todos (y reenviar) | todos | | de sus clientes | |
| Estadísticas | ✓ | ✓ | | | |
| Usuarios, ajustes, auditoría, estado | ✓ | | | | |

**Desde la web, sin tocar código:** Administración → Ajustes → **Qué ve cada rol** quita o pone
apartados enteros (Facturas, Clientes, Estadísticas, Tickets ChromGo, Documentos internos…) a cada
rol con casillas (`app/apartados.py`). Lo imprescindible de cada rol sale con candado y no se puede
quitar. Tickets ChromGo y Documentos internos vienen quitados para todos (en pausa) hasta que se
marquen. Y en Ajustes → **Correos al cliente** se cambia el texto de cada aviso que reciben los
clientes (también la invitación y el cambio de contraseña), la firma con los datos de contacto y el
logo (`app/correos_cliente.py`).

Dos capas: `app/permisos.py` decide **qué pantallas** (por rol) y `app/alcance.py` decide
**qué registros** dentro de ellas (por asignación/empresa). Toda consulta de clientes o pedidos
pasa por `filtrar_clientes()` / `filtrar_pedidos()` / `filtrar_mensajes()` o `cliente_o_404()` / `pedido_o_404()`.

**Referencias internas:** cada cliente tiene un prefijo (p. ej. `DiNA`) y un contador por año; cada
pedido recibe `YK-2026-DiNA-001`, `YK-2026-DiNA-002`… (formato en `models.referencia_pedido`). Los
números no se reutilizan aunque se borre un pedido. La proforma es `PF-{referencia}` (`-v2`, `-v3`…).

## Flujo de trabajo

1. **Proforma solicitada** → el cliente pide por kits (o Yikon pide por él). El precio se copia en
   ese momento: los cambios de tarifa no alteran pedidos ya hechos.
2. **Proforma enviada** → Yikon reserva lotes (FEFO) y envía la proforma con su **PDF obligatorio**.
   El cliente la acepta o pide cambios (**Cambios solicitados** → nueva versión).
3. **Aceptado** → Almacén (que desde aquí ya lo ve) lo pasa a **En preparación**, lo prepara y sube las fotos.
4. **Pendiente de validación** → el Soporte de cliente valida las fotos (**Listo para enviar**) o lo
   devuelve a preparación.
5. **Enviado** (transportista, seguimiento, fecha estimada) → el cliente marca **Recibido**.
6. **Factura** → Facturación usa «Preparar factura» (Excel con los datos), la hace en contabilidad y
   registra el PDF; puede pedir al Soporte de cliente que la revise antes de enviarla. Después,
   «Marcar pagada». Las pendientes con vencimiento pasado salen como vencidas.

Cada paso avisa por email a quien le toca. Los correos que genera el equipo de Yikon **no salen
solos**: se abre una ventana para revisarlos (asunto y texto) y enviarlos, guardarlos o descartarlos.
Los que nacen de un cliente y los de cambio de contraseña sí salen automáticamente.

Cada cambio queda en **Auditoría** (quién, cuándo, qué cambió).

## Qué hace (resumen)

- **Kits**: agrupaciones de productos con precio estándar. **Precios especiales** por cliente, de
  kits y de productos sueltos, y **catálogo propio** de cada cliente (qué kits puede pedir y qué
  productos ve).
- **Proforma**: el cliente pide proforma, Yikon la revisa y la envía (PDF sin precios con la
  caducidad prevista); al aceptarla pasa a pedido. Versiones si pide cambios.
- **Pedidos**: el cliente pide por kits (puede quitar productos o cambiar cantidades), con su
  referencia y documento opcional; admin y logistics también, y además productos sueltos.
  Precio a mano en la ficha. Flujo con fotos y validación, historial, "Repetir pedido".
- **Envío**: fecha estimada, transportista y seguimiento; el cliente recibe emails en su idioma.
- **Inventario por lotes**: caducidad obligatoria, lote reservado por pedido desde la proforma (propuesta FEFO), caducados bloqueados,
  avisos a 7 días, trazabilidad del lote en cada pedido.
- **Mensajes** con el cliente: conversación general por cliente y una en cada pedido, con
  archivos adjuntos, no leídos, avisos en la campana y por email (uno hasta que se lee). Qué roles
  escriben al cliente lo decide admin en Ajustes → Qué ve cada rol → «Quién habla con los clientes».
- **Facturas** (registro de las emitidas por contabilidad, con su PDF oficial); el cliente ve
  las suyas y descarga el PDF. **Estadísticas** (admin).
- **Exportar** a PDF y Excel respetando filtros, orden y permisos. Las listas se **ordenan pulsando las cabeceras**
  (Productos, Kits, Clientes, Pedidos, Facturas, Inventario) y tienen buscador.
- **Usuarios** por invitación (eligen su contraseña), recuperar contraseña, límite de intentos y
  cierre por inactividad (plazos en Ajustes → **Seguridad**, `app/seguridad.py`). Admin puede **ver
  como** otro usuario, en solo lectura (`app/ver_como.py`).
- **Incidencias**: el cliente avisa de un problema con un pedido enviado o recibido (motivo, texto y
  fotos); se habla en el chat del pedido y Yikon la cierra con «Resuelta» (`app/incidencias.py`).
- **Avisos por email del cliente**: en su ficha, qué recibe cada usuario y emails en copia
  (`app/avisos_cliente.py`). **Aviso para clientes** arriba de su inicio (`app/aviso_clientes.py`).
- **Exportar todo lo de un cliente** en un ZIP (solo admin, `app/clientes/exportar.py`).
- **Correos**: revisión antes de enviar, registro de enviados con reenvío de los fallidos
  (Administración → Correos enviados) y destinatarios configurables de los avisos internos.
- **Administración**: ajustes desde la web (datos de la empresa, proformas, plazos, seguridad,
  qué ve cada rol, correos), **modo mantenimiento** (solo entra admin), página de **Estado**,
  auditoría y listas paginadas de 10 en 10.

## Traducciones (español / inglés)

La web está en español y en inglés (Flask-Babel). Cada usuario elige el idioma en el menú
de su nombre (o arriba a la derecha en el login); se guarda en su ficha y sus **correos le
llegan en ese idioma**. Si no ha elegido, se usa el idioma de su navegador.

- En el código, cada texto visible va marcado: `_('Pedidos')` (plantillas y Python) o
  `_l('...')` en formularios y diccionarios que se definen al importar.
- Con variables, siempre con nombre: `_('Pedido %(ref)s creado.', ref=p.referencia_interna)`.
- Las traducciones están en `app/translations/en/LC_MESSAGES/messages.po`.
- Los datos (nombres de productos, clientes…) NO se traducen: son los de la base de datos.
- La auditoría se guarda siempre en español.

**Cuando añadas o cambies textos** (desde la carpeta del proyecto, con el entorno activado):

```
pybabel extract -F babel.cfg -k _l -o messages.pot .     # 1. saca todos los textos marcados
pybabel update -i messages.pot -d app/translations       # 2. añade los nuevos al catálogo .po
#   3. abre messages.po y rellena los msgstr "" vacíos (y revisa los marcados como "fuzzy")
pybabel compile -d app/translations                      # 4. genera el .mo que lee la app
```

El test `test_catalogo_ingles_completo_y_con_las_mismas_variables` falla si queda algún
texto sin traducir o si una traducción pierde un `%(variable)s`.

## Git

Guía paso a paso en **GIT.md** (instalar, primer commit, día a día, ramas, recibir cambios).

## Cargar datos desde Excel (productos, kits y empresas)

Para meter muchos de golpe en vez de uno a uno: se rellena **`deploy/plantilla_carga.xlsx`** (hojas
Productos, Kits, Componentes y Empresas; instrucciones en la primera hoja) y se carga con:

```bash
flask importar-datos plantilla.xlsx            # PRUEBA: dice qué crearía y qué está mal; no guarda nada
flask importar-datos plantilla.xlsx --guardar  # lo guarda
```

Solo crea: lo que ya existe (misma referencia, nombre o CIF) no se toca. Si hay algún error, no se
guarda nada. Todo queda en la auditoría. Stock, precios especiales, catálogo de cada cliente y usuarios
se hacen desde la web. En el servidor: se sube el Excel con `scp archivo.xlsx alvaro@2.31.22.223:/tmp/`
y se ejecuta `sudo -u yikonpo -H bash -c "cd /srv/yikonpo/app && ../venv/bin/flask importar-datos /tmp/archivo.xlsx"`
(y luego con `--guardar`). Código: `app/importar.py`; test: `tests/test_importar.py`.

## Cambiar el modelo de datos

```bash
# 1. edita app/models.py
flask db migrate -m "añade campo X a Cliente"
# 2. revisa el archivo generado en migrations/versions/
flask db upgrade
```

Nunca borres la base de datos para aplicar cambios cuando ya haya datos reales.

## Producción

En marcha desde el 13/10/2026 en **https://yikonsupport.com** (Hetzner, Ubuntu, PostgreSQL,
gunicorn, nginx, HTTPS de Let's Encrypt, correo con Brevo). Cómo entrar al servidor, copias y datos
del montaje: «Nuestro servidor» al principio de **[DESPLIEGUE.md](DESPLIEGUE.md)**; el resto de esa
guía es la instalación paso a paso. Los archivos de configuración están en `deploy/`.

**Subir un cambio:** en tu PC, tests en verde → `git commit` → `git push`; en el servidor:
`sudo -u yikonpo -H bash -c "cd /srv/yikonpo/app && ./deploy/actualizar.sh"` (copia de seguridad,
descarga, librerías, migraciones, reinicio y comprobación). Variables nuevas del `.env` se añaden a
mano en el servidor.

- `FLASK_CONFIG=prod` activa las comprobaciones de arranque y el funcionamiento detrás de
  nginx (`app/produccion.py`).
- `/salud` responde `ok` si la plataforma llega a la base de datos (para comprobarla desde fuera).
- Los tests se pueden pasar contra PostgreSQL:
  `TEST_DATABASE_URL=postgresql+psycopg://usuario@localhost/pruebas python -m pytest`

**Copia de seguridad en la página de Estado:** `deploy/copia_seguridad.sh`, al terminar bien, escribe la
hora en `/srv/yikonpo/ultima_copia.txt`, y el `.env` del servidor tiene
`COPIA_SEGURIDAD_MARCA=/srv/yikonpo/ultima_copia.txt`. Administración → Estado avisa si pasan más de 2
días sin copia. Sin esa línea en el `.env`, la tarjeta dice «Sin configurar».
