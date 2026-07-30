
import { filaTicker, renderKpisGlobales, agruparPreciosPorTicker, obtenerUltimoPrecio } from './ui-common.js';
import { cargarSnapshotFecha } from './data-loader.js';

// ── Variables de módulo ───────────────────────────────────────────────────
let cacheScreenerCompleto  = [];
let cacheScreenerHistorico = [];
let arbolSectoresCache     = {};
let filtroActivo = { sector: 'Todos', industry: 'Todas', rating: 'Todos', busqueda: '' };
let modoHistorico          = false;
let fechaHistoricaActual   = null;
let cacheFechasDisponibles = [];
let screenerActualRef      = [];
let cachePreciosPorTicker  = {};

// ── Árbol sector → industrias ─────────────────────────────────────────────
function construirArbolSectorIndustria_(screener) {
  const arbol = {};
  screener.forEach(r => {
    const sector    = r.sector   || 'Sin sector';
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

// ── Selects de filtro ─────────────────────────────────────────────────────
function poblarSelectsFiltro_() {
  const selectSector = document.getElementById('filtro-sector-select');
  if (!selectSector) return;
  selectSector.innerHTML =
    '<option value="Todos">Todos los sectores</option>' +
    Object.keys(arbolSectoresCache).sort()
      .map(s => `<option value="${s}">${s}</option>`).join('');
  actualizarOpcionesIndustria_('Todos');
}

function actualizarOpcionesIndustria_(sectorSeleccionado) {
  const selectIndustry = document.getElementById('filtro-industry-select');
  if (!selectIndustry) return;
  let industrias = [];
  if (sectorSeleccionado === 'Todos') {
    const todasSet = new Set();
    Object.values(arbolSectoresCache).forEach(lista => lista.forEach(i => todasSet.add(i)));
    industrias = Array.from(todasSet).sort();
  } else {
    industrias = (arbolSectoresCache[sectorSeleccionado] || []).slice().sort();
  }
  selectIndustry.innerHTML =
    '<option value="Todas">Todas las industrias</option>' +
    industrias.map(i => `<option value="${i}">${i}</option>`).join('');
}

// ── Aplicar filtros y renderizar tabla ────────────────────────────────────
function aplicarFiltros_(mostrarDelta = false) {
  const fuente  = modoHistorico ? cacheScreenerHistorico : cacheScreenerCompleto;
  let resultado = [...fuente];

  if (filtroActivo.sector   !== 'Todos')
    resultado = resultado.filter(r => r.sector   === filtroActivo.sector);
  if (filtroActivo.industry !== 'Todas')
    resultado = resultado.filter(r => r.industry === filtroActivo.industry);
  if (filtroActivo.rating   !== 'Todos')
    resultado = resultado.filter(r => r.rating   === filtroActivo.rating);
  if (filtroActivo.busqueda) {
    const q = filtroActivo.busqueda.toUpperCase();
    resultado = resultado.filter(r =>
      (r.ticker    || '').toUpperCase().includes(q) ||
      (r.shortName || '').toUpperCase().includes(q)
    );
  }
  resultado.sort((a, b) => (a.rank || 999999) - (b.rank || 999999));

  const contKpis = document.getElementById('kpis-screener-completo');
  if (contKpis) contKpis.innerHTML = renderKpisGlobales(resultado);

  const cont = document.getElementById('tabla-completa-container');
  if (!cont) return;

  let bannerHtml = '';
  if (modoHistorico && fechaHistoricaActual) {
    bannerHtml = `<div class="banner-historico">
      📅 Ranking del <strong>${formatearFecha_(fechaHistoricaActual)}</strong>
      — scores y posiciones de esa fecha, no las actuales.
    </div>`;
  }

  if (resultado.length === 0) {
    cont.innerHTML = bannerHtml +
      `<p style="text-align:center;color:var(--texto-secundario);padding:24px">
        No hay tickers que coincidan con estos filtros.
       </p>`;
    return;
  }

  cont.innerHTML = bannerHtml +
    `<div class="ranking-list">
      ${resultado.map(r => filaTickerConDelta_(r, mostrarDelta)).join('')}
     </div>`;

  cont.querySelectorAll('.ranking-row').forEach(row => {
    row.addEventListener('click', () => {
      document.dispatchEvent(new CustomEvent('abrir-detalle-ticker', {
        detail: { ticker: row.dataset.ticker }
      }));
    });
  });
}

// ── Inicialización principal ──────────────────────────────────────────────
export function inicializarScreener({ screener, precios, fechasHistorial }) {
  cachePreciosPorTicker = agruparPreciosPorTicker(precios);

  cacheScreenerCompleto = screener.map(row => {
    const tienePrecio = row.lastPrice !== null && row.lastPrice !== undefined;
    return {
      ...row,
      lastPrice: tienePrecio
        ? row.lastPrice
        : obtenerUltimoPrecio(cachePreciosPorTicker, row.ticker)
    };
  });
  screenerActualRef      = cacheScreenerCompleto;
  cacheFechasDisponibles = fechasHistorial || [];

  arbolSectoresCache = construirArbolSectorIndustria_(cacheScreenerCompleto);
  poblarSelectsFiltro_();
  poblarSelectorFechas_(cacheFechasDisponibles);

  // ── Listeners: filtros ───────────────────────────────────────────────
  document.getElementById('filtro-sector-select')?.addEventListener('change', (e) => {
    filtroActivo.sector   = e.target.value;
    filtroActivo.industry = 'Todas';
    actualizarOpcionesIndustria_(e.target.value);
    aplicarFiltros_();
  });
  document.getElementById('filtro-industry-select')?.addEventListener('change', (e) => {
    filtroActivo.industry = e.target.value;
    aplicarFiltros_();
  });
  document.getElementById('filtro-rating')?.addEventListener('change', (e) => {
    filtroActivo.rating = e.target.value;
    aplicarFiltros_();
  });
  document.getElementById('buscador')?.addEventListener('input', (e) => {
    filtroActivo.busqueda = e.target.value;
    aplicarFiltros_();
  });

  // ── Listeners: modo histórico ────────────────────────────────────────
  document.getElementById('btn-modo-actual')
    ?.addEventListener('click', activarModoActual_);

  document.getElementById('btn-modo-historico')
    ?.addEventListener('click', () => {
      const selectorDiv = document.getElementById('selector-fecha-historico');
      if (selectorDiv) {
        selectorDiv.classList.remove('oculto');
        selectorDiv.style.display = 'flex';
      }
      document.getElementById('btn-modo-historico')?.classList.add('activo');
      document.getElementById('btn-modo-actual')?.classList.remove('activo');

      if (cacheFechasDisponibles.length > 0) {
        const selectFecha = document.getElementById('select-fecha-historico');
        if (selectFecha) selectFecha.selectedIndex = 0;
        cargarFechaHistorica_(cacheFechasDisponibles[0]);
      } else {
        const cont = document.getElementById('tabla-completa-container');
        if (cont) cont.innerHTML = `
          <div class="banner-historico">
            📅 Aún no hay historial acumulado.
            El historial se genera automáticamente cada vez que se ejecuta el pipeline Python.
          </div>`;
      }
    });

  document.getElementById('select-fecha-historico')
    ?.addEventListener('change', (e) => {
      if (e.target.value) cargarFechaHistorica_(e.target.value);
    });

  document.getElementById('btn-comparar-actual')
    ?.addEventListener('click', activarModoComparacion_);

  // ── Listener: recibir filtro desde la página Mercado ─────────────────
  document.addEventListener('filtrar-screener', (e) => {
    const { sector, industry } = e.detail;
    filtroActivo.sector   = sector   || 'Todos';
    filtroActivo.industry = industry || 'Todas';
    filtroActivo.rating   = 'Todos';
    filtroActivo.busqueda = '';

    const selSector = document.getElementById('filtro-sector-select');
    if (selSector) selSector.value = filtroActivo.sector;
    actualizarOpcionesIndustria_(filtroActivo.sector);
    const selInd = document.getElementById('filtro-industry-select');
    if (selInd) selInd.value = filtroActivo.industry;

    aplicarFiltros_();
  });
}

export function mostrarVistaCompleta() {
  aplicarFiltros_();
}

// ── Selector de fechas históricas ─────────────────────────────────────────
function poblarSelectorFechas_(fechas) {
  const sel = document.getElementById('select-fecha-historico');
  if (!sel) return;
  sel.innerHTML = fechas.length === 0
    ? '<option>Sin historial aún</option>'
    : fechas.map(f => `<option value="${f}">${formatearFecha_(f)}</option>`).join('');
}

function formatearFecha_(fechaStr) {
  if (!fechaStr) return fechaStr;
  const d = new Date(fechaStr + 'T00:00:00');
  return d.toLocaleDateString('es-AR', { day: '2-digit', month: 'short', year: 'numeric' });
}

// ── Cargar snapshot de una fecha histórica ────────────────────────────────
async function cargarFechaHistorica_(fecha) {
  modoHistorico        = true;
  fechaHistoricaActual = fecha;

  const badge = document.getElementById('badge-modo-historico');
  if (badge) badge.textContent = `📅 ${formatearFecha_(fecha)}`;

  const contTabla = document.getElementById('tabla-completa-container');
  if (contTabla) {
    contTabla.innerHTML = `
      <div class="skeleton skeleton-row" style="height:60px;margin-bottom:8px"></div>
      <div class="skeleton skeleton-row" style="height:60px;margin-bottom:8px"></div>
      <div class="skeleton skeleton-row" style="height:60px"></div>`;
  }

  try {
    const snapshot         = await cargarSnapshotFecha(fecha);
    cacheScreenerHistorico = snapshot;
    arbolSectoresCache     = construirArbolSectorIndustria_(snapshot);
    poblarSelectsFiltro_();
    aplicarFiltros_();
  } catch (err) {
    if (contTabla) {
      contTabla.innerHTML =
        `<p style="color:var(--rojo);padding:20px">Error cargando snapshot: ${err.message}</p>`;
    }
  }
}

// ── Volver a datos actuales ───────────────────────────────────────────────
function activarModoActual_() {
  modoHistorico          = false;
  fechaHistoricaActual   = null;
  cacheScreenerHistorico = [];

  document.getElementById('btn-modo-actual')?.classList.add('activo');
  document.getElementById('btn-modo-historico')?.classList.remove('activo');

  const selectorDiv = document.getElementById('selector-fecha-historico');
  if (selectorDiv) {
    selectorDiv.style.display = '';
    selectorDiv.classList.add('oculto');
  }

  arbolSectoresCache = construirArbolSectorIndustria_(cacheScreenerCompleto);
  poblarSelectsFiltro_();
  aplicarFiltros_();
}

// ── Modo comparación: delta de rank + rentabilidad ────────────────────────
function activarModoComparacion_() {
  if (!modoHistorico || !cacheScreenerHistorico.length) return;

  const rankActualMap = {};
  screenerActualRef.forEach(r => { rankActualMap[r.ticker] = r.rank; });

  cacheScreenerHistorico = cacheScreenerHistorico.map(r => {
    const rank_actual = rankActualMap[r.ticker] ?? null;
    const rank_delta  = rank_actual != null ? r.rank - rank_actual : null;

    let retorno_desde_fecha = null;
    const serie = cachePreciosPorTicker[r.ticker];

    if (serie && serie.length > 0 && fechaHistoricaActual) {
      const puntoHistorico = serie.find(p => p.Date >= fechaHistoricaActual);
      const puntoActual    = serie[serie.length - 1];
      if (puntoHistorico && puntoActual && puntoHistorico.Value > 0) {
        retorno_desde_fecha = (puntoActual.Value / puntoHistorico.Value - 1) * 100;
      }
    }

    return { ...r, rank_actual, rank_delta, retorno_desde_fecha };
  });

  aplicarFiltros_(true);
}

// ── Fila con delta de rank y rentabilidad ─────────────────────────────────
function filaTickerConDelta_(row, mostrarDelta) {
  let base = filaTicker(row);
  if (!mostrarDelta) return base;

  // 1. Badge de delta de rank
  
  if (row.rank_delta != null) {
    const delta = row.rank_delta;
    let deltaHtml;
    if      (delta > 0) deltaHtml = `<span class="rank-delta rank-delta-sube">↑${delta} pos. vs hoy</span>`;
    else if (delta < 0) deltaHtml = `<span class="rank-delta rank-delta-baja">↓${Math.abs(delta)} pos. vs hoy</span>`;
    else                deltaHtml = `<span class="rank-delta rank-delta-igual">= igual</span>`;

    base = base.replace(
      `<div class="rank-number">#${row.rank ?? '-'}</div>`,
      `<div class="rank-number" style="display:flex;flex-direction:column;gap:2px">
        #${row.rank ?? '-'} ${deltaHtml}
       </div>`
    );
  }

  // 2. Rentabilidad desde la fecha histórica
  if (row.retorno_desde_fecha != null) {
    const ret    = row.retorno_desde_fecha;
    const color  = ret >= 0 ? 'var(--verde)' : 'var(--rojo)';
    const signo  = ret >= 0 ? '+' : '';
    const flecha = ret >= 0 ? '↑' : '↓';

    const retHtml = `<div class="retorno-historico" style="color:${color}">
      ${flecha} ${signo}${ret.toFixed(2)}%
    </div>`;

    base = base.replace(
      /(<div class="precio-mini">[\s\S]*?<\/div>)/,
      `$1${retHtml}`
    );
  }

  return base;
}
