// Conversaciones (ficha del pedido y página de Mensajes):
//  - baja hasta el último mensaje al abrir
//  - cada 30 s pregunta al servidor si hay mensajes nuevos y los añade (sin recargar)
//  - Ctrl + Intro (o Cmd + Intro en Mac) envía el mensaje
document.querySelectorAll("[data-conversacion]").forEach(function (caja) {
  const lista = caja.querySelector("[data-mensajes]");
  const url = caja.dataset.urlNuevos;
  const form = caja.querySelector("[data-form-mensaje]");

  function ultimoId() {
    const burbujas = lista.querySelectorAll(".burbuja");
    return burbujas.length ? burbujas[burbujas.length - 1].dataset.id : 0;
  }
  function alFinal() { lista.scrollTop = lista.scrollHeight; }
  function cercaDelFinal() { return lista.scrollHeight - lista.scrollTop - lista.clientHeight < 80; }

  alFinal();

  let abierto = false;   // true justo al abrir el chat: el servidor lo da por leído aunque no haya nuevos
  function comprobar() {
    if (document.visibilityState !== "visible") return;   // pestaña oculta: no gastes
    if (caja.closest(".collapse:not(.show)")) return;    // chat plegado: no los des por leídos sin verlos
    if (caja.closest("[hidden]")) return;                // chat cerrado (botones de la ficha del pedido): igual
    fetch(url + "?despues=" + ultimoId() + (abierto ? "&abierto=1" : ""), { headers: { "X-Requested-With": "fetch" }, credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (datos) {
        abierto = false;
        if (!datos || !datos.html.trim()) return;
        const bajar = cercaDelFinal();
        const vacio = lista.querySelector("[data-vacio]");
        if (vacio) vacio.remove();
        lista.insertAdjacentHTML("beforeend", datos.html);
        if (bajar) alFinal();
      })
      .catch(function () { /* sin conexión: ya lo intentará en la próxima vuelta */ });
  }
  setInterval(comprobar, 30000);
  // Dentro de un desplegable (chat interno): al abrirlo, al último mensaje y mira si hay nuevos
  const plegable = caja.closest(".collapse");
  if (plegable) {
    plegable.addEventListener("shown.bs.collapse", function () { alFinal(); comprobar(); });
    // Si se llega con #interno (campana, email o tras enviar una nota), se abre
    const bloque = plegable.parentElement && plegable.parentElement.closest("[id]");
    if (bloque && location.hash === "#" + bloque.id && window.bootstrap) {
      bootstrap.Collapse.getOrCreateInstance(plegable).show();
    }
  }
  // Chat de la ficha del pedido que se abre con su botón (js/chat_pedido.js)
  const panel = caja.closest("[data-chat-panel]");
  if (panel) panel.addEventListener("chat:abierto", function () { alFinal(); abierto = true; comprobar(); });
  document.addEventListener("visibilitychange", comprobar);   // al volver a la pestaña

  if (form) {
    const texto = form.querySelector("textarea");
    const ficheros = form.querySelector("[data-adjuntos]");
    const nombres = form.querySelector("[data-nombres-adjuntos]");
    const ayuda = nombres ? nombres.textContent : "";
    // Enseña qué archivos has elegido (el campo de archivo está oculto tras el botón 📎)
    if (ficheros) ficheros.addEventListener("change", function () {
      const lista = Array.from(ficheros.files).map(function (f) { return f.name; });
      nombres.textContent = lista.length ? "📎 " + lista.join(", ") : ayuda;
    });
    texto.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); form.requestSubmit(); }
    });
    form.addEventListener("submit", function (e) {
      const hayArchivos = ficheros && ficheros.files.length > 0;
      if (!texto.value.trim() && !hayArchivos) { e.preventDefault(); texto.focus(); return; }
      form.querySelector("[type=submit]").disabled = true;   // evita enviarlo dos veces
    });
  }
});
