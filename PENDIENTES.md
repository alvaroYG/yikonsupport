# Pendientes

Funcionalidades acordadas pero **aún no desarrolladas**. Cada una con lo pedido, una idea
de diseño y las preguntas a resolver antes de empezar.

---

## ✅ 1. Inventario de la oficina — HECHO (25/09/2026)

Decisiones tomadas (cambiables si no encajan):
- El stock baja al pasar un pedido a **Enviado**; si ese envío se anula (vuelve a un estado
  anterior o se cancela) las unidades vuelven. "Entregado" no toca el stock.
- **Sin stock suficiente no se puede marcar como Enviado** (mensaje con lo que falta).
- Al marcar Enviado sale una **ventana de confirmación** con lo que se resta (stock ahora → quedarán).
  El servidor exige esa confirmación (`confirmar_stock=1`): sin ella no resta nada.
- Productos con "Controlar stock" desmarcado (servicios) no mueven inventario.
- Una sola ubicación (la oficina). Lotes y caducidad: ver punto 5.

---

## ✅ 2. Fotos de validación del pedido — HECHO (25/09/2026)

Flujo: Solicitado → Confirmado → (admin sube fotos) → Pendiente de validación →
Validado por logistics → Enviado → Entregado. Si logistics rechaza → "Revisar urgente"
(aviso en el menú y en el inicio de admin) → admin corrige → vuelve a validación.

Decisiones tomadas:
- Solo admin sube/quita fotos. Valida normalmente logistics (del cliente); admin puede
  validar en su lugar si hace falta (queda anotado "en lugar de logistics").
- Admin puede pasar un pedido a CUALQUIER estado saltándose el flujo; queda en auditoría
  como "CAMBIO FORZADO". Logistics y cliente siguen limitados al flujo. El stock se respeta siempre.
- Rechazar exige comentario. Historial de validaciones en la ficha del pedido.
- El cliente nunca ve las fotos ni los estados internos (le sale "En preparación").
- Fotos JPG/PNG/WEBP, máx. 10 MB cada una, en `instance/fotos_pedidos` (carpeta privada).
  En producción: disco persistente incluido en las copias de seguridad.
- Los estados solo avanzan por las transiciones definidas en `TRANSICIONES` (models.py).

Pendiente de valorar: aviso por email a admin cuando algo pasa a "Revisar urgente".

---

## ✅ 3. Documentos del pedido — HECHO (25/09/2026)

- El cliente adjunta su orden de compra / registro interno al hacer el pedido (opcional) o
  después desde la ficha. Admin y logistics también pueden adjuntar.
- Lo ven el cliente de ese pedido, sus logistics y admin. Otra empresa nunca (404).
- Tipos: PDF, Word, Excel, CSV, OpenOffice, RTF, TXT, JPG/PNG, EML/MSG, ZIP. Máx. 15 MB.
  Nada ejecutable ni HTML. Siempre se descargan como adjunto.
- Quitar: admin siempre; quien lo subió, mientras el pedido no se haya enviado.
- Guardados en `instance/documentos_pedidos` (privado). En producción: disco persistente + backups.

Pendiente de valorar: ¿debe ser **obligatorio** adjuntar el documento al hacer el pedido?

---

## ✅ 4. Tanda del 25/09 (tarde) — HECHO

- **Color corporativo #a61c92** en barra, botones, enlaces y PDF (estados siguen azul/naranja/marrón).
- **Varios kits por pedido** en el formulario del cliente (filas + "Añadir otro kit"; kits repetidos se suman).
- **Documento adjunto**: se queda opcional (decidido).
- **Emails** (`app/correo.py`, `app/notificaciones.py`, plantillas en `templates/correos/`):
  - A admins cuando logistics rechaza → "Revisar urgente".
  - A los usuarios de la empresa cliente cuando cambia el estado QUE ELLOS VEN
    (En preparación / Enviado / Entregado / Cancelado). Los pasos internos no mandan correo.
  - Solo se envían si el cambio se guarda (tras el commit).
  - Sin MAIL_SERVER (desarrollo) se guardan como .eml en `instance/correos/`.
- **Recuperar contraseña** por email (enlace firmado, caduca en 1 h, de un solo uso).
- **Límite de intentos de login**: 5 fallos por email o 20 por IP en 15 min → bloqueo temporal.
- **noindex** (meta + cabecera X-Robots-Tag + robots.txt) y cabeceras anti-iframe.
- **Registro de errores** en `instance/logs/plataforma.log`; en producción, errores 500 por email a ADMIN_EMAILS.

## ✅ 5. Tanda del 27/09 — HECHO

- **Lotes y caducidad** (`app/inventario/stock.py`):
  - Toda entrada lleva lote y caducidad (obligatorios). Un mismo código en el mismo producto
    suma al lote existente (si la fecha no cuadra, se rechaza).
  - Al enviar sale primero el lote que caduca antes (FEFO). Los caducados **no se envían nunca**.
  - Aviso de caducidad a **7 días** (`DIAS_AVISO_CADUCIDAD`): inicio de admin, inventario y
    página "Caducidades".
  - Trazabilidad: la ficha del pedido muestra qué lotes salieron (admin y logistics; **el cliente no**).
  - Al anular un envío, cada unidad vuelve a su lote.
  - El stock anterior se migró a un lote "SIN LOTE" por producto (sin fecha: sale el último).
- **Pedido de admin/logistics en un paso**: ventana emergente con cliente + varios productos;
  "Hacer un pedido" desde la ficha de un cliente lo trae ya elegido.
- **Envío**: transportista, nº y enlace de seguimiento (los ve el cliente y le llegan por email);
  email al cliente si cambian la fecha estimada o el seguimiento; fecha estimada en el PDF.
- **Exportar a Excel** pedidos (con los filtros; el cliente sin importes) y facturas.
- **Repetir pedido**, **historial** del pedido (completo para admin/logistics, simplificado
  para el cliente) y **estadísticas** (solo admin).
- **Invitaciones**: el usuario nuevo recibe un enlace (7 días, un solo uso) para elegir su
  contraseña; "Reenviar invitación" en la lista de usuarios. Idioma por usuario.
- Revisión independiente: 12 fallos corregidos (fórmulas en Excel, invitación reutilizable,
  stock negativo heredado, ids repetidos...) + migración antigua que fallaba en PostgreSQL.

## ✅ 6. Kits — HECHO (28/09/2026)

- **Kits** en el catálogo (Kits, junto a Productos): referencia, nombre, precio estándar, IVA
  y productos con su cantidad por kit. El kit no tiene stock propio: se monta con los productos.
- **Precio por cliente**: en la ficha del cliente, "Precios especiales de kits" (solo admin).
  Precio automático = el especial del cliente o, si no tiene, el estándar.
- **Pedido**: el cliente elige kits y nº de kits; le salen sus productos y puede quitarlos o
  cambiar cantidades (no añadir otros). Admin/logistics pueden además añadir productos sueltos.
  Un kit cambiado respecto al estándar sale "✎ modificado" (solo lo ve Yikon).
- **Precio a mano** en la ficha del pedido (admin/logistics), hasta que el pedido sale.
  Sustituye al descuento % (los pedidos antiguos con descuento lo siguen mostrando).
- Cantidades, añadir/quitar kits y productos: en la ficha, mientras el pedido está "solicitado".
- Stock y lotes: se descuentan de los productos de cada kit (igual que antes).
- Filtro por kit en la lista de pedidos y "Kits más pedidos" en estadísticas.

## ✅ 7. Mensajes con el cliente — HECHO (28/09/2026)

- **Dos conversaciones**: la general de cada cliente (menú "Mensajes") y la de cada pedido
  (en su ficha, "Mensajes sobre este pedido"). El cliente ve y escribe en las de su empresa;
  logistics, en las de sus clientes; admin, en todas.
- Los mensajes **no se editan ni se borran** (quedan como registro). Todo lo que se escribe lo
  ve el cliente: para lo interno siguen las "Notas internas" del pedido.
- **No leídos** por persona: contador en el menú, en la campana y 💬 en la lista de pedidos.
  Lo que escribe un compañero de tu mismo lado no cuenta como pendiente.
- **Aviso por email** a la otra parte (logistics del cliente, o admins si no tiene; o los
  usuarios del cliente), en su idioma. Un solo email hasta que entra a leer.
- Los mensajes nuevos aparecen solos (el navegador pregunta cada 30 s), sin recargar.
- **Archivos adjuntos** (hasta 5 por mensaje, 15 MB cada uno, mismos tipos que los documentos).
- Pendiente si hace falta: responder desde el propio email.

## ✅ 8. Facturas para el cliente — HECHO (28/09/2026)

- Admin sube el **PDF oficial** (el del sistema contable) al registrar o editar la factura.
  Subir otro lo sustituye. Solo se aceptan PDF de verdad.
- El cliente tiene **"Facturas"** en el menú (sus facturas: número, pedido, fechas, estado y el
  PDF) y las ve también en la ficha de cada pedido. Sin importes en pantalla ni notas internas:
  el detalle está en el PDF.

## ✅ 9. Inventario con kits — HECHO (29/09/2026)

- "Registrar movimiento" es ahora un botón que abre una ventana (y un "+" en cada producto que
  la abre con ese producto elegido): la lista de inventario ocupa todo el ancho.
- Pestañas **Productos / Kits**. Los kits no tienen stock propio: se muestra cuántos kits
  completos se pueden montar con el stock disponible y qué producto lo limita.

## ✅ 10. Productos y SDS para el cliente — HECHO (29/09/2026)

- Admin sube la **ficha de seguridad (SDS)** en PDF en cada producto (subir otra la sustituye).
- El cliente tiene **"Productos"** en el menú: todo el catálogo activo por marca, con buscador y
  el botón para descargar la SDS de cada producto. Sin precios.

## ✅ 11. Proforma antes del pedido — HECHO (29/09/2026)

- El cliente ya no hace el pedido directamente: **"Solicitar proforma"** (estado "Proforma solicitada").
- Admin/logistics revisan (pueden ajustar el pedido) y **"Enviar proforma al cliente"**: se genera
  la proforma **sin precios** (PF-2026-0001…), con logo, datos de Yikon y del cliente, productos por
  kit con su **caducidad prevista** (FEFO), plazo de entrega, notas y validez. Es una foto fija.
- El cliente la descarga en PDF y **acepta** (→ "Solicitado", que logistics confirma) o **pide
  cambios** (el motivo va a los mensajes del pedido; Yikon envía otra versión). Yikon puede retirarla.
- Un pedido con proforma aceptada ya no se edita: para cambiarlo, "Proforma solicitada" y otra nueva.
  Si se cancela y se reabre, vuelve a la fase de proforma.
- Los pedidos que crean admin/logistics siguen sin proforma.
- Datos de la empresa en la cabecera: EMPRESA_NOMBRE y EMPRESA_DATOS en el .env.
- Pendiente de definir: más detalles en la proforma (conservación, lote, ref. fabricante…).

## ✅ 12. Tanda del 29/09 — HECHO

- **Mensaje nuevo** (admin/logistics) desde Mensajes: ventana para elegir cliente y escribir.
- Filtros de la lista de pedidos en **una sola línea** en pantallas anchas.
- Tarjeta **"Proformas pendientes"** en el inicio de admin/logistics; todas las tarjetas en una línea.
- **Catálogo del cliente**: productos y kits en una sola lista con filtros (texto, tipo, marca);
  en los kits, las SDS de sus productos.
- **"Ve precios" por cliente** (interruptor en Clientes, admin y logistics): si está activado, sus
  usuarios ven sus tarifas en el catálogo, precios y totales de sus pedidos e importes de facturas.
  La proforma sigue sin precios.
- Botón **"Cambiar estado"** en la cabecera del pedido; iconos de **stock bajo** y **caducidades**
  en la barra superior (admin); pedidos a todo el ancho en el inicio.
- **Facturas desde el pedido** (recuadro a `col-12`, cambio de Álvaro): registrar la factura con
  los importes del pedido y subir/sustituir su PDF sin salir de la ficha.
- **Corregir inventario** (botón "Corregir" en cada producto): código y caducidad de los lotes,
  cantidad y nota de entradas/ajustes, o borrarlos. Las salidas por envío no se tocan y nunca
  se deja un lote en negativo. Todo queda en la auditoría.
- Lotes sin caducidad ("SIN LOTE"): ahora se les puede **añadir la fecha** desde Corregir.
- **Vista de móvil "Preparar"** (menú "Preparar" y botón grande en el inicio del móvil): lista de
  pedidos por preparar (los de "Revisar urgente" primero) y, en cada uno, qué lleva con casillas,
  qué lotes coger, **hacer fotos con la cámara** o elegirlas de la galería (se reducen en el
  móvil antes de subirlas) y "Enviar a validación" fijo abajo. Sin precios ni menú lateral.

- **Inventario por kit** (según almacén: los kits llegan cerrados, en una bolsa con una sola
  etiqueta de lote y caducidad aunque tengan varias cajas):
  - Cada kit es **cerrado** (por defecto) o **montado en la oficina** (se elige en Kits).
  - Kit cerrado: stock, lotes, caducidad y mínimo propios; al enviar sale el kit entero de su lote
    (FEFO); la proforma y "Preparar" usan la caducidad del kit.
  - **Abrir kit** (Inventario): resta kits de un lote y suma sus productos como stock suelto con el
    mismo lote y caducidad.
  - ⚠ **Al instalar esta versión**: todos los kits pasan a cerrados con 0 unidades. Antes de enviar
    pedidos con kits hay que dar de alta su stock (Registrar movimiento → el kit) o marcar como
    "montado" los que se junten en la oficina.

- **Flujo de estados simplificado** (definido por Álvaro el 29/09):
  Proforma solicitada → Proforma enviada → (Cambios solicitados → Proforma enviada) → Aceptado →
  En preparación (fotos) → Pendiente de validación (logistics: OK → Listo para enviar, o lo devuelve a
  preparación con su comentario) → Enviado (transportista y nº de seguimiento obligatorios) →
  Recibido (lo marca el cliente; avisa a admin y logistics por email y en los mensajes del pedido).
  - Desaparecen "Solicitado", "Confirmado" y "Revisar urgente"; los pedidos que ya había se pasan solos.
  - Los pedidos que crea Yikon empiezan en "Aceptado". El cliente puede cancelar mientras es proforma;
    admin/logistics hasta antes de enviar. Admin puede marcar "Recibido" por el cliente.
  - Colores de estado nuevos (paleta Okabe-Ito, apta para daltonismo) con icono y leyenda.

## ✅ 13. Documentos internos y Soporte ChromGo (v1) — HECHO (30/09/2026)

- **Documentos internos** (menú "Equipo Yikon → Documentos internos"): los ven admin, logistics y
  Soporte ChromGo; suben admin y logistics; borra admin. El cliente nunca. Carpetas (Logos y marca,
  Plantillas, Protocolos, Fichas técnicas, Formación, Otros), buscador, miniatura de los logos
  (PNG/JPG/GIF/WEBP) y **versiones**: al subir un archivo nuevo, el anterior queda en el historial.
  Admite también SVG, AI, EPS, PSD, fuentes, PowerPoint, MP4… (hasta 40 MB).
- **Roles nuevos**: "Soporte ChromGo" (Yikon: solo tickets y documentos internos) y "Cliente ChromGo"
  (usuario de una empresa: solo sus tickets). Los usuarios "Cliente" pueden abrir tickets si su
  empresa tiene marcado **"Usa ChromGo"** (ficha del cliente).
- **Soporte ChromGo** (menú "Soporte"): tickets TK-AAAA-NNNN con tipo de problema, prioridad
  (explicada al cliente), ID de muestra/análisis (con aviso de protección de datos) y adjuntos
  (capturas, .log…). El equipo: contadores, filtros, panel de estado/prioridad/asignación, respuesta
  con "Dejar el ticket en…" y **notas internas** desplegables (el cliente no las ve). Estados
  automáticos al responder; el cliente puede cerrarlo. Avisos por email y en la campana.
  Va aparte de Mensajes.
- **Logistics en Soporte** (30/09): ve los tickets de SUS clientes asignados y sus notas internas,
  donde puede escribir (avisa por email a quien lleva el ticket). No responde al cliente ni cambia
  estado/prioridad/asignación. Los clientes sin logistics asignado solo los ve el equipo de soporte.
- Para presentarlo: `flask datos-demo` en una base vacía crea soporte@ejemplo.com, chromgo@ejemplo.com,
  4 tickets de ejemplo y los logos como documentos.

### Ideas para la v2 de Soporte (a valorar con el equipo)
- Plantillas de respuesta frecuentes y una base de conocimiento / preguntas frecuentes para clientes.
- Tiempos de respuesta (SLA) por prioridad y avisos si un urgente lleva X horas sin respuesta.
- Crear tickets respondiendo a un email (necesita un buzón y una tarea en el servidor).
- Encuesta de satisfacción al cerrar; estadísticas (tickets por tipo, tiempo medio de resolución).
- ¿Enlazar con ChromGo (abrir el ticket desde dentro de ChromGo con el ID de la muestra ya puesto)?

## ✅ 14. Roles nuevos — HECHO (30/09/2026)

| | Admin | Logística | FAS | Soporte | Cliente | Cliente ChromGo |
|---|---|---|---|---|---|---|
| Pedidos | todos | todos (prepara, fotos, envía) | sus clientes (valida fotos) | – | los suyos | – |
| Chat interno y mensajes | ✓ | ✓ | sus clientes | – | mensajes | – |
| Productos / inventario | ✓ / ✓ | ✓ / ✓ | ver / – | – | catálogo | – |
| Facturas | ✓ | ✓ | consulta (sus clientes) | – | las suyas | – |
| Clientes (ficha y "ve precios") | ✓ | – | sus clientes | – | – | – |
| Tickets ChromGo | todos | – | sus clientes (responde, no cambia estado) | todos | con «Acceso a Soporte» | los suyos |
| Documentos internos | subir/borrar | ver | ver | ver | – | – |
| Usuarios, estadísticas, auditoría | ✓ | – | – | – | – | – |

- Los "logistics" de antes pasan solos a **FAS** (migración `13f7b44dd422`), con sus clientes.
- **Logística** es nuevo: hay que asignárselo a mano en Usuarios.
- El acceso a Soporte de un Cliente es ahora **por usuario** (casilla en su ficha); la migración se
  lo da a los usuarios de las empresas que tenían "Usa ChromGo".

### Pendiente: revisar los emails con los roles nuevos
- Hoy: los mensajes del cliente avisan a su FAS (o admin); el chat interno a admin + FAS; "recibido"
  a admin + FAS; "devuelto por el FAS" a admin + Logística. Logística no recibe emails de mensajes.

## ✅ 15. Menú lateral por secciones — HECHO (30/09/2026)
- Idea y primera versión de Álvaro; ordenado en `app/navegacion.py`: Pedidos, Catálogo, Clientes y
  facturas, Soporte ChromGo, Equipo Yikon, Administración. La sección de la página actual llega
  abierta; las de un solo enlace van directas; los avisos se suman en la cabecera si está cerrada.

## ✅ 16. Modelo de pedido de compra — HECHO (01/10/2026)
- Word bilingüe (ES/EN) de una página en `app/recursos/Pedido_de_compra_Yikon.docx`; el cliente lo descarga
  desde la ventana de nuevo pedido y desde "Documentos del pedido" (`/pedidos/modelo-pedido-compra`).
- Se regenera con `node scripts/generar_modelo_pedido.js` (necesita `npm install docx`).
- ⚠ Confirmar la dirección de Yikon del modelo (Ronda General Mitre, 49 / Pl. Francesc Macià, 7).
- Catálogo del cliente: por defecto solo kits, con su contenido plegado ("Ver contenido").

## ✅ 17. Buscador y filtros en Usuarios y Clientes — HECHO (02/10/2026)
- **Usuarios**: buscar por nombre o email; filtrar por rol, empresa (sus usuarios y los FAS que la llevan)
  y estado (activos, invitación pendiente, desactivados). Ahora la lista va paginada.
- **Clientes**: buscar también por contacto, email y prefijo; filtrar por estado, FAS (o "sin FAS
  asignado") y "ve precios". El FAS solo busca entre sus clientes.

## ✅ 18. Lote al enviar, rastreo de lotes y buscador global — HECHO (02/10/2026)
- **Elegir el lote al enviar**: la ventana de confirmación propone el que caduca antes (FEFO) y deja
  cambiar las unidades por lote. El servidor comprueba que cuadra; si se elige a mano queda anotado
  en el movimiento y en la auditoría. Al anular, cada unidad vuelve a su lote.
- **¿Dónde está este lote?** (Catálogo → Rastrear lote): clientes y pedidos a los que fue, lo que
  queda en la oficina y Excel con los contactos. El FAS solo ve los envíos a sus clientes.
- **Buscador global** (barra superior; atajo `/` o Ctrl+K): pedidos, clientes, tickets, lotes, kits,
  productos, facturas, documentos y usuarios, cada uno con sus permisos y alcance (`app/buscador.py`).
  También **pedidos por lo que llevan**: buscar "PGT-A" saca los pedidos con ese kit o producto
  (y "ver todos" abre la lista de pedidos con el filtro `?contiene=`).

## ✅ 20. Reserva de lotes por pedido (hecho)

- El lote se decide **antes de enviar la proforma** (tarjeta "Lotes de este pedido" en la ficha) y
  queda reservado: la caducidad que aprueba el cliente es la de ese lote. Pedidos creados por
  Yikon: se reservan solos al crearlos (el que caduca antes) y se pueden cambiar hasta enviarlos.
- **Envío estricto**: salen exactamente los lotes reservados. Con la proforma aceptada no se
  cambian (solo se asigna lo que quedó "a confirmar"); para enviar otro lote, rehacer la proforma.
  Si la caducidad reservada no coincide con la aprobada, no deja enviar.
- Sin stock libre al hacer la proforma → caducidad **"a confirmar"**; el lote se asigna al llegar
  la mercancía.
- **Inventario → Reservas**: qué pedidos retienen stock y botón "Liberar" (proformas sin
  contestar: se retira la proforma). Sin caducidad automática de reservas.
- "Stock bajo" y "se pueden montar" cuentan lo libre (sin lo reservado).
- **Al instalarlo**: `flask db upgrade` y, una sola vez, `flask reservar-pendientes` (reserva
  lotes para los pedidos que ya estaban abiertos; avisa con ⚠ de los que haya que revisar).
- Pendiente de decidir: avisar automáticamente al cliente cuando se confirma una caducidad que
  salió "a confirmar" (ahora la plataforma solo recuerda a Yikon que se lo comunique).

## ✅ 21. Ficha del pedido en dos columnas de secciones plegables (hecho)

- Izquierda (ancha): contenido, lotes, proforma, fotos, mensajes. Derecha (estrecha): chat
  interno, documentos, facturas, datos de envío, historial. En móvil se apilan.
- Cada sección enseña su resumen en la cabecera. El orden no cambia nunca.
- Lo abierto/cerrado lo recuerda el navegador de cada persona (para todos los pedidos). Una
  sección con algo que hacer (enviar/aceptar la proforma, subir o validar fotos, problema con
  los lotes) llega siempre abierta. Botón "Abrir todo / Cerrar todo".
- Macro `seccion` en `_macros.html`; comportamiento en `static/js/ficha_pedido.js`.

## ✅ 22. Novedades por sección (hecho)

- Marca "nuevo" en la cabecera de la sección que ha cambiado desde tu última visita al pedido, y
  en la fila del pedido en la lista (dice qué ha cambiado y lleva a esa sección). En Inicio, bloque
  "Pedidos con novedades" con todos los que han cambiado, también los antiguos.
- Por persona; lo que haces tú no cuenta; se apaga al abrir la ficha. La primera vez que abres
  un pedido no hay novedades.
- El cliente solo las ve de proforma, documentos y facturas.
- Sale de la auditoría + tabla `vistas_pedido` (`app/pedidos/novedades.py`). Mensajes y chat
  interno siguen con su contador de no leídos.

## ✅ 23. Bloque "Pendientes" en Inicio (hecho)

- Lo que cada persona tiene que hacer, por grupos según sus permisos: proformas por enviar,
  aceptados sin empezar, devueltos por el FAS, lotes por asignar, listos para enviar, pendientes
  de validación, proformas por responder y enviados por recibir (cliente), mensajes sin leer.
  El FAS ve también los de la oficina (aceptados, devueltos, lotes, envíos) de sus clientes.
- Sale del estado de los pedidos: cada línea se va sola al hacerse; abrir el pedido no la quita.
- Sustituye al bloque "Pedidos con novedades" y a los avisos sueltos de devueltos/validación.
  La marca "nuevo" sigue en la lista, en "Últimos pedidos" y en las secciones de la ficha.
- Lógica en `app/pedidos/pendientes.py` (una función `_grupo` por tipo de pendiente).

## 19. Ideas para más adelante

- **Rol "Almacén"** para quien hace los paquetes: solo la vista "Preparar" (fotos y enviar a
  validación), sin facturas, precios ni usuarios. Ahora subir fotos es solo de admin.

- Recordatorio por email de facturas vencidas y de caducidades (necesita una tarea
  programada en el servidor: cron).
- Modo oscuro.
- Doble factor (2FA) para admin cuando la plataforma sea accesible desde internet.

---

## Soporte ChromGo: en pausa (paso 61)

Los tickets de ChromGo están desarrollados pero **apagados**: `SOPORTE_CHROMGO=0` (por defecto).
No se ha borrado nada: el código (`app/soporte/`), las tablas y los datos siguen ahí.
Para encenderlo: `SOPORTE_CHROMGO=1` en el `.env` y reiniciar. Interruptor: `soporte_activo()`
en `app/permisos.py`. Tests: `tests/test_soporte_en_pausa.py`.

**Documentos internos: también en pausa (paso 62).** `DOCUMENTOS_INTERNOS=0` por defecto; mismo
mecanismo (`en_pausa()` en `app/permisos.py`). Para encenderlos: `DOCUMENTOS_INTERNOS=1`.
Tests: `tests/test_documentos_en_pausa.py`. Los documentos de cada pedido no se ven afectados.

**Inicio en mosaico y mensajes flotantes (pasos 68-71).** Cliente: pedidos en curso, próximo envío,
documentos y actividad. Yikon: tira de fases, «Pendientes» con pestañas (los retrasos con reloj; plazos
en Administración → Ajustes, tabla `ajustes`) y actividad. Mensajes de Yikon: botón flotante en todas
las páginas (no es en directo: refresca el contador cada minuto). Pendiente: adjuntar archivos desde
el panel flotante, filtros fijos en las listas, página de «toda la actividad».

---

## Antes de producción

Código listo (paso 59): ver **DESPLIEGUE.md** y la carpeta `deploy/`. Probado con PostgreSQL 16
(migraciones desde cero + todos los tests), gunicorn en modo producción y copia + restauración.
Dominio: `yikonsupport.com` (comprado en dondominio el 13/10/2026; sin `.es`). Servidor: VPS alquilado a nombre
de Yikon España, en la UE.

Hecho (13–14/10/2026): servidor Hetzner, dominio, HTTPS, correo (Brevo, dominio verificado), Git,
copias nocturnas + Backups de Hetzner. Detalle en «Nuestro servidor» de DESPLIEGUE.md.

Queda por hacer (fuera del código):
- **Probar a restaurar** una copia en una base de datos de prueba (DESPLIEGUE.md, paso 9).
- Bajar de vez en cuando la carpeta `copias` a otro sitio (además de los Backups de Hetzner).
- RGPD: contrato de encargado del tratamiento con Hetzner y Brevo, aviso de privacidad, visto bueno interno.
- Una semana de uso interno y `flask reiniciar-datos` antes de dar acceso al primer cliente
  (lista completa al final de DESPLIEGUE.md).

## Preguntas resueltas

- ~~¿Varios kits distintos en un mismo pedido?~~ → Sí (hecho).
- ~~¿El pedido del cliente entra como "Confirmado"...?~~ → Entra como **Solicitado** y lo confirma logistics/admin.
- ~~¿Logistics también puede exportar el PDF?~~ → Sí: admin, logistics y cliente (cada uno lo suyo).

---

## ✅ Paso 92 — HECHO (13/10/2026)

Propuestas visuales aprobadas (artifacts "Bloque 2" a "Bloque 5"), todo en un solo paso:

1. **Aviso para clientes** (Ajustes → General): uno solo a la vez, texto ES/EN, fechas desde/hasta
   opcionales (con su estado: sin aviso / programado / se está viendo / ya ha pasado). Sale arriba en
   el inicio del cliente; lo puede cerrar y vuelve si cambia el texto. `app/aviso_clientes.py`
   (se guarda en `ajustes`; lo cerrado, en `usuarios.aviso_cerrado`).
2. **Incidencias** («Hay un problema con este pedido», en enviados/recibidos): motivo (Llegó dañado /
   Falta algo / Temperatura / Otro), texto y hasta 5 fotos (JPG/PNG). El texto y las fotos van también
   al chat del pedido (las fotos son los adjuntos de ese mensaje). Yikon: aviso arriba en la ficha,
   sección «Incidencias», pestaña «Incidencias» (la primera) en Pendientes y campana. Se cierra con
   «Resuelta» + nota, que le llega al cliente por el chat. Email: aviso nuevo «Un cliente avisa de un
   problema con un pedido» en Avisos internos (de fábrica: su Soporte de cliente y Logística).
   `app/incidencias.py`, tabla `incidencias`. Marca «nuevo» de la sección también para el cliente.
3. **Ver como un usuario** (Usuarios → icono 🕵 o ficha del usuario): solo admin, no con otro admin.
   Franja arriba con «Volver a mi usuario». Solo lectura de verdad: se rechaza cualquier envío y,
   además, toda la petición va en una transacción que se deshace (ni «visto», ni «leído», ni último
   acceso) y no sale ningún correo. Queda en la auditoría (acción «Ver como»). `app/ver_como.py`.
4. **Qué avisos recibe cada usuario del cliente**: ficha del cliente → «Avisos por email» (admin y su
   Soporte). Casillas por usuario: Proformas, Estado del pedido, Envío y seguimiento, Mensajes (de
   fábrica, todas). Emails en copia sin usuario (hasta 10), cada uno con sus tipos; reciben en el
   idioma del cliente y, de los mensajes, uno por mensaje. SIN aviso de «Facturas».
   `app/avisos_cliente.py`, `usuarios.avisos_desactivados`, tabla `copias_aviso`. En Correos al
   cliente cada correo dice de qué tipo es.
5. **Invitación y «cambiar contraseña» con logo y firma**: ahora son dos correos más de Ajustes →
   Correos al cliente (grupo «Acceso a la plataforma»), editables en ES/EN, con {nombre}, {email},
   {invita}, {enlace_acceso} (obligatorio) y {caducidad}. Las plantillas .txt viejas se han quitado.
6. **Ajustes → Seguridad**: caducidad de la invitación (7 días), del enlace de contraseña (2 h; antes
   1 h), bloqueo tras intentos fallidos (5 en 15 min) y cierre de sesión por inactividad (8 h; 0 =
   nunca; con «Recordarme» la cookie dura eso mismo). Los valores de fábrica siguen en config.py.
   Las consultas automáticas (contador de mensajes, chat abierto) no cuentan como actividad.
   `app/seguridad.py`. El límite por IP sigue en config.py.
7. **Exportar todo lo de un cliente** (solo admin, botón en su ficha): ZIP con pedidos.xlsx, facturas
   (PDF), proformas (todas las versiones), documentos de sus pedidos y un LEEME.txt (con lo que faltara
   en el servidor). Queda en la auditoría (acción «Exportar»). `app/clientes/exportar.py`.

Migración: `c3e7a9d15f02` (probada en SQLite y PostgreSQL 16, también hacia atrás).
Tests nuevos: test_ver_como, test_incidencias, test_avisos_cliente, test_aviso_y_seguridad,
test_exportar_cliente. 541 tests en SQLite. En PostgreSQL pasan todos menos dos que ya fallaban en el
paso 91 y no tienen que ver con este paso:
- `test_datos_prueba.py`: `flask datos-prueba` es solo para SQLite (en PostgreSQL ese archivo se cuelga).
- `test_numero_no_se_reutiliza_si_se_borra_un_pedido`: borra un pedido que ya tiene correos en el
  registro de «Correos enviados» y PostgreSQL no lo deja (clave foránea). La web nunca borra pedidos,
  solo ese test; si algún día se pueden borrar, habrá que borrar o desligar antes sus correos.

En reserva: «Mis lotes» (no se sabe aún si los clientes lo necesitan) y «Pedidos habituales» (13/10: se deja pendiente; de momento está «Repetir pedido»).
Descartado: facturación por defecto para clientes nuevos, motivos rápidos al devolver, papelera,
acciones en bloque con usuarios, varias direcciones de entrega, filtros recordados en las listas,
pruebas automáticas con navegador.

---

## ✅ Después del paso 92 — HECHO (13/10/2026)

- **Revisión de correos antes de enviarlos** (lo hizo Álvaro en otra conversación; ver
  `INSTRUCCIONES-REVISION-CORREOS.txt`, `app/revision_correo.py`, migración `a813c0e10213`): los correos del
  equipo quedan como borrador y se revisan en una ventana antes de salir.
- **Precios especiales de productos sueltos por cliente** (Álvaro; migración `b913c0e10213`).
- **Paginación de 10 en 10** en todas las listas largas (se puede elegir 25 o 50), con ‹ ›.
  `config.ELEMENTOS_POR_PAGINA`, `utils.paginar(select, parametro, tamano)`, macro `paginacion` en
  `_macros.html`. La ficha del cliente pagina sus pedidos y sus facturas por separado
  (`?pagina_pedidos=` / `?pagina_facturas=`). Test: `test_paginacion.py`.
- **Catálogo propio de cada cliente** (ficha del cliente → «Su catálogo», admin y su Soporte; queda en la
  auditoría): «Todo el catálogo» (de fábrica) o «Solo lo que se marque» (kits que puede pedir y productos que
  ve en Productos), con buscador, marcar/desmarcar todo y copiar de otro cliente. Yikon puede pedir cualquier
  cosa en su nombre. Si se quita un kit de una proforma abierta, avisa al guardar. `app/catalogo_cliente.py`,
  `Cliente.catalogo_propio`, tablas `catalogo_kits` y `catalogo_productos`, migración `c1d7e5a3b902`.
  Test: `test_catalogo_cliente.py`.

### Hecho el 13–14/10/2026
- **En producción** en https://yikonsupport.com (ver «Nuestro servidor» en DESPLIEGUE.md). Código en GitHub
  (`alvaroYG/yikonsupport`); se actualiza con `deploy/actualizar.sh`.
- **Tests de la revisión de correos adaptados**: `confirmar_correos()` en `tests/conftest.py` hace lo que el
  botón «Enviar» de la ventana de revisión. 564 + los nuevos, todos pasan. (`test_kits` fallaba por otra
  cosa: el apartado de la ficha ahora se llama «Precios especiales».)
- **Los avisos entre compañeros salen solos** (decisión de Álvaro, 14/10): si TODOS los destinatarios son
  usuarios activos del equipo (admin, Logística, Soporte de cliente, Soporte ChromGo), no pasan por la
  revisión: factura para revisar/devuelta, notas internas, «Compartir con Logística», devuelto a
  preparación, correo de prueba de Ajustes… Se siguen revisando: los que llevan a alguien de fuera
  (cliente o email en copia), las **invitaciones** (aunque sean para un compañero) y los **reenvíos** del
  registro. `revision_correo.solo_para_el_equipo()`, test: `test_correos_entre_companeros.py`.
- **Carga desde Excel** (`flask importar-datos plantilla.xlsx [--guardar]`, `app/importar.py`): productos,
  kits con sus componentes y empresas; sin `--guardar` es una prueba; solo crea (lo que existe no se toca);
  con un error no guarda nada. Plantilla vacía: `deploy/plantilla_carga.xlsx`. Test: `test_importar.py`.
  Primera carga: el catálogo de `Kits_1.xlsx` de Álvaro (78 productos, 43 kits) convertido a la plantilla con
  las propuestas aceptadas tal cual (14/10): **precios a 0**, todos los kits **montados**, referencias de kit
  inventadas (PGTA-CI-ILL-24…), índices con variantes «a decidir» en -001 y la primera opción en los kits con
  «ó». Se corrige todo después desde la web.
- **Recuperado lo de ChatGPT del 9/10** (se había perdido; 14/10): el **cliente pide productos sueltos**
  (solos o con kits; con catálogo propio, solo los de su catálogo; «Repetir» los conserva), el **documento
  del pedido es obligatorio para todos** (cliente y Yikon; el error sale en la ventana sin perder lo escrito y
  el servidor también lo exige) y **desplegables con buscador** (`static/js/selectores_buscables.js`,
  atributo `data-buscable`): cliente al crear un pedido, productos de un kit, ampliar un pedido; en la
  ventana de pedido, kits y sueltos con su buscador (`pedido.js`). Se mantiene el campo Fecha del pedido.
  Test: `test_pedido_sueltos_documento.py` (los tests crean los pedidos con `doc_pedido()` de conftest).
  Sin usar (restos antiguos): `pedidos/_campos_pedido_cliente.html`, `_modal_pedido_cliente.html`, `pedido_cliente.js`.
- **Ordenar por las cabeceras** (14/10) en Productos, Kits, Clientes, Pedidos, Facturas, Inventario y
  Movimientos: clic = A→Z / menor→mayor (fechas: lo más reciente primero), otro clic = al revés, con ▲/▼ y
  `aria-sort`. Lo hace el servidor (sirve con la paginación) y mantiene buscador y filtros; vuelve a la página 1.
  `utils.ordenar()` (consultas) y `utils.ordenar_lista()` (listas calculadas, como el stock) + macro `th_orden`
  en `_macros.html`. Pedidos: el estado se ordena por el flujo; el PDF y el Excel salen en el mismo orden.
  **Kits**: buscador (también por los productos que lleva: «YK001»; se marca el producto que coincide),
  paginación y Referencia/Nombre en columnas separadas; los inactivos, siempre al final. **Inventario**: buscador
  (kits y productos; un kit también por sus productos), columna Referencia aparte y se queda en la pestaña
  (#kits / #productos) al buscar u ordenar. **Movimientos**: buscador (artículo, lote, nota, pedido).
  Sin ordenar: Total y Productos de Pedidos, Estado de Facturas (se calculan). Test: `test_ordenar.py`.
- **Estado → copia de seguridad**: `copia_seguridad.sh` deja la hora en `/srv/yikonpo/ultima_copia.txt` y
  el `.env` del servidor lleva `COPIA_SEGURIDAD_MARCA` con esa ruta.

### Pendiente
- Botón «Pedir este kit» en la página de Productos del cliente (de la propuesta del catálogo; sin hacer:
  la ventana de pedido tendría que abrirse con el kit ya elegido).

