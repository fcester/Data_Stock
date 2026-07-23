import * as duckdb from 'https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@1.29.0/+esm';

const BASE_URL = 'https://raw.githubusercontent.com/fcester/Data_Stock/main/';

let dbInstance = null;
let alreadyRegistered = new Set();

async function obtenerDB_() {
  if (dbInstance) return dbInstance;

  const CDN_BUNDLES = duckdb.getJsDelivrBundles();
  const bundle = await duckdb.selectBundle(CDN_BUNDLES);

  const workerUrl = URL.createObjectURL(
    new Blob([`importScripts("${bundle.mainWorker}");`], { type: 'text/javascript' })
  );

  const worker = new Worker(workerUrl);
  const logger = new duckdb.ConsoleLogger();
  const db = new duckdb.AsyncDuckDB(logger, worker);
  await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
  URL.revokeObjectURL(workerUrl);

  dbInstance = db;
  return db;
}

async function registrarParquet_(nombreArchivo) {
  const alias = nombreArchivo.replace(/[^a-zA-Z0-9]/g, '_');
  if (alreadyRegistered.has(alias)) return alias;

  const db = await obtenerDB_();
  await db.registerFileURL(alias, BASE_URL + nombreArchivo, duckdb.DuckDBDataProtocol.HTTP, false);
  alreadyRegistered.add(alias);
  return alias;
}

// Ejecuta cualquier SQL contra los parquet ya registrados. Uso interno y externo (cartera, detalle, etc.)
export async function consultarSQL(sql) {
  const db = await obtenerDB_();
  const conn = await db.connect();
  try {
    const resultado = await conn.query(sql);
    return resultado.toArray().map(row => row.toJSON());
  } finally {
    await conn.close();
  }
}

// ===== CSV LOADER (Screener, liviano, se carga completo) =====
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

// ===== CARGA INICIAL: solo el screener completo + registro de los parquet (sin traerlos enteros) =====
export async
