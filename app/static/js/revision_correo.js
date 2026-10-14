// El servidor retiene el correo incluso sin JavaScript: este modal solo permite revisarlo.
(function () {
  const el = document.getElementById('modal-revision-correo');
  if (!el) return;
  const modal = new bootstrap.Modal(el, {keyboard: false});
  const form = el.querySelector('form');
  const para = el.querySelector('#revision-correo-para');
  const asunto = el.querySelector('#revision-correo-asunto');
  const texto = el.querySelector('#revision-correo-texto');
  const error = el.querySelector('[data-error-correo]');
  const aviso = document.getElementById('aviso-correos-revision');
  const principal = document.querySelector('main');
  if (principal) principal.prepend(aviso);
  let pendientes = [], actual = null, ocupado = false, consultando = false, abriendo = false, aperturaSolicitada = false;
  const aplazados = new Set();
  // Recordar los correos ya mostrados al navegar dentro de esta pestaña.
  // Solo se guardan identificadores; nunca destinatarios ni contenido del correo.
  const claveVistos = 'yikon.correos-revision.vistos';
  try {
    const vistos = JSON.parse(sessionStorage.getItem(claveVistos) || '[]');
    if (Array.isArray(vistos)) vistos.filter(Number.isInteger).forEach(id => aplazados.add(id));
  } catch (_) { /* Si el almacenamiento no está disponible, funciona en esta página. */ }
  function recordar(id) {
    aplazados.add(id);
    try { sessionStorage.setItem(claveVistos, JSON.stringify(Array.from(aplazados))); }
    catch (_) { /* El borrador sigue guardado en el servidor. */ }
  }
  function abrir(correo) {
    if (!correo || document.querySelector('.modal.show')) return;
    actual = correo;
    para.value = correo.para; asunto.value = correo.asunto; texto.value = correo.texto;
    error.hidden = correo.estado !== 'fallido';
    error.textContent = correo.estado === 'fallido' ? 'El intento anterior falló. Revisa el registro antes de volver a enviar.' : '';
    el.querySelector('[data-posicion-correo]').textContent = pendientes.length + ' correo(s) pendiente(s)';
    abriendo = true;
    modal.show();
    recordar(correo.id);
  }
  async function consultar(abrirSiempre = false) {
    if (abrirSiempre) aperturaSolicitada = true;
    if (ocupado || consultando || document.hidden) return;
    consultando = true;
    try {
      const r = await fetch(el.dataset.lista, {headers: {'Accept': 'application/json'}, cache: 'no-store'});
      if (!r.ok) return;
      pendientes = (await r.json()).correos;
      aviso.hidden = pendientes.length === 0;
      aviso.querySelector('[data-total-correos]').textContent = '(' + pendientes.length + ')';
      if (!actual) {
        abrir(pendientes.find(c => aperturaSolicitada || !aplazados.has(c.id)));
        aperturaSolicitada = false;
      }
    } catch (_) { /* Se recupera al volver a consultar; nunca se envía automáticamente. */ }
    finally { consultando = false; }
  }
  async function resolver(accion) {
    if (ocupado || !actual) return;
    if (accion !== 'descartar' && !form.reportValidity()) return;
    ocupado = true; error.hidden = true;
    el.querySelectorAll('button').forEach(b => b.disabled = true);
    try {
      const r = await fetch(el.dataset.base + '/' + actual.id, {
        method: 'POST', headers: {'Content-Type': 'application/json',
          'X-CSRFToken': form.querySelector('[name=csrf_token]').value},
        body: JSON.stringify({accion, version: actual.version, asunto: asunto.value, texto: texto.value})
      });
      const datos = await r.json();
      if (datos.version) actual.version = datos.version;
      if (!r.ok) throw new Error(datos.error || 'No se ha podido guardar. Recarga la página para actualizar el borrador.');
      if (accion === 'guardar') recordar(actual.id);
      if (abriendo) el.addEventListener('shown.bs.modal', () => modal.hide(), {once: true});
      else modal.hide();
    } catch (e) { error.textContent = e.message; error.hidden = false; }
    finally { ocupado = false; el.querySelectorAll('button').forEach(b => b.disabled = false); }
  }
  el.addEventListener('shown.bs.modal', () => { abriendo = false; });
  form.addEventListener('submit', e => { e.preventDefault(); resolver('enviar'); });
  form.querySelectorAll('[data-accion-correo]').forEach(b => b.addEventListener('click', () => resolver(b.dataset.accionCorreo)));
  el.querySelector('[data-bs-dismiss]').addEventListener('click', () => { if (actual) recordar(actual.id); });
  el.addEventListener('hidden.bs.modal', () => { actual = null; consultar(); });
  document.getElementById('abrir-correos-revision').addEventListener('click', () => consultar(true));
  window.addEventListener('focus', () => consultar());
  document.addEventListener('visibilitychange', () => consultar());
  setInterval(consultar, 5000);
  consultar();
})();
