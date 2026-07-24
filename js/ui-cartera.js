
import { claseBadge, flechaRendimiento, escapeHtml } from './ui-common.js';
import { calcularCartera, sugerirCartera } from './stats-cartera.js';

const MAX_CARTERA = 15;
const KPIS_SUGERIDOR = [
  { key: 'score_FINAL_adj', label: 'Score Fundamental' },
  { key: 'sharpe_ratio', label: 'Sharpe Ratio' },
  { key: 'sortino_ratio', label: 'Sortino Ratio' },
  { key: 'piotroski_score_adj', label: 'Piotroski (salud financiera)' },
  { key: 'analyst_upside', label: 'Upside de analistas' },
  { key: 'dividend_growth_streak', label: 'Crecimiento de dividendos' },
];

let cacheUniverso = [];
let cachePrecios = [];
let cacheTablaCartera = [];
let arbolSectoresCache = {};
let filtroCartera = { sector: 'Todos', industry: 'Todas', rating: 'Todos', busqueda: '' };
let seleccionCarteraMap = {};
let metodoSeleccionado = null;
let ordenActivo = { columna: null, direccion: 'asc' };
let kpisSugeridorElegidos = new Set();

// ===== SUGERIDOR: chips en vez de checkbox =====
function pintarSelectorKpisSugeridor_() {
  const cont = document.getElementById('kpis-sugeridor');
  cont.innerHTML = KPIS_SUGERIDOR.map(k => `
    <button type="button" class="chip-kpi" data-kpi="${k.key}">${k.label}</button>
  `).join('');

  cont.querySelectorAll('.chip-kpi').forEach(chip => {
    chip.addEventListener('click', () => {
      const kpi = chip.dataset.kpi;
      if (kpisSugeridorElegidos.has(kpi)) {
        kpisSugeridorElegidos.delete(kpi);
        chip.classList.remove('activo');
      } else {
        kpisSugeridorElegidos.add(kpi);
        chip.classList.add('activo');
      }
    });
  });
}

function ejecutarSugerencia_() {
  if (kpisSugeridorElegidos.size === 0) {
    alert('Elegí al menos un KPI para basar la sugerencia.');
    return;
  }
  const nActivos = Math.min(MAX_CARTERA, Math.max(2, Number(document.getElementById('sugeridor-n-activos').value) || 10));

  try {
    const sugeridos = sugerirCartera(cacheUniverso, Array.from(kpisSugeridorElegidos), nActivos);
    seleccionCarteraMap = {};
    sugeridos.forEach(r => { seleccionCarteraMap[r.ticker] = true; });
    renderizarTablaCarteraOrdenada();
    document.getElementById('resultado-cartera').innerHTML = `
      <div class="card" style="border-left:4px solid var(--azul-claro)">
        <p>✅ Se preseleccionaron ${sugeridos.length} activos diversificados entre
        ${new Set(sugeridos.map(s => s.sector)).size} sectores, priorizando: ${Array.from(kpisSugeridorElegidos).join(', ')}.
        Revisá la selección abajo y elegí un método de ponderación para calcular la cartera.</p>
      </div>
    `;
  } catch (err) {
    alert(err.message);
  }
}

// ===== FILTROS tipo Screener (sector/industria dependientes + rating + busqueda) =====
function construirArbolSectorIndustria_(lista) {
  const arbol = {};
  lista.forEach(r => {
    const sector = r.sector || 'Sin sector';
    const industria = r.industry || 'Sin industria';
    if (!arbol[sector]) arbol[sector] = new Set();
    arbol[sector].add(industria);
  });
  const resultado = {};
  Object.keys(arbol).sort().forEach(s => { resultado[s] = Array.from(arbol[s]).sort(); });
  return resultado;
}

function poblarSelectsFiltroCartera_() {
  const selectSector = document.getElementById('cartera-filtro-sector');
  selectSector.innerHTML = '<option value="Todos">Todos los sectores</option>' +
    Object.keys(arbolSectoresCache).sort().map(s => `<option value="${s}">${s}</option>`).join('');
  actualizarOpcionesIndustriaCartera_('Todos');
}

function actualizarOpcionesIndustriaCartera_(sectorSeleccionado) {
  const selectIndustry = document.getElementById('cartera-filtro-industry');
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

function aplicarFiltrosCartera_() {
  let resultado = [...cacheUniverso];

  if (filtroCartera.sector !== 'Todos') resultado = resultado.filter(r => r.sector === filtroCartera.sector);
  if (filtroCartera.industry !== 'Todas') resultado = resultado.filter(r => r.industry === filtroCartera.industry);
  if (filtroCartera.rating !== 'Todos') resultado = resultado.filter(r => r.rating === filtroCartera.rating);
  if (filtroCartera.busqueda) {
    const q = filtroCartera.busqueda.toUpperCase();
    resultado = resultado.filter(r =>
      (r.ticker || '').toUpperCase().includes(q) ||
      (r.shortName || '').toUpperCase().includes(q)
    );
  }

  cacheTablaCartera = resultado;
  renderizarTablaCarteraOrdenada();
}

// ===== TABLA ORDENABLE =====
function ordenarTablaCartera_(columna) {
  if (ordenActivo.columna === columna) {
    ordenActivo.direccion = ordenActivo.direccion === 'asc' ? 'desc' : 'asc';
  } else {
    ordenActivo.columna = columna;
    ordenActivo.direccion = 'asc';
  }
  renderizarTablaCarteraOrdenada();
}

function renderizarTablaCarteraOrdenada() {
  let lista = [...cacheTablaCartera];

  if (ordenActivo.columna) {
    const col = ordenActivo.columna;
    const dir = ordenActivo.direccion === 'asc' ? 1 : -1;
    lista.sort((a, b) => {
      let va = a[col], vb = b[col];
      if (va === null || va === undefined) va = typeof vb === 'number' ? -Infinity : '';
      if (vb === null || vb === undefined) vb = typeof va === 'number' ? -Infinity : '';
      if (typeof va === 'string') va = va.toUpperCase();
      if (typeof vb === 'string') vb = vb.toUpperCase();
      if (va < vb) return -1 * dir;
      if (va > vb) return 1 * dir;
      return 0;
    });

    document.querySelectorAll('[id^="flecha-orden-"]').forEach(el => { el.textContent = ''; });
    const flechaEl = document.getElementById('flecha-orden-' + col);
    if (flechaEl) flechaEl.textContent = ordenActivo.direccion === 'asc' ? '▲' : '▼';
  }

  const body = document.getElementById('tabla-seleccion-cartera-body');

  if (lista.length === 0) {
    body.innerHTML = '<tr><td colspan="7" style="text-align:center;color:var(--texto-secundario);padding:20px">No hay activos que coincidan con estos filtros.</td></tr>';
    actualizarContadorSeleccion_();
    return;
  }

  body.innerHTML = lista.map(t => {
    const seleccionado = !!seleccionCarteraMap[t.ticker];
    return `
      <tr class="${seleccionado ? 'seleccionada' : ''}">
        <td class="fila-checkbox"><input type="checkbox" data-ticker="${escapeHtml(t.ticker)}" ${seleccionado ? 'checked' : ''}></td>
        <td><strong>${escapeHtml(t.ticker)}</strong></td>
        <td>${escapeHtml(t.shortName)}</td>
        <td>${escapeHtml(t.sector)}</td>
        <td>${escapeHtml(t.industry)}</td>
        <td><span class="badge ${claseBadge(t.rating)}">${escapeHtml(t.rating)}</span></td>
        <td>${(t.score_FINAL_adj || 0).toFixed(2)}</td>
      </tr>
    `;
  }).join('');

  body.querySelectorAll('input[type="checkbox"]').forEach(chk => {
    chk.addEventListener('change', (e) => toggleSeleccionCartera_(e.target.dataset.ticker, e.target.checked));
  });

  actualizarContadorSeleccion_();
}

function toggleSeleccionCartera_(ticker, marcado) {
  if (marcado) {
    if (Object.keys(seleccionCarteraMap).length >= MAX_CARTERA) {
      alert(`Máximo ${MAX_CARTERA} activos por cartera.`);
      renderizarTablaCarteraOrdenada();
      return;
    }
    seleccionCarteraMap[ticker] = true;
  } else {
    delete seleccionCarteraMap[ticker];
  }
  actualizarContadorSeleccion_();
  if (metodoSeleccionado === 'customizable') pintarTablaPesosManuales_();
}

function actualizarContadorSeleccion_() {
  const el = document.getElementById('contador-seleccionados');
  if (el) el.textContent = Object.keys(seleccionCarteraMap).length;
}

function obtenerSeleccionArray_() {
  return Object.keys(seleccionCarteraMap);
}

// ===== METODO DE PONDERACION (fix: ahora son <button>, con estado visible claro) =====
function seleccionarMetodo_(metodo) {
  metodoSeleccionado = metodo;
  document.querySelectorAll('.metodo-btn').forEach(btn => {
    btn.classList.toggle('activo', btn.dataset.metodo === metodo);
  });

  const tablaPesos = document.getElementById('tabla-pesos-manuales');
  if (metodo === 'customizable') {
    tablaPesos.classList.remove('oculto');
    pintarTablaPesosManuales_();
  } else {
    tablaPesos.classList.add('oculto');
  }
}

function pintarTablaPesosManuales_() {
  const cont = document.getElementById('tabla-pesos-manuales');
  const tickers = obtenerSeleccionArray_();
  if (tickers.length === 0) {
    cont.innerHTML = '<p style="color:var(--texto-secundario)">Seleccioná activos primero.</p>';
    return;
  }
  const pesoSugerido = (100 / tickers.length).toFixed(1);
  cont.innerHTML = `
    <h4 style="margin:14px 0 6px">Asigná el % de cada activo</h4>
    ${tickers.map(tk => `
      <div class="tabla-pesos-row">
        <span>${escapeHtml(tk)}</span>
        <input type="number" class="peso-manual-input" data-ticker="${escapeHtml(tk)}" value="${pesoSugerido}" min="0" max="100" step="0.1">
      </div>
    `).join('')}
    <div id="suma-pesos" class="suma-pesos"></div>
  `;
  cont.querySelectorAll('.peso-manual-input').forEach(inp => inp.addEventListener('input', actualizarSumaPesos_));
  actualizarSumaPesos_();
}

function actualizarSumaPesos_() {
  const inputs = document.querySelectorAll('.peso-manual-input');
  let suma = 0;
  inputs.forEach(i => suma += Number(i.value) || 0);
  const cont = document.getElementById('suma-pesos');
  const ok = Math.abs(suma - 100) < 0.5;
  cont.textContent = `Suma actual: ${suma.toFixed(1)}% ${ok ? '✅' : '(debe sumar 100%)'}`;
  cont.className = 'suma-pesos ' + (ok ? 'ok' : 'error');
}

// ===== CALCULO FINAL =====
function calcularCarteraUI_() {
  const tickers = obtenerSeleccionArray_();
  if (tickers.length === 0) { alert('Seleccioná al menos un activo.'); return; }
  if (!metodoSeleccionado) { alert('Elegí un método de ponderación.'); return; }

  const monto = Number(document.getElementById('monto-total').value);
  if (!monto || monto <= 0) { alert('Ingresá un monto válido a invertir.'); return; }

  let pesosManuales = null;
  if (metodoSeleccionado === 'customizable') {
    pesosManuales = {};
    document.querySelectorAll('.peso-manual-input').forEach(i => { pesosManuales[i.dataset.ticker] = Number(i.value); });
    const suma = Object.values(pesosManuales).reduce((a, b) => a + b, 0);
    if (Math.abs(suma - 100) > 0.5) {
      alert(`Los porcentajes deben sumar 100%. Suma actual: ${suma.toFixed(1)}%`);
      return;
    }
  }

  const seleccionInfo = tickers.map(t => cacheUniverso.find(r => r.ticker === t)).filter(Boolean);

  const btn = document.getElementById('btn-calcular-cartera');
  btn.disabled = true;
  btn.textContent = 'Calculando...';
  document.getElementById('resultado-cartera').innerHTML = `<div class="skeleton skeleton-row" style="height:260px;margin-top:20px"></div>`;

  setTimeout(() => {
    try {
      const resultado = calcularCartera(seleccionInfo, monto, metodoSeleccionado, pesosManuales, cachePrecios);
      pintarResultadoCartera_(resultado);
    } catch (err) {
      document.getElementById('resultado-cartera').innerHTML = `<p style="color:var(--rojo)">Error: ${err.message}</p>`;
    } finally {
      btn.disabled = false;
      btn.textContent = 'Calcular cartera';
    }
  }, 0);
}

function pintarResultadoCartera_(res) {
  const r = res.resumen;
  const activos = res.detalleActivos;

  const corr = r.correlacionVsMercado;
  let lecturaCorr = 'Sin dato suficiente';
  if (corr !== null) {
    if (corr > 0.7) lecturaCorr = 'Se mueve muy parecido al mercado general (canasta equal-weight del universo)';
    else if (corr > 0.3) lecturaCorr = 'Se mueve moderadamente parecido al mercado';
    else if (corr > -0.3) lecturaCorr = 'Poca relación con el mercado general';
    else lecturaCorr = 'Tiende a moverse en sentido contrario al mercado';
  }

  document.getElementById('resultado-cartera').innerHTML = `
    <div class="card">
      <h3>Resumen de tu cartera (método: ${escapeHtml(r.metodo)})</h3>
      <div class="resumen-cartera-grid">
        <div class="kpi-card">
          <div class="kpi-valor">${r.indiceCalidadFundamental.toFixed(2)} <span style="font-size:0.9rem">/10</span></div>
          <div class="kpi-label">Índice de Calidad Fundamental ponderado</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-valor">${flechaRendimiento(r.rendimientoHistoricoPonderado)}</div>
          <div class="kpi-label">Rendimiento histórico ponderado (no es proyección)</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-valor">${r.betaCartera.toFixed(2)}</div>
          <div class="kpi-label">Beta de cartera (sensibilidad al mercado)</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-valor">${r.sectoresUnicos} / ${r.industriasUnicas}</div>
          <div class="kpi-label">Sectores / Industrias representados</div>
        </div>
      </div>

      <h4>Riesgo: el efecto real de diversificar</h4>
      <div class="comparativa-riesgo">
        <div class="comparativa-item">
          <div class="comparativa-valor" style="color:var(--rojo)">${r.volatilidadSimplePonderada.toFixed(1)}%</div>
          <div class="kpi-label">Riesgo SIN efecto de diversificación (suma simple)</div>
        </div>
        <div style="font-size:1.5rem">→</div>
        <div class="comparativa-item">
          <div class="comparativa-valor" style="color:var(--verde)">${r.volatilidadCarteraAnualizada.toFixed(1)}%</div>
          <div class="kpi-label">Riesgo REAL de tu cartera (con covarianza)</div>
        </div>
      </div>

      <h4 style="margin-top:16px">Comparación vs. mercado general</h4>
      <p>Correlación: <strong>${corr !== null ? corr.toFixed(2) : 'N/D'}</strong> — ${lecturaCorr}</p>
    </div>

    <div class="card">
      <h3>Distribución de tu cartera</h3>
      <p style="color:var(--texto-secundario);font-size:0.85rem">Anillo externo: sector · Anillo interno: industria</p>
      <div style="max-width:420px;margin:0 auto"><canvas id="donut-cartera" height="320"></canvas></div>
    </div>

    <div class="card">
      <h3>Detalle por activo</h3>
      <table class="tabla-activos-cartera">
        <thead>
          <tr><th>Ticker</th><th>Sector / Industria</th><th>Peso</th><th>Monto</th><th>Rating</th><th>Volatilidad</th><th>Rend. YTD</th><th>Max Drawdown</th></tr>
        </thead>
        <tbody>
          ${activos.map(a => `
            <tr>
              <td><strong>${escapeHtml(a.ticker)}</strong><br><span style="font-size:0.75rem;color:var(--texto-secundario)">${escapeHtml(a.shortName)}</span></td>
              <td style="font-size:0.8rem">${escapeHtml(a.sector)}<br>${escapeHtml(a.industry)}</td>
              <td>${(a.peso * 100).toFixed(1)}%</td>
              <td>$${a.montoAsignado.toFixed(2)}</td>
              <td><span class="badge ${claseBadge(a.rating)}">${escapeHtml(a.rating)}</span></td>
              <td>${a.volatilidad_anualizada !== null ? a.volatilidad_anualizada.toFixed(1) + '%' : 'N/D'}</td>
              <td>${flechaRendimiento(a.rendimiento_ytd)}</td>
              <td style="color:var(--rojo)">${a.max_drawdown !== null ? a.max_drawdown.toFixed(1) + '%' : 'N/D'}</td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>
  `;
  pintarDonutsCartera_(activos);
}

const PALETA_DONUT = ['#2649B2', '#4A74F3', '#8E7DE3', '#9D5CE6', '#D4D9F0', '#6C8BE0', '#B55CE6'];
let chartDonutCartera = null;

function pintarDonutsCartera_(activos) {
  const gruposSector = {};
  activos.forEach(a => { gruposSector[a.sector] = (gruposSector[a.sector] || 0) + a.peso; });

  const sectoresOrdenados = Object.keys(gruposSector);
  const industriaData = [], industriaLabels = [], industriaColores = [];

  sectoresOrdenados.forEach((sector, idxSector) => {
    const industriasDeEsteSector = {};
    activos.filter(a => a.sector === sector).forEach(a => {
      industriasDeEsteSector[a.industry] = (industriasDeEsteSector[a.industry] || 0) + a.peso;
    });
    Object.keys(industriasDeEsteSector).forEach(ind => {
      industriaLabels.push(`${ind} (${sector})`);
      industriaData.push((industriasDeEsteSector[ind] * 100).toFixed(1));
      industriaColores.push(PALETA_DONUT[idxSector % PALETA_DONUT.length]);
    });
  });

  if (chartDonutCartera) chartDonutCartera.destroy();

  chartDonutCartera = new Chart(document.getElementById('donut-cartera'), {
    type: 'doughnut',
    data: {
      labels: [...sectoresOrdenados, ...industriaLabels],
      datasets: [
        { label: 'Sector', data: Object.values(gruposSector).map(v => (v * 100).toFixed(1)), backgroundColor: sectoresOrdenados.map((_, i) => PALETA_DONUT[i % PALETA_DONUT.length]), radius: '90%', weight: 1 },
        { label: 'Industria', data: industriaData, backgroundColor: industriaColores, radius: '100%', weight: 1 }
      ]
    },
    options: {
      plugins: {
        legend: { position: 'bottom', labels: { boxWidth: 12, font: { size: 10 } } },
        tooltip: { callbacks: { label: ctx => `${ctx.label}: ${ctx.raw}%` } }
      }
    }
  });
}

export function inicializarCartera({ screener, precios }) {
  cacheUniverso = screener;
  cachePrecios = precios;
  cacheTablaCartera = screener;
  arbolSectoresCache = construirArbolSectorIndustria_(screener);

  pintarSelectorKpisSugeridor_();
  document.getElementById('btn-sugerir-cartera').addEventListener('click', ejecutarSugerencia_);

  poblarSelectsFiltroCartera_();
  document.getElementById('cartera-filtro-sector').addEventListener('change', (e) => {
    filtroCartera.sector = e.target.value;
    filtroCartera.industry = 'Todas';
    actualizarOpcionesIndustriaCartera_(e.target.value);
    aplicarFiltrosCartera_();
  });
  document.getElementById('cartera-filtro-industry').addEventListener('change', (e) => {
    filtroCartera.industry = e.target.value;
    aplicarFiltrosCartera_();
  });
  document.getElementById('cartera-filtro-rating').addEventListener('change', (e) => {
    filtroCartera.rating = e.target.value;
    aplicarFiltrosCartera_();
  });
  document.getElementById('buscador-tabla-cartera').addEventListener('input', (e) => {
    filtroCartera.busqueda = e.target.value;
    aplicarFiltrosCartera_();
  });

  document.querySelectorAll('.th-ordenable').forEach(th => {
    th.addEventListener('click', () => ordenarTablaCartera_(th.dataset.col));
  });

  document.querySelectorAll('.metodo-btn').forEach(btn => {
    btn.addEventListener('click', () => seleccionarMetodo_(btn.dataset.metodo));
  });

  document.getElementById('btn-calcular-cartera').addEventListener('click', calcularCarteraUI_);
  document.getElementById('btn-volver-home-cartera').addEventListener('click', () => {
    document.querySelectorAll('.vista').forEach(v => v.classList.add('oculto'));
    document.getElementById('vista-home').classList.remove('oculto');
  });

  renderizarTablaCarteraOrdenada();
}
