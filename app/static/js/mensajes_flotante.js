/*
  Botón flotante de mensajes (solo Yikon). No es un chat en directo:
    - al abrir el panel se piden las conversaciones al servidor (trozos de HTML);
    - el número del botón se refresca cada minuto y cada vez que se pinta algo.
  Todo lo que lleva data-mf-url carga esa dirección dentro del panel; el formulario de
  respuesta se envía sin recargar la página. Si algo falla, queda el enlace a la página de mensajes.
*/
(function () {
  "use strict";
  var raiz = document.getElementById("mensajes-flotante");
  if (!raiz) return;
  var boton = raiz.querySelector("[data-mf-boton]");
  var panel = raiz.querySelector("[data-mf-panel]");
  var contador = raiz.querySelector("[data-mf-contador]");
  var cargando = false;

  function ponerCuenta(n) {
    n = parseInt(n, 10) || 0;
    contador.textContent = n;
    contador.hidden = n === 0;
    boton.setAttribute("aria-label", boton.dataset.etiqueta.replace("{n}", n));
  }

  function pintar(html) {
    panel.innerHTML = html;
    var cuerpo = panel.querySelector("[data-cuenta]");
    if (cuerpo) ponerCuenta(cuerpo.dataset.cuenta);
    var final = panel.querySelector("[data-mf-al-final]");
    if (final) final.scrollTop = final.scrollHeight;          // una conversación: al último mensaje
    var texto = panel.querySelector("textarea");
    if (texto) texto.focus();
  }

  function cargar(url, opciones) {
    if (cargando) return;
    cargando = true;
    panel.setAttribute("aria-busy", "true");
    fetch(url, Object.assign({ credentials: "same-origin", headers: { "X-Requested-With": "fetch" } }, opciones || {}))
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(pintar)
      .catch(function () { panel.innerHTML = '<p class="m-3 small">' + raiz.dataset.error + ' <a href="' + raiz.dataset.pagina + '">' + raiz.dataset.enlace + "</a></p>"; })
      .finally(function () { cargando = false; panel.removeAttribute("aria-busy"); });
  }

  function abrir() {
    panel.hidden = false;
    raiz.classList.add("abierto");
    boton.setAttribute("aria-expanded", "true");
    cargar(raiz.dataset.lista);
  }

  function cerrar() {
    panel.hidden = true;
    raiz.classList.remove("abierto");
    boton.setAttribute("aria-expanded", "false");
    boton.focus();
  }

  boton.addEventListener("click", function () { panel.hidden ? abrir() : cerrar(); });

  panel.addEventListener("click", function (e) {
    if (e.target.closest("[data-mf-cerrar]")) { cerrar(); return; }
    var destino = e.target.closest("[data-mf-url]");
    if (destino) cargar(destino.dataset.mfUrl);
  });

  panel.addEventListener("submit", function (e) {
    var form = e.target.closest("[data-mf-form]");
    if (!form) return;
    e.preventDefault();
    cargar(form.action, { method: "POST", body: new FormData(form) });
  });

  // Enter envía; Mayús+Enter, salto de línea
  panel.addEventListener("keydown", function (e) {
    if (e.key === "Escape") { cerrar(); return; }
    if (e.key === "Enter" && !e.shiftKey && e.target.matches("textarea")) {
      e.preventDefault();
      e.target.form.requestSubmit();
    }
  });

  // El número del botón, al día sin recargar la página (cada minuto, solo con la pestaña visible)
  setInterval(function () {
    if (document.hidden || !panel.hidden) return;
    fetch(raiz.dataset.cuenta, { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d) ponerCuenta(d.sin_leer); })
      .catch(function () {});
  }, 60000);
})();
