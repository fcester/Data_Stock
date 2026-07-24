
// ===== HELPERS COMPARTIDOS ENTRE MÓDULOS DE UI =====
// Centraliza funciones que antes estaban duplicadas en ui-home.js y ui-screener.js.
// Cualquier módulo nuevo (ui-detalle.js, ui-cartera.js) debe importar desde acá
// en vez de volver a copiar estas funciones.

// Escapa caracteres HTML peligrosos antes de insertar texto con innerHTML.
// Sin esto, un shortName/sector que viniera con < > " ' & podría inyectar HTML/JS.
export function escapeHtml(valor) {
  if (valor === null || valor === undefined) return '';
  const texto = String(valor);
  const mapa = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
  return texto.replace(/[&<>"']/g, (c) => mapa[c]);
}

export function claseBadge(rating) {
  const mapa = {
    'Excelente': 'badge-excelente',
    'Buena': 'badge-buena',
    'Neutral': 'badge-neutral',
    'Débil': 'badge-debil',
    'Evitar': 'badge-evitar'
  };
  return mapa[rating] || 'badge-neutral';
}

export function flechaRendimiento(valor) {
  if (valor === null || valor === undefined || Number.isNaN(valor)) {
    return '<span class="flecha-flat">→ Sin dato</span>';
  }
  if (valor > 0) return `<span class="flecha-up">↑ +${valor.toFixed(2)}%</span>`;
  if (valor < 0) return `<span class="flecha-down">↓ ${valor.toFixed(2)}%</span>`;
  return '<span class="flecha-flat">→ 0%</span>';
}

// Clamp defensivo 0-100: evita que un score fuera de rango rompa visualmente la barra
export function anchoBarraScore(score) {
  const valor = (score === null || score === undefined || Number.isNaN(score)) ? 0 : score;
  return Math.max(0, Math.min(100, valor * 10));
}



export function filaTicker(row, totalTickers = null) {
  const score  = row.score_FINAL_adj !== null && row.score_FINAL_adj !== undefined ? row.score_FINAL_adj : 0;
  const precio = row.lastPrice !== null && row.lastPrice !== undefined ? '$' + Number(row.lastPrice).toFixed(2) : 'N/D';

  const ticker    = escapeHtml(row.ticker);
  const shortName = escapeHtml(row.shortName);
  const sector    = escapeHtml(row.sector);
  const industry  = escapeHtml(row.industry);
  const rating    = escapeHtml(row.rating);

  const textoRank = totalTickers
    ? `#${row.rank ?? '-'} <span class="rank-total">/ ${totalTickers}</span>`
    : `#${row.rank ?? '-'}`;

  // Badge de vuelta en su posicion original: al final de la fila, como estaba antes.
  return `
    <div class="ranking-row" data-ticker="${ticker}">
      <div class="rank-number">${textoRank}</div>
      <div class="ticker-cell">
        <div class="ticker-symbol">${ticker}</div>
        <div class="ticker-name">${shortName}</div>
        <div class="ticker-meta">${sector} · ${industry}</div>
      </div>
      <div class="precio-mini">${precio}</div>
      <div class="score-mobile-row">
        <div class="score-bar-bg"><div class="score-bar-fill" style="width:${anchoBarraScore(score)}%"></div></div>
        <div class="score-valor">${score.toFixed(2)}</div>
      </div>
      <div class="badge ${claseBadge(row.rating)}">${rating}</div>
    </div>
  `;
}

export function interpretarScoreMercado(score) {
  if (score === null || score === undefined || Number.isNaN(score)) {
    return 'Sin datos suficientes para este segmento';
  }
  if (score >= 6.5) return 'Fundamentos sólidos en promedio: predominan activos bien valuados y rentables dentro de su sector';
  if (score >= 5)   return 'Fundamentos mixtos: combinación equilibrada de activos fuertes y débiles';
  if (score >= 3.5) return 'Fundamentos débiles en promedio: predominan activos con valuación, rentabilidad o momentum bajos';
  return 'Fundamentos muy débiles: la mayoría de los activos de este segmento puntúan bajo en el modelo';
}

export function calcularKpisAgregados(listaTickers) {
  const distribucionRating = {};
  let sumaScore = 0, contScore = 0, sumaPrecio = 0, contPrecio = 0;

  listaTickers.forEach(row => {
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

  return {
    total: listaTickers.length,
    scorePromedio: contScore > 0 ? sumaScore / contScore : null,
    precioPromedio: contPrecio > 0 ? sumaPrecio / contPrecio : null,
    buenas: distribucionRating['Buena'] || 0,
    evitar: distribucionRating['Evitar'] || 0,
  };
}

// Tooltip real: el texto explicativo esta OCULTO por defecto (ver CSS),
// y solo aparece como popup al pasar el mouse sobre el icono subrayado "ℹ Score promedio".
export function renderKpisGlobales(listaTickers) {
  const k = calcularKpisAgregados(listaTickers);
  const scoreTexto = k.scorePromedio !== null ? k.scorePromedio.toFixed(2) : 'N/D';
  const precioTexto = k.precioPromedio !== null ? '$' + k.precioPromedio.toFixed(2) : 'N/D';
  const interpretacion = interpretarScoreMercado(k.scorePromedio);

  return `
    <div class="kpi-card">
      <div class="kpi-valor">${k.total}</div>
      <div class="kpi-label">Tickers en este segmento</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-valor">${scoreTexto}<span style="font-size:0.9rem;color:var(--texto-secundario)"> /10</span></div>
      <div class="kpi-label">
        <span class="tooltip-info">Score promedio del segmento
          <span class="tooltip-texto">${interpretacion}</span>
        </span>
      </div>
    </div>
    <div class="kpi-card">
      <div class="kpi-valor">${precioTexto}</div>
      <div class="kpi-label">Precio promedio</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-valor" style="color:#1FAE68">${k.buenas}</div>
      <div class="kpi-label">Rating Buena</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-valor" style="color:#E6483D">${k.evitar}</div>
      <div class="kpi-label">A evitar</div>
    </div>
  `;
}

