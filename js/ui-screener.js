
import { filaTicker, renderKpisGlobales, agruparPreciosPorTicker, obtenerUltimoPrecio } from './ui-common.js';

let cacheScreenerCompleto = [];
let arbolSectoresCache = {};
let filtroActivo = { sector: 'Todos', industry: 'Todas', rating: 'Todos', busqueda: '' };

function construirArbolSectorIndustria_(screener) {
  const arbol = {};
  screener.forEach(r => {
    const sector = r.sector || 'Sin sector';
    const industria = r.industry || 'Sin industria';
    if (!arbol[sector]) arbol[sector] = new Set();
    arbol[sector].add(industria);
  });
  const resultado = {};
  Object.keys(arbol).sort().forEach(s => {
    resultado[s] = Array.from(arbol[s]).sort();
  });
  return resultado;
}

function poblarSelectsFiltro_() {
  const selectSector = document.getElementById('filtro-sector-select');
  selectSector.innerHTML = '<option value="Todos">Todos los sectores</option>' +
    Object.keys(arbolSectoresCache).sort().map(s => `<option value="${s}">${s}</option>`).join('');
  actualizarOpcionesIndustria_('Todos');
}

function actualizarOpcionesIndustria_(sectorSeleccionado) {
  const selectIndustry = document.getElementById('filtro-industry-select');
  let industrias = [];
  if (sectorSeleccionado === 'Todos') {
    const todasSet = new Set();
    Object.values(arbolSectoresCache).forEach(lista => lista.forEach(i => todasSet.add(i)));
    industrias = Array.from(todasSet).sort();
  } else {
    industrias = (arbolSectoresCache[sectorSeleccionado] || []).slice().sort();
  }
  selectIndustry.innerHTML = '<option value="Todas">Todas las industrias</option>' +
    industrias.map(i => `<option value="${i}">${i}</option>`).join('');
}

function aplicarFiltros_() {
  let resultado = [...cacheScreenerCompleto];

  if (filtroActivo.sector !== 'Todos') {
    resultado = resultado.filter(r => r.sector === filtroActivo.sector);
  }
  if (filtroActivo.industry !== 'Todas') {
    resultado = resultado.filter(r => r.industry === filtroActivo.industry);
  }
  if (filtroActivo.rating !== 'Todos') {
    resultado = resultado.filter(r => r.rating === filtroActivo.rating);
  }
  if (filtroActivo.busqueda) {
    const q = filtroActivo.busqueda.toUpperCase();
    resultado = resultado.filter(r =>
      (r.ticker || '').toUpperCase().includes(q) ||
      (r.shortName || '').toUpperCase().includes(q)
    );
  }

  resultado.sort((a, b) => (a.rank || 999999) - (b.rank || 999999));

  const contKpis = document.getElementById('kpis-screener-completo');
  if (contKpis) contKpis.innerHTML = renderKpisGlobales(resultado);

  pintarTablaCompleta_(resultado);
}

function pintarTablaCompleta_(data) {
  const cont = document.getElementById('tabla-completa-container');

  if (data.length === 0) {
    cont.innerHTML = '<p style="text-align:center;color:var(--texto-secundario);padding:24px">No hay tickers que coincidan con estos filtros.</p>';
    return;
  }

  cont.innerHTML = `<div class="ranking-list">${data.map(r => filaTicker(r)).join('')}</div>`;

  cont.querySelectorAll('.ranking-row').forEach(row => {
    row.addEventListener('click', () => {
      const ticker = row.dataset.ticker;
      document.dispatchEvent(new CustomEvent('abrir-detalle-ticker', { detail: { ticker } }));
    });
  });
}

export function inicializarScreener({ screener, precios }) {
  const preciosPorTicker = agruparPreciosPorTicker(precios);
  cacheScreenerCompleto = screener.map(row => {
    const tienePrecio = row.lastPrice !== null && row.lastPrice !== undefined;
    const precioFinal = tienePrecio ? row.lastPrice : obtenerUltimoPrecio(preciosPorTicker, row.ticker);
    return { ...row, lastPrice: precioFinal };
  });

  arbolSectoresCache = construirArbolSectorIndustria_(cacheScreenerCompleto);
  poblarSelectsFiltro_();

  document.getElementById('filtro-sector-select').addEventListener('change', (e) => {
    filtroActivo.sector = e.target.value;
    filtroActivo.industry = 'Todas';
    actualizarOpcionesIndustria_(e.target.value);
    aplicarFiltros_();
  });

  document.getElementById('filtro-industry-select').addEventListener('change', (e) => {
    filtroActivo.industry = e.target.value;
    aplicarFiltros_();
  });

  document.getElementById('filtro-rating').addEventListener('change', (e) => {
    filtroActivo.rating = e.target.value;
    aplicarFiltros_();
  });

  document.getElementById('buscador').addEventListener('input', (e) => {
    filtroActivo.busqueda = e.target.value;
    aplicarFiltros_();
  });
}

export function mostrarVistaCompleta() {
  aplicarFiltros_();
}
