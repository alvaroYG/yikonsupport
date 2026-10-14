// Chats de la ficha del pedido (botones "Cliente" e "Interno" de la cabecera):
//  - cada botón abre su chat debajo de la cabecera; solo uno a la vez
//  - se cierra con ✕, con Esc o pulsando fuera
//  - se abre solo si se llega con #mensajes o #interno (campana, Pendientes, emails) o tras enviar
//  - al abrirlo, avisa a mensajes.js ("chat:abierto"): baja al final y los da por leídos
// Y en cualquier página: la cuenta atrás del aviso "Enviado · Deshacer".
(function () {
  const paneles = Array.from(document.querySelectorAll("[data-chat-panel]"));
  const botones = Array.from(document.querySelectorAll("[data-abre-chat]"));

  function boton(panel) { return botones.find(function (b) { return b.dataset.abreChat === panel.id; }); }

  function cerrar(panel) {
    if (panel.hidden) return;
    panel.hidden = true;
    const b = boton(panel);
    if (b) b.setAttribute("aria-expanded", "false");
  }

  function abrir(panel) {
    paneles.forEach(function (p) { if (p !== panel) cerrar(p); });
    panel.hidden = false;
    const b = boton(panel);
    if (b) {
      b.setAttribute("aria-expanded", "true");
      const contador = b.querySelector("[data-contador-chat]");
      if (contador) contador.remove();         // al abrirlo, quedan leídos
    }
    panel.dispatchEvent(new CustomEvent("chat:abierto"));
    const texto = panel.querySelector("textarea");
    if (texto && window.matchMedia("(min-width: 576px)").matches) texto.focus({ preventScroll: true });
  }

  botones.forEach(function (b) {
    b.addEventListener("click", function (e) {
      e.stopPropagation();
      const panel = document.getElementById(b.dataset.abreChat);
      if (!panel) return;
      (panel.hidden ? abrir : cerrar)(panel);
      // Desde un enlace de más abajo (p. ej. la proforma): subir hasta el chat
      if (!panel.hidden && b !== boton(panel)) panel.scrollIntoView({ block: "start", behavior: "smooth" });
    });
  });
  paneles.forEach(function (panel) {
    panel.querySelectorAll("[data-cierra-chat]").forEach(function (x) {
      x.addEventListener("click", function () { cerrar(panel); });
    });
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") paneles.forEach(cerrar);
  });
  document.addEventListener("click", function (e) {
    paneles.forEach(function (panel) {
      if (!panel.hidden && !panel.contains(e.target) && document.body.contains(e.target)) cerrar(panel);
    });
  });

  function segunHash() {
    const panel = paneles.find(function (p) { return "#" + p.id === location.hash; });
    if (panel) abrir(panel);
  }
  window.addEventListener("hashchange", segunHash);
  const forzado = paneles.find(function (p) { return p.hasAttribute("data-abrir"); });
  if (forzado) abrir(forzado); else segunHash();
  // Al llegar con #mensajes / #interno el navegador baja hasta el chat; mejor arriba, con la cabecera
  if (paneles.some(function (p) { return !p.hidden; })) {
    window.addEventListener("load", function () { window.scrollTo(0, 0); });
  }

  // "Enviado · Deshacer": cuenta atrás; a 0 desaparece (el mensaje ya le ha llegado al cliente)
  document.querySelectorAll("[data-deshacer]").forEach(function (aviso) {
    let quedan = parseInt(aviso.dataset.segundos, 10) || 0;
    const cuenta = aviso.querySelector("[data-cuenta]");
    const reloj = setInterval(function () {
      quedan -= 1;
      if (quedan <= 0) { clearInterval(reloj); aviso.remove(); return; }
      if (cuenta) cuenta.textContent = quedan + " s";
    }, 1000);
  });
})();
