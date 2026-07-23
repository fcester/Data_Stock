
console.log('PASO 1: main.js se está ejecutando');

import { cargarTodosLosDatos } from './data-loader.js';
console.log('PASO 2: import de data-loader.js resuelto correctamente');

import { inicializarHome } from './ui-home.js';
console.log('PASO 3: import de ui-home.js resuelto correctamente');

async function iniciar() {
  console.log('PASO 4: función iniciar() invocada');
  try {
    console.log('PASO 5: a punto de llamar cargarTodosLosDatos()');
    const datos = await cargarTodosLosDatos();
    console.log('PASO 6: datos recibidos:', datos);
    console.log('PASO 6b: cantidad de tickers:', datos?.screener?.length);

    inicializarHome(datos);
    console.log('PASO 7: inicializarHome ejecutado sin errores');

    document.getElementById('btn-ver-todo').addEventListener('click', () => {
      alert('Screener completo: próximo paso a construir.');
    });
    document.getElementById('btn-ir-cartera').addEventListener('click', () => {
      alert('Cartera: próximo paso a construir.');
    });

  } catch (err) {
    console.error('ERROR CAPTURADO EN iniciar():', err);
    document.getElementById('vista-home').innerHTML =
      `<p style="color:red">Error cargando datos: ${err.message}</p>`;
  }
}

console.log('PASO 3b: a punto de invocar iniciar()');
iniciar();
