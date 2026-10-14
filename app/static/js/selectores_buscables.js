// Selector flotante reutilizable para formularios del catálogo y pedidos.
(function () {
let siguienteBuscadorPedido = 100000;
const kitPorId = {};
function crear(etiqueta, atributos, hijos) {
  const el = document.createElement(etiqueta);
  Object.entries(atributos || {}).forEach(function ([k, v]) {
    if (k === "texto") el.textContent = v;
    else if (k === "clase") el.className = v;
    else el.setAttribute(k, v);
  });
  (hijos || []).forEach(function (h) { el.appendChild(h); });
  return el;
}

  function conBuscador(select, etiqueta) {
    const opciones = Array.from(select.options);
    select.hidden = true;
    const buscar = crear("input", { type: "search", clase: "form-control", placeholder: etiqueta,
      "aria-label": etiqueta, "data-buscar-catalogo": "", autocomplete: "off" });
    const estado = crear("div", { clase: "small text-muted", role: "status", "aria-live": "polite" });
    const lista = crear("div", { clase: "list-group mt-1", "data-resultados-busqueda": "",
      style: "max-height: 240px; overflow-y: auto;" });
    const panel = crear("div", { clase: "p-2 border rounded-3 bg-white shadow", id: "buscador-pedido-" + (++siguienteBuscadorPedido), hidden: "",
      popover: "manual", style: "position: fixed; inset: auto; margin: 0; z-index: 1080; box-sizing: border-box; overflow: auto;" }, [buscar, estado, lista]);
    const textoSeleccion = crear("span", { clase: "flex-grow-1 text-start text-break" });
    const boton = crear("button", { type: "button", clase: "btn border rounded-3 bg-white w-100 d-flex align-items-center gap-2 p-2",
      title: etiqueta, "aria-label": etiqueta, "aria-expanded": "false", "aria-controls": panel.id,
      "data-abrir-buscador": "" }, [crear("i", { clase: "fas fa-search text-muted", "aria-hidden": "true" }), textoSeleccion,
      crear("i", { clase: "fas fa-chevron-down small text-muted", "aria-hidden": "true" })]);
    const contenedor = crear("div", {"data-selector-buscable": ""}, [select, boton, panel]);
    select.focus = function () { boton.focus(); };
    function actualizarSeleccion() {
      const opcion = opciones.find(o => o.value === select.value) || opciones[0];
      textoSeleccion.textContent = opcion.textContent;
      textoSeleccion.classList.toggle("text-muted", !select.value);
      boton.setAttribute("aria-label", etiqueta + ": " + opcion.textContent);
    }
    select.actualizarSeleccion = actualizarSeleccion;
    actualizarSeleccion();
    let eventosAbierto;
    function posicionar() {
      if (panel.hidden) return;
      const rect = boton.getBoundingClientRect();
      const ancho = Math.min(Math.max(rect.width, 280), window.innerWidth - 24);
      panel.style.width = ancho + "px";
      const abajo = window.innerHeight - rect.bottom - 20;
      const arriba = rect.top - 20;
      const haciaArriba = abajo < 260 && arriba > abajo;
      const espacio = Math.max(80, haciaArriba ? arriba : abajo);
      panel.style.maxHeight = espacio + "px";
      lista.style.maxHeight = Math.max(40, Math.min(240, espacio - 76)) + "px";
      panel.style.left = Math.max(12, Math.min(rect.left, window.innerWidth - ancho - 12)) + "px";
      panel.style.top = Math.max(12, haciaArriba ? rect.top - panel.offsetHeight - 8 : rect.bottom + 8) + "px";
    }
    function mostrar(abierto, enfocar = true) {
      if (!abierto && panel.hidden) return;
      if (eventosAbierto) eventosAbierto.abort();
      if (!abierto && panel.hidePopover) panel.hidePopover();
      panel.hidden = !abierto;
      boton.setAttribute("aria-expanded", String(abierto));
      boton.classList.toggle("active", abierto);
      if (abierto) {
        filtrar();
        if (panel.showPopover) panel.showPopover();
        posicionar();
        buscar.focus({ preventScroll: true });
        eventosAbierto = new AbortController();
        const signal = eventosAbierto.signal;
        window.addEventListener("resize", posicionar, { signal });
        document.addEventListener("scroll", posicionar, { capture: true, signal });
        document.addEventListener("pointerdown", function (evento) {
          if (!contenedor.contains(evento.target)) mostrar(false, false);
        }, { signal });
        const modal = contenedor.closest(".modal");
        if (modal) modal.addEventListener("hide.bs.modal", function () { mostrar(false, false); }, { signal });
      }
      else {
        buscar.value = "";
        filtrar();
        if (enfocar) boton.focus();
      }
    }
    boton.addEventListener("click", function () { mostrar(panel.hidden); });
    function normalizar(texto) {
      return texto.normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase();
    }
    function filtrar() {
      const valor = select.value;
      const palabras = normalizar(buscar.value).trim().split(/\s+/).filter(Boolean);
      const coincide = opcion => palabras.every(p => normalizar(opcion.textContent).includes(p));
      const resultados = opciones.filter(o => o.value && coincide(o));
      // Conservar la selección evita cambiar el pedido mientras se busca otra opción.
      estado.textContent = palabras.length && !resultados.length ? select.dataset.sinResultados : "";
      lista.replaceChildren();
      resultados.forEach(function (opcion) {
        const kit = select.hasAttribute("data-kit") ? kitPorId[opcion.value] : null;
        const partes = opcion.textContent.split(" — ");
        const nombre = kit ? kit.nombre : (partes.length > 1 ? partes.slice(1).join(" — ") : opcion.textContent);
        const referencia = kit ? kit.referencia : (partes.length > 1 ? partes[0] : "");
        const resultado = crear("button", { type: "button",
          clase: "list-group-item list-group-item-action text-start rounded-2 border-0 mb-1" + (opcion.value === valor ? " active" : ""),
          "aria-pressed": String(opcion.value === valor) }, [
          crear("span", { clase: "d-block fw-semibold text-break", texto: nombre }),
          crear("span", { clase: "d-block small", texto: referencia }),
        ]);
        resultado.addEventListener("click", function () {
          const cambia = select.value !== opcion.value;
          select.value = opcion.value;
          if (cambia) select.dispatchEvent(new Event("change", { bubbles: true }));
          mostrar(false);
          select.focus();
        });
        lista.appendChild(resultado);
      });
      posicionar();
    }
    buscar.addEventListener("input", filtrar);
    buscar.addEventListener("keydown", function (evento) {
      if (evento.key === "Enter") {
        evento.preventDefault();
        if (lista.firstElementChild) lista.firstElementChild.click();
      }
      if (evento.key === "ArrowDown") {
        evento.preventDefault();
        if (lista.firstElementChild) lista.firstElementChild.focus();
      }
    });
    panel.addEventListener("keydown", function (evento) {
      if (evento.key === "Escape") {
        evento.preventDefault();
        evento.stopPropagation();
        mostrar(false);
      }
      if (lista.contains(evento.target) && ["ArrowDown", "ArrowUp"].includes(evento.key)) {
        evento.preventDefault();
        const siguiente = evento.key === "ArrowDown" ? evento.target.nextElementSibling : evento.target.previousElementSibling;
        (siguiente || buscar).focus();
      }
    });
    select.addEventListener("change", function () { actualizarSeleccion(); filtrar(); });
    contenedor.addEventListener("focusout", function (evento) {
      if (!contenedor.contains(evento.relatedTarget)) mostrar(false, false);
    });
    return contenedor;
  }


  window.iniciarSelectoresBuscables = function (raiz = document) {
    raiz.querySelectorAll('select[data-buscable]').forEach(function (select) {
      if (select.actualizarSeleccion) return;
      const padre = select.parentNode;
      const siguiente = select.nextSibling;
      const envoltorio = conBuscador(select, select.dataset.buscable);
      padre.insertBefore(envoltorio, siguiente);
    });
  };
  window.iniciarSelectoresBuscables();
})();
