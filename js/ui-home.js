
import { filaTicker, flechaRendimiento, renderKpisGlobales } from './ui-common.js';

export function inicializarHome({ screener, precios }) {
  document.getElementById('kpis-globales').innerHTML = renderKpisGlobales(screener);
  pintarTop10(screener, precios);
}

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
  const totalTickers = screener.length;

  const top10 = [...screener]
    .filter(r => r.score_FINAL_adj !== null && r.score_FINAL_adj !== undefined)
    .sort((a, b) => b.score_FINAL_adj - a.score_FINAL_adj)
    .slice(0, 10);

  document.getElementById('top10-container').innerHTML = top10.map(row => {
    const rendimiento1m = calcularRendimiento1m_(preciosPorTicker[row.ticker]);
    const filaBase = filaTicker(row, totalTickers);
    const rendimientoHtml = `<div class="ticker-rendimiento-1m">${flechaRendimiento(rendimiento1m)}</div>`;
    return filaBase.replace(
      /(<div class="precio-mini">[\s\S]*?<\/div>)/,
      `$1${rendimientoHtml}`
    );
  }).join('');
}
