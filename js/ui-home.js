
export function inicializarHome({ screener }) {
  pintarKPIs(screener);
  pintarTop10(screener);
}

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

function pintarKPIs(screener) {
  const totalTickers = screener.length;

  const distribucionRating = {};
  let sumaScore = 0, contScore = 0, sumaPrecio = 0, contPrecio = 0;

  screener.forEach(row => {
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

  const scorePromedio = contScore > 0 ? sumaScore / contScore : 0;
  const precioPromedio = contPrecio > 0 ? sumaPrecio / contPrecio : 0;
  const buenas = distribucionRating['Buena'] || 0;
  const evitar = distribucionRating['Evitar'] || 0;

  document.getElementById('kpis-globales').innerHTML = `
    <div class="kpi-card">
      <div class="kpi-valor">${totalTickers}</div>
      <div class="kpi-label">Tickers analizados</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-valor">${scorePromedio.toFixed(2)}<span style="font-size:0.9rem;color:var(--texto-secundario)"> /10</span></div>
      <div class="kpi-label">Score promedio del mercado</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-valor">$${precioPromedio.toFixed(2)}</div>
      <div class="kpi-label">Precio promedio</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-valor" style="color:#1FAE68">${buenas}</div>
      <div class="kpi-label">Rating Buena</div>
    </div>
    <div class="kpi-card">
      <div class="kpi-valor" style="color:#E6483D">${evitar}</div>
      <div class="kpi-label">A evitar</div>
    </div>
  `;
}

function filaTicker(row) {
  const score = row.score_FINAL_adj !== null && row.score_FINAL_adj !== undefined ? row.score_FINAL_adj : 0;
  const precio = row.lastPrice !== null && row.lastPrice !== undefined ? '$' + Number(row.lastPrice).toFixed(2) : 'N/D';
  return `
    <div class="ranking-row">
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

function pintarTop10(screener) {
  const top10 = [...screener]
    .filter(r => r.score_FINAL_adj !== null && r.score_FINAL_adj !== undefined)
    .sort((a, b) => b.score_FINAL_adj - a.score_FINAL_adj)
    .slice(0, 10);

  document.getElementById('top10-container').innerHTML = top10.map(filaTicker).join('');
}
