
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

// ============================================================
// NUEVO: UNIVERSO COMPLETO DE TICKERS (modelo dimension + hechos)
// ============================================================
// Tickers.csv actua como DIMENSION (lista maestra de tickers).
// Stock_Screener_PRO.csv y Stock_Advanced_Metrics.parquet actuan
// como tablas de HECHOS, unidas por ticker via LEFT JOIN.
// Con LEFT JOIN desde la dimension, ningun ticker desaparece aunque
// le falten datos en alguna de las dos tablas de hechos -- en ese
// caso simplemente trae NULL en esas columnas, en vez de ocultarlo.
export async function cargarUniversoCompleto() {
  const urlTickers   = BASE_URL + 'Tickers.csv';
  const urlScreener  = BASE_URL + 'Stock_Screener_PRO.csv';
  const urlAvanzados = BASE_URL + 'Stock_Advanced_Metrics.parquet';

  const sql = `
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
      s.revenue_accel, s.margin_accel,
      a.piotroski_score_adj, a.piotroski_tests_ok, a.piotroski_tests_total,
      a.sharpe_ratio, a.sortino_ratio, a.var_95_diario,
      a.analyst_upside, a.recommendationKey, a.recommendationMean, a.numberOfAnalystOpinions,
      a.targetMeanPrice, a.targetHighPrice, a.targetLowPrice,
      a.heldPercentInsiders, a.heldPercentInstitutions,
      a.shortRatio, a.sharesShort,
      a.dividend_growth_streak, a.dividend_growth_avg,
      a.quickRatio, a.bookValue, a.pegRatio
    FROM read_csv_auto('${urlTickers}') t
    LEFT JOIN read_csv_auto('${urlScreener}') s ON t.ticker = s.ticker
    LEFT JOIN read_parquet('${urlAvanzados}') a ON t.ticker = a.ticker
    ORDER BY s.rank NULLS LAST
  `;

  return consultarSQL(sql);
}

// ===== CARGA INICIAL: universo completo (screener + avanzados) + los dos parquet de series =====
export async function cargarTodosLosDatos() {
  const [screener, precios, fundamentales] = await Promise.all([
    cargarUniversoCompleto(),
    cargarParquetCompleto('Actual_Stock.parquet'),
    cargarParquetCompleto('stock_fundamentals_history.parquet')
  ]);

  return { screener, precios, fundamentales };
}
