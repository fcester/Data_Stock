

import { cargarTodosLosDatos } from './data-loader.js';
import { inicializarHome } from './ui-home.js';
import { inicializarScreener, mostrarVistaCompleta } from './ui-screener.js';
import { inicializarDetalle } from './ui-detalle.js';
import { inicializarCartera } from './ui-cartera.js';
import { inicializarMercado } from './ui-mercado.js';   // ← NUEVO

let datosGlobales = null;

function mostrarVista(idVista) {
  document.querySelectorAll('.vista').forEach(v => v.classList.add('oculto'));
  const el = document.getElementById(idVista);
  if (el) el.classList.remove('oculto');
}

// Helper defensivo para agregar listeners solo si el elemento existe
function onClickSi(id, fn) {
  const el = document.getElementById(id);
  if (el) el.addEventListener('click', fn);
}

async function iniciar() {
  try {
    const datos = await cargarTodosLosDatos();
    datosGlobales = datos;

    inicializarHome(datos);
    inicializarScreener(datos);
    inicializarDetalle(datos);
    inicializarCartera(datos);
    inicializarMercado(datos);             // ← NUEVO

    // ── Navegación ────────────────────────────────────────────────────
    onClickSi('btn-ver-todo', () => {
      mostrarVista('vista-completa');
      mostrarVistaCompleta();
    });
    onClickSi('btn-volver-home',         () => mostrarVista('vista-home'));
    onClickSi('btn-ir-cartera',          () => mostrarVista('vista-cartera'));
    onClickSi('btn-ir-mercado',          () => mostrarVista('vista-mercado'));   // ← NUEVO
    onClickSi('btn-volver-home-cartera', () => mostrarVista('vista-home'));
    onClickSi('btn-volver-home-mercado', () => mostrarVista('vista-home'));      // ← NUEVO

  } catch (err) {
    const vistaHome = document.getElementById('vista-home');
    if (vistaHome) {
      vistaHome.innerHTML = `<p style="color:red;padding:20px">
        ❌ Error cargando datos: ${err.message}
      </p>`;
    }
    console.error(err);
  }
}

iniciar();
