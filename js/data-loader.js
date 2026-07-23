
import * as duckdb from 'https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@1.29.0/+esm';

const BASE_URL = 'https://raw.githubusercontent.com/fcester/Data_Stock/main/';

let dbInstance = null;
let httpfsListo = false;

async function obtenerDB_() {
  if (dbInstance) return dbInstance;

  console.log('Iniciando DuckDB...');
  const CDN_BUNDLES = duckdb.getJsDelivrBundles();
  const bundle = await duckdb.selectBundle(CDN_BUNDLES);
  console.log('Bundle seleccionado:', bundle);

  const workerUrl = URL.createObjectURL(
    new Blob([`importScripts("${bundle.mainWorker}");`], { type: 'text/javascript' })
  );

  const worker = new Worker(workerUrl);
  console.log('Worker creado');

  const logger = new duckdb.ConsoleLogger();
  const db = new duckdb.AsyncDuckDB(logger, worker);
  console.log('Instanciando DB...');
  await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
  console.log('DB instanciada correctamente');

  URL.revokeObjectURL(workerUrl);
  dbInstance = db;
  return db;
}

async function asegurarHttpfs_(conn) {
  if (httpfsListo) return;
  console.log('Instalando y cargando extension httpfs...');
  await conn.query('INSTALL httpfs;');
  await conn.query('LOAD httpfs;');
  httpfsListo = true;
  console.log('httpfs listo');
}

// Ejecuta cualquier SQL, asegurando que httpfs este disponible antes de correr la query
export async function consultarSQL(sql) {
  const db = await obtenerDB_();
  const conn = await db.connect();
  try {
    await asegurarHttpfs_(conn);
    const resultado = await conn.query(sql);
    return resultado.toArray().map(row => row.toJSON());
  } finally {
    await conn.close();
  }
}

// Lee un parquet remoto directamente por URL, sin registerFileURL ni alias
export async function cargarParquetCompleto(nombreArchivo) {
  const url = BASE_URL + nombreArchivo;
  console.log('Consultando parquet directo por URL:', url);
  return consultarSQL(`SELECT * FROM read_parquet('${url}')`);
}

// ===== CSV LOADER (Screener, liviano, se carga completo) =====

async function cargarCSV(nombreArchivo) {
  console.log('Empezando a cargar CSV:', nombreArchivo);
  const res = await fetch(BASE_URL + nombreArchivo);
  console.log('Respuesta del CSV recibida, status:', res.status);
  if (!res.ok) throw new Error('No se pudo cargar ' + nombreArchivo);
  const texto = await res.text();
  console.log('CSV parseado, longitud de texto:', texto.length);
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

// ===== CARGA INICIAL: screener completo + los dos parquet completos =====
export async function cargarTodosLosDatos() {
  const [screener, precios, fundamentales] = await Promise.all([
    cargarCSV('Stock_Screener_PRO.csv'),
    cargarParquetCompleto('Actual_Stock.parquet'),
    cargarParquetCompleto('stock_fundamentals_history.parquet')
  ]);

  return { screener, precios, fundamentales };
}
