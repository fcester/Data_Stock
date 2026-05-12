import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, timezone
from scipy.stats import linregress
from concurrent.futures import ThreadPoolExecutor, as_completed
import pyarrow as pa
import pyarrow.parquet as pq
import time
import os

# ─────────────────────────────────────────────
# 1. CONFIG
# ─────────────────────────────────────────────
tickers = pd.read_csv("Tickers.csv")["ticker"].dropna().tolist()

PRICES_FILE      = "Actual_Stock.parquet"
HISTORICAL_FILE  = "stock_fundamentals_history.parquet"
FAILED_LOG       = "failed_tickers.csv"
MAX_WORKERS      = 10    # hilos paralelos para descarga de fundamentales
MAX_RETRIES      = 2     # reintentos por ticker en caso de error

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
    # Valoración
    "trailingPE", "forwardPE", "priceToBook", "enterpriseToEbitda",
    # Rentabilidad
    "returnOnEquity", "profitMargins", "operatingMargins",
    # Crecimiento
    "revenueGrowth", "earningsGrowth",
    # Salud financiera
    "debtToEquity", "currentRatio", "freeCashflow",
    # Precio técnico
    "fiftyDayAverage", "twoHundredDayAverage",
    "fiftyTwoWeekHigh", "fiftyTwoWeekLow",
    # Nuevas métricas
    "beta",
    "marketCap",
    "dividendYield",
    "mostRecentQuarter"
]

# ─────────────────────────────────────────────
# 2. FUNCIONES PARQUET — FORMATO LARGO ↔ ANCHO
# ─────────────────────────────────────────────
def save_parquet_pbi(df_wide, filepath):
    """
    Convierte ancho → largo y guarda compatible con Power BI.
    Columnas: Date | Ticker | Value | Key
    """
    df_long = (
        df_wide
        .reset_index()
        .melt(id_vars="Date", var_name="Ticker", value_name="Value")
    )
    df_long["Date"]  = pd.to_datetime(df_long["Date"]).dt.strftime("%Y-%m-%d")
    df_long          = df_long.dropna(subset=["Value"])
    df_long["Key"]   = df_long["Date"] + "_" + df_long["Ticker"]
    df_long          = df_long.drop_duplicates(subset=["Key"])
    df_long          = df_long.sort_values(["Ticker", "Date"]).reset_index(drop=True)
    df_long["Value"] = pd.to_numeric(df_long["Value"], errors="coerce").astype("float64")

    schema = pa.schema([
        pa.field("Date",   pa.string()),
        pa.field("Ticker", pa.string()),
        pa.field("Value",  pa.float64()),
        pa.field("Key",    pa.string()),
    ])

    table = pa.Table.from_pandas(df_long, schema=schema, preserve_index=False)
    pq.write_table(
        table, filepath,
        compression="gzip",
        use_deprecated_int96_timestamps=False,
        write_statistics=True,
        data_page_version="1.0",
    )
    return df_long

def read_parquet_prices(filepath):
    """
    Lee el parquet y devuelve formato ancho (fechas × tickers).
    Compatible con formato largo (nuevo) y ancho (anterior).
    """
    df = pd.read_parquet(filepath)

    if "Ticker" in df.columns and "Value" in df.columns:
        df_wide              = df.pivot_table(
            index="Date", columns="Ticker", values="Value", aggfunc="last"
        )
        df_wide.columns.name = None
        df_wide.index        = pd.to_datetime(df_wide.index)
        df_wide.index.name   = "Date"
        return df_wide.sort_index()

    if "Date" in df.columns:
        df.index = pd.to_datetime(df["Date"])
        df       = df.drop(columns=["Date"])
    else:
        df.index = pd.to_datetime(df.index)

    df.index.name = "Date"
    return df.sort_index()

# ─────────────────────────────────────────────
# 3. PRECIOS (últimos 6 meses)
# ─────────────────────────────────────────────
print("📥 Descargando precios...")
prices = yf.download(tickers, period="6mo", progress=False)["Close"]

if isinstance(prices, pd.Series):
    prices = prices.to_frame(name=tickers[0])

last_price = prices.iloc[-1]
print(f"   ✅ {len(prices)} fechas | {prices.shape[1]} tickers")

# ─────────────────────────────────────────────
# 4. FUNDAMENTALES — DESCARGA PARALELA CON RETRY
# ─────────────────────────────────────────────
def fetch_ticker_info(t, retries=MAX_RETRIES):
    """Descarga info de un ticker con reintentos automáticos."""
    for attempt in range(retries + 1):
        try:
            info = yf.Ticker(t).info
            # Validar que la respuesta tiene datos útiles
            if info and info.get("regularMarketPrice") is not None or info.get("trailingPE") is not None:
                return t, info, None
            return t, info, "empty_response"
        except Exception as e:
            if attempt < retries:
                time.sleep(1 * (attempt + 1))  # backoff: 1s, 2s
                continue
            return t, None, str(e)

print(f"\n🔄 Descargando fundamentales ({len(tickers)} tickers, {MAX_WORKERS} hilos)...")

data          = {}
new_hist_rows = []
failed        = []
fetch_date    = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

if os.path.exists(HISTORICAL_FILE):
    df_hist       = pd.read_parquet(HISTORICAL_FILE)
    existing_keys = set(zip(df_hist["ticker"], df_hist["report_date"]))
else:
    df_hist       = pd.DataFrame()
    existing_keys = set()

with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    futures = {executor.submit(fetch_ticker_info, t): t for t in tickers}

    for i, future in enumerate(as_completed(futures), 1):
        t, info, error = future.result()

        if error or info is None:
            failed.append({"ticker": t, "date": fetch_date, "error": error or "no_data"})
            continue

        # Datos para el screener
        data[t] = {a: info.get(a) for a in ATTRIBUTES}

        # Lógica del histórico de fundamentales
        report_ts = info.get("mostRecentQuarter")
        if report_ts:
            report_date = datetime.fromtimestamp(report_ts, tz=timezone.utc).strftime("%Y-%m-%d")
            if (t, report_date) not in existing_keys:
                row = {"ticker": t, "report_date": report_date, "fetch_date": fetch_date}
                for attr in HISTORICAL_ATTRIBUTES:
                    if attr != "mostRecentQuarter":
                        row[attr] = info.get(attr)
                new_hist_rows.append(row)
                existing_keys.add((t, report_date))

        if i % 50 == 0:
            print(f"   {i}/{len(tickers)} tickers procesados...")

print(f"   ✅ {len(data)} OK | ⚠  {len(failed)} fallidos")

# Guardar log de tickers fallidos
if failed:
    df_failed = pd.DataFrame(failed)
    if os.path.exists(FAILED_LOG):
        df_failed = pd.concat([pd.read_csv(FAILED_LOG), df_failed], ignore_index=True)
        df_failed = df_failed.drop_duplicates(subset=["ticker", "date"])
    df_failed.to_csv(FAILED_LOG, index=False)
    print(f"   📋 Tickers fallidos guardados en {FAILED_LOG}: {[f['ticker'] for f in failed]}")

# Guardar histórico de fundamentales
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
# 6. FEATURES DE PRECIO Y TÉCNICOS
# ─────────────────────────────────────────────
df["lastPrice"]      = df["ticker"].map(last_price)
df["priceVs50dMA"]   = df["lastPrice"] / df["fiftyDayAverage"]   - 1
df["priceVs200dMA"]  = df["lastPrice"] / df["twoHundredDayAverage"] - 1

# Distancia al máximo y mínimo de 52 semanas
df["priceVs52wHigh"] = df["lastPrice"] / df["fiftyTwoWeekHigh"]  - 1  # negativo = lejos del max
df["priceVs52wLow"]  = df["lastPrice"] / df["fiftyTwoWeekLow"]   - 1  # positivo = lejos del min

# Posición dentro del rango 52w (0 = mínimo, 1 = máximo)
df["position52w"] = (
    (df["lastPrice"] - df["fiftyTwoWeekLow"]) /
    (df["fiftyTwoWeekHigh"] - df["fiftyTwoWeekLow"])
).clip(0, 1)

# ─────────────────────────────────────────────
# 7. FILTRO DE LIQUIDEZ POR MARKET CAP
# ─────────────────────────────────────────────
# Penalización suave para microcaps (< 300M USD)
# No se excluyen, pero su score se reduce un 15%
MICROCAP_THRESHOLD = 300_000_000

df["marketCap"]      = pd.to_numeric(df["marketCap"], errors="coerce")
df["liquidity_flag"] = df["marketCap"] < MICROCAP_THRESHOLD
n_microcap           = df["liquidity_flag"].sum()
if n_microcap > 0:
    print(f"⚠  {n_microcap} microcaps detectados (< $300M) — penalización de liquidez aplicada.")

# ─────────────────────────────────────────────
# 8. KPIs DE EVOLUCIÓN HISTÓRICA
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
# 9. WINSORIZATION + IMPUTACIÓN
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
# 10. SCORING CONFIG
# ─────────────────────────────────────────────
CONFIG = {
    "valuation": {
        "trailingPE":         (True,  0.25),
        "forwardPE":          (True,  0.25),
        "priceToBook":        (True,  0.25),
        "enterpriseToEbitda": (True,  0.25),
        "weight": 0.18
    },
    "profitability": {
        "returnOnEquity":   (False, 0.4),
        "profitMargins":    (False, 0.3),
        "operatingMargins": (False, 0.3),
        "weight": 0.18
    },
    "growth": {
        "revenueGrowth":  (False, 0.5),
        "earningsGrowth": (False, 0.5),
        "weight": 0.14
    },
    "financial": {
        "debtToEquity": (True,  0.5),
        "currentRatio": (False, 0.5),
        "weight": 0.14
    },
    "momentum": {
        "priceVs50dMA":   (False, 0.30),
        "priceVs200dMA":  (False, 0.30),
        "priceVs52wHigh": (False, 0.20),  # cerca del max = bullish
        "position52w":    (False, 0.20),  # posición en rango anual
        "weight": 0.16
    },
    "fundamental_momentum": {
        "revenue_trend":        (False, 0.25),
        "ebitda_trend":         (False, 0.25),
        "margin_trend":         (False, 0.20),
        "debt_trend":           (True,  0.15),
        "fcf_trend":            (False, 0.10),
        "earnings_consistency": (False, 0.05),
        "weight": 0.14
    },
    "income": {
        "dividendYield": (False, 1.00),   # más dividendo = mejor
        "weight": 0.06
    }
}
# Pesos: 0.18+0.18+0.14+0.14+0.16+0.14+0.06 = 1.00 ✅

# ─────────────────────────────────────────────
# 11. SCORING POR SECTOR
# ─────────────────────────────────────────────
def score(series, inverse):
    series = winsorize(series)
    r      = series.rank(pct=True)
    if inverse:
        r = 1 - r
    return (r * 10).clip(0, 10)

all_metrics = []   # se deduplica al final para evitar doble conteo en penalización

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
            if k not in all_metrics:        # ← deduplicación
                all_metrics.append(k)

    df[f"score_{cat}"] = cat_score / total_w if total_w > 0 else np.nan

# ─────────────────────────────────────────────
# 12. SCORE FINAL
# ─────────────────────────────────────────────
cat_scores   = []
total_weight = 0

for cat, cfg in CONFIG.items():
    if f"score_{cat}" in df.columns:
        cat_scores.append(df[f"score_{cat}"] * cfg["weight"])
        total_weight += cfg["weight"]

df["score_FINAL"] = sum(cat_scores) / total_weight

# ─────────────────────────────────────────────
# 13. PENALIZACIÓN POR DATOS FALTANTES
# ─────────────────────────────────────────────
valid        = df[all_metrics].notna().sum(axis=1)
total        = len(all_metrics)
completeness = valid / total
penalty      = completeness.clip(lower=0.3)

df["score_FINAL_adj"] = df["score_FINAL"] * (0.7 + 0.3 * penalty)

# Penalización adicional para microcaps (-15%)
df.loc[df["liquidity_flag"], "score_FINAL_adj"] *= 0.85

# ─────────────────────────────────────────────
# 14. RANKING + LABEL
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
# 15. OUTPUT SCREENER
# ─────────────────────────────────────────────
df.drop(columns=["mostRecentQuarter"], inplace=True, errors="ignore")

output_cols = [
    "ticker", "shortName", "sector", "industry",
    "rank", "score_FINAL_adj", "rating",
    "score_valuation", "score_profitability", "score_growth",
    "score_financial", "score_momentum", "score_fundamental_momentum", "score_income",
    "revenue_trend", "ebitda_trend", "margin_trend",
    "debt_trend", "fcf_trend", "earnings_consistency",
    "lastPrice", "priceVs50dMA", "priceVs200dMA",
    "priceVs52wHigh", "priceVs52wLow", "position52w",
    "beta", "marketCap", "dividendYield", "liquidity_flag",
    "trailingPE", "forwardPE", "priceToBook", "enterpriseToEbitda",
    "returnOnEquity", "profitMargins", "operatingMargins",
    "revenueGrowth", "earningsGrowth",
    "debtToEquity", "currentRatio", "freeCashflow",
]

output_cols = [c for c in output_cols if c in df.columns]
df[output_cols].to_csv("Stock_Screener_PRO.csv", index=False)
print("✅ Stock_Screener_PRO.csv actualizado.")

# ─────────────────────────────────────────────
# 16. APPEND DIARIO → Actual_Stock.parquet
# ─────────────────────────────────────────────
if os.path.exists(PRICES_FILE):
    df_existente = read_parquet_prices(PRICES_FILE)
    start_date   = df_existente.index.min().strftime("%Y-%m-%d")

    # Tickers nuevos → descargar histórico completo
    new_tickers = [t for t in tickers if t not in df_existente.columns]

    if new_tickers:
        print(f"🆕 {len(new_tickers)} tickers nuevos: {new_tickers}")
        print(f"   Descargando histórico desde {start_date}...")
        try:
            prices_new = yf.download(new_tickers, start=start_date, progress=False)["Close"]
            if isinstance(prices_new, pd.Series):
                prices_new = prices_new.to_frame(name=new_tickers[0])

            todas_cols   = df_existente.columns.union(prices_new.columns)
            df_existente = df_existente.reindex(columns=todas_cols)

            fechas_solo_new = prices_new.index.difference(df_existente.index)
            if len(fechas_solo_new) > 0:
                df_existente = pd.concat([
                    df_existente,
                    prices_new.loc[fechas_solo_new].reindex(columns=todas_cols)
                ]).sort_index()

            fechas_overlap = prices_new.index.intersection(df_existente.index)
            for col in prices_new.columns:
                df_existente.loc[fechas_overlap, col] = prices_new.loc[fechas_overlap, col].values

            print(f"   ✅ Histórico incorporado para {len(new_tickers)} tickers nuevos.")

        except Exception as e:
            print(f"   ⚠  Error descargando histórico de nuevos tickers: {e}")

    # Fechas nuevas para todos los tickers
    todas_cols    = df_existente.columns.union(prices.columns)
    df_existente  = df_existente.reindex(columns=todas_cols)
    fechas_nuevas = prices.index.difference(df_existente.index)

    if len(fechas_nuevas) > 0:
        df_nuevas = prices.loc[fechas_nuevas].reindex(columns=todas_cols)
        df_final  = pd.concat([df_existente, df_nuevas]).sort_index()
        print(f"📈 {len(fechas_nuevas)} fechas nuevas agregadas.")
    else:
        df_final = df_existente
        print("✅ Sin fechas nuevas — parquet ya al día.")

    df_long = save_parquet_pbi(df_final, PRICES_FILE)

else:
    df_long = save_parquet_pbi(prices, PRICES_FILE)
    print(f"📊 Parquet creado desde cero: {len(prices)} filas.")

print(f"💾 Parquet guardado: {len(df_long):,} filas | "
      f"{df_long['Ticker'].nunique()} tickers | "
      f"{df_long['Date'].min()} → {df_long['Date'].max()}")

# ─────────────────────────────────────────────
# 17. RESUMEN CONSOLA
# ─────────────────────────────────────────────
print("\n" + "="*60)
print("🏆 TOP 15 — RANKING FINAL")
print("="*60)
top15 = df.sort_values("rank")[
    ["rank", "ticker", "shortName", "score_FINAL_adj", "rating",
     "score_valuation", "score_profitability",
     "score_momentum", "score_fundamental_momentum"]
].head(15)
print(top15.to_string(index=False))

print(f"\n📊 Distribución de ratings:")
print(df["rating"].value_counts().to_string())
