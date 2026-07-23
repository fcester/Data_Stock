
import { parquetRead } from 'https://cdn.jsdelivr.net/npm/hyparquet/+esm';

const BASE_URL = 'https://raw.githubusercontent.com/TU_USUARIO/TU_REPO/main/';

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

// ===== PARQUET LOADER (equivalente a leer la pestaña Precios / Fundamentales) =====
async function cargarParquet(nombreArchivo) {
  const res = await fetch(BASE_URL + nombreArchivo);
  if (!res.ok) throw new Error('No se pudo cargar ' + nombreArchivo);
  const buffer = await res.arrayBuffer();

  let filas = [];
  await parquetRead({
    file: buffer,
    onComplete: (data) => { filas = data; }
  });
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
