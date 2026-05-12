import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime
from scipy.stats import linregress
import pyarrow as pa
import pyarrow.parquet as pq
import os

# ─────────────────────────────────────────────
# 1. CONFIG
# ─────────────────────────────────────────────
tickers = pd.read_csv("Tickers.csv")["ticker"].dropna().tolist()

PRICES_FILE     = "Actual_Stock.parquet"
HISTORICAL_FILE = "stock_fundamentals_history.parquet"

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
# 2. FUNCIÓN GUARDADO COMPATIBLE CON POWER BI
# ─────────────────────────────────────────────
def save_parquet_pbi(df, filepath):
    """
    Guarda un DataFrame de precios en formato Parquet
    compatible con Power BI (gzip, data page v1, tipos explícitos).
    El índice datetime se convierte a columna 'Date' como string.
    """
    df_export = df.reset_index()
    df_export["Date"] = pd.to_datetime(df_export["Date"]).dt.strftime("%Y-%m-%d")

    for col in df_export.columns:
        if col != "Date":
            df_export[col] = pd.to_numeric(df_export[col], errors="coerce").astype("float64")

    fields = [pa.field("Date", pa.string())]
    for col in df_export.columns:
        if col != "Date":
            fields.append(pa.field(col, pa.float64()))

    schema = pa.schema(fields)
    table  = pa.Table.from_pandas(df_export, schema=schema, preserve_index=False)

    pq.write_table(
        table,
        filepath,
        compression="gzip",
        use_deprecated_int96_timestamps=False,
        write_statistics=True,
        data_page_version="1.0",
    )

def read_parquet_prices(filepath):
    """
    Lee el parquet de precios y devuelve un DataFrame
    con índice datetime (reconstruye desde columna 'Date').
    """
    df = pd.read_parquet(filepath)
    df.index = pd.to_datetime(df["Date"])
    df.index.name = "Date"
    df = df.drop(columns=["Date"])
    return df.sort_index()

# ─────────────────────────────────────────────
# 3. PRECIOS
# ─────────────────────────────────────────────
prices = yf.download(tickers, period="6mo", progress=False)["Close"]

if isinstance(prices, pd.Series):
    prices = prices.to_frame(name=tickers[0])

last_price = prices.iloc[-1]

# ─────────────────────────────────────────────
# 4. FUNDAMENTALES + HISTÓRICO
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
        info    = yf.Ticker(t).info
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
# 5. DATAFRAME SCREENER
# ─────────────────────────────────────────────
df = pd.DataFrame.from_dict(data, orient="index").reset_index()
df.rename(columns={"index": "ticker"}, inplace=True)

num_cols     = df.select_dtypes(include=np.number).columns
df[num_cols] = df[num_cols].apply(pd.to_numeric, errors="coerce")

# ─────────────────────────────────────────────
# 6. FEATURES DE PRECIO
# ─────────────────────────────────────────────
df["lastPrice"]     = df["ticker"].map(last_price)
df["priceVs50dMA"]  = df["lastPrice"] / df["fiftyDayAverage"]  - 1
df["priceVs200dMA"] = df["lastPrice"] / df["twoHundredDayAverage"] - 1

# ─────────────────────────────────────────────
# 7. KPIs DE EVOLUCIÓN HISTÓRICA
# ─────────────────────────────────────────────
def compute_trend(values):
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
    df_fund_hist = df_fund_hist.groupby("ticker").tail(8)

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
    df        = df.merge(df_trends, on="ticker", how="left")

    n_activos = df_trends[trend_kpis].notna().any(axis=1).sum()
    print(f"📈 KPIs de evolución calculados para {n_activos} tickers.")
else:
    for kpi in trend_kpis:
        df[kpi] = np.nan
    print("⚠  Sin histórico aún — KPIs de evolución en NaN.")

# ─────────────────────────────────────────────
# 8. WINSORIZATION + IMPUTACIÓN
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
# 9. SCORING CONFIG
# ─────────────────────────────────────────────
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
    "fundamental_momentum": {
        "revenue_trend":        (False, 0.25),
        "ebitda_trend":         (False, 0.25),
        "margin_trend":         (False, 0.20),
        "debt_trend":           (True,  0.15),
        "fcf_trend":            (False, 0.10),
        "earnings_consistency": (False, 0.05),
        "weight": 0.15
    }
}

# ─────────────────────────────────────────────
# 10. SCORING POR SECTOR
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
# 11. SCORE FINAL
# ─────────────────────────────────────────────
cat_scores   = []
total_weight = 0

for cat, cfg in CONFIG.items():
    if f"score_{cat}" in df.columns:
        cat_scores.append(df[f"score_{cat}"] * cfg["weight"])
        total_weight += cfg["weight"]

df["score_FINAL"] = sum(cat_scores) / total_weight

# ─────────────────────────────────────────────
# 12. PENALIZACIÓN
# ─────────────────────────────────────────────
valid        = df[all_metrics].notna().sum(axis=1)
total        = len(all_metrics)
completeness = valid / total
penalty      = completeness.clip(lower=0.3)

df["score_FINAL_adj"] = df["score_FINAL"] * (0.7 + 0.3 * penalty)

# ─────────────────────────────────────────────
# 13. RANKING + LABEL
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
# 14. OUTPUT SCREENER
# ─────────────────────────────────────────────
df.drop(columns=["mostRecentQuarter"], inplace=True, errors="ignore")

output_cols = [
    "ticker", "shortName", "sector", "industry",
    "rank", "score_FINAL_adj", "rating",
    "score_valuation", "score_profitability", "score_growth",
    "score_financial", "score_momentum", "score_fundamental_momentum",
    "revenue_trend", "ebitda_trend", "margin_trend",
    "debt_trend", "fcf_trend", "earnings_consistency",
    "lastPrice", "priceVs50dMA", "priceVs200dMA",
    "trailingPE", "forwardPE", "priceToBook", "enterpriseToEbitda",
    "returnOnEquity", "profitMargins", "operatingMargins",
    "revenueGrowth", "earningsGrowth",
    "debtToEquity", "currentRatio", "freeCashflow",
]

output_cols = [c for c in output_cols if c in df.columns]
df[output_cols].to_csv("Stock_Screener_PRO.csv", index=False)
print("✅ Stock_Screener_PRO.csv actualizado.")

# ─────────────────────────────────────────────
# 15. APPEND DIARIO → Actual_Stock.parquet
# ─────────────────────────────────────────────
if os.path.exists(PRICES_FILE):
    df_existente  = read_parquet_prices(PRICES_FILE)
    fechas_nuevas = prices.index.difference(df_existente.index)

    if len(fechas_nuevas) > 0:
        df_nuevas    = prices.loc[fechas_nuevas]
        todas_cols   = df_existente.columns.union(df_nuevas.columns)
        df_existente = df_existente.reindex(columns=todas_cols)
        df_nuevas    = df_nuevas.reindex(columns=todas_cols)
        df_final     = pd.concat([df_existente, df_nuevas]).sort_index()

        save_parquet_pbi(df_final, PRICES_FILE)

        print(f"📈 {len(fechas_nuevas)} fechas nuevas agregadas | "
              f"Total acumulado: {len(df_final)} filas")
    else:
        print("✅ Actual_Stock.parquet ya está al día.")
else:
    # Primera vez: guardar los precios descargados directamente
    save_parquet_pbi(prices, PRICES_FILE)
    print(f"📊 Actual_Stock.parquet creado desde cero con {len(prices)} filas.")

# ─────────────────────────────────────────────
# 16. RESUMEN CONSOLA
# ─────────────────────────────────────────────
print("\n" + "="*60)
print("🏆 TOP 15 — RANKING FINAL")
print("="*60)
top15 = df.sort_values("rank")[
    ["rank", "ticker", "shortName", "score_FINAL_adj", "rating",
     "score_valuation", "score_profitability", "score_fundamental_momentum"]
].head(15)
print(top15.to_string(index=False))
