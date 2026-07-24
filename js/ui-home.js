
import { claseBadge, filaTicker, flechaRendimiento } from './ui-common.js';

export function inicializarHome({ screener, precios }) {
  pintarKPIs(screener);
  pintarTop10(screener, precios);
}

function pintarKPIs(screener) {
  const totalTickers = screener.length;
  const distribucionRating = {};
  let sumaScore = 0, contScore = 0, sumaPrecio = 0, contPrecio = 0;

  screener.forEach(row => {
    const rating = row.rating || 'Sin dato';
    distribucionRating[rating] = (distribucionRating[rating] || 0) + 1;
    if (row.score_FINAL_adj !== null && row.score_FINAL_adj !== undefined) {
      sumaScore += row.score_FINAL_adj;
      contScore++;
    }
    if (row.lastPrice !== null && row.lastPrice !== undefined) {
      sumaPrecio += row.lastPrice;
      contPrecio++;
    }
  });

  const scorePromedio  = contScore > 0 ? sumaScore / contScore : 0;
  const precioPromedio = contPrecio > 0 ? sumaPrecio / contPrecio : 0;
  const buenas = distribucionRating['Buena'] || 0;
  const evitar = distribucionRating['Evitar'] || 0;

  document.getElementById('kpis-globales').innerHTML = `
    <div class="kpi-card">
      <div class="kpi-valor">${totalTickers}</div>
      <div class="kpi-label">Tickers analizados</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-valor">${scorePromedio.toFixed(2)}<span style="font-size:0.9rem;color:var(--texto-secundario)"> /10</span></div>
      <div class="kpi-label">Score promedio del mercado</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-valor">$${precioPromedio.toFixed(2)}</div>
      <div class="kpi-label">Precio promedio</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-valor" style="color:#1FAE68">${buenas}</div>
      <div class="kpi-label">Rating Buena</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-valor" style="color:#E6483D">${evitar}</div>
      <div class="kpi-label">A evitar</div>
    </div>
  `;
}

// Agrupa la serie "long" de precios (Date, Ticker, Value) por ticker,
// ordenada por fecha, para poder calcular rendimientos sin re-ordenar cada vez.
function agruparPreciosPorTicker_(precios) {
  const mapa = {};
  precios.forEach(p => {
    const t = p.Ticker;
    if (!mapa[t]) mapa[t] = [];
    mapa[t].push(p);
  });
  Object.keys(mapa).forEach(t => {
    mapa[t].sort((a, b) => new Date(a.Date) - new Date(b.Date));
  });
  return mapa;
}

// Rendimiento contra ~21 dias habiles atras (aprox 1 mes de trading),
// mismo criterio que ya usaban en Apps Script para rendimiento_1m.
function calcularRendimiento1m_(serieOrdenada, diasHabiles = 21) {
  if (!serieOrdenada || serieOrdenada.length < 2) return null;
  const valores = serieOrdenada.map(p => p.Value);
  const actual = valores[valores.length - 1];
  const idxHace1m = Math.max(0, valores.length - 1 - diasHabiles);
  const hace1m = valores[idxHace1m];
  if (!hace1m) return null;
  return ((actual - hace1m) / hace1m) * 100;
}

function pintarTop10(screener, precios) {
  const preciosPorTicker = agruparPreciosPorTicker_(precios);

  const top10 = [...screener]
    .filter(r => r.score_FINAL_adj !== null && r.score_FINAL_adj !== undefined)
    .sort((a, b) => b.score_FINAL_adj - a.score_FINAL_adj)
    .slice(0, 10);

  document.getElementById('top10-container').innerHTML = top10.map(row => {
    const rendimiento1m = calcularRendimiento1m_(preciosPorTicker[row.ticker]);
    return filaTickerConRendimiento_(row, rendimiento1m);
  }).join('');
}

// Extiende filaTicker() del común agregando la línea de rendimiento 1m debajo del precio.
function filaTickerConRendimiento_(row, rendimiento1m) {
  const base = filaTicker(row);
  const rendimientoHtml = `<div class="ticker-rendimiento-1m">${flechaRendimiento(rendimiento1m)}</div>`;
  // Inserta el rendimiento justo antes del cierre del bloque "precio-mini"
  return base.replace(
    /(<div class="precio-mini">[^<]*<\/div>)/,
    `$1${rendimientoHtml}`
  );
}
