// Tarjeta "Lotes de este pedido" (pedidos/_lotes.html).
// - Comprueba mientras escribes que no asignas más unidades de las que lleva el pedido ni más
//   de las que quedan libres en cada lote. (El servidor lo vuelve a comprobar al guardar.)
// - Si has cambiado algo y no lo has guardado, bloquea "Enviar proforma": la proforma lleva
//   la caducidad de los lotes GUARDADOS, no la de lo que hay escrito en pantalla.
(function () {
  const form = document.getElementById("form-lotes");
  if (!form) return;
  const guardar = document.getElementById("btn-guardar-lotes");
  const textos = form.dataset;
  const enviarProforma = document.querySelector('form[action$="/proforma/enviar"] [type="submit"]');
  const campos = Array.from(form.querySelectorAll("input.campo-lote"));
  // Lo que había al cargar la página (la propuesta): "cambiado" = distinto de eso
  campos.forEach(function (c) { c.dataset.inicial = c.value; });

  function rellenar(texto, valores) {
    return Object.keys(valores).reduce(function (t, k) { return t.replaceAll("{" + k + "}", valores[k]); }, texto);
  }

  function comprobar() {
    let todoBien = true;
    form.querySelectorAll("[data-articulo-lotes]").forEach(function (bloque) {
      const total = parseInt(bloque.dataset.necesarias, 10);
      const estado = bloque.querySelector("[data-estado-lotes]");
      if (!estado) return;                       // artículo sin lotes libres: nada que comprobar
      let suma = 0, mensaje = "";
      bloque.querySelectorAll("input.campo-lote, input[type=hidden]").forEach(function (campo) {
        const n = parseInt(campo.value, 10) || 0;
        suma += n;
        if (campo.type === "hidden") return;
        const min = parseInt(campo.min, 10) || 0, max = parseInt(campo.max, 10);
        const mal = n < min || n > max;
        campo.classList.toggle("is-invalid", mal);
        if (mal) mensaje = rellenar(textos.textoLote, { min: min, max: max });
      });
      if (!mensaje && suma > total) mensaje = rellenar(textos.textoSobran, { n: suma, total: total });
      estado.textContent = mensaje || rellenar(suma === total ? textos.textoOk : textos.textoFaltan, { n: suma, total: total });
      estado.classList.toggle("reparto-mal", Boolean(mensaje));
      estado.classList.toggle("reparto-pendiente", !mensaje && suma < total);
      if (mensaje) todoBien = false;
    });
    if (guardar) guardar.disabled = !todoBien;
    const cambiado = campos.some(function (c) { return c.value !== c.dataset.inicial; });
    if (enviarProforma) {
      enviarProforma.disabled = cambiado;
      enviarProforma.title = cambiado ? enviarProforma.dataset.avisoLotes || "" : "";
    }
    const aviso = document.getElementById("aviso-lotes-sin-guardar");
    if (aviso) aviso.hidden = !cambiado;
  }
  form.addEventListener("input", comprobar);
  comprobar();
})();
