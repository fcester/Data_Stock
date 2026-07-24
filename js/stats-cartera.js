
import { agruparPreciosPorTicker } from './ui-common.js';

// ===== ALINEACION POR FECHA REAL (fix de la deuda tecnica identificada) =====
// En vez de comparar retornos por POSICION de array (asumiendo que todos los
// tickers cotizaron los mismos dias exactos), se alinea por FECHA real.
function alinearRetornosPorFecha_(preciosPorTicker, tickers, ventanaDias) {
  const mapaFechaValor = {}; // { fecha: { ticker: valor } }

  tickers.forEach(t => {
    const serie = (preciosPorTicker[t] || []).slice(-ventanaDias - 1); // +1 para poder calcular el primer retorno
    serie.forEach(p => {
      if (!mapaFechaValor[p.Date]) mapaFechaValor[p.Date] = {};
      mapaFechaValor[p.Date][t] = p.Value;
    });
  });

  const fechasOrdenadas = Object.keys(mapaFechaValor).sort((a, b) => new Date(a) - new Date(b));

  // Retornos diarios por ticker, calculados solo entre fechas CONSECUTIVAS reales
  // donde AMBOS dias tienen dato para ese ticker especifico.
  const retornosPorTicker = {};
  tickers.forEach(t => { retornosPorTicker[t] = []; });

  const fechasRetorno = [];
  for (let i = 1; i < fechasOrdenadas.length; i++) {
    const fechaAnt = fechasOrdenadas[i - 1];
    const fechaHoy = fechasOrdenadas[i];
    let algunTickerTuvoRetorno = false;

    tickers.forEach(t => {
      const vAnt = mapaFechaValor[fechaAnt][t];
      const vHoy = mapaFechaValor[fechaHoy][t];
      if (vAnt !== undefined && vHoy !== undefined && vAnt !== 0) {
        retornosPorTicker[t].push((vHoy - vAnt) / vAnt);
        algunTickerTuvoRetorno = true;
      } else {
        retornosPorTicker[t].push(null); // hueco explicito, no se inventa dato
      }
    });

    if (algunTickerTuvoRetorno) fechasRetorno.push(fechaHoy);
  }

  return { retornosPorTicker, fechasRetorno };
}

function media_(arr) {
  const validos = arr.filter(x => x !== null && x !== undefined && !Number.isNaN(x));
  if (validos.length === 0) return 0;
  return validos.reduce((a, b) => a + b, 0) / validos.length;
}

function desviacionEstandar_(arr) {
  const validos = arr.filter(x => x !== null && x !== undefined && !Number.isNaN(x));
  if (validos.length < 2) return null;
  const m = media_(validos);
  const varianza = validos.reduce((sum, x) => sum + Math.pow(x - m, 2), 0) / (validos.length - 1);
  return Math.sqrt(varianza);
}

// Covarianza entre dos series de retornos YA alineadas por fecha (mismo indice = misma fecha).
// Ignora pares donde cualquiera de los dos sea null (hueco por falta de dato ese dia).
function covarianzaAlineada_(retA, retB) {
  const pares = [];
  for (let i = 0; i < Math.min(retA.length, retB.length); i++) {
    if (retA[i] !== null && retB[i] !== null) pares.push([retA[i], retB[i]]);
  }
  if (pares.length < 2) return null;
  const mA = media_(pares.map(p => p[0]));
  const mB = media_(pares.map(p => p[1]));
  let suma = 0;
  pares.forEach(([a, b]) => { suma += (a - mA) * (b - mB); });
  return suma / (pares.length - 1);
}

function correlacionAlineada_(retA, retB) {
  const cov = covarianzaAlineada_(retA, retB);
  const sdA = desviacionEstandar_(retA);
  const sdB = desviacionEstandar_(retB);
  if (cov === null || !sdA || !sdB) return null;
  return cov / (sdA * sdB);
}

function calcularKpisPrecio_(serieCompleta, ventanaDias) {
  const serie = serieCompleta.slice(-ventanaDias);
  const valores = serie.map(p => p.Value);
  if (valores.length < 2) {
    return { rendimiento_ytd: null, volatilidad_anualizada: null, max_drawdown: null };
  }
  const actual = valores[valores.length - 1];
  const anioActual = new Date(serie[serie.length - 1].Date).getFullYear();
  const primerDelAnio = serie.find(p => new Date(p.Date).getFullYear() === anioActual);
  const valorYtd = primerDelAnio ? primerDelAnio.Value : valores[0];

  const retornos = [];
  for (let i = 1; i < valores.length; i++) {
    if (valores[i - 1]) retornos.push((valores[i] - valores[i - 1]) / valores[i - 1]);
  }
  const sd = desviacionEstandar_(retornos);
  const volatilidadAnualizada = sd !== null ? sd * Math.sqrt(252) * 100 : null;

  let pico = valores[0];
  let maxDD = 0;
  valores.forEach(v => {
    if (v > pico) pico = v;
    const dd = (v - pico) / pico;
    if (dd < maxDD) maxDD = dd;
  });

  return {
    rendimiento_ytd: valorYtd ? ((actual - valorYtd) / valorYtd) * 100 : null,
    volatilidad_anualizada: volatilidadAnualizada,
    max_drawdown: maxDD * 100
  };
}

function calcularIndiceSinteticoMercado_(retornosPorTicker, tickers) {
  const largoMinimo = Math.min(...tickers.map(t => retornosPorTicker[t].length));
  const indice = [];
  for (let i = 0; i < largoMinimo; i++) {
    const valoresDelDia = tickers.map(t => retornosPorTicker[t][i]).filter(v => v !== null);
    indice.push(valoresDelDia.length > 0 ? media_(valoresDelDia) : null);
  }
  return indice;
}

const VENTANA_CARTERA_DIAS = 120;
const MAX_TICKERS_CARTERA = 15;

export function calcularCartera(seleccion, montoTotal, metodo, pesosManualesOpcional, precios) {
  if (!seleccion || seleccion.length === 0) throw new Error('Debes seleccionar al menos un ticker.');
  if (seleccion.length > MAX_TICKERS_CARTERA) throw new Error(`Máximo ${MAX_TICKERS_CARTERA} tickers por cartera.`);

  const preciosPorTicker = agruparPreciosPorTicker(precios);
  const tickers = seleccion.map(t => t.ticker);

  let pesos = {};
  if (metodo === 'diversificacion') {
    const pesoIgual = 1 / seleccion.length;
    seleccion.forEach(t => pesos[t.ticker] = pesoIgual);

  } else if (metodo === 'equilibrado') {
    const sectores = {};
    seleccion.forEach(t => {
      if (!sectores[t.sector]) sectores[t.sector] = {};
      if (!sectores[t.sector][t.industry]) sectores[t.sector][t.industry] = [];
      sectores[t.sector][t.industry].push(t.ticker);
    });
    const nSectores = Object.keys(sectores).length;
    const pesoPorSector = 1 / nSectores;
    Object.keys(sectores).forEach(sector => {
      const industrias = sectores[sector];
      const nIndustrias = Object.keys(industrias).length;
      const pesoPorIndustria = pesoPorSector / nIndustrias;
      Object.keys(industrias).forEach(industria => {
        const tickersDeIndustria = industrias[industria];
        const pesoPorTicker = pesoPorIndustria / tickersDeIndustria.length;
        tickersDeIndustria.forEach(tk => pesos[tk] = pesoPorTicker);
      });
    });

  } else if (metodo === 'customizable') {
    if (!pesosManualesOpcional) throw new Error('Faltan los pesos manuales.');
    const sumaPct = Object.values(pesosManualesOpcional).reduce((a, b) => a + Number(b), 0);
    if (Math.abs(sumaPct - 100) > 0.5) {
      throw new Error(`Los porcentajes deben sumar 100%. Suma actual: ${sumaPct.toFixed(1)}%`);
    }
    Object.keys(pesosManualesOpcional).forEach(tk => {
      pesos[tk] = Number(pesosManualesOpcional[tk]) / 100;
    });
  } else {
    throw new Error(`Método de ponderación no reconocido: ${metodo}`);
  }

  const { retornosPorTicker } = alinearRetornosPorFecha_(preciosPorTicker, tickers, VENTANA_CARTERA_DIAS);

  const detalleActivos = seleccion.map(t => {
    const serie = preciosPorTicker[t.ticker] || [];
    const kpis = calcularKpisPrecio_(serie, VENTANA_CARTERA_DIAS);
    const peso = pesos[t.ticker];
    return {
      ticker: t.ticker,
      shortName: t.shortName,
      sector: t.sector,
      industry: t.industry,
      rating: t.rating,
      score_FINAL_adj: t.score_FINAL_adj,
      beta: t.beta,
      sharpe_ratio: t.sharpe_ratio,
      piotroski_score_adj: t.piotroski_score_adj,
      peso: peso,
      montoAsignado: montoTotal * peso,
      volatilidad_anualizada: kpis.volatilidad_anualizada,
      rendimiento_ytd: kpis.rendimiento_ytd,
      max_drawdown: kpis.max_drawdown,
    };
  });

  const n = detalleActivos.length;
  let varianzaCartera = 0;
  for (let i = 0; i < n; i++) {
    for (let j = 0; j < n; j++) {
      const retI = retornosPorTicker[detalleActivos[i].ticker];
      const retJ = retornosPorTicker[detalleActivos[j].ticker];
      const cov = covarianzaAlineada_(retI, retJ) || 0;
      varianzaCartera += detalleActivos[i].peso * detalleActivos[j].peso * cov;
    }
  }
  const volatilidadCarteraAnualizada = Math.sqrt(Math.max(varianzaCartera, 0)) * Math.sqrt(252) * 100;
  const volatilidadSimplePonderada = detalleActivos.reduce((sum, a) => sum + (a.peso * (a.volatilidad_anualizada || 0)), 0);
  const betaCartera = detalleActivos.reduce((sum, a) => sum + a.peso * (a.beta || 1), 0);
  const indiceCalidadFundamental = detalleActivos.reduce((sum, a) => sum + a.peso * (a.score_FINAL_adj || 0), 0);
  const rendimientoHistoricoPonderado = detalleActivos.reduce((sum, a) => sum + a.peso * (a.rendimiento_ytd || 0), 0);
  const sectoresUnicos = new Set(detalleActivos.map(a => a.sector)).size;
  const industriasUnicas = new Set(detalleActivos.map(a => a.industry)).size;

  const indiceMercado = calcularIndiceSinteticoMercado_(retornosPorTicker, tickers);
  const largoMinimo = Math.min(...tickers.map(t => retornosPorTicker[t].length));
  const retornosCarteraPonderados = [];
  for (let i = 0; i < largoMinimo; i++) {
    let suma = 0, pesoTotal = 0;
    detalleActivos.forEach(a => {
      const ret = retornosPorTicker[a.ticker][i];
      if (ret !== null) { suma += a.peso * ret; pesoTotal += a.peso; }
    });
    retornosCarteraPonderados.push(pesoTotal > 0 ? suma : null);
  }
  const correlacionVsMercado = correlacionAlineada_(retornosCarteraPonderados, indiceMercado);

  return {
    detalleActivos,
    resumen: {
      montoTotal, metodo,
      volatilidadCarteraAnualizada,
      volatilidadSimplePonderada,
      betaCartera,
      indiceCalidadFundamental,
      rendimientoHistoricoPonderado,
      sectoresUnicos,
      industriasUnicas,
      correlacionVsMercado,
      ventanaDiasUsada: VENTANA_CARTERA_DIAS
    }
  };
}

// ===== SUGERIDOR DE CARTERA (feature nueva) =====
// Dado un universo, KPIs elegidos por el usuario, sector a excluir (opcional)
// y cantidad de activos deseada, arma una seleccion diversificada por sector
// priorizando -dentro de cada sector- a los mejores segun el score compuesto
// de los KPIs elegidos.
export function sugerirCartera(universo, kpisElegidos, nActivos) {
  if (!kpisElegidos || kpisElegidos.length === 0) {
    throw new Error('Elegí al menos un KPI para basar la sugerencia.');
  }

  const candidatos = universo.filter(r =>
    kpisElegidos.some(k => r[k] !== null && r[k] !== undefined && !Number.isNaN(r[k]))
  );

  // Percentil de cada KPI (mayor valor = mejor). Se calcula sobre los candidatos con dato.
  const percentiles = {};
  kpisElegidos.forEach(kpi => {
    const valores = candidatos
      .map(r => ({ ticker: r.ticker, valor: r[kpi] }))
      .filter(v => v.valor !== null && v.valor !== undefined && !Number.isNaN(v.valor))
      .sort((a, b) => a.valor - b.valor);

    const n = valores.length;
    valores.forEach((v, idx) => {
      if (!percentiles[v.ticker]) percentiles[v.ticker] = [];
      percentiles[v.ticker].push(n > 1 ? idx / (n - 1) : 1);
    });
  });

  const conScore = candidatos
    .filter(r => percentiles[r.ticker] && percentiles[r.ticker].length === kpisElegidos.length)
    .map(r => ({
      ...r,
      score_compuesto: percentiles[r.ticker].reduce((a, b) => a + b, 0) / percentiles[r.ticker].length
    }));

  const sectores = [...new Set(conScore.map(r => r.sector))];
  const nSectores = sectores.length;
  if (nSectores === 0) throw new Error('No hay suficientes datos para sugerir una cartera con estos KPIs.');

  const cupoPorSector = Math.max(1, Math.floor(nActivos / nSectores));
  let seleccion = [];

  sectores.forEach(sector => {
    const delSector = conScore
      .filter(r => r.sector === sector)
      .sort((a, b) => b.score_compuesto - a.score_compuesto)
      .slice(0, cupoPorSector);
    seleccion = seleccion.concat(delSector);
  });

  if (seleccion.length < nActivos) {
    const yaElegidos = new Set(seleccion.map(r => r.ticker));
    const restantes = conScore
      .filter(r => !yaElegidos.has(r.ticker))
      .sort((a, b) => b.score_compuesto - a.score_compuesto)
      .slice(0, nActivos - seleccion.length);
    seleccion = seleccion.concat(restantes);
  }

  return seleccion
    .sort((a, b) => b.score_compuesto - a.score_compuesto)
    .slice(0, nActivos);
}
