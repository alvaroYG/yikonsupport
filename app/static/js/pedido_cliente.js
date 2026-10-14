// Filas de kits del pedido del cliente: añadir / quitar.
// Funciona en cualquier formulario que tenga un contenedor [data-filas-kits]
// (la página normal y la ventana emergente usan este mismo archivo).
document.querySelectorAll("form").forEach(function (form) {
  const contenedor = form.querySelector("[data-filas-kits]");
  const boton = form.querySelector("[data-anadir-fila]");
  if (!contenedor || !boton) return;

  // índice para la siguiente fila: uno más que el mayor que exista
  let siguiente = 0;
  contenedor.querySelectorAll("select").forEach(function (s) {
    const n = parseInt((s.name.match(/lineas-(\d+)-/) || [])[1], 10);
    if (!isNaN(n)) siguiente = Math.max(siguiente, n + 1);
  });

  boton.addEventListener("click", function () {
    if (contenedor.querySelectorAll(".fila-kit").length >= 20) return;
    const nueva = contenedor.querySelector(".fila-kit").cloneNode(true);
    nueva.querySelectorAll("select, input").forEach(function (campo) {
      campo.name = campo.name.replace(/lineas-\d+-/, "lineas-" + siguiente + "-");
      campo.id = campo.name;
      campo.value = campo.tagName === "SELECT" ? "0" : "1";
    });
    siguiente++;
    contenedor.appendChild(nueva);
    nueva.querySelector("select").focus();
  });

  contenedor.addEventListener("click", function (evento) {
    if (!evento.target.classList.contains("quitar-fila")) return;
    const filas = contenedor.querySelectorAll(".fila-kit");
    if (filas.length > 1) evento.target.closest(".fila-kit").remove();
    else filas[0].querySelector("select").value = "0";   // la última no se borra: se vacía
  });
});

// Validación en el navegador ANTES de enviar: si falta algo, el mensaje sale en rojo
// debajo del campo y el formulario no se envía (la ventana no se cierra).
// El servidor vuelve a comprobarlo todo: esto es solo para que sea más cómodo.
document.querySelectorAll("form").forEach(function (form) {
  const contenedor = form.querySelector("[data-filas-kits]");
  const referencia = form.querySelector('input[name="referencia"]');
  if (!contenedor || !referencia) return;
  const errorReferencia = form.querySelector("[data-error-referencia]");
  const errorKits = form.querySelector("[data-error-kits]");

  function hayKits() {
    return Array.from(contenedor.querySelectorAll(".fila-kit")).some(function (fila) {
      return fila.querySelector("select").value !== "0" &&
             parseInt(fila.querySelector("input").value, 10) > 0;
    });
  }

  form.addEventListener("submit", function (evento) {
    let primerError = null;
    if (!referencia.value.trim()) {
      referencia.classList.add("is-invalid");
      errorReferencia.hidden = false;
      primerError = primerError || referencia;
    }
    if (!hayKits()) {
      errorKits.hidden = false;
      primerError = primerError || contenedor.querySelector("select");
    }
    if (primerError) {
      evento.preventDefault();
      primerError.focus();
    }
  });

  // en cuanto lo corrige, el error desaparece
  referencia.addEventListener("input", function () {
    if (referencia.value.trim()) {
      referencia.classList.remove("is-invalid");
      errorReferencia.hidden = true;
    }
  });
  contenedor.addEventListener("change", function () {
    if (hayKits()) errorKits.hidden = true;
  });
});
