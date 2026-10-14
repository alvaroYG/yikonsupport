// Filas que se añaden y quitan en un formulario (p. ej. los productos de un kit).
// Uso en la plantilla:
//   <div data-filas="componentes">  ...una o más <div class="fila">...</div>...  </div>
//   <button type="button" data-anadir-a="componentes">Añadir</button>
// Cada campo de la fila se llama "componentes-0-producto_id", "componentes-0-cantidad"...
// (lo que espera un FieldList de WTForms). Al añadir se copia la última fila con el
// número siguiente; al quitar, la última que queda se vacía en vez de borrarse.
// Botones opcionales [data-subir-fila] / [data-bajar-fila]: mueven la fila. Después de
// mover (o quitar) se renumeran todas: el servidor lee el orden por esos números.
document.querySelectorAll("[data-filas]").forEach(function (contenedor) {
  const prefijo = contenedor.dataset.filas;
  const boton = document.querySelector('[data-anadir-a="' + prefijo + '"]');
  const patron = new RegExp(prefijo + "-(\\d+)-");
  const maximo = parseInt(contenedor.dataset.maximo || "40", 10);
  let siguiente = 0;
  contenedor.querySelectorAll("[name]").forEach(function (campo) {
    const m = campo.name.match(patron);
    if (m) siguiente = Math.max(siguiente, parseInt(m[1], 10) + 1);
  });
  function vaciar(fila) {
    fila.querySelectorAll("select").forEach(function (s) { s.value = s.options[0] ? s.options[0].value : ""; });
    fila.querySelectorAll("input").forEach(function (i) { i.value = i.defaultValue && i.type === "number" ? "1" : ""; });
  }
  if (boton) boton.addEventListener("click", function () {
    const filas = contenedor.querySelectorAll(".fila");
    if (filas.length >= maximo) return;
    const nueva = filas[filas.length - 1].cloneNode(true);
    nueva.querySelectorAll("[name]").forEach(function (campo) {
      campo.name = campo.name.replace(patron, prefijo + "-" + siguiente + "-");
      campo.id = campo.name;
    });
    vaciar(nueva);
    siguiente++;
    contenedor.appendChild(nueva);
    const primero = nueva.querySelector("select, input");
    if (primero) primero.focus();
  });
  // Renumera las filas según su posición en pantalla: 0, 1, 2...
  function renumerar() {
    contenedor.querySelectorAll(".fila").forEach(function (fila, i) {
      fila.querySelectorAll("[name]").forEach(function (campo) {
        campo.name = campo.name.replace(patron, prefijo + "-" + i + "-");
        campo.id = campo.name;
      });
    });
    siguiente = contenedor.querySelectorAll(".fila").length;
  }
  contenedor.addEventListener("click", function (evento) {
    const subir = evento.target.closest("[data-subir-fila]");
    const bajar = evento.target.closest("[data-bajar-fila]");
    if (subir || bajar) {
      const fila = (subir || bajar).closest(".fila");
      const otra = subir ? fila.previousElementSibling : fila.nextElementSibling;
      if (otra && otra.classList.contains("fila")) {
        if (subir) contenedor.insertBefore(fila, otra);
        else contenedor.insertBefore(otra, fila);
        renumerar();
        (subir || bajar).focus();          // el foco sigue en la flecha (se puede pulsar otra vez)
      }
      return;
    }
    const quitar = evento.target.closest("[data-quitar-fila]");
    if (!quitar) return;
    const filas = contenedor.querySelectorAll(".fila");
    if (filas.length > 1) { quitar.closest(".fila").remove(); renumerar(); }
    else vaciar(filas[0]);
  });
});
