
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

export function filaTicker(row) {
  const score  = row.score_FINAL_adj !== null && row.score_FINAL_adj !== undefined ? row.score_FINAL_adj : 0;
  const precio = row.lastPrice !== null && row.lastPrice !== undefined ? '$' + Number(row.lastPrice).toFixed(2) : 'N/D';

  const ticker    = escapeHtml(row.ticker);
  const shortName = escapeHtml(row.shortName);
  const sector    = escapeHtml(row.sector);
  const industry  = escapeHtml(row.industry);
  const rating    = escapeHtml(row.rating);

  return `
    <div class="ranking-row" data-ticker="${ticker}">
      <div class="rank-number">#${row.rank ?? '-'}</div>
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
