
import { tableFromIPC } from 'https://cdn.jsdelivr.net/npm/apache-arrow@16.0.0/+esm';
import initWasm, { readParquet } from 'https://cdn.jsdelivr.net/npm/parquet-wasm@0.7.1/esm/parquet_wasm.js';

const BASE_URL = 'https://raw.githubusercontent.com/fcester/Data_Stock/main/';

let wasmInicializado = false;



let promesaWasm = null;

function asegurarWasm_() {
  if (!promesaWasm) {
    const wasmUrl = 'https://cdn.jsdelivr.net/npm/parquet-wasm@0.7.1/esm/parquet_wasm_bg.wasm';
    promesaWasm = initWasm(wasmUrl);
  }
  return promesaWasm;
}



// ===== CSV LOADER (equivalente a leer la pestaña Screener) =====
async function cargarCSV(nombreArchivo) {
  const res = await fetch(BASE_URL + nombreArchivo);
  if (!res.ok) throw new Error('No se pudo cargar ' + nombreArchivo);
  const texto = await res.text();
  return parsearCSV_(texto);
}

function parsearCSV_(texto) {
  const lineas = texto.trim().split('\n');
  const headers = lineas[0].split(',').map(h => h.trim());
  return lineas.slice(1).map(linea => {
    const valores = linea.split(',');
    const obj = {};
    headers.forEach((h, i) => {
      obj[h] = normalizarValor_(h, valores[i]);
    });
    return obj;
  });
}

const COLUMNAS_TEXTO = new Set(['ticker', 'shortName', 'sector', 'industry', 'rating', 'Ticker']);

function normalizarValor_(columna, valor) {
  if (valor === undefined || valor === '') return null;
  const limpio = valor.trim();
  if (COLUMNAS_TEXTO.has(columna)) return limpio;
  const num = parseFloat(limpio.replace(',', '.'));
  return isNaN(num) ? limpio : num;
}


async function cargarParquet(nombreArchivo) {
  await asegurarWasm_();

  const res = await fetch(BASE_URL + nombreArchivo);
  if (!res.ok) throw new Error('No se pudo cargar ' + nombreArchivo);
  const buffer = await res.arrayBuffer();

  const wasmTable = readParquet(new Uint8Array(buffer));
  const arrowTable = tableFromIPC(wasmTable.intoIPCStream());
  const filas = arrowTable.toArray().map(row => row.toJSON());

  wasmTable.free();
  return filas;
}

// ===== CARGA GENERAL AL INICIAR LA APP =====
export async function cargarTodosLosDatos() {
  const [screener, precios, fundamentales] = await Promise.all([
    cargarCSV('Stock_Screener_PRO.csv'),
    cargarParquet('Actual_Stock.parquet'),
    cargarParquet('stock_fundamentals_history.parquet')
  ]);

  return { screener, precios, fundamentales };
}
