
export function calcularRetornosDiarios(precios) {
  const retornos = [];
  for (let i = 1; i < precios.length; i++) {
    const anterior = precios[i - 1];
    const actual = precios[i];
    if (anterior && actual && anterior !== 0) {
      retornos.push((actual - anterior) / anterior);
    }
  }
  return retornos;
}

export function media(arr) {
  if (arr.length === 0) return 0;
  return arr.reduce((a, b) => a + b, 0) / arr.length;
}

export function desviacionEstandar(arr) {
  if (arr.length < 2) return null;
  const m = media(arr);
  const varianza = arr.reduce((sum, x) => sum + Math.pow(x - m, 2), 0) / (arr.length - 1);
  return Math.sqrt(varianza);
}

export function covarianza(arrA, arrB) {
  const n = Math.min(arrA.length, arrB.length);
  if (n < 2) return null;
  const mA = media(arrA.slice(0, n));
  const mB = media(arrB.slice(0, n));
  let suma = 0;
  for (let i = 0; i < n; i++) suma += (arrA[i] - mA) * (arrB[i] - mB);
  return suma / (n - 1);
}

export function correlacion(arrA, arrB) {
  const cov = covarianza(arrA, arrB);
  const sdA = desviacionEstandar(arrA);
  const sdB = desviacionEstandar(arrB);
  if (cov === null || !sdA || !sdB) return null;
  return cov / (sdA * sdB);
}

// El resto (calcularKpisPrecio, calcularIndiceSinteticoMercado, calcularCartera)
// se porta igual: misma lógica, misma matemática, solo cambia de donde vienen los datos
// (ya no sheetToObjects_, sino el array ya cargado en memoria por data-loader.js)
