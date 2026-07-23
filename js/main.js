
import { cargarTodosLosDatos } from './data-loader.js';
import { inicializarHome } from './ui-home.js';

async function iniciar() {
  try {
    const datos = await cargarTodosLosDatos();
    inicializarHome(datos);

    document.getElementById('btn-ver-todo').addEventListener('click', () => {
      alert('Screener completo: próximo paso a construir.');
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
