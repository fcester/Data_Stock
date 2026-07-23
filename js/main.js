
import { cargarTodosLosDatos } from './data-loader.js';
import { inicializarHome } from './ui-home.js';
import { inicializarScreener, mostrarVistaCompleta } from './ui-screener.js';

let datosGlobales = null;

function mostrarVista(idVista) {
  document.querySelectorAll('.vista').forEach(v => v.classList.add('oculto'));
  document.getElementById(idVista).classList.remove('oculto');
}

async function iniciar() {
  try {
    const datos = await cargarTodosLosDatos();
    datosGlobales = datos;

    inicializarHome(datos);
    inicializarScreener(datos);

    document.getElementById('btn-ver-todo').addEventListener('click', () => {
      mostrarVista('vista-completa');
      mostrarVistaCompleta();
    });

    document.getElementById('btn-volver-home')?.addEventListener('click', () => {
      mostrarVista('vista-home');
    });

    document.getElementById('btn-ir-cartera').addEventListener('click', () => {
      alert('Cartera: próximo paso a construir.');
    });

  } catch (err) {
    document.getElementById('vista-home').innerHTML =
      `<p style="color:red">Error cargando datos: ${err.message}</p>`;
    console.error(err);
  }
}

iniciar();
