
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
  const filas = parsearCSVConComillas_(texto);
  const headers = filas[0].map(h => h.trim());
  return filas.slice(1).map(valores => {
    const obj = {};
    headers.forEach((h, i) => {
      obj[h] = normalizarValor_(h, valores[i]);
    });
    return obj;
  });
}

// Parser CSV que respeta comillas dobles, incluyendo comas y saltos de linea dentro de un campo
function parsearCSVConComillas_(texto) {
  const filas = [];
  let fila = [];
  let campo = '';
  let dentroDeComillas = false;

  for (let i = 0; i < texto.length; i++) {
    const char = texto[i];
    const siguiente = texto[i + 1];

    if (dentroDeComillas) {
      if (char === '"' && siguiente === '"') {
        campo += '"';
        i++;
      } else if (char === '"') {
        dentroDeComillas = false;
      } else {
        campo += char;
      }
    } else {
      if (char === '"') {
        dentroDeComillas = true;
      } else if (char === ',') {
        fila.push(campo);
        campo = '';
      } else if (char === '\n' || (char === '\r' && siguiente === '\n')) {
        if (char === '\r') i++;
        fila.push(campo);
        filas.push(fila);
        fila = [];
        campo = '';
      } else if (char === '\r') {
        // salto de linea viejo estilo Mac, ignorar
      } else {
        campo += char;
      }
    }
  }

  if (campo.length > 0 || fila.length > 0) {
    fila.push(campo);
    filas.push(fila);
  }

  return filas.filter(f => f.length > 1 || f[0] !== '');
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
