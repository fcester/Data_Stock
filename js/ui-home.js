
import { filaTicker, flechaRendimiento, renderKpisGlobales, agruparPreciosPorTicker, obtenerUltimoPrecio } from './ui-common.js';

export function inicializarHome({ screener, precios }) {
  const preciosPorTicker = agruparPreciosPorTicker(precios);
  const screenerConPrecio = enriquecerConPrecioActual_(screener, preciosPorTicker);

  document.getElementById('kpis-globales').innerHTML = renderKpisGlobales(screenerConPrecio);
  pintarTop10(screenerConPrecio, preciosPorTicker);
}

// Si lastPrice viene null/undefined (bug de pipeline), usa el ultimo precio
// disponible en la serie historica como fallback confiable.
function enriquecerConPrecioActual_(screener, preciosPorTicker) {
  return screener.map(row => {
    const tienePrecio = row.lastPrice !== null && row.lastPrice !== undefined;
    const precioFinal = tienePrecio ? row.lastPrice : obtenerUltimoPrecio(preciosPorTicker, row.ticker);
    return { ...row, lastPrice: precioFinal };
  });
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

function pintarTop10(screener, preciosPorTicker) {
  const top10 = [...screener]
    .filter(r => r.score_FINAL_adj !== null && r.score_FINAL_adj !== undefined)
    .sort((a, b) => b.score_FINAL_adj - a.score_FINAL_adj)
    .slice(0, 10);

  const cont = document.getElementById('top10-container');
  cont.innerHTML = top10.map(row => {
    const rendimiento1m = calcularRendimiento1m_(preciosPorTicker[row.ticker]);
    const filaBase = filaTicker(row);
    const rendimientoHtml = `<div class="ticker-rendimiento-1m">${flechaRendimiento(rendimiento1m)}</div>`;
    return filaBase.replace(
      /(<div class="precio-mini">[\s\S]*?<\/div>)/,
      `$1${rendimientoHtml}`
    );
  }).join('');

  cont.querySelectorAll('.ranking-row').forEach(row => {
    row.addEventListener('click', () => {
      const ticker = row.dataset.ticker;
      document.dispatchEvent(new CustomEvent('abrir-detalle-ticker', { detail: { ticker } }));
    });
  });
}
