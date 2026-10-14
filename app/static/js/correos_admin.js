// Ajustes → editar un correo al cliente:
//  - los botones de datos ({referencia}…) los ponen donde está el cursor (en el asunto o en el texto)
//  - la vista previa se actualiza sola mientras escribes (sin guardar nada)
//  - "Volver al texto original" pide confirmación
(function () {
  const form = document.getElementById("form-correo");
  if (!form) return;
  const campos = Array.from(form.querySelectorAll("[data-campo-correo]"));
  let ultimo = form.querySelector("#cuerpo");
  campos.forEach(function (c) { c.addEventListener("focus", function () { ultimo = c; }); });

  form.querySelectorAll("[data-insertar]").forEach(function (b) {
    b.addEventListener("click", function () {
      const texto = b.dataset.insertar;
      const ini = ultimo.selectionStart ?? ultimo.value.length;
      const fin = ultimo.selectionEnd ?? ini;
      ultimo.value = ultimo.value.slice(0, ini) + texto + ultimo.value.slice(fin);
      ultimo.focus();
      ultimo.setSelectionRange(ini + texto.length, ini + texto.length);
      actualizar();
    });
  });

  const iframe = document.getElementById("vista-html");
  const asunto = document.getElementById("vista-asunto");
  const errores = document.getElementById("correo-errores");
  let espera = null, pedida = 0;
  function actualizar() {
    clearTimeout(espera);
    espera = setTimeout(function () {
      const esta = ++pedida;
      fetch(form.dataset.vistaUrl, { method: "POST", body: new FormData(form), credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          if (!d || esta !== pedida) return;            // (llegó tarde: ya hay otra más nueva)
          iframe.srcdoc = d.html;
          if (asunto) asunto.textContent = d.asunto;
          const lista = errores.querySelector("ul");
          lista.innerHTML = "";
          d.errores.forEach(function (e) { const li = document.createElement("li"); li.textContent = e; lista.appendChild(li); });
          errores.classList.toggle("d-none", d.errores.length === 0);
        })
        .catch(function () {});
    }, 400);
  }
  campos.forEach(function (c) { c.addEventListener("input", actualizar); });

  form.querySelectorAll("[data-confirmar]").forEach(function (b) {
    b.addEventListener("click", function (e) { if (!confirm(b.dataset.confirmar)) e.preventDefault(); });
  });
})();
