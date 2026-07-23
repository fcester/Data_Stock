
import * as duckdb from 'https://cdn.jsdelivr.net/npm/@duckdb/duckdb-wasm@1.29.0/+esm';

const BASE_URL = 'https://raw.githubusercontent.com/fcester/Data_Stock/main/';

let dbInstance = null;
let alreadyRegistered = new Set();

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



async function registrarParquet_(nombreArchivo) {
  // Alias con barra inicial: le indica a DuckDB que es un path absoluto,
  // evitando que lo interprete como identificador/glob y "mangle" el punto.
  const alias = '/' + nombreArchivo;
  if (alreadyRegistered.has(alias)) return alias;

  const db = await obtenerDB_();
  await db.registerFileURL(alias, BASE_URL + nombreArchivo, duckdb.DuckDBDataProtocol.HTTP, false);
  alreadyRegistered.add(alias);
  return alias;
}

export async function cargarParquetCompleto(nombreArchivo) {
  const alias = await registrarParquet_(nombreArchivo);
  return consultarSQL(`SELECT * FROM parquet_scan('${alias}')`);
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

// Trae TODAS las filas de un parquet registrado (usar con cuidado en archivos grandes)
export async function cargarParquetCompleto(nombreArchivo) {
  const alias = await registrarParquet_(nombreArchivo);
  return consultarSQL(`SELECT * FROM parquet_scan('${alias}')`);
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
