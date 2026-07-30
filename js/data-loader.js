
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

// Recorre las columnas de una fila y convierte cualquier BigInt a Number.
// DuckDB-WASM devuelve columnas enteras (ej. "rank") como BigInt, lo cual
// rompe operaciones normales de JS como .sort() o restas con Number comun.
function normalizarBigInts_(fila) {
  const normalizada = {};
  for (const clave in fila) {
    const valor = fila[clave];
    normalizada[clave] = typeof valor === 'bigint' ? Number(valor) : valor;
  }
  return normalizada;
}

// Ejecuta cualquier SQL, asegurando que httpfs este disponible antes de correr la query.
// Todas las filas devueltas ya vienen normalizadas (sin BigInt).
export async function consultarSQL(sql) {
  const db = await obtenerDB_();
  const conn = await db.connect();
  try {
    await asegurarHttpfs_(conn);
    const resultado = await conn.query(sql);
    const filas = resultado.toArray().map(row => row.toJSON());
    return filas.map(normalizarBigInts_);
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

// ============================================================
// UNIVERSO COMPLETO DE TICKERS (modelo dimension + hechos)
// ============================================================
// Tickers.csv actua como DIMENSION (lista maestra de tickers).
// Stock_Screener_PRO.csv y Stock_Advanced_Metrics.parquet actuan
// como tablas de HECHOS, unidas por ticker via LEFT JOIN.
// Con LEFT JOIN desde la dimension, ningun ticker desaparece aunque
// le falten datos en alguna de las dos tablas de hechos.
export async function cargarUniversoCompleto() {
  const urlTickers   = BASE_URL + 'Tickers.csv';
  const urlScreener  = BASE_URL + 'Stock_Screener_PRO.csv';
  const urlAvanzados = BASE_URL + 'Stock_Advanced_Metrics.parquet';

  const sql = `
    WITH tickers_norm AS (
      SELECT DISTINCT TRIM(CAST(ticker AS VARCHAR)) AS ticker
      FROM read_csv_auto('${urlTickers}')
    ),
    screener_norm AS (
      SELECT * EXCLUDE (ticker), TRIM(CAST(ticker AS VARCHAR)) AS ticker
      FROM read_csv_auto('${urlScreener}')
    ),
    avanzados_norm AS (
      SELECT * EXCLUDE (ticker), TRIM(CAST(ticker AS VARCHAR)) AS ticker
      FROM read_parquet('${urlAvanzados}')
    )
    SELECT
      t.ticker,
      s.shortName, s.sector, s.industry, s.rank, s.score_FINAL_adj,
      s.rating, s.data_completeness,
      s.score_valuation, s.score_profitability, s.score_growth,
      s.score_financial, s.score_momentum, s.score_fundamental_momentum, s.score_income,
      s.lastPrice, s.priceVs50dMA, s.priceVs200dMA, s.priceVs52wHigh, s.priceVs52wLow,
      s.position52w, s.beta, s.marketCap, s.dividendYield, s.liquidity_flag,
      s.trailingPE, s.forwardPE, s.priceToBook, s.enterpriseToEbitda,
      s.returnOnEquity, s.profitMargins, s.operatingMargins,
      s.revenueGrowth, s.earningsGrowth, s.debtToEquity, s.currentRatio, s.freeCashflow,
      s.revenue_trend, s.ebitda_trend, s.margin_trend, s.debt_trend, s.fcf_trend,
      s.earnings_consistency, s.revenue_r2, s.ebitda_r2, s.revenue_cagr, s.ebitda_cagr,
      s.revenue_qoq, s.ebitda_qoq, s.revenue_accel, s.margin_accel,
      a.piotroski_score_adj, a.piotroski_tests_ok, a.piotroski_tests_total,
      a.sharpe_ratio, a.sortino_ratio, a.var_95_diario,
      a.analyst_upside, a.recommendationKey, a.recommendationMean, a.numberOfAnalystOpinions,
      a.targetMeanPrice, a.targetHighPrice, a.targetLowPrice,
      a.heldPercentInsiders, a.heldPercentInstitutions,
      a.shortRatio, a.sharesShort,
      a.dividend_growth_streak, a.dividend_growth_avg,
      a.quickRatio, a.bookValue, a.pegRatio,
      a.fcf_yield,
      a.price_to_fcf,
      a.graham_number,
      a.graham_margin_of_safety,
      a.ev_to_sales,
      a.earnings_quality,
      a.max_drawdown,
      a.current_drawdown,
      a.calmar_ratio,
      a.volatility_annual,
      a.rsi_14,
      a.momentum_1m,
      a.momentum_3m,
      a.momentum_6m,
      a.net_debt,
      a.net_debt_to_ebitda,
      a.roic,
      a.asset_turnover,
      a.interest_coverage,
      a.working_capital,
      a.analyst_conviction,
      a.short_pct_float,
      a.beta_adj
      
    FROM tickers_norm t
    LEFT JOIN screener_norm s  ON t.ticker = s.ticker
    LEFT JOIN avanzados_norm a ON t.ticker = a.ticker
    ORDER BY s.rank NULLS LAST
  `;

  return consultarSQL(sql);
}

// ===== CSV LOADER manual (sin uso activo hoy: cargarTodosLosDatos ya no lo llama,
// se mantiene por si lo necesitas en otro lugar. Se puede borrar con seguridad
// si confirmas que no se usa en ningun otro modulo) =====
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

// ===== CARGA INICIAL: universo completo (screener + avanzados) + los dos parquet de series =====

// ── NUEVO: fechas disponibles en el historial del screener ──────────────
// Devuelve solo los snapshot_date únicos ordenados DESC (más reciente primero).
// NO descarga todo el parquet, DuckDB filtra en origen.
export async function cargarFechasHistorial() {
  const url = BASE_URL + 'Stock_Screener_History.parquet';
  try {
    const filas = await consultarSQL(`
      SELECT DISTINCT snapshot_date
      FROM read_parquet('${url}')
      ORDER BY snapshot_date DESC
    `);
    return filas.map(f => f.snapshot_date);
  } catch (e) {
    console.warn('Sin historial disponible aún:', e.message);
    return [];
  }
}

// ── NUEVO: snapshot completo de una fecha específica ────────────────────
export async function cargarSnapshotFecha(fecha) {
  const url = BASE_URL + 'Stock_Screener_History.parquet';
  return consultarSQL(`
    SELECT *
    FROM read_parquet('${url}')
    WHERE snapshot_date = '${fecha}'
    ORDER BY rank ASC NULLS LAST
  `);
}

// ── NUEVO: evolución histórica de un ticker individual ─────────────────
// Para el gráfico de ranking/score en el panel de detalle.
export async function cargarEvolucionTicker(ticker) {
  const url = BASE_URL + 'Stock_Screener_History.parquet';
  return consultarSQL(`
    SELECT
      snapshot_date,
      rank,
      score_FINAL_adj,
      rating,
      score_valuation,
      score_profitability,
      score_growth,
      score_financial,
      score_momentum,
      score_fundamental_momentum
    FROM read_parquet('${url}')
    WHERE TRIM(CAST(ticker AS VARCHAR)) = '${ticker}'
    ORDER BY snapshot_date ASC
  `);
}

// ── ACTUALIZAR cargarTodosLosDatos para incluir fechas del historial ────
export async function cargarTodosLosDatos() {
  const [screener, precios, fundamentales, fechasHistorial] = await Promise.all([
    cargarUniversoCompleto(),
    cargarParquetCompleto('Actual_Stock.parquet'),
    cargarParquetCompleto('stock_fundamentals_history.parquet'),
    cargarFechasHistorial()                          // ← NUEVO
  ]);
  return { screener, precios, fundamentales, fechasHistorial };  // ← NUEVO campo
}
