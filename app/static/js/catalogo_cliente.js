// Ficha del cliente → «Su catálogo»: enseñar la lista solo en «Solo lo que se marque», buscar y
// marcar/desmarcar lo que se ve. Sin JavaScript, la lista sale igual y el formulario funciona.
(function () {
  document.querySelectorAll("[data-catalogo-cliente]").forEach(function (form) {
    const lista = form.querySelector("[data-lista-catalogo]");
    const filas = Array.from(form.querySelectorAll("[data-fila-catalogo]"));
    const buscar = form.querySelector("[data-buscar-catalogo]");
    function modo() {
      const propio = form.querySelector('input[name="modo"][value="propio"]');
      if (lista) lista.hidden = !(propio && propio.checked);
    }
    form.querySelectorAll('input[name="modo"]').forEach(function (r) { r.addEventListener("change", modo); });
    if (buscar) buscar.addEventListener("input", function () {
      const q = buscar.value.trim().toLowerCase();
      filas.forEach(function (f) { f.hidden = q && f.dataset.texto.indexOf(q) === -1; });
    });
    form.querySelectorAll("[data-marcar-todo]").forEach(function (b) {
      b.addEventListener("click", function () {
        filas.forEach(function (f) {
          if (!f.hidden) f.querySelector('input[type="checkbox"]').checked = b.dataset.marcarTodo === "1";
        });
      });
    });
    modo();
  });
})();
