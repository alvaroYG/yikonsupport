// Formulario de pedido (cliente y admin/logistics), en la página normal y en la ventana.
//
// El contenido del pedido se arma aquí y viaja al servidor en el campo oculto
// "contenido" como JSON:
//   {"kits": [{"kit_id": 3, "cantidad": 2, "productos": [{"producto_id": 7, "cantidad": 4}]}],
//    "sueltos": [{"producto_id": 9, "cantidad": 1}]}
// El servidor lo vuelve a comprobar TODO (app/pedidos/forms.py): esto es solo la parte cómoda.

let siguienteBuscadorPedido = 0;

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

document.querySelectorAll("[data-pedido][data-catalogo]").forEach(function (caja) {
  const form = caja.closest("form");
  if (!form) return;
  const oculto = form.querySelector('input[name="contenido"]');
  const catalogo = JSON.parse(caja.dataset.catalogo || "[]");
  const productos = JSON.parse(caja.dataset.productos || "[]");
  const txt = caja.dataset;
  const zonaKits = caja.querySelector("[data-kits]");
  const zonaSueltos = caja.querySelector("[data-sueltos]");
  const errorKits = caja.querySelector("[data-error-kits]");
  const kitPorId = {};
  catalogo.forEach(function (k) { kitPorId[k.id] = k; });

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
    const contenedor = crear("div", {}, [select, boton, panel]);
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
      estado.textContent = palabras.length && !resultados.length ? txt.txtSinResultados : "";
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

  // ---------- Un bloque de kit: elegir kit, nº de kits y sus productos ----------
  function pintarProductos(bloque, cantidades) {
    const kit = kitPorId[bloque.querySelector("[data-kit]").value];
    const n = entre(bloque.querySelector("[data-num-kits]").value, 1, 1000, 1);
    const tabla = bloque.querySelector("[data-componentes]");
    const descripcion = bloque.querySelector("[data-descripcion]");
    tabla.innerHTML = "";
    descripcion.textContent = kit ? kit.descripcion : "";
    if (!kit) return;
    kit.componentes.forEach(function (c) {
      // cantidades: al repetir un pedido o si el servidor devolvió un error, las que había
      const tenia = cantidades ? cantidades[c.producto_id] : undefined;
      const incluido = tenia === undefined ? true : tenia > 0;
      const casilla = crear("input", { type: "checkbox", clase: "form-check-input me-2", "aria-label": txt.txtIncluir });
      casilla.checked = incluido;
      const cantidad = crear("input", { type: "number", min: "1", max: "100000", clase: "form-control form-control-sm text-end",
                                        "aria-label": txt.txtCantidad + " · " + c.nombre });
      cantidad.value = tenia ? tenia : c.cantidad * n;
      cantidad.disabled = !incluido;
      cantidad.dataset.porKit = c.cantidad;
      if (tenia !== undefined && tenia !== c.cantidad * n) cantidad.dataset.editado = "1";
      const fila = crear("div", { clase: "componente" + (incluido ? "" : " quitado"), "data-producto": c.producto_id }, [
        crear("label", { clase: "componente-nombre" }, [casilla, document.createTextNode(c.nombre)]),
        crear("span", { clase: "componente-por-kit small text-muted", texto: c.cantidad + " " + txt.txtPorKit }),
        crear("div", { clase: "componente-cantidad" }, [cantidad]),
      ]);
      casilla.addEventListener("change", function () {
        cantidad.disabled = !casilla.checked;
        fila.classList.toggle("quitado", !casilla.checked);
        comprobar();
      });
      cantidad.addEventListener("input", function () { cantidad.dataset.editado = "1"; });
      tabla.appendChild(fila);
    });
  }

  function anadirKit(datos) {
    const select = crear("select", { clase: "form-select", "data-kit": "", "aria-label": txt.txtEligeKit },
      [crear("option", { value: "", texto: txt.txtEligeKit })].concat(catalogo.map(function (k) {
        return crear("option", { value: k.id, texto: k.nombre + " · " + k.referencia });
      })));
    const numero = crear("input", { type: "number", min: "1", max: "1000", value: "1", clase: "form-control",
                                    "data-num-kits": "", "aria-label": txt.txtNumKits, title: txt.txtNumKits });
    const quitar = crear("button", { type: "button", clase: "btn btn-outline-secondary", title: txt.txtQuitarKit,
                                     "aria-label": txt.txtQuitarKit, texto: "✕" });
    const bloque = crear("div", { clase: "kit-bloque" }, [
      crear("div", { clase: "kit-cabecera" }, [
        crear("div", { clase: "kit-select" }, [conBuscador(select, txt.txtBuscarKit)]),
        crear("div", { clase: "input-group kit-numero" }, [crear("span", { clase: "input-group-text small", texto: txt.txtNumKits }), numero]),
        quitar,
      ]),
      crear("div", { clase: "small text-muted mt-1", "data-descripcion": "" }),
      crear("div", { clase: "kit-componentes", "data-componentes": "" }),
    ]);
    select.addEventListener("change", function () { pintarProductos(bloque); comprobar(); });
    // Cambiar el nº de kits recalcula las cantidades que no has tocado a mano
    numero.addEventListener("input", function () {
      const n = entre(numero.value, 1, 1000, 1);
      bloque.querySelectorAll("[data-componentes] input[type=number]").forEach(function (c) {
        if (!c.dataset.editado) c.value = parseInt(c.dataset.porKit, 10) * n;
      });
    });
    quitar.addEventListener("click", function () {
      bloque.remove();
      if (!zonaKits.children.length && !(zonaSueltos && zonaSueltos.children.length)) anadirKit();
      comprobar();
    });
    zonaKits.appendChild(bloque);
    if (datos && kitPorId[datos.kit_id]) {
      select.value = datos.kit_id;
      select.actualizarSeleccion();
      numero.value = datos.cantidad || 1;
      const cantidades = {};
      (datos.productos || []).forEach(function (p) { cantidades[p.producto_id] = p.cantidad; });
      pintarProductos(bloque, cantidades);
    }
    return bloque;
  }

  // ---------- Productos sueltos (Yikon: todos los activos; el cliente: los de su catálogo) ----------
  function anadirSuelto(datos) {
    if (!zonaSueltos) return;
    const select = crear("select", { clase: "form-select", "data-suelto": "", "aria-label": txt.txtEligeProducto },
      [crear("option", { value: "", texto: txt.txtEligeProducto })].concat(productos.map(function (p) {
        return crear("option", { value: p.id, texto: p.texto });
      })));
    const cantidad = crear("input", { type: "number", min: "1", max: "100000", value: "1", clase: "form-control", "aria-label": txt.txtCantidad });
    const quitar = crear("button", { type: "button", clase: "btn btn-outline-secondary", title: txt.txtQuitar,
                                     "aria-label": txt.txtQuitar, texto: "✕" });
    const fila = crear("div", { clase: "row g-2 mb-2 fila-suelto" }, [
      crear("div", { clase: "col-8" }, [conBuscador(select, txt.txtBuscarProducto)]), crear("div", { clase: "col-3" }, [cantidad]),
      crear("div", { clase: "col-1" }, [quitar]),
    ]);
    quitar.addEventListener("click", function () { fila.remove(); comprobar(); });
    select.addEventListener("change", comprobar);
    if (datos) { select.value = datos.producto_id; select.actualizarSeleccion(); cantidad.value = datos.cantidad; }
    zonaSueltos.appendChild(fila);
  }

  // Números dentro de límites (el servidor los vuelve a comprobar: esto solo evita
  // que un "-3" o un "99999999" escrito a mano acabe en un error poco claro)
  function entre(texto, minimo, maximo, siVacio) {
    const n = parseInt(texto, 10);
    if (isNaN(n)) return siVacio;
    return Math.min(maximo, Math.max(minimo, n));
  }

  // ---------- Recoger todo en el JSON ----------
  function recoger() {
    const kits = [];
    zonaKits.querySelectorAll(".kit-bloque").forEach(function (bloque) {
      const kitId = bloque.querySelector("[data-kit]").value;
      if (!kitId) return;
      const lista = [];
      bloque.querySelectorAll(".componente").forEach(function (fila) {
        const casilla = fila.querySelector("input[type=checkbox]");
        const cantidad = entre(fila.querySelector("input[type=number]").value, 0, 100000, 0);
        lista.push({ producto_id: parseInt(fila.dataset.producto, 10), cantidad: casilla.checked ? cantidad : 0 });
      });
      kits.push({ kit_id: parseInt(kitId, 10),
                  cantidad: entre(bloque.querySelector("[data-num-kits]").value, 1, 1000, 1), productos: lista });
    });
    const sueltos = [];
    if (zonaSueltos) zonaSueltos.querySelectorAll(".fila-suelto").forEach(function (fila) {
      const id = fila.querySelector("select").value;
      const cantidad = entre(fila.querySelector('input[type="number"]').value, 0, 100000, 0);
      if (id && cantidad > 0) sueltos.push({ producto_id: parseInt(id, 10), cantidad: cantidad });
    });
    return { kits: kits, sueltos: sueltos };
  }

  function hayAlgo(datos) {
    return datos.kits.some(function (k) { return k.productos.some(function (p) { return p.cantidad > 0; }); })
           || datos.sueltos.length > 0;
  }

  function comprobar() {
    if (errorKits && hayAlgo(recoger())) errorKits.hidden = true;
  }

  // (Re)construir desde un JSON: al abrir, al repetir un pedido o si el servidor devolvió un error
  function cargar(json) {
    zonaKits.innerHTML = "";
    if (zonaSueltos) zonaSueltos.innerHTML = "";
    let datos = {};
    try { datos = JSON.parse(json || "{}") || {}; } catch (e) { datos = {}; }
    (datos.kits || []).forEach(function (k) { anadirKit(k); });
    (datos.sueltos || []).forEach(function (s) { anadirSuelto(s); });
    if (!zonaKits.children.length) anadirKit();
    if (errorKits) errorKits.hidden = true;
  }
  caja.cargar = cargar;          // para "Repetir pedido" (más abajo)

  caja.querySelector("[data-anadir-kit]").addEventListener("click", function () {
    anadirKit().querySelector("select").focus();
  });
  const botonSuelto = caja.querySelector("[data-anadir-suelto]");
  if (botonSuelto) botonSuelto.addEventListener("click", function () { anadirSuelto(); });

  form.addEventListener("submit", function (evento) {
    const datos = recoger();
    oculto.value = JSON.stringify(datos);
    if (!hayAlgo(datos)) {
      evento.preventDefault();
      errorKits.hidden = false;
      const primero = zonaKits.querySelector("select");
      if (primero) primero.focus();
    }
  });

  cargar(oculto.value);
});

// ---------- Referencia de la empresa: obligatoria para el cliente ----------
document.querySelectorAll("form").forEach(function (form) {
  const referencia = form.querySelector('input[name="referencia"]');
  const errorReferencia = form.querySelector("[data-error-referencia]");
  if (!referencia || !errorReferencia || !referencia.required) return;
  form.addEventListener("submit", function (evento) {
    if (!referencia.value.trim()) {
      referencia.classList.add("is-invalid");
      errorReferencia.hidden = false;
      evento.preventDefault();
      referencia.focus();
    }
  });
  referencia.addEventListener("input", function () {
    if (referencia.value.trim()) {
      referencia.classList.remove("is-invalid");
      errorReferencia.hidden = true;
    }
  });
});

// El modal lleva novalidate: mostramos el error aquí sin enviar el formulario
// ni perder los kits, cantidades y referencia que ya se han escrito.
document.querySelectorAll("form").forEach(function (form) {
  const documento = form.querySelector('input[type="file"][name="documento"]');
  const error = form.querySelector("[data-error-documento]");
  if (!documento || !error || !documento.required) return;

  form.addEventListener("submit", function (evento) {
    if (!documento.files || documento.files.length === 0) {
      evento.preventDefault();
      documento.classList.add("is-invalid");
      documento.setAttribute("aria-invalid", "true");
      error.textContent = error.dataset.obligatorio;
      error.hidden = false;
      documento.focus();
    }
  });
  documento.addEventListener("change", function () {
    if (documento.files && documento.files.length > 0) {
      documento.classList.remove("is-invalid");
      documento.setAttribute("aria-invalid", "false");
      error.hidden = true;
      error.textContent = "";
    }
  });
});

// ---------- Admin / logistics: elegir el cliente ----------
// Al elegirlo, la insignia de arriba muestra la referencia interna que se le asignará
// (p. ej. NORTE_005). Las referencias vienen en el atributo data-proximas del desplegable.
document.querySelectorAll('select[name="cliente_id"][data-proximas]').forEach(function (select) {
  const proximas = JSON.parse(select.dataset.proximas || "{}");
  const contenedor = select.closest(".modal") || document;
  const insignia = contenedor.querySelector("[data-ref-interna]");
  function actualizar() {
    if (!insignia) return;
    const ref = proximas[select.value];
    insignia.textContent = ref || "";
    insignia.hidden = !ref;
  }
  select.addEventListener("change", actualizar);
  actualizar();
  // Un botón con data-cliente-id (p. ej. "Hacer un pedido" en la ficha de un cliente)
  // abre la ventana con ese cliente ya elegido
  const modal = select.closest(".modal");
  if (modal) modal.addEventListener("show.bs.modal", function (evento) {
    const boton = evento.relatedTarget;
    if (boton && boton.dataset.clienteId) {
      select.value = boton.dataset.clienteId;
      if (select.actualizarSeleccion) select.actualizarSeleccion();
      actualizar();
    }
  });
});

// ---------- Al abrir la ventana: vacía, o con el contenido de "Repetir pedido" ----------
document.querySelectorAll(".modal").forEach(function (modal) {
  const caja = modal.querySelector("[data-pedido][data-catalogo]");
  if (!caja) return;
  modal.addEventListener("show.bs.modal", function (evento) {
    const boton = evento.relatedTarget;
    caja.cargar(boton && boton.dataset.repetir ? boton.dataset.repetir : "");
  });
});
