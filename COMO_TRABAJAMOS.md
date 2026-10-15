# Cómo trabajamos

Para cualquier conversación nueva con Claude sobre la plataforma: **léelo entero antes de hacer nada**.
Recoge cómo le gusta trabajar a Álvaro y las reglas que se han ido decidiendo. `PENDIENTES.md` dice
*qué* hay que hacer; este archivo dice *cómo*.

---

## Quién y qué

- **Álvaro Ballesteros**, Yikon Genomics España (Barcelona). Ahora es FAS (dry + wet lab), pero sigue
  siendo el responsable de la plataforma, el dominio (`yikonsupport.com`) y el servidor.
- **Plataforma «Yikon Genomics PO»**: Flask (app factory, blueprints), SQLAlchemy 2, Alembic
  (`render_as_batch`), Flask-Login, Flask-WTF, Flask-Babel (es/en), Bootstrap 5.3, Font Awesome 5, pytest.
- Álvaro trabaja en Windows: `C:\Users\Alvaro\PycharmProjects\plataforma_clientes\plataforma`, SQLite
  `dev.db`, `.venv`. Copia los archivos que le mandamos encima de su carpeta y ejecuta `flask db upgrade`.
- **Tiene deuteranopia**: el color **nunca** puede ser la única señal. Siempre texto y/o icono además del
  color, y una paleta que se distinga (azul/naranja/gris, no rojo/verde). Color de la marca: `#a61c92`.

## Cómo se trabaja cada cambio

1. **Primero hablar, después código.** Si Álvaro dice «no hagas código aún» o «contéstame antes», solo se
   responde (texto o propuesta visual). Para cosas visibles, **propuesta visual primero** (una página HTML
   publicada como artifact, con el aspecto de la plataforma), y al final las preguntas concretas que
   necesitas que decida. No se programa nada sin su visto bueno.
2. **Se agrupan cambios en bloques** para no rehacer el código cada vez: él elige qué entra y qué no.
   Lo que descarta no se vuelve a proponer.
3. **Al programar**:
   - Copia de seguridad antes de tocar: `cp -r app tests config.py README.md migrations /tmp/claude-0/antesNN/`.
   - Lee el código que vas a tocar antes de editarlo (no lo reconstruyas de memoria).
   - Tests nuevos para lo nuevo, con aserciones **que comprueben algo de verdad** (no le gustan las
     aserciones vacías). Ajusta los tests existentes solo si el comportamiento cambió a propósito.
   - Pasa **toda** la batería (`python -m pytest -q`) antes de entregar. Hoy son 678 tests y pasan todos:
     no se entrega nada con alguno en rojo.
   - Traducciones al inglés (ver más abajo): `tests/test_idioma.py` falla si queda algo sin traducir.
   - Migraciones: una por paso, encadenada a la última, probada **subiendo, bajando y volviendo a subir**.
   - Mira las pantallas nuevas con una captura (Playwright) antes de darlas por buenas.
4. **Entrega**:
   - **Solo los archivos que cambian.** Si el ordenador de Álvaro está enlazado a la conversación, se
     escriben **directamente en su carpeta** (antes se comprueba con md5 que sus archivos son los que se
     tomaron como base, para no pisar cambios suyos) y se le manda solo `pasoNN.diff`. Si no está enlazado:
     `pasoNN_cambios.zip` con la carpeta `plataforma/` dentro, que él descomprime en `plataforma_clientes`
     (no dentro de `plataforma`, o queda `plataforma\plataforma`). Nunca el proyecto entero salvo que lo
     pida. Los zips **nunca** llevan `*.db`, `.env` ni `instance/`.
   - Respetar los saltos de línea de cada archivo (algunos suyos son de Windows, CRLF), para que el diff
     muestre solo lo cambiado.
   - Incluye `app/translations/en/LC_MESSAGES/messages.mo` si cambian las traducciones.
   - Dile si hace falta `flask db upgrade` y si hay archivos que puede borrar.
5. **Cómo se le explica** (siempre en español):
   - Qué se ha hecho, por qué, y **dónde** (archivo y función).
   - Las decisiones que has tomado tú, para que las revise.
   - Lo que no has podido comprobar.
   - Sin rodeos ni relleno; listas cuando hay varias cosas.

## Ahorro de tokens (le importa)

- Respuestas al grano. Para cambios pequeños, dile dónde y qué editar en vez de mandar zip.
- No repitas en el texto lo que ya está en una propuesta o en un archivo.
- Capturas solo cuando hay pantalla nueva; nada de varias vueltas de capturas.
- Si la conversación se hace muy larga, avísale y sugiere empezar otra con este archivo.

## Reglas de la plataforma que no se tocan

- **La plataforma NO genera facturas** (tema delicado). Facturación las hace a mano; la plataforma
  solo da un Excel básico de datos («Preparar factura») y registra el PDF. Nº de factura = referencia
  interna del pedido.
- **Roles** (desde el 14/10/2026): admin, **facturacion** («Facturación»: proformas, facturas, clientes,
  precios y catálogo; inventario en consulta), **logistica** (se muestra como **«Almacén»**: los pedidos
  desde que el cliente acepta, fotos, envío, lotes e inventario; sin precios, proformas, facturas ni
  clientes), fas (se muestra como **«Soporte de cliente»**, lo usan FAS y business developers; nombre
  visible en `permisos.NOMBRE_FAS`), soporte (ChromGo), cliente, cliente_chromgo. Aina es Almacén. Solo
  admin asigna el Soporte de cliente de una empresa. Almacén ve los pedidos con `alcance.pedido_de_almacen()`.
- **Admin no existe para el cliente**: lo ve todo, pero nunca se le nombra en lo que ve el cliente.
- La **conversación general** del cliente es **privada con su Soporte de cliente** (y admin). Almacén y
  Facturación solo ven lo que el Soporte les comparte (elige con quién: `Mensaje.compartido_con`). Lo de un
  pedido va en el chat del pedido (ahí sí están los dos; Almacén, desde que se acepta).
- **Quién escribe al cliente** lo decide admin en Ajustes → Qué ve cada rol → «Quién habla con los clientes»
  (`apartados.py`: `hablar_general` → `mensajes.general`, `hablar_pedidos` → `mensajes.pedido_cliente`). Lo de
  arriba es lo de fábrica. Sin la casilla, el rol lee pero no escribe; las notas internas no cambian.
- **Pedidos**: el documento del pedido es **obligatorio** (cliente y Yikon), y para el cliente también el
  **uso** (RUO / IVD / indiferente: `Pedido.uso`; los tests lo mandan en `pedido_cliente(uso="ruo")`). El cliente pide kits y productos
  sueltos de su catálogo; Yikon, cualquier cosa.
- Proforma: número `PF-{referencia interna}` (`-v2`, `-v3`…) y **PDF obligatorio** al enviarla.
- Tickets ChromGo y Documentos internos: hechos pero **en pausa** (se activan en Ajustes → Qué ve cada rol).
- Herramientas de pruebas (`flask datos-prueba`, barra «Entrar como»): **solo en desarrollo** (`ENTORNO=dev`).
- No leer ni mostrar el `.env` de Álvaro, ni repetir credenciales. Su `dev.db` tiene datos reales: si te
  la pasa, trabaja sobre una copia y bórrala al acabar.

## Dónde está cada cosa (lo que más se toca)

- Permisos: `app/permisos.py` (techo por rol) + `app/apartados.py` (lo que admin quita/pone por rol).
  Las vistas preguntan por el permiso (`current_user.puede(...)`), nunca por el rol.
- Qué registros ve cada uno: `app/alcance.py` (`filtrar_pedidos`, `filtrar_mensajes`…).
- Ajustes que cambia admin desde la web: tabla `ajustes` (clave → valor), con valor de fábrica en código
  y solo se guarda lo que difiere. Módulos: `ajustes.py` (plazos, proformas), `correos_cliente.py`,
  `avisos_internos.py`, `datos_empresa.py`, `apartados.py`, `mantenimiento.py`.
- Correos: `app/correo.py` (envío tras el commit, registro de enviados, reenviar); al cliente con texto
  editable en `correos_cliente.py`; internos con destinatarios configurables en `avisos_internos.py`.
- Listas: `utils.paginar()` + macro `paginacion`; ordenar por cabeceras con `utils.ordenar()` /
  `utils.ordenar_lista()` + macro `th_orden` (ver Productos o Kits como ejemplo).
- Auditoría: `app/auditoria.py` (`registrar(...)` guarda también el nombre legible del objeto).
- Estado de pedidos y transiciones: `pedidos/routes.py` → `_cambiar_estado` (único punto).

## Traducciones

```
pybabel extract -F babel.cfg -k _l -o /tmp/claude-0/messages.pot .
pybabel update -i /tmp/claude-0/messages.pot -d app/translations
# rellenar los msgstr vacíos o fuzzy (quitar fuzzy y previous_id), write_po(width=76)
pybabel compile -d app/translations
```
Textos de la web siempre con `_()` / `_l()`; en plantillas `{{ _('...') }}`.

## Probar en local (contenedor)

```
DATABASE_URL=sqlite:////tmp/claude-0/prueba.db SECRET_KEY=x UPLOAD_FOLDER=/tmp/claude-0/up \
DOCUMENTOS_FOLDER=/tmp/claude-0/doc ENTORNO=dev flask --app run run --port 5089
flask --app run datos-prueba --si     # borra y crea datos de prueba con todos los casos
```
Para parar el servidor: `pkill -f "run run --port 5089"` en su propia llamada.
Existe un **guion de pruebas** (artifact «guion-pruebas») que Álvaro pasa a mano tras cada bloque y del
que te trae un informe; se amplía con los pasos de lo nuevo.

## Estado

- Hecho hasta el **paso 92** y, después, revisión de correos, precios de productos por cliente, paginación
  de 10 en 10 y catálogo propio por cliente (detalle al final de `PENDIENTES.md`).
- Última migración: `b5e1c7d9a206` (mapa de clientes: latitud y longitud).
- **En producción** desde el 13/10/2026 en https://yikonsupport.com (Hetzner). Cómo entrar al servidor
  (`ssh alvaro@2.31.22.223`), correo (Brevo), copias y cómo actualizar: «Nuestro servidor» en `DESPLIEGUE.md`.
- Tests: 678, todos pasan (los de la revisión de correos se adaptaron con `confirmar_correos()` de
  `tests/conftest.py`, que hace lo que el botón «Enviar» de la ventana de revisión).
