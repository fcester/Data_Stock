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
# Definición de métricas por categoría y si son INVERSAS (menor = mejor)
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


def score_series(series: pd.Series, inverse: bool) -> pd.Series:
    """Convierte una serie numérica a puntaje 0–10 por rango percentil."""
    valid = series.dropna()
    if valid.nunique() < 2:
        return pd.Series(5.0, index=series.index)  # neutro si no hay variación
    ranks = series.rank(pct=True, na_option="keep")
    if inverse:
        ranks = 1 - ranks
    return (ranks * 10).clip(0, 10)


# Calcular scores individuales
for cat, cfg in SCORING_CONFIG.items():
    cat_scores = []
    total_w = sum(m["weight"] for m in cfg["metrics"].values())
    for metric, meta in cfg["metrics"].items():
        if metric in all_stats.columns:
            col_score = score_series(all_stats[metric], meta["inverse"])
            all_stats[f"score_{metric}"] = col_score.round(2)
            cat_scores.append(col_score * (meta["weight"] / total_w))
    if cat_scores:
        all_stats[f"score_{cat}"] = sum(cat_scores).round(2)
    else:
        all_stats[f"score_{cat}"] = np.nan

# Score final ponderado
all_stats["score_FINAL"] = sum(
    all_stats[f"score_{cat}"] * cfg["category_weight"]
    for cat, cfg in SCORING_CONFIG.items()
    if f"score_{cat}" in all_stats.columns
).round(2)

# Clasificación cualitativa
def rating_label(score):
    if pd.isna(score):  return "Sin datos"
    if score >= 8:      return "⭐ Excelente"
    if score >= 6.5:    return "✅ Buena"
    if score >= 5:      return "🔶 Neutral"
    if score >= 3:      return "⚠️ Débil"
    return                     "🔴 Evitar"

all_stats["rating"] = all_stats["score_FINAL"].apply(rating_label)

# Ranking general
all_stats["rank_overall"] = all_stats["score_FINAL"].rank(
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
     "rank_overall", "score_FINAL", "rating"]
    + [f"score_{cat}" for cat in SCORING_CONFIG]
    + [f"score_{m}" for cat in SCORING_CONFIG.values() for m in cat["metrics"]]
)
score_cols = [c for c in score_cols if c in all_stats.columns]
all_stats[score_cols].sort_values("rank_overall").to_csv(file_score_name, index=False)
print(f"🏆 Scores guardados        → {file_score_name}")
print(f"\n📌 Total acciones procesadas: {len(all_stats)}")
print(all_stats[["ticker", "score_FINAL", "rating", "rank_overall"]].sort_values("rank_overall").to_string(index=False))
