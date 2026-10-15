// Mapa de clientes (d3 + el mapa del mundo de static/vendor/mapa: nada de servicios de fuera).
//  1. Clientes → Mapa (clientes/mapa.html): un punto por cliente (no mide nada: solo lo señala; el
//     relleno dice si tiene pedidos, si es nuevo o si está inactivo, con forma distinta, no solo color).
//     Al pasar el ratón, su nombre; al hacer clic, su resumen a la derecha. «Todo · Europa ·
//     Latinoamérica», rueda o +/− para acercarse, la lista «Por país» y el filtro de Soporte de cliente.
//     Los que se pisan (misma ciudad, o cerca con poco zoom) van en UN punto con el número: al hacer
//     clic, si están en sitios distintos el mapa se acerca y se separan; si están en el mismo sitio,
//     su lista sale a la derecha. Al cambiar el zoom se vuelven a agrupar.
//  2. El formulario del cliente (clientes/form.html): un mapa pequeño con su punto; al hacer clic se
//     pone el punto ahí (campos ocultos latitud/longitud y ubicacion_manual=1).
(function () {
  if (!window.d3 || !window.topojson) return;

  const ZONAS = { todo: [[-118, -42], [42, 60]], europa: [[-12, 34], [30, 59]], latam: [[-118, -42], [-32, 30]] };

  // Un mapa dentro de `caja` (que tiene un <svg>). Devuelve lo necesario para pintar encima.
  function crearMapa(caja, alto, alListo) {
    const svg = d3.select(caja).select("svg").attr("height", alto);
    const ancho = () => caja.clientWidth || 800;
    const proyeccion = d3.geoNaturalEarth1();
    const ruta = d3.geoPath(proyeccion);
    const capa = svg.append("g");
    const gPaises = capa.append("g"), gEtiquetas = capa.append("g"), gPuntos = capa.append("g");
    const mapa = { svg, capa, gPaises, gEtiquetas, gPuntos, proyeccion, k: 1, paises: [], alPintar: () => {} };

    const zoom = d3.zoom().scaleExtent([1, 16]).on("zoom", (e) => {
      mapa.k = e.transform.k;
      capa.attr("transform", e.transform);
      gPaises.selectAll("path").attr("stroke-width", .6 / mapa.k);
      gEtiquetas.attr("opacity", mapa.k > 2.2 ? 0 : 1);
      mapa.alPintar();
    });
    zoom.on("end", () => mapa.alTerminar());
    svg.call(zoom);
    mapa.zoom = zoom;
    mapa.alTerminar = () => {};

    mapa.irA = function (zona, animar) {
      const [[x0, y0], [x1, y1]] = Array.isArray(zona) ? zona : ZONAS[zona];
      const a = proyeccion([x0, y1]), b = proyeccion([x1, y0]);
      const escala = Math.min(16, .9 / Math.max((b[0] - a[0]) / ancho(), (b[1] - a[1]) / alto));
      const t = d3.zoomIdentity.translate(ancho() / 2, alto / 2).scale(escala).translate(-(a[0] + b[0]) / 2, -(a[1] + b[1]) / 2);
      (animar === false ? svg : svg.transition().duration(800)).call(zoom.transform, t);
    };
    // Del clic (en pantalla) a [longitud, latitud]
    mapa.lugarDe = function (evento) {
      const [x, y] = d3.zoomTransform(svg.node()).invert(d3.pointer(evento, svg.node()));
      return proyeccion.invert([x, y]);
    };
    mapa.escalaPunto = () => 1 / Math.pow(mapa.k, .8);

    d3.json(caja.dataset.mundo).then((mundo) => {
      const [[x0, y0], [x1, y1]] = ZONAS.todo;
      proyeccion.fitExtent([[16, 24], [ancho() - 16, alto - 40]],
        { type: "Feature", geometry: { type: "MultiPoint", coordinates: [[x0, y0], [x1, y1]] } });
      mapa.paises = topojson.feature(mundo, mundo.objects.countries).features.filter((f) => f.id !== "010");
      gPaises.selectAll("path").data(mapa.paises).join("path").attr("class", "mapa-pais").attr("d", ruta)
        .classed("lejos", (f) => { const [lon] = d3.geoCentroid(f); return lon > 50 || lon < -170; });
      const cargando = caja.querySelector(".mapa-cargando");
      if (cargando) cargando.remove();
      alListo(mapa);
    }).catch(() => {
      const cargando = caja.querySelector(".mapa-cargando");
      if (cargando) cargando.textContent = "⚠";
    });
    return mapa;
  }

  // ---------------------------------------------------------------- 1. Clientes → Mapa
  const caja = document.getElementById("mapa-clientes");
  if (caja) {
    const CLIENTES = JSON.parse(document.getElementById("mapa-datos").textContent);
    const T = JSON.parse(document.getElementById("mapa-textos").textContent);
    const tip = caja.querySelector(".mapa-tooltip");
    const filtro = document.getElementById("filtro-soporte");
    const alto = window.innerWidth < 768 ? 380 : 560;
    let elegido = null;

    const visibles = () => CLIENTES.filter((c) => !filtro || !filtro.value || c.soporte.split(", ").includes(filtro.value));
    const pais = (c) => c.pais || T.sin_pais;
    const texto = (s) => String(s).replace(/[&<>"]/g, (x) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[x]));

    const mapa = crearMapa(caja, alto, (m) => {
      m.gEtiquetas.selectAll("text").data([[T.europa, 2, 57], [T.latam, -80, 25]]).join("text")
        .attr("class", "mapa-region").attr("text-anchor", "middle")
        .attr("x", (d) => m.proyeccion([d[1], d[2]])[0]).attr("y", (d) => m.proyeccion([d[1], d[2]])[1]).text((d) => d[0]);
      m.gPaises.selectAll("path").on("click", (e, f) => {
        const del = visibles().filter((c) => d3.geoContains(f, [c.lon, c.lat]));
        if (del.length === 1) elegir(del[0]);
        else if (del.length) irAPais(del);
      });
      pintar();
      m.irA("todo", false);
    });
    // Posición de cada punto/grupo; al acabar un zoom, se vuelven a agrupar
    mapa.alPintar = () => mapa.gPuntos.selectAll(".mapa-punto")
      .attr("transform", (g) => `translate(${mapa.proyeccion([g.lon, g.lat])}) scale(${mapa.escalaPunto()})`);
    let kAgrupado = null;
    mapa.alTerminar = () => { if (Math.abs(mapa.k - kAgrupado) > 0.01) pintarPuntos(); };

    const SEPARACION = 20;           // px en pantalla: más cerca que esto, se pisan → un solo punto
    const MISMO_SITIO = 0.02;        // grados: a esta distancia (la misma ciudad) no se separan nunca

    // Agrupa los clientes que en pantalla, con el zoom de ahora, quedan a menos de SEPARACION px
    function agrupar(datos) {
      const grupos = [];
      datos.forEach((c) => {
        const [x, y] = mapa.proyeccion([c.lon, c.lat]).map((v) => v * mapa.k);
        const cerca = grupos.find((g) => Math.hypot(g.x - x, g.y - y) < SEPARACION);
        if (cerca) cerca.miembros.push(c);
        else grupos.push({ x, y, miembros: [c] });
      });
      return grupos.map((g) => {
        const m = g.miembros;
        const ciudades = [...new Set(m.map((c) => c.ciudad).filter(Boolean))];
        return {
          clave: m.map((c) => c.id).sort((a, b) => a - b).join("-"), miembros: m,
          lon: d3.mean(m, (c) => c.lon), lat: d3.mean(m, (c) => c.lat),
          // Estado del grupo: si alguno tiene pedidos, el de pedidos; si no, nuevo; si no, inactivo
          estado: ["con_pedidos", "nuevo", "inactivo"].find((e) => m.some((c) => c.estado === e)),
          lugar: ciudades.length <= 2 ? ciudades.join(" / ") : `${ciudades.slice(0, 2).join(" / ")}…`,
          mismoSitio: d3.max(m, (c) => Math.hypot(c.lon - m[0].lon, c.lat - m[0].lat)) < MISMO_SITIO,
        };
      });
    }

    function pintarPuntos() {
      kAgrupado = mapa.k;
      const grupos = agrupar(visibles());
      const sel = mapa.gPuntos.selectAll(".mapa-punto").data(grupos, (g) => g.clave);
      sel.exit().remove();
      const nuevos = sel.enter().append("g")
        .attr("class", (g) => `mapa-punto ${g.estado}${g.miembros.length > 1 ? " grupo" : ""}`)
        .attr("tabindex", 0).attr("role", "button")
        .attr("aria-label", (g) => g.miembros.length > 1
          ? `${g.lugar}: ${g.miembros.length} ${T.clientes}` : `${g.miembros[0].nombre}, ${g.miembros[0].ciudad}`)
        .on("mousemove", (e, g) => {
          const r = caja.getBoundingClientRect();
          const m = g.miembros;
          tip.innerHTML = m.length === 1
            ? `<b>${texto(m[0].nombre)}</b><br>${texto([m[0].ciudad, m[0].pais].filter(Boolean).join(", "))}`
            : `<b>${texto(g.lugar)} · ${m.length} ${texto(T.clientes)}</b><br>`
              + m.slice(0, 6).map((c) => texto(c.nombre)).join("<br>") + (m.length > 6 ? "<br>…" : "");
          tip.style.left = (e.clientX - r.left + 14) + "px";
          tip.style.top = (e.clientY - r.top - 10) + "px";
          tip.classList.add("visible");
        })
        .on("mouseleave", () => tip.classList.remove("visible"))
        .on("click", (e, g) => { e.stopPropagation(); abrir(g); })
        .on("keydown", (e, g) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); abrir(g); } });
      nuevos.append("circle").attr("class", "halo").attr("r", (g) => g.miembros.length > 1 ? 17 : 13);
      nuevos.append("circle").attr("class", "nucleo").attr("r", (g) => g.miembros.length > 1 ? 11 : 7);
      nuevos.filter((g) => g.miembros.length > 1).append("text").attr("class", "cuantos")
        .attr("text-anchor", "middle").attr("dy", "0.35em").text((g) => g.miembros.length);
      mapa.alPintar();
      marcarElegido();
    }

    function pintar() {
      const datos = visibles();
      pintarPuntos();
      // Los países con clientes, en el color de la marca
      mapa.gPaises.selectAll("path").classed("con-clientes", (f) => datos.some((c) => d3.geoContains(f, [c.lon, c.lat])));
      resumen(datos);
    }

    function marcarElegido() {
      mapa.gPuntos.selectAll(".mapa-punto").classed("elegido", (g) => !!elegido && g.miembros.includes(elegido));
    }

    // Clic en un punto: un cliente → su resumen; un grupo → acercarse (si se pueden separar) o su lista
    function abrir(g) {
      tip.classList.remove("visible");
      if (g.miembros.length === 1) { elegir(g.miembros[0]); return; }
      if (!g.mismoSitio && mapa.k < 15) {
        const xs = d3.extent(g.miembros, (c) => c.lon), ys = d3.extent(g.miembros, (c) => c.lat);
        const margen = Math.max(xs[1] - xs[0], ys[1] - ys[0], 0.5);
        mapa.irA([[xs[0] - margen, ys[0] - margen], [xs[1] + margen, ys[1] + margen]]);
        return;
      }
      lista(g);
    }

    function lista(g) {
      elegido = null;
      marcarElegido();
      const ficha = document.getElementById("mapa-ficha");
      ficha.innerHTML = `
        <h3 class="h5 mb-0">${texto(g.lugar || T.sin_pais)}</h3>
        <p class="small text-muted mb-2">${g.miembros.length} ${texto(T.clientes)}</p>
        <ul class="mapa-lista-grupo">${g.miembros.slice().sort((a, b) => a.nombre.localeCompare(b.nombre)).map((c) =>
          `<li><button type="button" data-id="${c.id}"><i class="mapa-ley ${c.estado}" aria-hidden="true"></i>
            <span>${texto(c.nombre)}</span><span class="small text-muted ms-auto">${texto(T[c.estado])}</span></button></li>`).join("")}</ul>`;
      ficha.querySelectorAll("button[data-id]").forEach((b) => b.addEventListener("click", () => {
        const c = g.miembros.find((x) => x.id === +b.dataset.id);
        elegir(c, g);
      }));
    }

    function contar(clave, hasta) {
      const el = document.querySelector(`[data-kpi="${clave}"]`);
      const desde = +el.textContent || 0;
      d3.select(el).transition().duration(600).tween("text", () => {
        const i = d3.interpolateRound(desde, hasta);
        return (t) => { el.textContent = i(t); };
      });
    }

    function resumen(datos) {
      const paises = d3.rollups(datos, (v) => v, pais).sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]));
      contar("clientes", datos.length);
      contar("paises", paises.filter((p) => p[0] !== T.sin_pais).length);
      contar("pedidos", d3.sum(datos, (c) => c.pedidos_anio));
      const max = d3.max(paises, (p) => p[1].length) || 1;
      const lista = d3.select("#mapa-paises").selectAll("li").data(paises, (p) => p[0]).join((entrar) => {
        const li = entrar.append("li").attr("tabindex", 0).attr("role", "button");
        li.append("span").attr("class", "nombre");
        li.append("strong").attr("class", "cuantos");
        li.append("div").attr("class", "barra").append("i");
        return li;
      });
      lista.order();
      lista.select(".nombre").text((p) => p[0]);
      lista.select(".cuantos").text((p) => `${p[1].length} ${p[1].length === 1 ? T.cliente : T.clientes}`);
      lista.select(".barra i").style("width", (p) => (p[1].length / max * 100) + "%");
      lista.on("click", (e, p) => irAPais(p[1]))
        .on("keydown", (e, p) => { if (e.key === "Enter") irAPais(p[1]); });
    }

    function irAPais(lista) {
      if (lista.length === 1) { elegir(lista[0]); return; }
      const [primero] = lista;
      if (lista.every((c) => Math.hypot(c.lon - primero.lon, c.lat - primero.lat) < MISMO_SITIO)) {
        abrir({ miembros: lista, mismoSitio: true, lugar: [...new Set(lista.map((c) => c.ciudad).filter(Boolean))].join(" / ") });
        return;
      }
      const xs = d3.extent(lista, (c) => c.lon), ys = d3.extent(lista, (c) => c.lat);
      mapa.irA([[xs[0] - 3, ys[0] - 2], [xs[1] + 3, ys[1] + 2]]);
    }

    // grupo: si viene de la lista de un grupo, para poder volver a ella
    function elegir(c, grupo) {
      elegido = c;
      marcarElegido();
      const max = d3.max(c.serie) || 1;
      const ficha = document.getElementById("mapa-ficha");
      ficha.innerHTML = `
        ${grupo ? `<button type="button" class="btn btn-link btn-sm px-0 mb-1" data-volver>← ${texto(grupo.lugar)} · ${grupo.miembros.length} ${texto(T.clientes)}</button>` : ""}
        <h3 class="h5 mb-0">${texto(c.nombre)}</h3>
        <p class="small text-muted mb-2">${texto([c.ciudad, c.pais].filter(Boolean).join(", "))}
          · <span class="mapa-estado ${c.estado}">${texto(T[c.estado])}</span></p>
        <dl class="mapa-dl">
          <dt>${texto(T.pedidos_anio)}</dt><dd>${c.pedidos_anio}</dd>
          <dt>${texto(T.ultimo)}</dt><dd>${texto(c.ultimo || "—")}</dd>
          <dt>${texto(T.soporte)}</dt><dd>${texto(c.soporte || "—")}</dd>
        </dl>
        <div class="mapa-serie" title="${texto(T.por_mes)}" aria-label="${texto(T.por_mes)}: ${c.serie.join(", ")}">
          ${c.serie.map((v, i) => `<i class="${i === c.serie.length - 1 ? "ultimo" : ""}" style="height:${Math.max(6, v / max * 100)}%" title="${T.meses[i]}: ${v}"></i>`).join("")}
        </div>
        <a class="btn btn-primary btn-sm" href="${texto(c.url)}">${texto(T.ver_ficha)} →</a>`;
      const volver = ficha.querySelector("[data-volver]");
      if (volver) volver.addEventListener("click", () => lista(grupo));
    }

    document.querySelectorAll("[data-zona]").forEach((b) => b.addEventListener("click", () => {
      document.querySelectorAll("[data-zona]").forEach((x) => {
        x.classList.toggle("activo", x === b);
        x.setAttribute("aria-pressed", x === b ? "true" : "false");
      });
      mapa.irA(b.dataset.zona);
    }));
    caja.querySelectorAll("[data-zoom]").forEach((b) => b.addEventListener("click", () =>
      mapa.svg.transition().duration(300).call(mapa.zoom.scaleBy, +b.dataset.zoom)));
    if (filtro) filtro.addEventListener("change", pintar);
  }

  // ---------------------------------------------------------------- 2. Formulario del cliente
  const elegir = document.querySelector("[data-mapa-elegir]");
  if (elegir) {
    const f = elegir.closest("form");
    const lat = f.querySelector('input[name="latitud"]'), lon = f.querySelector('input[name="longitud"]');
    const manual = f.querySelector('input[name="ubicacion_manual"]');
    const quitar = elegir.parentElement.querySelector("[data-mapa-quitar]");
    const mapa = crearMapa(elegir, 260, (m) => {
      pintar();
      if (lat.value && lon.value) m.irA([[+lon.value - 12, +lat.value - 8], [+lon.value + 12, +lat.value + 8]], false);
      else m.irA("todo", false);
      m.svg.on("click", (e) => {
        const [x, y] = m.lugarDe(e);
        lat.value = y.toFixed(5); lon.value = x.toFixed(5); manual.value = "1";
        pintar();
      });
    });
    mapa.alPintar = () => mapa.gPuntos.selectAll("g").attr("transform",
      (d) => `translate(${mapa.proyeccion(d)}) scale(${mapa.escalaPunto()})`);
    function pintar() {
      const hay = lat.value !== "" && lon.value !== "";
      const g = mapa.gPuntos.selectAll("g").data(hay ? [[+lon.value, +lat.value]] : []);
      g.exit().remove();
      const nuevo = g.enter().append("g").attr("class", "mapa-punto con_pedidos elegido");
      nuevo.append("circle").attr("class", "halo").attr("r", 13);
      nuevo.append("circle").attr("class", "nucleo").attr("r", 7);
      mapa.gPuntos.selectAll("g").data(hay ? [[+lon.value, +lat.value]] : []);
      mapa.alPintar();
      if (quitar) quitar.hidden = !hay;
    }
    if (quitar) quitar.addEventListener("click", () => {
      lat.value = ""; lon.value = ""; manual.value = "quitar";
      pintar();
    });
  }
})();
