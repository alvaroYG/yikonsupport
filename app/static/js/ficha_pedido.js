// Ficha del pedido (pedidos/detalle.html).
//
// 1. PESTAÑAS de la columna ancha. Cada .grupo-pestana del HTML es una pestaña (Contenido y
//    lotes · Proforma · Fotos · Facturas); aquí se pinta la barra de pestañas con las
//    que tienen algo (el nombre y, si los hay, su contador, la marca «nuevo» y el aviso de
//    data-aviso: «por validar», «faltan lotes»…) y se enseña una cada vez. Sin JavaScript se ve todo seguido, como antes.
//    - Qué pestaña se abre: la de la dirección (#facturas, #lotes, #fotos…: el id de una sección
//      o de algo de dentro), si no la de la barra «Lo que toca» (data-pestana-inicial), si no
//      la de una sección con algo que hacer (data-forzar) y si no la primera.
//    - Los enlaces con data-ir-a="<sección>" (barra «Lo que toca») abren su pestaña y van a ella;
//      data-enfocar="<selector>" pone además el cursor ahí (p. ej. el comentario al rechazar).
//    - Dentro de una pestaña las secciones están siempre abiertas (sin plegar).
// 2. SECCIONES PLEGABLES de la columna estrecha (documentos, datos de envío, historial): recuerda cuáles
//    tiene abiertas cada persona, en SU navegador (localStorage), para todos los pedidos.
// 3. «Enviar…» de la barra abre la ventana Cambiar estado con «Enviado» ya elegido.
(function () {
  const principal = document.querySelector(".ficha-principal");
  const nav = document.querySelector("[data-pestanas]");
  const grupos = Array.from(document.querySelectorAll(".grupo-pestana"))
    .filter(function (g) { return g.querySelector("[data-seccion]"); })
    .sort(function (a, b) { return (+a.dataset.orden || 0) - (+b.dataset.orden || 0); });
  const botones = {};
  const conPestanas = !!(nav && principal && grupos.length > 1);

  function grupoDe(el) { return el && el.closest ? el.closest(".grupo-pestana") : null; }
  function texto(el) { return el ? el.textContent.replace(/\s+/g, " ").trim() : ""; }

  // ---------- 1. Pestañas ----------
  function crearBoton(g) {
    const clave = g.dataset.pestana;
    const primera = g.querySelector("[data-seccion]");
    const b = document.createElement("button");
    b.type = "button";
    b.className = "pestana-ficha";
    b.id = "tab-" + clave;
    b.setAttribute("role", "tab");
    b.setAttribute("aria-controls", g.id);
    const icono = document.createElement("i");
    icono.className = "fas " + (g.dataset.icono || "fa-circle");
    icono.setAttribute("aria-hidden", "true");
    const titulo = document.createElement("span");
    titulo.className = "pestana-titulo";
    titulo.textContent = g.dataset.titulo || texto(primera.querySelector(".seccion-titulo"));
    b.append(icono, titulo);
    // Contador (si la pestaña es una sola sección con contador: facturas…)
    const contador = g.querySelectorAll("[data-seccion]").length === 1 && primera.querySelector(".seccion-contador");
    if (contador) {
      const c = document.createElement("span");
      c.className = "badge rounded-pill seccion-contador";
      c.textContent = texto(contador);
      b.append(c);
    }
    // Aviso: solo si ahí hay algo que te toca o un problema («por validar», «faltan lotes»…)
    if (g.dataset.aviso) {
      const a = document.createElement("span");
      a.className = "pestana-aviso";
      a.innerHTML = '<i class="fas fa-exclamation-circle" aria-hidden="true"></i> ';
      a.append(g.dataset.aviso);
      b.append(a);
    }
    const nuevo = g.querySelector("[data-nuevo]");
    if (nuevo) {
      const n = nuevo.cloneNode(true);
      n.removeAttribute("data-nuevo");
      n.dataset.nuevoPestana = "";
      b.append(n);
    }
    b.addEventListener("click", function () { activar(clave, true); });
    return b;
  }

  function activar(clave, aMano) {
    grupos.forEach(function (g) {
      const activa = g.dataset.pestana === clave;
      const b = botones[g.dataset.pestana];
      g.hidden = !activa;
      b.setAttribute("aria-selected", activa ? "true" : "false");
      b.tabIndex = activa ? 0 : -1;
      b.classList.toggle("activa", activa);
      if (activa && aMano) {
        // Ya lo has visto: fuera las marcas «nuevo» de esa pestaña
        g.querySelectorAll("[data-nuevo]").forEach(function (m) { m.remove(); });
        const marca = b.querySelector("[data-nuevo-pestana]");
        if (marca) marca.remove();
        // Que al recargar siga en esta pestaña (replaceState no mueve la página)
        if (history.replaceState) history.replaceState(null, "", "#" + g.querySelector("[data-seccion]").id);
      }
    });
  }

  function destinoDe(id) {
    if (!id) return null;
    const el = document.getElementById(id);
    const g = grupoDe(el);
    return g && grupos.indexOf(g) >= 0 ? { clave: g.dataset.pestana, el: el } : null;
  }

  // Ir a una sección (o a algo de dentro): abre su pestaña y baja hasta ella
  function irA(id, enfocar) {
    const destino = destinoDe(id);
    if (!destino) return false;
    activar(destino.clave, false);
    destino.el.scrollIntoView({ block: "start" });
    if (enfocar) {
      const campo = document.querySelector(enfocar);
      if (campo) campo.focus({ preventScroll: true });
    }
    return true;
  }

  if (conPestanas) {
    principal.classList.add("con-pestanas");
    nav.setAttribute("role", "tablist");
    grupos.forEach(function (g) {
      const b = crearBoton(g);
      botones[g.dataset.pestana] = b;
      nav.append(b);
      g.setAttribute("role", "tabpanel");
      g.setAttribute("aria-labelledby", b.id);
      // Dentro de una pestaña, las secciones abiertas y sin plegar
      g.querySelectorAll("[data-seccion]").forEach(function (s) {
        const cab = s.querySelector(".seccion-cab");
        s.querySelector(":scope > .collapse").classList.add("show");
        cab.classList.remove("collapsed");
        cab.removeAttribute("data-bs-toggle");
        cab.removeAttribute("aria-expanded");
        cab.tabIndex = -1;
        s.classList.add("en-pestana");
      });
    });
    nav.hidden = false;
    // Flechas del teclado entre pestañas
    nav.addEventListener("keydown", function (e) {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      const lista = grupos.map(function (g) { return botones[g.dataset.pestana]; });
      const i = lista.indexOf(document.activeElement);
      if (i < 0) return;
      const siguiente = lista[(i + (e.key === "ArrowRight" ? 1 : lista.length - 1)) % lista.length];
      siguiente.focus();
      siguiente.click();
      e.preventDefault();
    });
    // Pestaña inicial
    if (!irA(decodeURIComponent(location.hash.slice(1)))) {
      const barra = document.querySelector("[data-pestana-inicial]");
      const deLaBarra = barra && destinoDe(barra.dataset.pestanaInicial);
      const forzada = grupos.find(function (g) { return g.querySelector("[data-forzar]"); });
      activar(deLaBarra ? deLaBarra.clave : (forzada || grupos[0]).dataset.pestana, false);
    }
    window.addEventListener("hashchange", function () { irA(decodeURIComponent(location.hash.slice(1))); });
  }

  document.querySelectorAll("[data-ir-a]").forEach(function (a) {
    a.addEventListener("click", function (e) {
      if (conPestanas && irA(a.dataset.irA, a.dataset.enfocar)) e.preventDefault();
    });
  });

  // ---------- 2. Secciones plegables (las que no van en una pestaña) ----------
  const CLAVE = "ficha-pedido-secciones";
  const plegables = Array.from(document.querySelectorAll("[data-seccion]"))
    .filter(function (s) { return !(conPestanas && grupoDe(s)); });

  function leer() {
    try { return JSON.parse(localStorage.getItem(CLAVE)) || {}; } catch (e) { return {}; }   // (modo privado, etc.)
  }
  function guardar(estado) {
    try { localStorage.setItem(CLAVE, JSON.stringify(estado)); } catch (e) { /* sin almacenamiento: no se recuerda */ }
  }
  const cuerpo = function (s) { return s.querySelector(":scope > .collapse"); };
  const boton = function (s) { return s.querySelector(".seccion-cab"); };
  function poner(seccion, abierta) {
    cuerpo(seccion).classList.toggle("show", abierta);
    boton(seccion).classList.toggle("collapsed", !abierta);
    boton(seccion).setAttribute("aria-expanded", abierta ? "true" : "false");
  }
  function apuntar(seccion, abierta) {
    const estado = leer();
    estado[seccion.dataset.seccion] = abierta;
    guardar(estado);
  }
  const guardado = leer();
  plegables.forEach(function (s) {
    if (!s.hasAttribute("data-forzar") && typeof guardado[s.dataset.seccion] === "boolean") poner(s, guardado[s.dataset.seccion]);
    cuerpo(s).addEventListener("shown.bs.collapse", function (e) {
      if (e.target !== cuerpo(s)) return;
      apuntar(s, true);
      const marca = s.querySelector("[data-nuevo]");       // ya lo has visto
      if (marca) marca.remove();
    });
    cuerpo(s).addEventListener("hidden.bs.collapse", function (e) { if (e.target === cuerpo(s)) apuntar(s, false); });
  });
  // #documentos, #envio…: se abre y se va a ella (solo para esta visita, no se apunta)
  function irAPlegable() {
    const id = decodeURIComponent(location.hash.slice(1));
    const s = id && plegables.find(function (x) { return x.id === id; });
    if (!s) return;
    poner(s, true);
    s.scrollIntoView({ block: "start" });
  }
  window.addEventListener("hashchange", irAPlegable);
  irAPlegable();

  // ---------- 3. «Enviar…»: Cambiar estado con el destino ya elegido ----------
  const ventanaEstado = document.getElementById("modal-estado");
  if (ventanaEstado) ventanaEstado.addEventListener("show.bs.modal", function (e) {
    const destino = e.relatedTarget && e.relatedTarget.dataset.estadoDestino;
    const select = ventanaEstado.querySelector('select[name="estado"]');
    if (destino && select && select.querySelector('option[value="' + destino + '"]')) {
      select.value = destino;
      select.dispatchEvent(new Event("change"));
    }
  });

  // Botones de la cabecera con title: el aviso de Bootstrap (al pasar el ratón o con el teclado)
  if (window.bootstrap) document.querySelectorAll("#acciones-pedido [title]").forEach(function (el) {
    new bootstrap.Tooltip(el, { placement: "bottom", trigger: "hover focus" });
  });
})();
