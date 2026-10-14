// Buscador global de la barra superior.
//  - Mientras se escribe (2 letras o más) pide sugerencias al servidor y las enseña debajo.
//  - Flechas ↑ ↓ para moverse, Intro para abrir, Esc para cerrar.
//  - Atajo: "/" o Ctrl+K (Cmd+K en Mac) lleva el cursor a la caja desde cualquier página.
// Sin JavaScript sigue funcionando: Intro envía el formulario a la página de resultados.
(function () {
  var caja = document.querySelector("[data-buscador]");
  if (!caja) return;
  var campo = caja.querySelector("input[type=search]"), panel = caja.querySelector("[data-buscador-panel]");
  var url = caja.dataset.url, espera = null, ultima = "", activo = -1;

  function opciones() { return Array.prototype.slice.call(panel.querySelectorAll("[role=option]")); }
  function cerrar() { panel.hidden = true; campo.setAttribute("aria-expanded", "false"); activo = -1; }
  function abrir() { panel.hidden = false; campo.setAttribute("aria-expanded", "true"); }
  function marcar(i) {
    var ops = opciones();
    if (!ops.length) return;
    activo = (i + ops.length) % ops.length;
    ops.forEach(function (o, n) { o.classList.toggle("activo", n === activo); });
    ops[activo].scrollIntoView({ block: "nearest" });
  }
  function pedir() {
    var q = campo.value.trim();
    if (q.length < 2) { cerrar(); ultima = ""; return; }
    if (q === ultima) { abrir(); return; }
    ultima = q;
    fetch(url + "?q=" + encodeURIComponent(q), { headers: { "X-Requested-With": "fetch" }, credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (datos) {
        // Si entretanto se ha seguido escribiendo, esta respuesta ya es vieja: se ignora
        if (!datos || datos.q !== campo.value.trim().replace(/\s+/g, " ")) return;
        panel.innerHTML = datos.html;
        activo = -1;
        abrir();
      })
      .catch(function () { /* sin conexión: Intro sigue llevando a la página de resultados */ });
  }
  campo.addEventListener("input", function () { clearTimeout(espera); espera = setTimeout(pedir, 220); });
  campo.addEventListener("focus", function () { if (campo.value.trim().length >= 2) pedir(); });
  campo.addEventListener("keydown", function (e) {
    if (e.key === "ArrowDown") { e.preventDefault(); if (panel.hidden) pedir(); else marcar(activo + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); marcar(activo - 1); }
    else if (e.key === "Escape") { cerrar(); }
    else if (e.key === "Enter" && activo >= 0 && !panel.hidden) { e.preventDefault(); opciones()[activo].click(); }
  });
  document.addEventListener("click", function (e) { if (!caja.contains(e.target)) cerrar(); });
  document.addEventListener("keydown", function (e) {
    var escribiendo = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName) || document.activeElement.isContentEditable;
    if ((e.key === "/" && !escribiendo) || ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k")) {
      e.preventDefault(); campo.focus(); campo.select();
    }
  });
})();
