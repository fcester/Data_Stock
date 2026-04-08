import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime
import os

# ─────────────────────────────────────────────
#  1. CONFIGURACIÓN
# ─────────────────────────────────────────────
tickers_df = pd.read_csv("Tickers.csv")
tickers = tickers_df["ticker"].dropna().tolist()
tickers_dict = {str(ticker): True for ticker in tickers_df["ticker"].dropna()}

# ─────────────────────────────────────────────
#  2. PRECIOS (últimos 5 días → último cierre)
# ─────────────────────────────────────────────
raw = yf.download(tickers, period="5d", interval="1d", auto_adjust=True, progress=False)
df = raw["Close"]

# Si solo hay un ticker yfinance devuelve Serie -> convertir a DataFrame
if isinstance(df, pd.Series):
    df = df.to_frame(name=tickers[0])

# Eliminar columnas (tickers) sin ningun dato (delisted, etc.)
df = df.dropna(axis=1, how="all")
df = df.tail(1)

file_name = "Actual_Stock.csv"
if not os.path.exists(file_name) or os.stat(file_name).st_size == 0:
    df.to_csv(file_name, index=True)
    print("📊 Archivo de precios creado.")
else:
    df_existente = pd.read_csv(file_name, index_col="Date")
    df_existente.index = pd.to_datetime(df_existente.index)
    fecha_nueva = df.index[0]
    if fecha_nueva not in df_existente.index:
        df_final = pd.concat([df_existente, df])
        df_final.to_csv(file_name)
        print("📈 Precios actualizados.")

# ─────────────────────────────────────────────
#  3. ATRIBUTOS FUNDAMENTALES A EXTRAER
# ─────────────────────────────────────────────
ATTRIBUTES = [
    # Identificación
    "shortName", "sector", "industry", "country", "fullTimeEmployees",

    # Valuación
    "marketCap", "enterpriseValue",
    "trailingPE", "forwardPE", "trailingPegRatio",
    "priceToBook", "priceToSalesTrailing12Months",
    "enterpriseToEbitda", "enterpriseToRevenue",

    # Rentabilidad
    "returnOnEquity", "returnOnAssets",
    "profitMargins", "grossMargins", "operatingMargins", "ebitdaMargins",

    # Crecimiento
    "revenueGrowth", "earningsGrowth", "earningsQuarterlyGrowth",
    "revenuePerShare", "bookValue",

    # Solidez financiera
    "debtToEquity", "currentRatio", "quickRatio",
    "totalCash", "totalCashPerShare", "totalDebt",
    "freeCashflow", "operatingCashflow",

    # Resultados
    "totalRevenue", "grossProfits", "ebitda",
    "trailingEps", "forwardEps",

    # Dividendos
    "dividendYield", "dividendRate", "payoutRatio",
    "fiveYearAvgDividendYield",

    # Mercado / Riesgo
    "beta", "shortRatio", "shortPercentOfFloat",
    "52WeekChange", "SandP52WeekChange",
    "fiftyTwoWeekHigh", "fiftyTwoWeekLow",
    "fiftyDayAverage", "twoHundredDayAverage",

    # Analistas
    "targetMeanPrice", "targetHighPrice", "targetLowPrice",
    "recommendationMean", "numberOfAnalystOpinions",
]

# ─────────────────────────────────────────────
#  4. DESCARGA DE FUNDAMENTALES
# ─────────────────────────────────────────────
dow_stats = {}
print("\n⏳ Descargando fundamentales...")
for ticker_look in tickers_dict:
    try:
        temp = yf.Ticker(ticker_look).info
        filtered_data = {attr: temp.get(attr) for attr in ATTRIBUTES}
        dow_stats[ticker_look] = pd.DataFrame([filtered_data])
    except Exception as e:
        print(f"  ⚠️  Error en {ticker_look}: {e}")

all_stats = pd.concat(dow_stats, keys=dow_stats.keys(), names=["ticker", "Index"])
all_stats = all_stats.reset_index(level="Index", drop=True).reset_index()

# ─────────────────────────────────────────────
#  5. LIMPIEZA DE TIPOS
# ─────────────────────────────────────────────
numeric_cols = [c for c in all_stats.columns if c not in
                ["ticker", "shortName", "sector", "industry", "country"]]
all_stats[numeric_cols] = all_stats[numeric_cols].apply(pd.to_numeric, errors="coerce")

# ─────────────────────────────────────────────
#  6. COLUMNAS DERIVADAS ÚTILES PARA PBI
# ─────────────────────────────────────────────
# Último precio: df tiene fechas como índice y tickers como columnas
# → transponemos para obtener un DataFrame con ticker como índice
last_prices = df.iloc[-1]  # Series: índice = tickers, valores = precios
last_prices_df = last_prices.reset_index()
last_prices_df.columns = ["ticker", "lastPrice"]

all_stats = all_stats.merge(last_prices_df, on="ticker", how="left")

all_stats["upsidePotential_pct"] = (
    (all_stats["targetMeanPrice"] - all_stats["lastPrice"]) / all_stats["lastPrice"] * 100
)
all_stats["distanceTo52wHigh_pct"] = (
    (all_stats["fiftyTwoWeekHigh"] - all_stats["lastPrice"]) / all_stats["lastPrice"] * 100
)
all_stats["distanceTo52wLow_pct"] = (
    (all_stats["lastPrice"] - all_stats["fiftyTwoWeekLow"]) / all_stats["lastPrice"] * 100
)
all_stats["priceVs50dMA"] = all_stats["lastPrice"] / all_stats["fiftyDayAverage"] - 1
all_stats["priceVs200dMA"] = all_stats["lastPrice"] / all_stats["twoHundredDayAverage"] - 1
all_stats["extractedAt"] = datetime.now().strftime("%Y-%m-%d %H:%M")

# ─────────────────────────────────────────────
#  7. SISTEMA DE SCORING (0–10 por percentil)
# ─────────────────────────────────────────────
SCORING_CONFIG = {
    "valuation": {
        "metrics": {
            "trailingPE":                   {"inverse": True,  "weight": 0.20},
            "forwardPE":                    {"inverse": True,  "weight": 0.20},
            "trailingPegRatio":             {"inverse": True,  "weight": 0.20},
            "priceToBook":                  {"inverse": True,  "weight": 0.15},
            "priceToSalesTrailing12Months": {"inverse": True,  "weight": 0.15},
            "enterpriseToEbitda":           {"inverse": True,  "weight": 0.10},
        },
        "category_weight": 0.30,
    },
    "profitability": {
        "metrics": {
            "returnOnEquity":    {"inverse": False, "weight": 0.25},
            "returnOnAssets":    {"inverse": False, "weight": 0.20},
            "profitMargins":     {"inverse": False, "weight": 0.20},
            "grossMargins":      {"inverse": False, "weight": 0.15},
            "operatingMargins":  {"inverse": False, "weight": 0.10},
            "ebitdaMargins":     {"inverse": False, "weight": 0.10},
        },
        "category_weight": 0.25,
    },
    "growth": {
        "metrics": {
            "revenueGrowth":             {"inverse": False, "weight": 0.35},
            "earningsGrowth":            {"inverse": False, "weight": 0.35},
            "earningsQuarterlyGrowth":   {"inverse": False, "weight": 0.30},
        },
        "category_weight": 0.25,
    },
    "financial_health": {
        "metrics": {
            "debtToEquity": {"inverse": True,  "weight": 0.30},
            "currentRatio": {"inverse": False, "weight": 0.25},
            "quickRatio":   {"inverse": False, "weight": 0.20},
            "freeCashflow": {"inverse": False, "weight": 0.25},
        },
        "category_weight": 0.20,
    },
}

# ── 7a. IMPUTACIÓN JERÁRQUICA: Industry → Sector → Mediana global ──────────
# Solo para columnas numéricas usadas en el scoring
all_scoring_metrics = [
    m for cfg in SCORING_CONFIG.values() for m in cfg["metrics"]
]

def impute_hierarchical(df: pd.DataFrame, metric: str) -> pd.Series:
    """Imputa NaN en 3 niveles: industry median → sector median → global median."""
    series = df[metric].copy()
    # Nivel 1: mediana por industry (mínimo 3 valores válidos para ser confiable)
    industry_med = df.groupby("industry")[metric].transform(
        lambda x: x.median() if x.notna().sum() >= 3 else np.nan
    )
    # Nivel 2: mediana por sector
    sector_med = df.groupby("sector")[metric].transform(
        lambda x: x.median() if x.notna().sum() >= 3 else np.nan
    )
    # Nivel 3: mediana global
    global_med = series.median()

    imputed = series.copy()
    mask_nan = series.isna()
    imputed[mask_nan] = industry_med[mask_nan]
    still_nan = imputed.isna()
    imputed[still_nan] = sector_med[still_nan]
    still_nan2 = imputed.isna()
    imputed[still_nan2] = global_med
    return imputed

# Crear columnas imputadas (sufijo _imp) — no pisamos los originales
imputed_cols = []
for metric in all_scoring_metrics:
    if metric in all_stats.columns:
        imp_col = f"{metric}_imp"
        # Solo imputa si sector/industry están disponibles
        if "industry" in all_stats.columns and "sector" in all_stats.columns:
            all_stats[imp_col] = impute_hierarchical(all_stats, metric)
        else:
            all_stats[imp_col] = all_stats[metric].fillna(all_stats[metric].median())
        imputed_cols.append(metric)

# Columna auxiliar: cuántas métricas originales tenía cada acción (transparencia)
all_stats["metrics_with_data"] = all_stats[all_scoring_metrics].notna().sum(axis=1)
all_stats["metrics_total"]     = len(all_scoring_metrics)
all_stats["data_completeness_pct"] = (
    all_stats["metrics_with_data"] / all_stats["metrics_total"] * 100
).round(1)

# ── 7b. SCORING SOBRE VALORES IMPUTADOS ────────────────────────────────────
def score_series(series: pd.Series, inverse: bool) -> pd.Series:
    """Convierte una serie numérica a puntaje 0–10 por rango percentil."""
    valid = series.dropna()
    if valid.nunique() < 2:
        return pd.Series(5.0, index=series.index)
    ranks = series.rank(pct=True, na_option="keep")
    if inverse:
        ranks = 1 - ranks
    return (ranks * 10).clip(0, 10)

for cat, cfg in SCORING_CONFIG.items():
    cat_scores = []
    available_weights = {}
    for metric, meta in cfg["metrics"].items():
        imp_col = f"{metric}_imp"
        if imp_col in all_stats.columns:
            available_weights[metric] = meta["weight"]

    total_w = sum(available_weights.values()) or 1
    for metric, meta in cfg["metrics"].items():
        imp_col = f"{metric}_imp"
        if imp_col in all_stats.columns:
            col_score = score_series(all_stats[imp_col], meta["inverse"])
            all_stats[f"score_{metric}"] = col_score.round(2)
            cat_scores.append(col_score * (available_weights[metric] / total_w))

    all_stats[f"score_{cat}"] = sum(cat_scores).round(2) if cat_scores else np.nan

# Score final ponderado (reponderado si alguna categoría entera falta)
cat_contributions = []
total_cat_w = 0
for cat, cfg in SCORING_CONFIG.items():
    score_col = f"score_{cat}"
    if score_col in all_stats.columns:
        cat_contributions.append((all_stats[score_col], cfg["category_weight"]))
        total_cat_w += cfg["category_weight"]

if cat_contributions:
    all_stats["score_FINAL"] = sum(
        s * (w / total_cat_w) for s, w in cat_contributions
    ).round(2)
else:
    all_stats["score_FINAL"] = np.nan

# Penalización suave por baja completitud de datos (evita que imputados suban mucho)
# Acciones con < 30% de datos reales reciben un descuento proporcional
completeness = all_stats["data_completeness_pct"] / 100
penalty = completeness.clip(lower=0.30)   # mínimo 30% → máximo 30% de penalización
all_stats["score_FINAL_adj"] = (all_stats["score_FINAL"] * (0.70 + 0.30 * penalty)).round(2)

def rating_label(score):
    if pd.isna(score):  return "Sin datos"
    if score >= 8:      return "⭐ Excelente"
    if score >= 6.5:    return "✅ Buena"
    if score >= 5:      return "🔶 Neutral"
    if score >= 3:      return "⚠️ Débil"
    return                     "🔴 Evitar"

all_stats["rating"] = all_stats["score_FINAL_adj"].apply(rating_label)

# Dos rankings: uno con score ajustado (recomendado) y uno puro
all_stats["rank_overall"] = all_stats["score_FINAL_adj"].rank(
    ascending=False, method="min", na_option="bottom"
).astype(int)
all_stats["rank_raw"] = all_stats["score_FINAL"].rank(
    ascending=False, method="min", na_option="bottom"
).astype(int)

# ─────────────────────────────────────────────
#  8. EXPORTACIÓN
# ─────────────────────────────────────────────
file_info_name  = "Stock_Info.csv"
file_score_name = "Stock_Scores.csv"

all_stats.to_csv(file_info_name, index=False)
print(f"\n✅ Fundamentales guardados → {file_info_name}")

# Tabla de scores resumida (ideal para tabla de ranking en PBI)
score_cols = (
    ["ticker", "shortName", "sector", "industry", "lastPrice",
     "rank_overall", "rank_raw", "score_FINAL_adj", "score_FINAL", "rating",
     "data_completeness_pct", "metrics_with_data", "metrics_total"]
    + [f"score_{cat}" for cat in SCORING_CONFIG]
    + [f"score_{m}" for cat in SCORING_CONFIG.values() for m in cat["metrics"]]
)
score_cols = [c for c in score_cols if c in all_stats.columns]
all_stats[score_cols].sort_values("rank_overall").to_csv(file_score_name, index=False)
print(f"🏆 Scores guardados        → {file_score_name}")
print(f"\n📌 Total acciones procesadas: {len(all_stats)}")
print(all_stats[["ticker", "score_FINAL_adj", "rating", "rank_overall", "data_completeness_pct"]].sort_values("rank_overall").head(20).to_string(index=False))
ranked_total = all_stats["score_FINAL_adj"].notna().sum()
print(f"\n📊 Acciones rankeadas: {ranked_total} / {len(all_stats)}")
