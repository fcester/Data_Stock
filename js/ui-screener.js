
import { filaTicker, renderKpisGlobales, agruparPreciosPorTicker, obtenerUltimoPrecio } from './ui-common.js';
import { cargarSnapshotFecha } from './data-loader.js';

let cacheScreenerCompleto = [];      // datos actuales (siempre cargados)
let cacheScreenerHistorico = [];     // snapshot de la fecha elegida
let arbolSectoresCache = {};
let filtroActivo = { sector: 'Todos', industry: 'Todas', rating: 'Todos', busqueda: '' };

// ── Estado del modo fecha ─────────────────────────────────────────────────
let modoHistorico = false;           // false = datos actuales, true = snapshot histórico
let fechaHistoricaActual = null;     // fecha seleccionada en el selector
let cacheFechasDisponibles = [];     // lista de fechas del historial
let screenerActualParaComparar = []; // referencia a datos actuales para el diff de rank


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


function aplicarFiltros_(mostrarDelta = false) {
  // Fuente de datos según modo
  const fuente = modoHistorico ? cacheScreenerHistorico : cacheScreenerCompleto;
  let resultado = [...fuente];

  if (filtroActivo.sector !== 'Todos')    resultado = resultado.filter(r => r.sector === filtroActivo.sector);
  if (filtroActivo.industry !== 'Todas') resultado = resultado.filter(r => r.industry === filtroActivo.industry);
  if (filtroActivo.rating !== 'Todos')   resultado = resultado.filter(r => r.rating === filtroActivo.rating);
  if (filtroActivo.busqueda) {
    const q = filtroActivo.busqueda.toUpperCase();
    resultado = resultado.filter(r =>
      (r.ticker || '').toUpperCase().includes(q) ||
      (r.shortName || '').toUpperCase().includes(q)
    );
  }

  resultado.sort((a, b) => (a.rank || 999999) - (b.rank || 999999));

  // KPIs
  const contKpis = document.getElementById('kpis-screener-completo');
  if (contKpis) contKpis.innerHTML = renderKpisGlobales(resultado);

  // Banner de modo histórico
  const contTabla = document.getElementById('tabla-completa-container');
  let bannerHtml = '';
  if (modoHistorico && fechaHistoricaActual) {
    bannerHtml = `
      <div class="banner-historico" id="banner-historico">
        📅 Mostrando ranking del <strong>${formatearFecha_(fechaHistoricaActual)}</strong>
        — Los scores y posiciones son los de esa fecha, no los actuales.
      </div>
    `;
  }

  contTabla.innerHTML = bannerHtml +
    `<div class="ranking-list">
      ${resultado.map(r => filaTickerConDelta_(r, mostrarDelta)).join('')}
    </div>`;

  contTabla.querySelectorAll('.ranking-row').forEach(row => {
    row.addEventListener('click', () => {
      document.dispatchEvent(new CustomEvent('abrir-detalle-ticker', { detail: { ticker: row.dataset.ticker } }));
    });
  });
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


export function inicializarScreener({ screener, precios, fechasHistorial }) {
  const preciosPorTicker = agruparPreciosPorTicker(precios);
  cacheScreenerCompleto = screener.map(row => {
    const tienePrecio = row.lastPrice !== null && row.lastPrice !== undefined;
    const precioFinal = tienePrecio ? row.lastPrice : obtenerUltimoPrecio(preciosPorTicker, row.ticker);
    return { ...row, lastPrice: precioFinal };
  });
  screenerActualParaComparar = cacheScreenerCompleto;  // guarda referencia a datos actuales

  // ── Poblar fechas históricas ─────────────────────────────────────────
  cacheFechasDisponibles = fechasHistorial || [];
  poblarSelectorFechas_(cacheFechasDisponibles);

  arbolSectoresCache = construirArbolSectorIndustria_(cacheScreenerCompleto);
  poblarSelectsFiltro_();

  // ── Listeners filtros existentes ────────────────────────────────────
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

  // ── NUEVOS: Listeners modo fecha ────────────────────────────────────
  document.getElementById('btn-modo-actual').addEventListener('click', () => {
    activarModoActual_();
  });

  document.getElementById('btn-modo-historico').addEventListener('click', () => {
    document.getElementById('selector-fecha-historico').classList.remove('oculto');
    document.getElementById('selector-fecha-historico').style.display = 'flex';
    document.getElementById('btn-modo-historico').classList.add('activo');
    document.getElementById('btn-modo-actual').classList.remove('activo');
    // Carga la primera fecha disponible por defecto
    if (cacheFechasDisponibles.length > 0) {
      cargarFechaHistorica_(cacheFechasDisponibles[0]);
    }
  });

  document.getElementById('select-fecha-historico').addEventListener('change', (e) => {
    if (e.target.value) cargarFechaHistorica_(e.target.value);
  });

  document.getElementById('btn-comparar-actual').addEventListener('click', () => {
    activarModoComparacion_();
  });
}

// ── Poblar el select de fechas históricas ────────────────────────────────
function poblarSelectorFechas_(fechas) {
  const sel = document.getElementById('select-fecha-historico');
  if (fechas.length === 0) {
    sel.innerHTML = '<option>Sin historial disponible</option>';
    return;
  }
  sel.innerHTML = fechas.map(f => `<option value="${f}">${formatearFecha_(f)}</option>`).join('');
}

function formatearFecha_(fechaStr) {
  const d = new Date(fechaStr + 'T00:00:00');
  return d.toLocaleDateString('es-AR', { day: '2-digit', month: 'short', year: 'numeric' });
}

// ── Cargar snapshot de una fecha histórica ───────────────────────────────
async function cargarFechaHistorica_(fecha) {
  modoHistorico = true;
  fechaHistoricaActual = fecha;

  const badge = document.getElementById('badge-modo-historico');
  badge.textContent = `📅 ${formatearFecha_(fecha)}`;

  // Skeleton mientras carga
  document.getElementById('tabla-completa-container').innerHTML = `
    <div class="skeleton skeleton-row" style="height:60px;margin-bottom:8px"></div>
    <div class="skeleton skeleton-row" style="height:60px;margin-bottom:8px"></div>
    <div class="skeleton skeleton-row" style="height:60px"></div>
  `;

  try {
    const snapshot = await cargarSnapshotFecha(fecha);
    cacheScreenerHistorico = snapshot;

    // Actualizar árbol de sectores con los datos históricos
    arbolSectoresCache = construirArbolSectorIndustria_(snapshot);
    poblarSelectsFiltro_();

    aplicarFiltros_();
  } catch (err) {
    document.getElementById('tabla-completa-container').innerHTML =
      `<p style="color:var(--rojo);padding:20px">Error cargando snapshot: ${err.message}</p>`;
  }
}

// ── Volver a datos actuales ──────────────────────────────────────────────
function activarModoActual_() {
  modoHistorico = false;
  fechaHistoricaActual = null;

  document.getElementById('btn-modo-actual').classList.add('activo');
  document.getElementById('btn-modo-historico').classList.remove('activo');
  document.getElementById('selector-fecha-historico').classList.add('oculto');

  // Restaurar árbol con datos actuales
  arbolSectoresCache = construirArbolSectorIndustria_(cacheScreenerCompleto);
  poblarSelectsFiltro_();

  // Limpiar banner si existía
  const banner = document.getElementById('banner-historico');
  if (banner) banner.remove();

  aplicarFiltros_();
}

// ── Modo comparación: filas con delta de rank ────────────────────────────
function activarModoComparacion_() {
  if (!modoHistorico || !cacheScreenerHistorico.length) return;

  // Mapa de rank actual por ticker
  const rankActual = {};
  screenerActualParaComparar.forEach(r => { rankActual[r.ticker] = r.rank; });

  // Enriquecer datos históricos con delta vs hoy
  const conDelta = cacheScreenerHistorico.map(r => ({
    ...r,
    rank_actual: rankActual[r.ticker] ?? null,
    rank_delta:  rankActual[r.ticker] !== null ? r.rank - rankActual[r.ticker] : null,
    // delta positivo = bajó de rank (era mejor antes), negativo = subió
  }));

  cacheScreenerHistorico = conDelta;
  aplicarFiltros_(true); // true = mostrar columna delta
}

export function mostrarVistaCompleta() {
  aplicarFiltros_();
}

// Extiende filaTicker agregando el indicador de cambio de rank
// cuando estamos en modo comparación histórica
function filaTickerConDelta_(row, mostrarDelta) {
  const base = filaTicker(row);
  if (!mostrarDelta || row.rank_delta === null || row.rank_delta === undefined) {
    return base;
  }

  const delta = row.rank_delta; // positivo = era mejor antes (bajó), negativo = mejoró
  let deltaHtml = '';
  if (delta < 0) {
    // Mejoró: subió posiciones (ahora tiene rank menor = mejor)
    deltaHtml = `<span class="rank-delta rank-delta-sube">↑ ${Math.abs(delta)} vs hoy</span>`;
  } else if (delta > 0) {
    // Empeoró: bajó posiciones
    deltaHtml = `<span class="rank-delta rank-delta-baja">↓ ${delta} vs hoy</span>`;
  } else {
    deltaHtml = `<span class="rank-delta rank-delta-igual">= mismo rank</span>`;
  }

  // Insertar el delta al lado del rank number
  return base.replace(
    `<div class="rank-number">#${row.rank ?? '-'}</div>`,
    `<div class="rank-number">#${row.rank ?? '-'} ${deltaHtml}</div>`
  );
}
