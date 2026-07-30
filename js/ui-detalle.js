
import { claseBadge, escapeHtml } from './ui-common.js';

let cacheScreenerCompleto = [];
let cachePrecios = [];
let chartPrecioActual = null;
let serieTickerActual = [];
let rangoActivo = '1A';

const RANGOS = [
  { key: '1M', label: '1M' },
  { key: '3M', label: '3M' },
  { key: '6M', label: '6M' },
  { key: 'YTD', label: 'YTD' },
  { key: '1A', label: '1A' },
  { key: '5A', label: '5A' },
  { key: 'MAX', label: 'Máx' },
];

const EXPLICACION_CATEGORIAS = {
  valuation: 'Compara PE, PB y EV/EBITDA contra el sector. Menor valuación relativa = mejor score.',
  profitability: 'Mide ROE, margen neto y margen operativo frente a pares del sector.',
  growth: 'Evalúa crecimiento de ingresos y de ganancias interanual.',
  financial: 'Mide solidez financiera: deuda/patrimonio y liquidez corriente.',
  momentum: 'Compara el precio actual contra sus promedios móviles de 50/200 días y su posición en el rango de 52 semanas.',
  fundamental_momentum: 'Analiza tendencia, consistencia (R²), CAGR y aceleración de ingresos, EBITDA, márgenes, deuda y FCF de los últimos 8 trimestres.',
  income: 'Evalúa el dividendo entregado frente al sector, más el historial de crecimiento de dividendos.'
};

function calcularRetornosDiarios_(precios) {
  const retornos = [];
  for (let i = 1; i < precios.length; i++) {
    const anterior = precios[i - 1];
    const actual = precios[i];
    if (anterior && actual && anterior !== 0) retornos.push((actual - anterior) / anterior);
  }
  return retornos;
}

function desviacionEstandar_(arr) {
  if (arr.length < 2) return null;
  const m = arr.reduce((a, b) => a + b, 0) / arr.length;
  const varianza = arr.reduce((sum, x) => sum + Math.pow(x - m, 2), 0) / (arr.length - 1);
  return Math.sqrt(varianza);
}

function calcularKpisPrecio_(serieCompleta, ventanaDias) {
  const serie = serieCompleta.slice(-ventanaDias);
  const valores = serie.map(p => p.value);
  if (valores.length < 2) {
    return { rendimiento_1m: null, rendimiento_3m: null, rendimiento_ytd: null, volatilidad_anualizada: null, max_drawdown: null };
  }
  const actual = valores[valores.length - 1];
  const hace1m = valores[Math.max(0, valores.length - 1 - 21)];
  const hace3m = valores[Math.max(0, valores.length - 1 - 63)];
  const anioActual = new Date(serie[serie.length - 1].date).getFullYear();
  const primerDelAnio = serie.find(p => new Date(p.date).getFullYear() === anioActual);
  const valorYtd = primerDelAnio ? primerDelAnio.value : valores[0];
  const retornos = calcularRetornosDiarios_(valores);
  const sd = desviacionEstandar_(retornos);
  const volatilidadAnualizada = sd !== null ? sd * Math.sqrt(252) * 100 : null;
  let pico = valores[0], maxDD = 0;
  valores.forEach(v => {
    if (v > pico) pico = v;
    const dd = (v - pico) / pico;
    if (dd < maxDD) maxDD = dd;
  });
  return {
    rendimiento_1m: hace1m ? ((actual - hace1m) / hace1m) * 100 : null,
    rendimiento_3m: hace3m ? ((actual - hace3m) / hace3m) * 100 : null,
    rendimiento_ytd: valorYtd ? ((actual - valorYtd) / valorYtd) * 100 : null,
    volatilidad_anualizada: volatilidadAnualizada,
    max_drawdown: maxDD * 100
  };
}

function obtenerSerieTicker_(precios, ticker) {
  return precios
    .filter(p => (p.Ticker || '').toUpperCase() === ticker.toUpperCase())
    .sort((a, b) => new Date(a.Date) - new Date(b.Date))
    .map(p => ({ date: p.Date, value: p.Value }));
}

// ===== FILTRADO Y RENDIMIENTO POR RANGO (nuevo) =====
function filtrarPorRango_(serie, rango) {
  if (!serie || serie.length === 0) return [];
  const ultimaFecha = new Date(serie[serie.length - 1].date);

  if (rango === 'MAX') return serie;
  if (rango === 'YTD') {
    const inicioAnio = new Date(ultimaFecha.getFullYear(), 0, 1);
    return serie.filter(p => new Date(p.date) >= inicioAnio);
  }
  const diasHabiles = { '1M': 21, '3M': 63, '6M': 126, '1A': 252, '5A': 252 * 5 };
  const n = diasHabiles[rango] || 252;
  return serie.slice(-n);
}

function rendimientoDelPeriodo_(serieFiltrada) {
  if (serieFiltrada.length < 2) return null;
  const primero = serieFiltrada[0].value;
  const ultimo = serieFiltrada[serieFiltrada.length - 1].value;
  if (!primero) return null;
  return ((ultimo - primero) / primero) * 100;
}

function claseFlechaSimple_(valor) {
  if (valor === null || valor === undefined) return 'N/D';
  if (valor > 0) return `<span class="flecha-up">↑ +${valor.toFixed(2)}%</span>`;
  if (valor < 0) return `<span class="flecha-down">↓ ${valor.toFixed(2)}%</span>`;
  return '<span class="flecha-flat">→ 0%</span>';
}

function renderKpiAvanzado_(label, valor, sufijo = '', tooltip = null) {
  const valorTexto = (valor === null || valor === undefined || Number.isNaN(valor)) ? 'N/D' : `${valor.toFixed(2)}${sufijo}`;
  const labelHtml = tooltip
    ? `<span class="tooltip-info">${label}<span class="tooltip-texto">${tooltip}</span></span>`
    : label;
  return `<div class="kpi-card"><div class="kpi-valor">${valorTexto}</div><div class="kpi-label">${labelHtml}</div></div>`;
}

function pintarDetalle_(ticker) {
  const info = cacheScreenerCompleto.find(r => (r.ticker || '').toUpperCase() === ticker.toUpperCase());
  const contenido = document.getElementById('panel-detalle-contenido');

  if (!info) {
    contenido.innerHTML = '<p>Ticker no encontrado en el universo cargado.</p>';
    return;
  }

  serieTickerActual = obtenerSerieTicker_(cachePrecios, ticker);
  rangoActivo = '1A';
  const precioActual = serieTickerActual.length > 0 ? serieTickerActual[serieTickerActual.length - 1].value : (info.lastPrice ?? null);
  const kpisPrecio = calcularKpisPrecio_(serieTickerActual, serieTickerActual.length);
  const score = info.score_FINAL_adj !== null && info.score_FINAL_adj !== undefined ? info.score_FINAL_adj : 0;

  const tooltipRankingGeneral = `
    Score final ponderado: Valuation 16% + Profitability 16% + Growth 12% + Financial Health 12%
    + Price Momentum 14% + Fundamental Momentum 24% + Income 6%.
    Cada categoría se calcula por percentil dentro del mismo sector, con penalización si
    faltan datos (completitud: ${info.data_completeness ?? 'N/D'}%) o si es microcap.
  `;

  const categorias = [
    ['valuation', 'Valuation', info.score_valuation],
    ['profitability', 'Profitability', info.score_profitability],
    ['growth', 'Growth', info.score_growth],
    ['financial', 'Financial Health', info.score_financial],
    ['momentum', 'Price Momentum', info.score_momentum],
    ['fundamental_momentum', 'Fundamental Momentum', info.score_fundamental_momentum],
    ['income', 'Income', info.score_income]
  ];

  const similares = cacheScreenerCompleto
    .filter(r => r.ticker !== info.ticker && r.sector === info.sector && r.industry === info.industry && r.score_FINAL_adj !== null)
    .sort((a, b) => (b.score_FINAL_adj || 0) - (a.score_FINAL_adj || 0))
    .slice(0, 6);

  const htmlSimilares = similares.map(s => `
    <div class="similar-card" data-ticker="${escapeHtml(s.ticker)}">
      <strong>${escapeHtml(s.ticker)}</strong>
      <div>${(s.score_FINAL_adj || 0).toFixed(2)}</div>
      <div class="badge ${claseBadge(s.rating)}">${escapeHtml(s.rating)}</div>
    </div>
  `).join('') || '<p>No hay tickers similares disponibles.</p>';

  const recomendacion = info.recommendationKey
    ? `${escapeHtml(info.recommendationKey)} (${info.numberOfAnalystOpinions ?? 0} analistas)`
    : 'Sin cobertura de analistas';
  const upsideHtml = info.analyst_upside !== null && info.analyst_upside !== undefined
    ? claseFlechaSimple_(info.analyst_upside * 100)
    : 'N/D';

  contenido.innerHTML = `
    <div class="detalle-header" style="flex-direction:column;align-items:flex-start;gap:12px">
      <div>
        <h2>${escapeHtml(info.ticker)} — ${escapeHtml(info.shortName)}</h2>
        <p>${escapeHtml(info.sector)} · ${escapeHtml(info.industry)}</p>
      </div>
      <div style="display:flex;justify-content:space-between;width:100%;align-items:center">
        <div>
          <div class="precio-actual">$${precioActual !== null ? Number(precioActual).toFixed(2) : 'N/D'}</div>
          <div class="precio-label">Precio actual</div>
        </div>
        <div style="text-align:center">
          <div class="score-gauge">${score.toFixed(2)}<span style="font-size:1rem">/10</span></div>
          <div class="badge ${claseBadge(info.rating)}">${escapeHtml(info.rating)}</div>
        </div>
      </div>
      <div class="tooltip-info">
        ℹ ¿Cómo se calcula este score?
        <span class="tooltip-texto">${tooltipRankingGeneral}</span>
      </div>
    </div>

    <div class="card">
      <h4>Rendimiento reciente</h4>
      <p>Último mes: ${claseFlechaSimple_(kpisPrecio.rendimiento_1m)}</p>
      <p>Últimos 3 meses: ${claseFlechaSimple_(kpisPrecio.rendimiento_3m)}</p>
      <p>En lo que va del año (YTD): ${claseFlechaSimple_(kpisPrecio.rendimiento_ytd)}</p>
      <p>Volatilidad anualizada: ${kpisPrecio.volatilidad_anualizada !== null ? kpisPrecio.volatilidad_anualizada.toFixed(1) + '%' : 'N/D'}</p>
      <p>Máxima caída registrada: <span style="color:var(--rojo)">${kpisPrecio.max_drawdown !== null ? kpisPrecio.max_drawdown.toFixed(1) + '%' : 'N/D'}</span></p>
    </div>

    <div class="card">
      <div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px">
        <h4 style="margin:0">Precio histórico</h4>
        <div id="rendimiento-periodo-grafico" class="rendimiento-periodo-badge"></div>
      </div>
      <div class="selector-rangos" id="selector-rangos"></div>
      <canvas id="grafico-precio-detalle" height="220"></canvas>
    </div>

   
    <div class="card">
      <h4>Indicadores de riesgo y mercado</h4>
      <div class="kpis-grid-compacta">
        ${renderKpiAvanzado_('Sharpe Ratio', info.sharpe_ratio, '', 'Retorno anualizado ajustado por volatilidad total. Mayor es mejor.')}
        ${renderKpiAvanzado_('Sortino Ratio', info.sortino_ratio, '', 'Similar al Sharpe, pero solo penaliza la volatilidad negativa (caídas).')}
        ${renderKpiAvanzado_('VaR diario 95%', info.var_95_diario !== null && info.var_95_diario !== undefined ? info.var_95_diario * 100 : null, '%', 'En el 95% de los días históricos, la pérdida no superó este valor.')}
        ${renderKpiAvanzado_('Beta', info.beta, '', 'Sensibilidad del precio frente al mercado. 1 = se mueve igual que el mercado.')}
        ${renderKpiAvanzado_('Beta ajustado', info.beta_adj, '', 'Ajuste Blume (0.67 × Beta + 0.33). Corrige la tendencia a extremos del beta histórico, acercándolo a 1.')}
        ${renderKpiAvanzado_('Volatilidad Anual', info.volatility_annual !== null && info.volatility_annual !== undefined ? info.volatility_annual * 100 : null, '%', 'Desviación estándar de retornos diarios × √252. Mide la dispersión anualizada del precio.')}
        ${renderKpiAvanzado_('Max Drawdown', info.max_drawdown !== null && info.max_drawdown !== undefined ? info.max_drawdown * 100 : null, '%', 'Mayor caída desde un pico en el período histórico disponible. Métrica de riesgo real más intuitiva que el VaR.')}
        ${renderKpiAvanzado_('Calmar Ratio', info.calmar_ratio, '', 'CAGR del período / |Max Drawdown|. Mide el retorno ajustado por la peor caída histórica. > 1 = excelente.')}
      </div>
    </div>

    <div class="card">
      <h4>Salud financiera y consenso de mercado</h4>
      <div class="kpis-grid-compacta">
        ${renderKpiAvanzado_('Piotroski adaptado', info.piotroski_score_adj, '/6', `Salud financiera basada en ${info.piotroski_tests_total ?? 0} de 6 factores posibles (versión adaptada, no el F-Score académico completo).`)}
      </div>
      <p style="margin-top:10px">Consenso de analistas: <strong>${recomendacion}</strong></p>
      <p>Upside implícito vs. precio objetivo promedio: ${upsideHtml}</p>
      <p>Insiders: ${info.heldPercentInsiders !== null && info.heldPercentInsiders !== undefined ? (info.heldPercentInsiders * 100).toFixed(1) + '%' : 'N/D'}
         · Institucional: ${info.heldPercentInstitutions !== null && info.heldPercentInstitutions !== undefined ? (info.heldPercentInstitutions * 100).toFixed(1) + '%' : 'N/D'}
      </p>
    </div>

    
    <div class="card">
      <h4>Dividendos</h4>
      <p>Dividend Yield: ${info.dividendYield !== null && info.dividendYield !== undefined ? (info.dividendYield * 100).toFixed(2) + '%' : 'N/D'}</p>
      <p>Años consecutivos de aumento: ${info.dividend_growth_streak ?? 0}</p>
      <p>Crecimiento promedio interanual: ${info.dividend_growth_avg !== null && info.dividend_growth_avg !== undefined ? (info.dividend_growth_avg * 100).toFixed(1) + '%' : 'N/D'}</p>
    </div>

    <div class="card">
      <h4>Valoración profunda</h4>
      <div class="kpis-grid-compacta">
        ${renderKpiAvanzado_('FCF Yield', info.fcf_yield !== null && info.fcf_yield !== undefined ? info.fcf_yield * 100 : null, '%', 'Flujo de Caja Libre / Market Cap. Cuánto cash genera la empresa por cada dólar invertido.')}
        ${renderKpiAvanzado_('Price / FCF', info.price_to_fcf, 'x', 'Precio sobre FCF por acción. Alternativa al P/E basada en caja real, más difícil de manipular contablemente.')}
        ${renderKpiAvanzado_('Graham Number', info.graham_number, '', 'Precio intrínseco teórico = √(22.5 × EPS × Book Value). Si precio actual < Graham Number → posiblemente subvalorado.')}
        ${renderKpiAvanzado_('Margen de Seguridad', info.graham_margin_of_safety !== null && info.graham_margin_of_safety !== undefined ? info.graham_margin_of_safety * 100 : null, '%', 'Diferencia % entre Graham Number y precio actual. Positivo = cotiza bajo su valor teórico de Graham.')}
        ${renderKpiAvanzado_('EV / Sales', info.ev_to_sales, 'x', 'Enterprise Value / Ventas. Útil para empresas sin EBITDA positivo (growth, tech sin profits).')}
        ${renderKpiAvanzado_('Earnings Quality', info.earnings_quality, 'x', 'OCF / Net Income. > 1: ganancias respaldadas por caja real. < 0.8: posibles accruals elevados o contabilidad agresiva.')}
      </div>
    </div>

    <div class="card">
      <h4>Solidez financiera</h4>
      <div class="kpis-grid-compacta">
        ${renderKpiAvanzado_('ROIC', info.roic !== null && info.roic !== undefined ? info.roic * 100 : null, '%', 'Return on Invested Capital. Si ROIC > costo de capital (WACC), la empresa destruye valor al crecer.')}
        ${renderKpiAvanzado_('Net Debt / EBITDA', info.net_debt_to_ebitda, 'x', 'Palanca financiera neta. < 2x: sólido · 2-4x: moderado · > 4x: apalancado y con riesgo.')}
        ${renderKpiAvanzado_('Interest Coverage', info.interest_coverage, 'x', 'EBIT / Gastos financieros. Cuántas veces puede pagar sus intereses. < 1.5x: riesgo de impago · > 5x: muy sólido.')}
        ${renderKpiAvanzado_('Asset Turnover', info.asset_turnover, 'x', 'Ventas / Activos Totales. Eficiencia en el uso de activos para generar ingresos. Alto = más eficiente en capital.')}
      </div>
    </div>

    <div class="card">
      <h4>Momentum y señales técnicas</h4>
      <div class="kpis-grid-compacta">
        ${renderKpiAvanzado_('RSI 14 días', info.rsi_14, '', 'Relative Strength Index. > 70 = sobrecomprado · < 30 = sobrevendido · 30-70 = zona neutral.')}
        ${renderKpiAvanzado_('Momentum 1M', info.momentum_1m !== null && info.momentum_1m !== undefined ? info.momentum_1m * 100 : null, '%', 'Retorno del precio en el último mes (~21 días hábiles).')}
        ${renderKpiAvanzado_('Momentum 3M', info.momentum_3m !== null && info.momentum_3m !== undefined ? info.momentum_3m * 100 : null, '%', 'Retorno del precio en los últimos 3 meses (~63 días hábiles).')}
        ${renderKpiAvanzado_('Momentum 6M', info.momentum_6m !== null && info.momentum_6m !== undefined ? info.momentum_6m * 100 : null, '%', 'Retorno del precio en los últimos 6 meses (~126 días hábiles).')}
      </div>
      ${info.rsi_14 !== null && info.rsi_14 !== undefined ? `
        <div style="margin-top:16px">
          <div style="display:flex;justify-content:space-between;font-size:0.72rem;color:var(--texto-secundario);margin-bottom:6px">
            <span>Sobrevendido &lt;30</span>
            <span style="font-weight:700">RSI: ${info.rsi_14.toFixed(1)}</span>
            <span>Sobrecomprado &gt;70</span>
          </div>
          <div style="position:relative;height:10px;background:linear-gradient(90deg, var(--rojo) 0%, var(--amarillo) 30%, var(--verde) 30%, var(--verde) 70%, var(--amarillo) 70%, var(--rojo) 100%);border-radius:5px">
            <div style="position:absolute;left:${Math.min(Math.max(info.rsi_14, 0), 100)}%;top:-4px;width:18px;height:18px;background:white;border:3px solid var(--azul-primario);border-radius:50%;transform:translateX(-50%);box-shadow:0 2px 6px rgba(0,0,0,0.25)"></div>
          </div>
        </div>
      ` : ''}
    </div>

    <div class="card">
      <h4>Desglose del score por categoría</h4>

      ${categorias.map(([key, label, valor]) => `
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
          <span class="tooltip-info">${label}<span class="tooltip-texto">${EXPLICACION_CATEGORIAS[key]}</span></span>
          <div style="display:flex;align-items:center;gap:8px;width:55%">
            <div class="score-bar-bg" style="flex:1"><div class="score-bar-fill" style="width:${Math.max(0, Math.min(100, (valor || 0) * 10))}%"></div></div>
            <span style="font-size:0.85rem;font-weight:600">${(valor || 0).toFixed(1)}</span>
          </div>
        </div>
      `).join('')}
    </div>

    <div class="card">
      <h4>Tickers similares (mismo sector e industria)</h4>
      <div class="similares-grid">${htmlSimilares}</div>
    </div>
  `;

  contenido.querySelectorAll('.similar-card').forEach(card => {
    card.addEventListener('click', () => abrirDetalle(card.dataset.ticker));
  });

  pintarSelectorRangos_();
  actualizarGrafico_();
}

function pintarSelectorRangos_() {
  const cont = document.getElementById('selector-rangos');
  cont.innerHTML = RANGOS.map(r => `
    <button type="button" class="btn-rango ${r.key === rangoActivo ? 'activo' : ''}" data-rango="${r.key}">${r.label}</button>
  `).join('');

  cont.querySelectorAll('.btn-rango').forEach(btn => {
    btn.addEventListener('click', () => {
      rangoActivo = btn.dataset.rango;
      cont.querySelectorAll('.btn-rango').forEach(b => b.classList.toggle('activo', b.dataset.rango === rangoActivo));
      actualizarGrafico_();
    });
  });
}

function actualizarGrafico_() {
  const serieFiltrada = filtrarPorRango_(serieTickerActual, rangoActivo);
  const rendimiento = rendimientoDelPeriodo_(serieFiltrada);

  const badge = document.getElementById('rendimiento-periodo-grafico');
  if (badge) {
    badge.innerHTML = rendimiento !== null
      ? (rendimiento >= 0
          ? `<span class="flecha-up">↑ +${rendimiento.toFixed(2)}% en el período</span>`
          : `<span class="flecha-down">↓ ${rendimiento.toFixed(2)}% en el período</span>`)
      : '<span class="flecha-flat">Sin datos suficientes</span>';
  }

  pintarGraficoPrecio_(serieFiltrada);
}

function pintarGraficoPrecio_(serie) {
  const canvas = document.getElementById('grafico-precio-detalle');
  if (!canvas) return;

  if (chartPrecioActual) {
    chartPrecioActual.destroy();
    chartPrecioActual = null;
  }
  if (serie.length === 0) return;

  const esGanancia = serie[serie.length - 1].value >= serie[0].value;
  const colorLinea = esGanancia ? '#1FAE68' : '#E6483D';
  const colorFondo = esGanancia ? 'rgba(31,174,104,0.1)' : 'rgba(230,72,61,0.1)';

  const unidadTiempo = serie.length > 400 ? 'year' : (serie.length > 90 ? 'month' : 'day');

  chartPrecioActual = new Chart(canvas, {
    type: 'line',
    data: {
      datasets: [{
        label: 'Precio',
        data: serie.map(p => ({ x: p.date, y: p.value })),
        borderColor: colorLinea,
        backgroundColor: colorFondo,
        fill: true,
        tension: 0.25,
        pointRadius: 0,
        pointHoverRadius: 5,
        borderWidth: 2
      }]
    },
    options: {
      responsive: true,
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (ctx) => `$${Number(ctx.parsed.y).toFixed(2)}` } }
      },
      scales: {
        x: {
          type: 'time',
          time: { unit: unidadTiempo, tooltipFormat: 'dd MMM yyyy', displayFormats: { day: 'dd MMM', month: 'MMM yyyy', year: 'yyyy' } },
          ticks: { maxTicksLimit: 6 },
          grid: { display: false }
        },
        y: { beginAtZero: false, ticks: { callback: v => '$' + v } }
      }
    }
  });
}

export function abrirDetalle(ticker) {
  document.getElementById('overlay-detalle').classList.remove('oculto');
  document.getElementById('panel-detalle').classList.remove('oculto');
  pintarDetalle_(ticker);
}

function cerrarPanelDetalle() {
  document.getElementById('overlay-detalle').classList.add('oculto');
  document.getElementById('panel-detalle').classList.add('oculto');
  if (chartPrecioActual) {
    chartPrecioActual.destroy();
    chartPrecioActual = null;
  }
}

export function inicializarDetalle({ screener, precios }) {
  cacheScreenerCompleto = screener;
  cachePrecios = precios;

  document.getElementById('btn-cerrar-panel').addEventListener('click', cerrarPanelDetalle);
  document.getElementById('overlay-detalle').addEventListener('click', cerrarPanelDetalle);

  document.addEventListener('abrir-detalle-ticker', (e) => {
    abrirDetalle(e.detail.ticker);
  });
}
