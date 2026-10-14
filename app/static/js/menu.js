// Plegar / desplegar la barra lateral.
// - En escritorio: el menú pasa de ancho (icono + texto) a estrecho (solo iconos).
// - En móvil: el menú se muestra en estrecho y el botón ☰ lo oculta / muestra.
// La clase "menu-plegado" va en <html> (la pone también el <script> del <head>
// al cargar, para que no dé un salto). Se recuerda en localStorage.
document.querySelectorAll('[data-plegar-menu]').forEach(function (boton) {
  boton.addEventListener('click', function () {
    var plegado = document.documentElement.classList.toggle('menu-plegado');
    try { localStorage.setItem('menuPlegado', plegado ? '1' : '0'); } catch (e) { /* sin almacenamiento: no pasa nada */ }
  });
});
