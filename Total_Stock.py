import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime
from scipy.stats import linregress
import os

# ─────────────────────────────────────────────
# 1. CONFIG
# ─────────────────────────────────────────────
tickers = pd.read_csv("Tickers.csv")["ticker"].dropna().tolist()

PRICES_FILE      = "Total_Stock.parquet"
HIST_CSV_FILE    = "Historical_Stock.csv"
ACTUAL_CSV_FILE  = "Actual_Stock.csv"
HISTORICAL_FILE  = "stock_fundamentals_history.parquet"

HISTORICAL_ATTRIBUTES = [
    "shortName", "sector", "industry",
    "trailingPE", "forwardPE", "priceToBook", "enterpriseToEbitda",
    "returnOnEquity", "profitMargins", "operatingMargins",
    "revenueGrowth", "earningsGrowth",
    "debtToEquity", "currentRatio", "freeCashflow",
    "ebitda", "totalRevenue", "netIncome", "totalDebt",
    "mostRecentQuarter",
]

ATTRIBUTES = [
    "shortName", "sector", "industry",
    "trailingPE", "forwardPE", "priceToBook", "enterpriseToEbitda",
    "returnOnEquity", "profitMargins", "operatingMargins",
    "revenueGrowth", "earningsGrowth",
    "debtToEquity", "currentRatio", "freeCashflow",
    "fiftyDayAverage", "twoHundredDayAverage",
    "mostRecentQuarter"
]

# ─────────────────────────────────────────────
# 2. PRECIOS
# ─────────────────────────────────────────────
prices = yf.download(tickers, period="6mo", progress=False)["Close"]

if isinstance(prices, pd.Series):
    prices = prices.to_frame(name=tickers[0])

last_price = prices.iloc[-1]

# ─────────────────────────────────────────────
# 3. FUNDAMENTALES + HISTÓRICO
# ─────────────────────────────────────────────
if os.path.exists(HISTORICAL_FILE):
    df_hist = pd.read_parquet(HISTORICAL_FILE)
    existing_keys = set(zip(df_hist["ticker"], df_hist["report_date"]))
else:
    df_hist = pd.DataFrame()
    existing_keys = set()

data          = {}
new_hist_rows = []
fetch_date    = datetime.today().strftime("%Y-%m-%d")

for t in tickers:
    try:
        info   = yf.Ticker(t).info
        data[t] = {a: info.get(a) for a in ATTRIBUTES}

        report_ts = info.get("mostRecentQuarter")
        if report_ts:
            report_date = datetime.utcfromtimestamp(report_ts).strftime("%Y-%m-%d")
            if (t, report_date) not in existing_keys:
                row = {"ticker": t, "report_date": report_date, "fetch_date": fetch_date}
                for attr in HISTORICAL_ATTRIBUTES:
                    if attr != "mostRecentQuarter":
                        row[attr] = info.get(attr)
                new_hist_rows.append(row)
                existing_keys.add((t, report_date))

    except Exception as e:
        print(f"⚠  Error en {t}: {e}")
        continue

if new_hist_rows:
    df_new = pd.DataFrame(new_hist_rows)
    if df_hist.empty:
        df_updated = df_new
    else:
        df_updated = pd.concat([df_hist, df_new], ignore_index=True)
    df_updated = df_updated.sort_values(["ticker", "report_date"]).reset_index(drop=True)
    df_updated.to_parquet(HISTORICAL_FILE, index=False)
    print(f"📚 Histórico actualizado: +{len(new_hist_rows)} registros | "
          f"{df_updated['ticker'].nunique()} tickers | "
          f"{len(df_updated)} filas totales")
else:
    print("✅ Histórico sin cambios — no hubo nuevos reportes trimestrales.")

# ─────────────────────────────────────────────
# 4. DATAFRAME SCREENER
# ─────────────────────────────────────────────
df = pd.DataFrame.from_dict(data, orient="index").reset_index()
df.rename(columns={"index": "ticker"}, inplace=True)

num_cols      = df.select_dtypes(include=np.number).columns
df[num_cols]  = df[num_cols].apply(pd.to_numeric, errors="coerce")

# ─────────────────────────────────────────────
# 5. FEATURES DE PRECIO
# ─────────────────────────────────────────────
df["lastPrice"]     = df["ticker"].map(last_price)
df["priceVs50dMA"]  = df["lastPrice"] / df["fiftyDayAverage"]  - 1
df["priceVs200dMA"] = df["lastPrice"] / df["twoHundredDayAverage"] - 1

# ─────────────────────────────────────────────
# 6. KPIs DE EVOLUCIÓN HISTÓRICA
# ─────────────────────────────────────────────
def compute_trend(values):
    """
    Pendiente de regresión lineal normalizada por la media.
    Resultado: % de cambio por trimestre.
    Mínimo 3 puntos para ser estadísticamente válido.
    """
    values = values.dropna()
    if len(values) < 3:
        return np.nan
    x                 = np.arange(len(values))
    slope, _, _, _, _ = linregress(x, values)
    mean_val          = values.abs().mean()
    if mean_val == 0 or np.isnan(mean_val):
        return np.nan
    return slope / mean_val

def compute_consistency(values):
    """
    Estabilidad de resultados vía coeficiente de variación inverso.
    Mayor valor = beneficios más predecibles = mayor calidad.
    """
    values = values.dropna()
    if len(values) < 3:
        return np.nan
    mean_val = values.mean()
    std_val  = values.std()
    if mean_val == 0 or np.isnan(mean_val):
        return np.nan
    cv = std_val / abs(mean_val)
    return 1 / (1 + cv)

trend_kpis = ["revenue_trend", "ebitda_trend", "margin_trend",
              "debt_trend", "fcf_trend", "earnings_consistency"]

if os.path.exists(HISTORICAL_FILE):
    df_fund_hist = pd.read_parquet(HISTORICAL_FILE)
    df_fund_hist["report_date"] = pd.to_datetime(df_fund_hist["report_date"])
    df_fund_hist = df_fund_hist.sort_values(["ticker", "report_date"])
    df_fund_hist = df_fund_hist.groupby("ticker").tail(8)  # últimos 8 trimestres

    trend_results = {}
    for ticker, group in df_fund_hist.groupby("ticker"):
        trend_results[ticker] = {
            "revenue_trend":        compute_trend(group["totalRevenue"]),
            "ebitda_trend":         compute_trend(group["ebitda"]),
            "margin_trend":         compute_trend(group["operatingMargins"]),
            "debt_trend":           compute_trend(group["totalDebt"]),
            "fcf_trend":            compute_trend(group["freeCashflow"]),
            "earnings_consistency": compute_consistency(group["netIncome"]),
        }

    df_trends = pd.DataFrame.from_dict(trend_results, orient="index").reset_index()
    df_trends.rename(columns={"index": "ticker"}, inplace=True)
    df       = df.merge(df_trends, on="ticker", how="left")

    n_activos = df_trends[trend_kpis].notna().any(axis=1).sum()
    print(f"📈 KPIs de evolución calculados para {n_activos} tickers "
          f"({len(tickers) - n_activos} sin histórico suficiente aún).")
else:
    for kpi in trend_kpis:
        df[kpi] = np.nan
    print("⚠  Sin histórico aún — KPIs de evolución en NaN (se activarán tras 3 trimestres).")

# ─────────────────────────────────────────────
# 7. WINSORIZATION + IMPUTACIÓN
# ─────────────────────────────────────────────
def winsorize(s):
    if s.notna().sum() < 10:
        return s
    return s.clip(s.quantile(0.05), s.quantile(0.95))

def impute(df, col):
    industry_med = df.groupby("industry")[col].transform(
        lambda x: x.median() if x.notna().sum() >= 3 else np.nan
    )
    sector_med = df.groupby("sector")[col].transform(
        lambda x: x.median() if x.notna().sum() >= 3 else np.nan
    )
    global_med = df[col].median()

    s = df[col].copy()
    s = s.fillna(industry_med)
    s = s.fillna(sector_med)
    s = s.fillna(global_med)
    return s

# ─────────────────────────────────────────────
# 8. SCORING CONFIG
# ─────────────────────────────────────────────
#
#  Cada categoría: { métrica: (inverse, peso_interno), "weight": peso_global }
#  inverse=True  → menor valor es mejor (ej: PE bajo es buena valoración)
#  inverse=False → mayor valor es mejor (ej: ROE alto es mejor rentabilidad)
#
#  Los pesos globales suman 1.0:
#  0.20 + 0.20 + 0.15 + 0.15 + 0.15 + 0.15 = 1.00 ✅
#
CONFIG = {
    "valuation": {
        "trailingPE":         (True,  0.25),
        "forwardPE":          (True,  0.25),
        "priceToBook":        (True,  0.25),
        "enterpriseToEbitda": (True,  0.25),
        "weight": 0.20
    },
    "profitability": {
        "returnOnEquity":   (False, 0.4),
        "profitMargins":    (False, 0.3),
        "operatingMargins": (False, 0.3),
        "weight": 0.20
    },
    "growth": {
        "revenueGrowth":  (False, 0.5),
        "earningsGrowth": (False, 0.5),
        "weight": 0.15
    },
    "financial": {
        "debtToEquity": (True,  0.5),
        "currentRatio": (False, 0.5),
        "weight": 0.15
    },
    "momentum": {
        "priceVs50dMA":  (False, 0.5),
        "priceVs200dMA": (False, 0.5),
        "weight": 0.15
    },
    # ── Activa desde el 3er trimestre de datos históricos ──
    "fundamental_momentum": {
        "revenue_trend":        (False, 0.25),  # ingresos crecientes = mejor
        "ebitda_trend":         (False, 0.25),  # EBITDA creciente   = mejor
        "margin_trend":         (False, 0.20),  # márgenes crecientes = mejor
        "debt_trend":           (True,  0.15),  # deuda creciente    = peor
        "fcf_trend":            (False, 0.10),  # FCF creciente      = mejor
        "earnings_consistency": (False, 0.05),  # más estable        = mejor
        "weight": 0.15
    }
}

# ─────────────────────────────────────────────
# 9. SCORING POR SECTOR
# ─────────────────────────────────────────────
def score(series, inverse):
    series = winsorize(series)
    r      = series.rank(pct=True)
    if inverse:
        r = 1 - r
    return (r * 10).clip(0, 10)

all_metrics = []

for cat, cfg in CONFIG.items():
    cat_score = 0
    total_w   = 0

    for k, v in cfg.items():
        if k == "weight":
            continue

        inverse, w = v

        if k in df.columns:
            imp              = impute(df, k)
            s                = df.groupby("sector")[imp.name].transform(
                                   lambda x: score(x, inverse))
            df[f"score_{k}"] = s
            cat_score       += s * w
            total_w         += w
            all_metrics.append(k)

    df[f"score_{cat}"] = cat_score / total_w if total_w > 0 else np.nan

# ─────────────────────────────────────────────
# 10. SCORE FINAL PONDERADO
# ─────────────────────────────────────────────
#
#  score_FINAL = suma ponderada de los 6 score_{cat}
#
#  Ejemplo para un activo con todos los datos:
#  ┌─────────────────────────┬────────┬───────────────────────────────┐
#  │ Categoría               │ Peso   │ Contribución al score final   │
#  ├─────────────────────────┼────────┼───────────────────────────────┤
#  │ valuation               │ 20%    │ score_valuation × 0.20        │
#  │ profitability           │ 20%    │ score_profitability × 0.20    │
#  │ growth                  │ 15%    │ score_growth × 0.15           │
#  │ financial               │ 15%    │ score_financial × 0.15        │
#  │ momentum                │ 15%    │ score_momentum × 0.15         │
#  │ fundamental_momentum    │ 15%    │ score_fund_momentum × 0.15    │
#  └─────────────────────────┴────────┴───────────────────────────────┘
#
cat_scores   = []
total_weight = 0

for cat, cfg in CONFIG.items():
    if f"score_{cat}" in df.columns:
        cat_scores.append(df[f"score_{cat}"] * cfg["weight"])
        total_weight += cfg["weight"]

df["score_FINAL"] = sum(cat_scores) / total_weight

# ─────────────────────────────────────────────
# 11. PENALIZACIÓN POR DATOS FALTANTES
# ─────────────────────────────────────────────
valid        = df[all_metrics].notna().sum(axis=1)
total        = len(all_metrics)
completeness = valid / total
penalty      = completeness.clip(lower=0.3)

df["score_FINAL_adj"] = df["score_FINAL"] * (0.7 + 0.3 * penalty)

# ─────────────────────────────────────────────
# 12. RANKING + LABEL
# ─────────────────────────────────────────────
df["rank"] = df["score_FINAL_adj"].rank(ascending=False)

def label(x):
    if x >= 8:   return "Excelente"
    if x >= 6.5: return "Buena"
    if x >= 5:   return "Neutral"
    if x >= 3:   return "Débil"
    return "Evitar"

df["rating"] = df["score_FINAL_adj"].apply(label)

# ─────────────────────────────────────────────
# 13. OUTPUT SCREENER
# ─────────────────────────────────────────────
df.drop(columns=["mostRecentQuarter"], inplace=True, errors="ignore")

output_cols = [
    # Identificación
    "ticker", "shortName", "sector", "industry",
    # Score final
    "rank", "score_FINAL_adj", "rating",
    # Scores por categoría
    "score_valuation", "score_profitability", "score_growth",
    "score_financial", "score_momentum", "score_fundamental_momentum",
    # KPIs de evolución (legibles para análisis manual)
    "revenue_trend", "ebitda_trend", "margin_trend",
    "debt_trend", "fcf_trend", "earnings_consistency",
    # Precio
    "lastPrice", "priceVs50dMA", "priceVs200dMA",
    # Fundamentales raw
    "trailingPE", "forwardPE", "priceToBook", "enterpriseToEbitda",
    "returnOnEquity", "profitMargins", "operatingMargins",
    "revenueGrowth", "earningsGrowth",
    "debtToEquity", "currentRatio", "freeCashflow",
]

# Solo exportar columnas que existan (evita error si alguna falta)
output_cols = [c for c in output_cols if c in df.columns]
df[output_cols].to_csv("Stock_Screener_PRO.csv", index=False)
print("✅ Stock_Screener_PRO.csv actualizado.")

# ─────────────────────────────────────────────
# 14. GUARDAR PRECIOS → Actual_Stock.parquet
# ─────────────────────────────────────────────
def load_csv_prices(filepath):
    df_p = pd.read_csv(filepath, index_col=0)
    df_p.index = pd.to_datetime(df_p.index, utc=False, errors="coerce")
    df_p.index.name = "Date"
    df_p = df_p[df_p.index.notna()].sort_index()
    df_p.columns = df_p.columns.str.strip()
    df_p = df_p.apply(pd.to_numeric, errors="coerce")
    return df_p

def merge_price_frames(*frames):
    combined = pd.concat(frames, axis=0)
    combined = combined[~combined.index.duplicated(keep="last")]
    all_cols = frames[0].columns
    for f in frames[1:]:
        all_cols = all_cols.union(f.columns)
    return combined.reindex(columns=all_cols).sort_index()

# ── Migración (solo primera ejecución) ──────────────────────────────────────
if not os.path.exists(PRICES_FILE):
    print("🔄 Parquet no encontrado — iniciando migración de CSVs históricos...")
    frames_to_merge = []

    if os.path.exists(HIST_CSV_FILE):
        df_hist_csv = load_csv_prices(HIST_CSV_FILE)
        frames_to_merge.append(df_hist_csv)
        print(f"   📂 {HIST_CSV_FILE}: {len(df_hist_csv)} filas | "
              f"{df_hist_csv.index[0].date()} → {df_hist_csv.index[-1].date()}")
    else:
        print(f"   ⚠  {HIST_CSV_FILE} no encontrado — se omite.")

    if os.path.exists(ACTUAL_CSV_FILE) and os.stat(ACTUAL_CSV_FILE).st_size > 0:
        df_actual_csv = load_csv_prices(ACTUAL_CSV_FILE)
        frames_to_merge.append(df_actual_csv)
        print(f"   📂 {ACTUAL_CSV_FILE}: {len(df_actual_csv)} filas | "
              f"{df_actual_csv.index[0].date()} → {df_actual_csv.index[-1].date()}")
    else:
        print(f"   ⚠  {ACTUAL_CSV_FILE} no encontrado o vacío — se omite.")

    if frames_to_merge:
        df_migrado = merge_price_frames(*frames_to_merge) if len(frames_to_merge) > 1 else frames_to_merge[0]
        df_migrado.to_parquet(PRICES_FILE, index=True)
        print(f"\n✅ Migración completada → {PRICES_FILE}")
        print(f"   📊 {len(df_migrado)} filas | {df_migrado.shape[1]} tickers | "
              f"{df_migrado.index[0].date()} → {df_migrado.index[-1].date()}")
        for old_file in [HIST_CSV_FILE, ACTUAL_CSV_FILE]:
            if os.path.exists(old_file):
                backup = old_file.replace(".csv", "_backup.csv")
                os.rename(old_file, backup)
                print(f"   📁 {old_file} → {backup} (backup)")
    else:
        prices.to_parquet(PRICES_FILE, index=True)
        print(f"📊 Parquet creado desde cero: {len(prices)} filas | {len(prices.columns)} tickers.")

# ── Append diario ────────────────────────────────────────────────────────────
if os.path.exists(PRICES_FILE):
    df_existente  = pd.read_parquet(PRICES_FILE)
    df_existente.index = pd.to_datetime(df_existente.index)
    fechas_nuevas = prices.index.difference(df_existente.index)

    if len(fechas_nuevas) > 0:
        df_nuevas    = prices.loc[fechas_nuevas]
        todas_cols   = df_existente.columns.union(df_nuevas.columns)
        df_existente = df_existente.reindex(columns=todas_cols)
        df_nuevas    = df_nuevas.reindex(columns=todas_cols)
        df_final     = pd.concat([df_existente, df_nuevas]).sort_index()
        df_final.to_parquet(PRICES_FILE, index=True)
        print(f"📈 {len(fechas_nuevas)} fechas nuevas en Actual_Stock.parquet | "
              f"Total: {len(df_final)} filas")
    else:
        print("✅ Actual_Stock.parquet ya está al día.")

# ─────────────────────────────────────────────
# 15. RESUMEN CONSOLA
# ─────────────────────────────────────────────
print("\n" + "="*60)
print("🏆 TOP 15 — RANKING FINAL")
print("="*60)
top15 = df.sort_values("rank")[
    ["rank", "ticker", "shortName", "score_FINAL_adj", "rating",
     "score_valuation", "score_profitability",
     "score_fundamental_momentum"]
].head(15)
print(top15.to_string(index=False))
