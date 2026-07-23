
let cacheScreenerCompleto = [];
let arbolSectoresCache = {};
let filtroActivo = { sector: 'Todos', industry: 'Todas', rating: 'Todos', busqueda: '' };

function claseBadge(rating) {
  const mapa = {
    'Excelente': 'badge-excelente',
    'Buena': 'badge-buena',
    'Neutral': 'badge-neutral',
    'Débil': 'badge-debil',
    'Evitar': 'badge-evitar'
  };
  return mapa[rating] || 'badge-neutral';
}

function filaTicker(row) {
  const score = row.score_FINAL_adj !== null && row.score_FINAL_adj !== undefined ? row.score_FINAL_adj : 0;
  const precio = row.lastPrice !== null && row.lastPrice !== undefined ? '$' + Number(row.lastPrice).toFixed(2) : 'N/D';
  return `
    <div class="ranking-row" data-ticker="${row.ticker}">
      <div class="rank-number">#${row.rank}</div>
      <div class="ticker-cell">
        <div class="ticker-symbol">${row.ticker}</div>
        <div class="ticker-name">${row.shortName}</div>
        <div class="ticker-meta">${row.sector} · ${row.industry}</div>
      </div>
      <div class="precio-mini">${precio}</div>
      <div class="score-mobile-row">
        <div class="score-bar-bg"><div class="score-bar-fill" style="width:${score * 10}%"></div></div>
        <div class="score-valor">${score.toFixed(2)}</div>
      </div>
      <div class="badge ${claseBadge(row.rating)}">${row.rating}</div>
    </div>
  `;
}

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
  pintarTablaCompleta_(resultado);
}

function pintarTablaCompleta_(data) {
  const cont = document.getElementById('tabla-completa-container');
  cont.innerHTML = `<div class="ranking-list">${data.map(filaTicker).join('')}</div>`;

  cont.querySelectorAll('.ranking-row').forEach(row => {
    row.addEventListener('click', () => {
      const ticker = row.dataset.ticker;
      document.dispatchEvent(new CustomEvent('abrir-detalle-ticker', { detail: { ticker } }));
    });
  });
}

// ===== API PÚBLICA DEL MÓDULO =====
export function inicializarScreener({ screener }) {
  cacheScreenerCompleto = screener;
  arbolSectoresCache = construirArbolSectorIndustria_(screener);

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

// Se llama cada vez que el usuario entra a la vista completa (por si los filtros necesitan refrescarse)
export function mostrarVistaCompleta() {
  aplicarFiltros_();
}
