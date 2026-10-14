# Plataforma de clientes — esqueleto

Registro de clientes (clínicas), productos, pedidos y facturas, con usuarios por roles.
Flask + SQLAlchemy, misma base que el tutorial de Corey Schafer, pero con la estructura
de una aplicación "de verdad" (application factory, migraciones, permisos, auditoría y tests).

> ⚠ La plataforma **registra** facturas emitidas por el sistema contable; **no emite** facturas
> legales (eso tendría requisitos de VeriFactu / Reglamento de facturación).

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

Usuarios demo (contraseña `demo123456`): `admin@ejemplo.com`, `ana@ejemplo.com` (administración),
`carlos@ejemplo.com` (comercial), `lucia@ejemplo.com` (solo lectura).

Tests: `pytest`

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
  extensions.py        db, migrate, bcrypt, login_manager, csrf
  models.py            User, Cliente, Producto, Pedido, LineaPedido, Factura, RegistroAuditoria
  permisos.py          ROLES + PERMISOS + decorador @requiere_permiso  ← quién puede qué
  auditoria.py         registrar(): deja rastro de cada cambio
  cli.py               flask crear-admin / flask datos-demo
  auth/  admin/  main/  clientes/  productos/  pedidos/  facturas/   (un blueprint por área)
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

| Permiso | Admin | Logistics | Cliente |
|---|:-:|:-:|:-:|
| Ver clientes | todos | solo los asignados | — |
| Crear/editar clientes, asignar logistics | ✓ | | |
| Ver catálogo de productos / editarlo | ✓ / ✓ | ✓ / — | — |
| Ver pedidos | todos | de sus clientes | de su empresa |
| Crear pedidos | ✓ | para sus clientes | para su empresa (kit + cantidad), vía proforma |
| Enviar / retirar proformas | ✓ | de sus clientes | |
| Aceptar la proforma o pedir cambios | | | de su empresa |
| Confirmar pedidos solicitados, cambiar estado, editar líneas | ✓ | de sus clientes | |
| Inventario de la oficina | ✓ | | |
| Subir fotos de preparación / enviar a validación | ✓ | | |
| Validar o rechazar las fotos (Revisar urgente) | ✓ (si logistics no puede) | de sus clientes | |
| Cambiar a cualquier estado fuera del flujo (queda en auditoría) | ✓ | | |
| Marcar Enviado / Entregado | ✓ | | |
| Exportar PDF de pedidos | ✓ | de sus clientes | de su empresa |
| Ver importes (precios, IVA, totales) | ✓ | ✓ | solo si su empresa tiene "Ve precios" |
| Activar "Ve precios" de un cliente | ✓ | de sus clientes | |
| Mensajes (general del cliente y de cada pedido) | todos | de sus clientes | de su empresa |
| Facturas (todas), usuarios, auditoría | ✓ | | |
| Sus facturas y el PDF (sin importes en pantalla) | | | de su empresa |

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

**Referencias internas:** cada cliente tiene un prefijo (DiNA) y un contador; cada pedido nuevo
recibe `DiNA_001`, `DiNA_002`… Los números no se reutilizan aunque se borre un pedido.

## Flujo de trabajo

1. **Cliente** → se da de alta la clínica.
2. **Pedido** → se crea en *borrador*, se añaden líneas (el precio se copia del catálogo en ese
   momento, así los cambios de precio no alteran pedidos antiguos) y se *confirma*.
3. Administración va cambiando el estado (enviado, entregado…).
4. **Factura** → desde el pedido, "Registrar factura" rellena cliente e importes; se añade el
   número del sistema contable. Se valida que base + IVA = total.
5. Cuando se cobra → "Marcar pagada". Las pendientes con vencimiento pasado salen como vencidas.

Cada cambio queda en **Auditoría** (quién, cuándo, qué cambió).

## Qué hace (resumen)

- **Kits**: agrupaciones de productos con precio estándar y precio especial por cliente.
- **Proforma**: el cliente pide proforma, Yikon la revisa y la envía (PDF sin precios con la
  caducidad prevista); al aceptarla pasa a pedido. Versiones si pide cambios.
- **Pedidos**: el cliente pide por kits (puede quitar productos o cambiar cantidades), con su
  referencia y documento opcional; admin y logistics también, y además productos sueltos.
  Precio a mano en la ficha. Flujo con fotos y validación, historial, "Repetir pedido".
- **Envío**: fecha estimada, transportista y seguimiento; el cliente recibe emails en su idioma.
- **Inventario por lotes**: caducidad obligatoria, lote reservado por pedido desde la proforma (propuesta FEFO), caducados bloqueados,
  avisos a 7 días, trazabilidad del lote en cada pedido.
- **Mensajes** con el cliente: conversación general por cliente y una en cada pedido, con
  archivos adjuntos, no leídos, avisos en la campana y por email (uno hasta que se lee).
- **Facturas** (registro de las emitidas por contabilidad, con su PDF oficial); el cliente ve
  las suyas y descarga el PDF. **Estadísticas** (admin).
- **Exportar** a PDF y Excel respetando filtros y permisos.
- **Usuarios** por invitación (eligen su contraseña), recuperar contraseña, límite de intentos y
  cierre por inactividad (plazos en Ajustes → **Seguridad**, `app/seguridad.py`). Admin puede **ver
  como** otro usuario, en solo lectura (`app/ver_como.py`).
- **Incidencias**: el cliente avisa de un problema con un pedido enviado o recibido (motivo, texto y
  fotos); se habla en el chat del pedido y Yikon la cierra con «Resuelta» (`app/incidencias.py`).
- **Avisos por email del cliente**: en su ficha, qué recibe cada usuario y emails en copia
  (`app/avisos_cliente.py`). **Aviso para clientes** arriba de su inicio (`app/aviso_clientes.py`).
- **Exportar todo lo de un cliente** en un ZIP (solo admin, `app/clientes/exportar.py`).

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

## Cambiar el modelo de datos

```bash
# 1. edita app/models.py
flask db migrate -m "añade campo X a Cliente"
# 2. revisa el archivo generado en migrations/versions/
flask db upgrade
```

Nunca borres la base de datos para aplicar cambios cuando ya haya datos reales.

## Producción

Guía de instalación paso a paso en un servidor (Ubuntu, PostgreSQL, gunicorn, nginx, HTTPS,
copias de seguridad): **[DESPLIEGUE.md](DESPLIEGUE.md)**. Los archivos de configuración están
en `deploy/`.

- `FLASK_CONFIG=prod` activa las comprobaciones de arranque y el funcionamiento detrás de
  nginx (`app/produccion.py`).
- `/salud` responde `ok` si la plataforma llega a la base de datos (para comprobarla desde fuera).
- Los tests se pueden pasar contra PostgreSQL:
  `TEST_DATABASE_URL=postgresql+psycopg://usuario@localhost/pruebas python -m pytest`

**Copia de seguridad en la página de Estado:** el script de copias del servidor, al terminar, escribe la
hora en un archivo (por ejemplo `date -Iseconds > /srv/yikon/ultima_copia.txt`) y en el `.env` se pone
`COPIA_SEGURIDAD_MARCA=/srv/yikon/ultima_copia.txt`. Administración → Estado avisa si pasan más de 2
días sin copia. Sin configurarlo, la tarjeta dice «Sin configurar».
