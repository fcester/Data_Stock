
// ============================================================
// ui-mercado.js — Análisis de mercado por sector e industria
// Usa solo datos ya cargados en memoria (screener + tendencia).
// Sin llamadas de red adicionales después de la carga inicial.
// ============================================================
import { escapeHtml, claseBadge } from './ui-common.js';

let cacheScreener       = [];
let cacheTendencia      = {};   // { sector: avg_score_ref }
let modoVista           = 'sectores';   // 'sectores' | 'industrias'
let cacheTrendsPython   = [];   // datos de Sector_Industry_Trends.parquet (beta/PE/dividendo reales por grupo)
let filtroTendencia     = 'todos';
let ordenActual         = 'score';
let busquedaActual      = '';
let sectorDrilldown     = null;   // null = vista general, 'Technology' = drill-down
let chartSectores       = null;

// ── Entry point ──────────────────────────────────────────────────────────

export function inicializarMercado({ screener, tendenciaSectores, tendenciaGruposCompleta }) {
  cacheScreener     = screener || [];
  cacheTrendsPython = tendenciaGruposCompleta || [];

  // Construir mapa de tendencia: { sector → avg_score_ref }
  (tendenciaSectores || []).forEach(r => {
    if (r.sector) cacheTendencia[r.sector] = r.avg_score_ref;
  });


  // ── Listeners (defensivos) ──────────────────────────────────────────
  document.getElementById('tab-sectores')?.addEventListener('click', () => {
    modoVista      = 'sectores';
    sectorDrilldown = null;
    actualizarTabsActivo_('tab-sectores');
    renderizarContenido_();
  });
  document.getElementById('tab-industrias')?.addEventListener('click', () => {
    modoVista      = 'industrias';
    sectorDrilldown = null;
    actualizarTabsActivo_('tab-industrias');
    renderizarContenido_();
  });

  document.querySelectorAll('.btn-filtro-tend').forEach(btn => {
    btn.addEventListener('click', () => {
      filtroTendencia = btn.dataset.tend;
      document.querySelectorAll('.btn-filtro-tend').forEach(b => b.classList.remove('activo'));
      btn.classList.add('activo');
      renderizarContenido_();
    });
  });

  document.getElementById('mercado-orden')?.addEventListener('change', (e) => {
    ordenActual = e.target.value;
    renderizarContenido_();
  });

  document.getElementById('buscador-mercado')?.addEventListener('input', (e) => {
    busquedaActual = e.target.value.toLowerCase();
    renderizarContenido_();
  });

  renderizarContenido_();
}

// ── Helpers de cálculo ───────────────────────────────────────────────────
function calcularEstadisticasGrupo_(lista, claveTendencia) {
  const scores     = lista.map(r => r.score_FINAL_adj).filter(s => s != null);
  const scoreAct   = scores.length > 0 ? scores.reduce((a, b) => a + b, 0) / scores.length : null;
  const scoreRef   = cacheTendencia[claveTendencia] ?? null;
  const delta      = scoreAct != null && scoreRef != null ? scoreAct - scoreRef : null;

  const ratings = { Excelente: 0, Buena: 0, Neutral: 0, 'Débil': 0, Evitar: 0 };
  lista.forEach(r => { if (r.rating && ratings[r.rating] !== undefined) ratings[r.rating]++; });

  const topTickers = [...lista]
    .filter(r => r.score_FINAL_adj != null)
    .sort((a, b) => (b.score_FINAL_adj || 0) - (a.score_FINAL_adj || 0))
    .slice(0, 3);

  const betas    = lista.map(r => r.beta).filter(v => v != null);
  const divYield = lista.map(r => r.dividendYield).filter(v => v != null);
  const pes      = lista.map(r => r.trailingPE).filter(v => v != null && v > 0 && v < 200);

  const avg = arr => arr.length > 0 ? arr.reduce((a, b) => a + b, 0) / arr.length : null;

  let tendencia;
  if (delta === null)    tendencia = 'sin-dato';
  else if (delta > 0.1)  tendencia = 'sube';
  else if (delta < -0.1) tendencia = 'baja';
  else                   tendencia = 'estable';

  return {
    scoreActual: scoreAct,
    scoreRef,
    delta,
    tendencia,
    ratings,
    topTickers,
    nTickers: lista.length,
    avgBeta:     avg(betas),
    avgDivYield: avg(divYield),
    avgPE:       avg(pes),
  };
}

function calcularSectores_() {
  const mapa = {};
  cacheScreener.forEach(r => {
    const k = r.sector || 'Sin sector';
    if (!mapa[k]) mapa[k] = [];
    mapa[k].push(r);
  });
  return Object.entries(mapa).map(([nombre, lista]) => ({
    nombre,
    ...calcularEstadisticasGrupo_(lista, nombre)
  }));
}

function calcularIndustrias_(soloSector = null) {
  const mapa = {};
  const fuente = soloSector
    ? cacheScreener.filter(r => r.sector === soloSector)
    : cacheScreener;

  fuente.forEach(r => {
    const k = r.industry || 'Sin industria';
    if (!mapa[k]) mapa[k] = { lista: [], sector: r.sector };
    mapa[k].lista.push(r);
  });

  // La tendencia de industria usa el score del sector como referencia
  return Object.entries(mapa).map(([nombre, { lista, sector }]) => ({
    nombre,
    sector,
    ...calcularEstadisticasGrupo_(lista, sector)
  }));
}

// ── Filtrado y ordenamiento ───────────────────────────────────────────────
function filtrarYOrdenar_(grupos) {
  let res = [...grupos];

  if (filtroTendencia !== 'todos') {
    res = res.filter(g => g.tendencia === filtroTendencia);
  }

  if (busquedaActual) {
    res = res.filter(g => g.nombre.toLowerCase().includes(busquedaActual));
  }

  const dir = { score: -1, tickers: -1, mejora: -1, nombre: 1 };
  const key = { score: 'scoreActual', tickers: 'nTickers', mejora: 'delta', nombre: 'nombre' };

  res.sort((a, b) => {
    const va = a[key[ordenActual]] ?? (ordenActual === 'nombre' ? '' : -Infinity);
    const vb = b[key[ordenActual]] ?? (ordenActual === 'nombre' ? '' : -Infinity);
    if (typeof va === 'string') return va.localeCompare(vb) * dir[ordenActual];
    return (vb - va) * dir[ordenActual] * -1;
  });

  return res;
}

// ── KPIs globales del mercado ─────────────────────────────────────────────
function renderizarKpisGlobales_() {
  const cont = document.getElementById('kpis-mercado');
  if (!cont) return;

  const total     = cacheScreener.length;
  const conScore  = cacheScreener.filter(r => r.score_FINAL_adj != null);
  const scoreGlob = conScore.length > 0
    ? conScore.reduce((s, r) => s + r.score_FINAL_adj, 0) / conScore.length : null;

  const nBuenas   = cacheScreener.filter(r => r.rating === 'Excelente' || r.rating === 'Buena').length;
  const sectores  = new Set(cacheScreener.map(r => r.sector).filter(Boolean)).size;
  const industrias= new Set(cacheScreener.map(r => r.industry).filter(Boolean)).size;
  const alcistas  = Object.values(
    calcularSectores_().reduce((acc, s) => { acc[s.nombre] = s; return acc; }, {})
  ).filter(s => s.tendencia === 'sube').length;

  cont.innerHTML = `
    <div class="kpi-card">
      <div class="kpi-valor">${total}</div>
      <div class="kpi-label">Tickers en universo</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-valor">${scoreGlob !== null ? scoreGlob.toFixed(2) : 'N/D'}
        <span style="font-size:0.9rem;color:var(--texto-secundario)">/10</span>
      </div>
      <div class="kpi-label">Score promedio global</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-valor" style="color:var(--verde)">
        ${((nBuenas / total) * 100).toFixed(0)}%
      </div>
      <div class="kpi-label">Tickers Excelente o Buena</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-valor">${sectores}</div>
      <div class="kpi-label">Sectores · ${industrias} industrias</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-valor" style="color:var(--verde)">${alcistas}</div>
      <div class="kpi-label">Sectores en tendencia alcista</div>
    </div>
  `;
}

// ── Breadcrumb ────────────────────────────────────────────────────────────
function renderizarBreadcrumb_() {
  const cont = document.getElementById('mercado-breadcrumb');
  if (!cont) return;

  if (!sectorDrilldown) {
    cont.classList.add('oculto');
    return;
  }

  cont.classList.remove('oculto');
  cont.innerHTML = `
    <button class="breadcrumb-link" id="btn-breadcrumb-volver">
      ${modoVista === 'sectores' ? '🏭 Todos los sectores' : '🔬 Todas las industrias'}
    </button>
    <span class="breadcrumb-sep">›</span>
    <span class="breadcrumb-actual">${escapeHtml(sectorDrilldown)}</span>
  `;

  document.getElementById('btn-breadcrumb-volver')?.addEventListener('click', () => {
    sectorDrilldown = null;
    renderizarContenido_();
  });
}

// ── Card de sector/industria ──────────────────────────────────────────────
function htmlCard_(grupo, esSector) {
  const score     = grupo.scoreActual;
  const anchoBarra= score !== null ? Math.min(100, Math.max(0, score * 10)) : 0;

  const iconTend = { sube: '↑', baja: '↓', estable: '→', 'sin-dato': '–' };
  const clsTend  = { sube: 'tend-sube', baja: 'tend-baja', estable: 'tend-estable', 'sin-dato': 'tend-sindata' };
  const deltaStr = grupo.delta !== null
    ? `${grupo.delta >= 0 ? '+' : ''}${grupo.delta.toFixed(2)}`
    : 'sin ref.';

  const totalRatings = Object.values(grupo.ratings).reduce((a, b) => a + b, 0) || 1;
  const coloresRating = {
    Excelente: 'var(--verde)', Buena: '#5FCB8F', Neutral: 'var(--amarillo)',
    'Débil': '#F0894A', Evitar: 'var(--rojo)'
  };

  const ratingBars = Object.entries(grupo.ratings).map(([r, n]) => {
    const pct = ((n / totalRatings) * 100).toFixed(0);
    return pct > 0
      ? `<div class="rating-dist-seg" title="${r}: ${n} (${pct}%)"
             style="width:${pct}%;background:${coloresRating[r]}"></div>` : '';
  }).join('');

  const ratingLeyenda = Object.entries(grupo.ratings).map(([r, n]) =>
    n > 0 ? `<span style="color:${coloresRating[r]}">${n} ${r}</span>` : ''
  ).filter(Boolean).join(' · ');

  const topTickersHtml = grupo.topTickers.map(t => `
    <span class="top-ticker-pill" data-ticker="${escapeHtml(t.ticker)}">
      ${escapeHtml(t.ticker)} ${(t.score_FINAL_adj || 0).toFixed(1)}
    </span>`).join('');

  const botonDrill = esSector
    ? `<button class="btn-ver-drill" data-sector="${escapeHtml(grupo.nombre)}">
        Ver industrias de ${escapeHtml(grupo.nombre)} →
       </button>`
    : `<button class="btn-ver-drill btn-ver-en-screener" data-industry="${escapeHtml(grupo.nombre)}" data-sector="${escapeHtml(grupo.sector || '')}">
        Ver tickers en Screener →
       </button>`;

  return `
    <div class="sector-card">
      <div class="sector-card-header">
        <div>
          <div class="sector-nombre">${escapeHtml(grupo.nombre)}</div>
          <div class="sector-meta">
            ${grupo.nTickers} tickers
            ${grupo.sector && !esSector ? `· ${escapeHtml(grupo.sector)}` : ''}
          </div>
        </div>
        <div class="sector-score-col">
          <div class="sector-score-valor">
            ${score !== null ? score.toFixed(2) : 'N/D'}
          </div>
          <span class="tendencia-badge ${clsTend[grupo.tendencia]}">
            ${iconTend[grupo.tendencia]} ${deltaStr}
          </span>
        </div>
      </div>

      <div class="sector-score-bar">
        <div class="sector-score-fill" style="width:${anchoBarra}%"></div>
      </div>

      <div class="rating-dist-wrap">
        <div class="rating-dist-bar-row">${ratingBars}</div>
        <div class="rating-dist-legend">${ratingLeyenda}</div>
      </div>

      <div class="sector-kpis-row">
        <div class="sector-kpi">
          <div class="sector-kpi-valor">
            ${grupo.avgBeta !== null ? grupo.avgBeta.toFixed(2) : 'N/D'}
          </div>
          <div class="sector-kpi-label">Beta prom.</div>
        </div>
        <div class="sector-kpi">
          <div class="sector-kpi-valor">
            ${grupo.avgDivYield !== null ? (grupo.avgDivYield * 100).toFixed(1) + '%' : 'N/D'}
          </div>
          <div class="sector-kpi-label">Div. Yield</div>
        </div>
        <div class="sector-kpi">
          <div class="sector-kpi-valor">
            ${grupo.avgPE !== null ? grupo.avgPE.toFixed(1) + 'x' : 'N/D'}
          </div>
          <div class="sector-kpi-label">P/E prom.</div>
        </div>
        <div class="sector-kpi">
          <div class="sector-kpi-valor">${grupo.nTickers}</div>
          <div class="sector-kpi-label">Tickers</div>
        </div>
      </div>

      <div class="top-tickers-mini">${topTickersHtml}</div>

      ${botonDrill}
    </div>
  `;
}

// ── Render principal ──────────────────────────────────────────────────────
function renderizarContenido_() {
  renderizarKpisGlobales_();
  renderizarBreadcrumb_();

  const cont = document.getElementById('mercado-contenido');
  if (!cont) return;

  let grupos;
  if (modoVista === 'sectores' && !sectorDrilldown) {
    grupos = calcularSectores_();
  } else if (modoVista === 'sectores' && sectorDrilldown) {
    // Drill-down: industrias dentro del sector elegido
    grupos = calcularIndustrias_(sectorDrilldown);
  } else {
    // Vista de todas las industrias
    grupos = calcularIndustrias_(null);
  }

  const filtrados = filtrarYOrdenar_(grupos);
  const esSector  = modoVista === 'sectores' && !sectorDrilldown;

  if (filtrados.length === 0) {
    cont.innerHTML = `<div style="grid-column:1/-1;text-align:center;color:var(--texto-secundario);padding:40px">
      No hay resultados para este filtro.
    </div>`;
    return;
  }

  cont.innerHTML = filtrados.map(g => htmlCard_(g, esSector)).join('');

  // ── Listeners de las cards ──────────────────────────────────────────
  // Drill-down en sector
  cont.querySelectorAll('.btn-ver-drill:not(.btn-ver-en-screener)').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      sectorDrilldown = btn.dataset.sector;
      renderizarContenido_();
    });
  });

  // Ir al screener filtrado por industria
  cont.querySelectorAll('.btn-ver-en-screener').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      // Emite evento que ui-screener.js puede escuchar para pre-filtrar
      document.dispatchEvent(new CustomEvent('filtrar-screener', {
        detail: {
          sector:   btn.dataset.sector,
          industry: btn.dataset.industry
        }
      }));
      // Navegar a la vista completa del screener
      document.querySelectorAll('.vista').forEach(v => v.classList.add('oculto'));
      document.getElementById('vista-completa')?.classList.remove('oculto');
    });
  });

  // Abrir detalle de ticker desde top-ticker-pill
  cont.querySelectorAll('.top-ticker-pill').forEach(pill => {
    pill.addEventListener('click', (e) => {
      e.stopPropagation();
      document.dispatchEvent(new CustomEvent('abrir-detalle-ticker', {
        detail: { ticker: pill.dataset.ticker }
      }));
    });
  });
}

function actualizarTabsActivo_(idActivo) {
  document.querySelectorAll('.tab-mercado').forEach(t => t.classList.remove('activo'));
  document.getElementById(idActivo)?.classList.add('activo');
}
