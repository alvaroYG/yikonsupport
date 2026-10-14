// Documentos internos y tickets: si el servidor devolvió el formulario con errores,
// la ventana (modal) se abre sola al cargar la página para que se vean.
document.querySelectorAll("[data-abrir-al-cargar]").forEach(function (modal) {
  if (window.bootstrap) bootstrap.Modal.getOrCreateInstance(modal).show();
});
