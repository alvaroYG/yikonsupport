// Vista de móvil "Preparar": sube las fotos en cuanto se eligen o se hacen con la cámara.
//
// Las fotos de un móvil pesan 3-8 MB. Antes de subirlas se reducen aquí mismo a un
// máximo de 2000 px por lado (JPEG al 85 %): se ven igual de bien para validar el
// pedido y suben mucho más rápido con la wifi del almacén o con datos.
// Si algo falla (navegador antiguo…), se envía el formulario normal con las originales.
(function () {
  var form = document.querySelector('[data-subir-fotos]');
  if (!form) return;
  var estado = form.querySelector('[data-estado-subida]');
  var entradas = form.querySelectorAll('input[type=file]');
  var LADO_MAX = 2000, CALIDAD = 0.85;

  function reducir(archivo) {
    return new Promise(function (resolver) {
      // Pequeñas o que no son imagen: tal cual
      if (!/^image\//.test(archivo.type) || archivo.size < 1.5 * 1024 * 1024) return resolver(archivo);
      var url = URL.createObjectURL(archivo);
      var img = new Image();
      img.onload = function () {
        var escala = Math.min(1, LADO_MAX / Math.max(img.naturalWidth, img.naturalHeight));
        var canvas = document.createElement('canvas');
        canvas.width = Math.round(img.naturalWidth * escala);
        canvas.height = Math.round(img.naturalHeight * escala);
        canvas.getContext('2d').drawImage(img, 0, 0, canvas.width, canvas.height);
        URL.revokeObjectURL(url);
        canvas.toBlob(function (blob) {
          if (!blob) return resolver(archivo);
          var nombre = (archivo.name || 'foto').replace(/\.[^.]+$/, '') + '.jpg';
          resolver(new File([blob], nombre, { type: 'image/jpeg' }));
        }, 'image/jpeg', CALIDAD);
      };
      img.onerror = function () { URL.revokeObjectURL(url); resolver(archivo); };
      img.src = url;
    });
  }

  function bloquear(si) {
    form.querySelectorAll('label.btn').forEach(function (b) { b.classList.toggle('disabled', si); });
  }

  entradas.forEach(function (entrada) {
    entrada.addEventListener('change', function () {
      var archivos = Array.prototype.slice.call(entrada.files || []);
      if (!archivos.length) return;
      if (!window.fetch || !window.FormData || !window.Promise) return form.submit();
      bloquear(true);
      var hechos = 0;
      estado.textContent = form.dataset.textoPreparando || '…';
      Promise.all(archivos.map(function (a) {
        return reducir(a).then(function (r) {
          hechos += 1;
          estado.textContent = '⏳ ' + hechos + ' / ' + archivos.length;
          return r;
        });
      })).then(function (listos) {
        var datos = new FormData();
        form.querySelectorAll('input[type=hidden]').forEach(function (h) { datos.append(h.name, h.value); });
        listos.forEach(function (f) { datos.append(entrada.name, f, f.name); });
        estado.textContent = form.dataset.textoSubiendo || '⏳';
        // redirect: 'manual' → no se sigue aquí la redirección del servidor; si se siguiera,
        // esa página invisible se "comería" el aviso de "foto subida" antes de verlo.
        return fetch(form.action, { method: 'POST', body: datos, credentials: 'same-origin', redirect: 'manual' });
      }).then(function () {
        window.location.href = window.location.pathname;   // recargar: fotos nuevas + aviso
      }).catch(function () {
        bloquear(false);
        form.submit();   // plan B: formulario normal
      });
    });
  });
})();
