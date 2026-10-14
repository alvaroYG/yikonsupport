// Ficha del pedido: secciones plegables (macro `seccion` de _macros.html).
//
// - Recuerda qué secciones tiene abiertas cada persona, en SU navegador (localStorage) y para
//   todos los pedidos: si te gusta el historial abierto, lo tendrás abierto en todas las fichas.
// - Una sección con algo que hacer (data-forzar) llega abierta aunque la tuvieras cerrada.
// - Si la dirección trae #facturas, #lotes, #mensajes…, esa sección se abre y se va a ella.
// - Botón "Abrir todo / Cerrar todo".
(function () {
  const CLAVE = "ficha-pedido-secciones";
  const secciones = Array.from(document.querySelectorAll("[data-seccion]"));
  if (!secciones.length) return;

  function leer() {
    try { return JSON.parse(localStorage.getItem(CLAVE)) || {}; } catch (e) { return {}; }   // (modo privado, etc.)
  }
  function guardar(estado) {
    try { localStorage.setItem(CLAVE, JSON.stringify(estado)); } catch (e) { /* sin almacenamiento: no se recuerda */ }
  }
  const cuerpo = function (s) { return s.querySelector(":scope > .collapse"); };
  const boton = function (s) { return s.querySelector(".seccion-cab"); };

  // Abrir o cerrar SIN animación (al cargar la página, para que no "salte")
  function poner(seccion, abierta) {
    cuerpo(seccion).classList.toggle("show", abierta);
    boton(seccion).classList.toggle("collapsed", !abierta);
    boton(seccion).setAttribute("aria-expanded", abierta ? "true" : "false");
  }

  // 1. Al cargar: lo que esta persona dejó la última vez (salvo las forzadas)
  const guardado = leer();
  secciones.forEach(function (s) {
    const clave = s.dataset.seccion;
    if (!s.hasAttribute("data-forzar") && typeof guardado[clave] === "boolean") poner(s, guardado[clave]);
  });

  // 2. Cada vez que se abre o se cierra una a mano, se apunta
  secciones.forEach(function (s) {
    cuerpo(s).addEventListener("shown.bs.collapse", function (e) { if (e.target === cuerpo(s)) apuntar(s, true); });
    cuerpo(s).addEventListener("hidden.bs.collapse", function (e) { if (e.target === cuerpo(s)) apuntar(s, false); });
  });
  // La marca "nuevo" se quita al abrir la sección a mano: ya lo has visto
  secciones.forEach(function (s) {
    cuerpo(s).addEventListener("shown.bs.collapse", function (e) {
      const marca = e.target === cuerpo(s) && s.querySelector("[data-nuevo]");
      if (marca) marca.remove();
    });
  });
  function apuntar(seccion, abierta) {
    const estado = leer();
    estado[seccion.dataset.seccion] = abierta;
    guardar(estado);
    pintarBoton();
  }

  // 3. Enlaces con #seccion (p. ej. "Registrar factura", o al volver de guardar los lotes)
  function irA() {
    const id = decodeURIComponent(location.hash.slice(1));
    const seccion = id && secciones.find(function (s) { return s.id === id; });
    if (!seccion) return;
    poner(seccion, true);          // (no se apunta: es solo para esta visita)
    seccion.scrollIntoView({ block: "start" });
    pintarBoton();
  }
  window.addEventListener("hashchange", irA);
  irA();

  // 4. Abrir todo / Cerrar todo
  const todo = document.getElementById("btn-secciones");
  function todasAbiertas() { return secciones.every(function (s) { return cuerpo(s).classList.contains("show"); }); }
  function pintarBoton() {
    if (!todo) return;
    const abiertas = todasAbiertas();
    // El botón es solo un icono: el texto va en el mensaje al pasar el ratón y en aria-label
    const texto = abiertas ? todo.dataset.cerrar : todo.dataset.abrir;
    todo.setAttribute("aria-label", texto);
    const aviso = window.bootstrap && bootstrap.Tooltip.getInstance(todo);
    if (aviso) aviso.setContent({ ".tooltip-inner": texto }); else todo.title = texto;
    todo.querySelector("i").className = "fas " + (abiertas ? "fa-compress-alt" : "fa-expand-alt");
  }
  if (todo) todo.addEventListener("click", function () {
    const abrir = !todasAbiertas();
    const estado = leer();
    secciones.forEach(function (s) { poner(s, abrir); estado[s.dataset.seccion] = abrir; });
    guardar(estado);
    pintarBoton();
  });
  // 5. Botones de solo icono de la cabecera: el title se enseña como aviso de Bootstrap
  //    (sale al momento y con el estilo de la plataforma). Solo al pasar el ratón o con el
  //    teclado: así no se queda pegado tras pulsar un botón que abre una ventana.
  document.querySelectorAll("#acciones-pedido [title]").forEach(function (el) {
    new bootstrap.Tooltip(el, { placement: "bottom", trigger: "hover focus" });
  });
  pintarBoton();
})();
