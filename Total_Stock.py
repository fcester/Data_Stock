
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

PRICES_FILE     = "Actual_Stock.parquet"
HISTORICAL_FILE = "stock_fundamentals_history.parquet"
TICKERS_FILE    = "Tickers.csv"
MAX_WORKERS     = 4          # bajado de 10 a 4 para no saturar a Yahoo Finance
MAX_RETRIES     = 2
REQUEST_DELAY   = 0.3        # pausa base entre requests (segundos), throttle anti rate-limit
CIRCUIT_BREAKER_ERRORES_401 = 15   # si vemos esto seguido, es bloqueo de Yahoo, no tickers rotos

MICROCAP_THRESHOLD = 300_000_000

# ---- NUEVO: archivo separado, no toca nada de lo que ya usa Power BI ----
ADVANCED_METRICS_FILE = "Stock_Advanced_Metrics.parquet"
RISK_FREE_RATE_ANUAL  = 0.04     # proxy tasa libre de riesgo (ej. T-Bill 3m), ajustable a mano
MIN_OBS_RATIOS_RIESGO = 20       # observaciones minimas para Sharpe/Sortino/VaR confiables
DIVIDENDS_PERIOD      = "5y"     # ventana para historial de dividendos (llamada bulk, no per-ticker)

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
    "fiftyTwoWeekHigh", "fiftyTwoWeekLow",
    "beta", "marketCap", "dividendYield",
    "mostRecentQuarter"
]

# ---- NUEVO: estos campos YA vienen dentro del mismo "info" que se descarga en el
# paso 4 (yf.Ticker(t).info). No agregan ningun request HTTP nuevo por ticker,
# solo leemos mas llaves del mismo diccionario que ya viaja por la red. ----
ADVANCED_ATTRIBUTES = [
    "totalAssets", "totalCurrentAssets", "totalCurrentLiabilities",
    "returnOnAssets", "operatingCashflow",
    "recommendationKey", "recommendationMean", "numberOfAnalystOpinions",
    "targetMeanPrice", "targetHighPrice", "targetLowPrice",
    "heldPercentInsiders", "heldPercentInstitutions",
    "shortRatio", "sharesShort",
    "grossMargins", "quickRatio", "bookValue", "pegRatio",
    "totalCashPerShare", "trailingEps",
]

# ─────────────────────────────────────────────
# 2. FUNCIONES PARQUET (sin cambios respecto al script original)
# ─────────────────────────────────────────────

def to_numeric_safe(series):
    """
    Convierte una columna a numerico de forma robusta:
    reemplaza los strings 'Infinity' / '-Infinity' / 'NaN' que a veces
    devuelve yfinance en vez de floats, y convierte inf/-inf resultantes
    a NaN para que no rompan pyarrow ni el ranking por percentil.
    """
    s = series.replace(
        {"Infinity": np.inf, "-Infinity": -np.inf, "NaN": np.nan}
    )
    s = pd.to_numeric(s, errors="coerce")
    s = s.replace([np.inf, -np.inf], np.nan)
    return s


def save_parquet_pbi(df_wide, filepath):
    df_long = (
        df_wide.reset_index()
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
    pq.write_table(table, filepath, compression="gzip",
                   use_deprecated_int96_timestamps=False,
                   write_statistics=True, data_page_version="1.0")
    return df_long

def read_parquet_prices(filepath):
    df = pd.read_parquet(filepath)
    if "Ticker" in df.columns and "Value" in df.columns:
        df_wide              = df.pivot_table(index="Date", columns="Ticker",
                                              values="Value", aggfunc="last")
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
# 3. PRECIOS (últimos 6 meses) — con try/except crítico
# ─────────────────────────────────────────────
print("📥 Descargando precios...")
try:
    prices = yf.download(tickers, period="6mo", progress=False)["Close"]
except Exception as e:
    raise SystemExit(f"❌ ERROR CRITICO descargando precios, se aborta el pipeline: {e}")

if isinstance(prices, pd.Series):
    prices = prices.to_frame(name=tickers[0])
last_price = prices.iloc[-1]
print(f"   ✅ {len(prices)} fechas | {prices.shape[1]} tickers")

# ─────────────────────────────────────────────
# 3B. NUEVO: DIVIDENDOS + SPLITS EN BLOQUE (1 sola llamada para todos los tickers)
# ─────────────────────────────────────────────
print("\n📥 Descargando dividendos históricos (bloque único, no per-ticker)...")
dividendos_por_ticker = {}
try:
    datos_acciones = yf.download(
        tickers, period=DIVIDENDS_PERIOD, actions=True, progress=False
    )
    if "Dividends" in datos_acciones.columns.get_level_values(0):
        div_wide = datos_acciones["Dividends"]
        if isinstance(div_wide, pd.Series):
            div_wide = div_wide.to_frame(name=tickers[0])
        for t in div_wide.columns:
            serie_t = div_wide[t].dropna()
            serie_t = serie_t[serie_t > 0]
            if len(serie_t) > 0:
                serie_anual = serie_t.groupby(serie_t.index.year).sum()
                dividendos_por_ticker[t] = serie_anual
    print(f"   ✅ Dividendos obtenidos para {len(dividendos_por_ticker)} tickers.")
except Exception as e:
    print(f"   ⚠  No se pudieron descargar dividendos en bloque: {e}")
    print("   Se continúa sin KPIs de crecimiento de dividendos (no es crítico).")

# ─────────────────────────────────────────────
# 4. FUNDAMENTALES — DESCARGA PARALELA CON RETRY (misma mecánica que ya tenían)
# ─────────────────────────────────────────────

def fetch_ticker_info(t, retries=MAX_RETRIES):
    for attempt in range(retries + 1):
        try:
            time.sleep(REQUEST_DELAY)  # throttle basico, evita saturar a Yahoo
            info = yf.Ticker(t).info
            if info and (info.get("regularMarketPrice") is not None
                         or info.get("trailingPE") is not None):
                return t, info, None
            return t, info, "empty_response"
        except Exception as e:
            if attempt < retries:
                # backoff mas agresivo si detectamos señales de rate-limit/bloqueo
                es_bloqueo = "401" in str(e) or "429" in str(e) or "Invalid Crumb" in str(e)
                espera = (5 if es_bloqueo else 1) * (attempt + 1)
                time.sleep(espera)
                continue
            return t, None, str(e)


print(f"\n🔄 Descargando fundamentales ({len(tickers)} tickers, {MAX_WORKERS} hilos)...")


data          = {}
info_completo = {}   # se guarda el dict info COMPLETO para reusarlo en KPIs avanzados
                      # sin generar ni un solo request HTTP adicional
new_hist_rows = []
failed        = []
failed_con_error = []   # guarda (ticker, motivo) — util para cuando reactivemos la cuarentena
fetch_date    = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

if os.path.exists(HISTORICAL_FILE):
    df_hist       = pd.read_parquet(HISTORICAL_FILE)
    existing_keys = set(zip(df_hist["ticker"], df_hist["report_date"]))
else:
    df_hist       = pd.DataFrame()
    existing_keys = set()


circuito_abierto     = False
contador_401         = 0

with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
    futures = {executor.submit(fetch_ticker_info, t): t for t in tickers}
    for i, future in enumerate(as_completed(futures), 1):

        if circuito_abierto:
            # la sesion ya se detecto como bloqueada: no seguimos marcando tickers buenos como fallidos
            t_pendiente = futures[future]
            failed.append(t_pendiente)
            failed_con_error.append((t_pendiente, "circuito_abierto_401"))
            continue

        t, info, error = future.result()

        if error and ("401" in str(error) or "Invalid Crumb" in str(error) or "429" in str(error)):
            contador_401 += 1
            if contador_401 >= CIRCUIT_BREAKER_ERRORES_401:
                circuito_abierto = True
                print(f"\n🚨 CIRCUITO ABIERTO: {contador_401} errores 401/429 seguidos.")
                print("   Yahoo Finance esta bloqueando la sesion (rate-limit), no son tickers rotos.")
                print("   Se abortan los reintentos restantes de esta ejecucion.")
        else:
            contador_401 = 0

        if error or info is None:
            failed.append(t)
            failed_con_error.append((t, error or "info_vacio_o_none"))
            continue

        data[t]          = {a: info.get(a) for a in ATTRIBUTES}
        info_completo[t] = info

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
if circuito_abierto:
    print(f"   🚨 Circuito abierto durante esta ejecucion — parte de los 'fallidos' "
          f"son por bloqueo de Yahoo, no datos rotos.")

# ─────────────────────────────────────────────
# 5. ELIMINAR TICKERS FALLIDOS DE Tickers.csv (sin cambios)
# ─────────────────────────────────────────────
# ⚠ BORRADO AUTOMATICO DESACTIVADO TEMPORALMENTE (18-ago-2026)
# Motivo: un fallo puntual (ej. rate-limit/401 de Yahoo) NO debe borrar
# tickers reales de Tickers.csv. Pendiente: implementar cuarentena con
# Tickers_Fallos.csv (contador de fallos consecutivos + circuit breaker
# ya aplicado arriba en el paso 4). Hasta entonces, solo se informa.
# ─────────────────────────────────────────────
if failed:
    print(f"\n⚠  {len(failed)} tickers fallaron en esta ejecucion (NO se eliminan, borrado desactivado):")
    print(f"   {failed}")
    if circuito_abierto:
        print("   Motivo probable: bloqueo/rate-limit de Yahoo Finance (circuito abierto), no datos rotos.")

# --- CODIGO ORIGINAL, DESACTIVADO A PROPOSITO. Reactivar cuando este lista la cuarentena ---
# if failed:
#     print(f"\n🗑  Eliminando {len(failed)} tickers fallidos de {TICKERS_FILE}...")
#     print(f"   Eliminados: {failed}")
#     df_tickers_original = pd.read_csv(TICKERS_FILE)
#     df_tickers_clean    = df_tickers_original[
#         ~df_tickers_original["ticker"].isin(failed)
#     ]
#     df_tickers_clean.to_csv(TICKERS_FILE, index=False)
#     print(f"   ✅ {TICKERS_FILE} actualizado: "
#           f"{len(df_tickers_original)} → {len(df_tickers_clean)} tickers")


# ─────────────────────────────────────────────
# 6. GUARDAR HISTÓRICO DE FUNDAMENTALES (sin cambios)
# ─────────────────────────────────────────────

if new_hist_rows:
    df_new = pd.DataFrame(new_hist_rows)

    # Saneamiento defensivo del lado NUEVO (por si yfinance trajo "Infinity")
    for _col in HISTORICAL_ATTRIBUTES:
        if _col != "mostRecentQuarter" and _col in df_new.columns and _col not in ["ticker", "shortName", "sector", "industry"]:
            df_new[_col] = to_numeric_safe(df_new[_col])

    # Saneamiento defensivo del lado VIEJO (el parquet ya en disco puede tener
    # "Infinity" persistido de ejecuciones anteriores al fix)
    if not df_hist.empty:
        _cols_no_numericas_hist = ["ticker", "report_date", "fetch_date", "shortName", "sector", "industry"]
        for _col in df_hist.columns:
            if _col not in _cols_no_numericas_hist:
                df_hist[_col] = to_numeric_safe(df_hist[_col])

    if df_hist.empty:
        df_updated = df_new
    else:
        df_updated = pd.concat([df_hist, df_new], ignore_index=True)
    df_updated = df_updated.sort_values(["ticker", "report_date"]).reset_index(drop=True)
    df_updated.to_parquet(HISTORICAL_FILE, index=False)

    print(f"\n📚 Histórico actualizado: +{len(new_hist_rows)} registros | "
          f"{df_updated['ticker'].nunique()} tickers | "
          f"{len(df_updated)} filas totales")
else:
    print("\n✅ Histórico sin cambios — no hubo nuevos reportes trimestrales.")

# ─────────────────────────────────────────────
# 7. DATAFRAME SCREENER — CONVERSIÓN NUMÉRICA EXPLÍCITA (sin cambios)
# ─────────────────────────────────────────────
df = pd.DataFrame.from_dict(data, orient="index").reset_index()
df.rename(columns={"index": "ticker"}, inplace=True)

STR_COLS = ["ticker", "shortName", "sector", "industry"]

for col in df.columns:
    if col not in STR_COLS:
                 df[col] = to_numeric_safe(df[col])

# ─────────────────────────────────────────────
# 8. FEATURES DE PRECIO Y TÉCNICOS (sin cambios)
# ─────────────────────────────────────────────
df["lastPrice"]      = pd.to_numeric(df["ticker"].map(last_price), errors="coerce")
df["priceVs50dMA"]   = df["lastPrice"] / df["fiftyDayAverage"]      - 1
df["priceVs200dMA"]  = df["lastPrice"] / df["twoHundredDayAverage"] - 1
df["priceVs52wHigh"] = df["lastPrice"] / df["fiftyTwoWeekHigh"]     - 1
df["priceVs52wLow"]  = df["lastPrice"] / df["fiftyTwoWeekLow"]      - 1
df["position52w"]    = (
    (df["lastPrice"] - df["fiftyTwoWeekLow"]) /
    (df["fiftyTwoWeekHigh"] - df["fiftyTwoWeekLow"])
).clip(0, 1)

# ── NUEVO: RSI 14 dias y drawdown actual, calculados aqui para poder
# usarlos en el scoring principal (antes solo vivian en el archivo avanzado) ──
def calcular_rsi_14(serie_precios):
    delta   = serie_precios.diff().dropna()
    ganan   = delta.clip(lower=0)
    pierden = (-delta).clip(lower=0)
    avg_g   = ganan.ewm(alpha=1/14, min_periods=14).mean()
    avg_p   = pierden.ewm(alpha=1/14, min_periods=14).mean()
    rs      = avg_g / avg_p.replace(0, np.nan)
    rsi     = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if len(rsi) > 0 else np.nan

rsi_dict       = {}
drawdown_dict  = {}
for t in prices.columns:
    serie_t = prices[t].dropna()
    if len(serie_t) < 15:
        rsi_dict[t]      = np.nan
        drawdown_dict[t] = np.nan
        continue
    rsi_dict[t] = calcular_rsi_14(serie_t)
    rolling_max      = serie_t.cummax()
    drawdown_dict[t] = float(((serie_t - rolling_max) / rolling_max).iloc[-1])

df["rsi_14"]            = df["ticker"].map(rsi_dict)
df["current_drawdown"]  = df["ticker"].map(drawdown_dict)

# Distancia a zona "sana" de RSI (45-65). Cerca de 0 = ni sobrecomprado ni sobrevendido.
# Lejos de 0 en RSI alto = sobrecompra (riesgo de reversion bajista).
# Lejos de 0 en RSI bajo = caida fuerte (cuchillo cayendo, no necesariamente rebote).
df["rsi_distancia_zona_sana"] = (df["rsi_14"] - 55).abs()

# ─────────────────────────────────────────────
# 9. FILTRO DE LIQUIDEZ POR MARKET CAP (sin cambios)
# ─────────────────────────────────────────────
df["liquidity_flag"] = df["marketCap"] < MICROCAP_THRESHOLD
n_microcap           = df["liquidity_flag"].sum()
if n_microcap > 0:
    print(f"\n⚠  {n_microcap} microcaps detectados (< $300M) — penalización aplicada.")

# ── NUEVO: metricas de valor profundo (deep value), calculadas aqui para
# poder integrarlas al scoring principal. Reusan info_completo, sin red nueva ──
def calcular_deep_value(ticker, info, precio_actual):
    fila = {}
    market_cap = info.get("marketCap")
    fcf        = info.get("freeCashflow")
    fila["fcf_yield"] = fcf / market_cap if (fcf and market_cap and market_cap > 0) else np.nan

    eps      = info.get("trailingEps")
    book_val = info.get("bookValue")
    if eps and book_val and eps > 0 and book_val > 0 and precio_actual and precio_actual > 0:
        graham = (22.5 * eps * book_val) ** 0.5
        fila["graham_margin_of_safety"] = (graham / precio_actual) - 1
    else:
        fila["graham_margin_of_safety"] = np.nan

    target_mean = info.get("targetMeanPrice")
    if target_mean and precio_actual and precio_actual > 0:
        fila["analyst_upside"] = (target_mean / precio_actual) - 1
    else:
        fila["analyst_upside"] = np.nan
    return fila

deep_value_rows = {}
for t in data.keys():
    info_t   = info_completo.get(t, {})
    precio_t = last_price[t] if t in last_price.index else np.nan
    deep_value_rows[t] = calcular_deep_value(t, info_t, precio_t)

df_deep_value = pd.DataFrame.from_dict(deep_value_rows, orient="index").reset_index()
df_deep_value.rename(columns={"index": "ticker"}, inplace=True)
df = df.merge(df_deep_value, on="ticker", how="left")

# ─────────────────────────────────────────────
# 10. KPIs HISTÓRICOS AMPLIADOS (sin cambios respecto al script original)
# ─────────────────────────────────────────────
def compute_full_stats(values, periods_per_year=4):
    values = values.dropna().reset_index(drop=True)
    n      = len(values)

    out = dict(trend=np.nan, r2=np.nan, cagr=np.nan,
               last_qoq=np.nan, acceleration=np.nan)

    if n < 2:
        return out

    v_prev = values.iloc[-2]
    v_last = values.iloc[-1]
    if v_prev != 0 and not np.isnan(v_prev):
        out["last_qoq"] = (v_last - v_prev) / abs(v_prev)

    if n < 3:
        return out

    x                     = np.arange(n)
    slope, _, r_val, _, _ = linregress(x, values)
    mean_val              = values.abs().mean()
    out["r2"]             = r_val ** 2
    if mean_val != 0:
        out["trend"] = slope / mean_val

    v_first = values.iloc[0]
    years   = (n - 1) / periods_per_year
    if v_first > 0 and v_last > 0 and years > 0:
        out["cagr"] = (v_last / v_first) ** (1 / years) - 1

    if n >= 6:
        mid    = n // 2
        s1, *_ = linregress(np.arange(mid),     values.iloc[:mid])
        s2, *_ = linregress(np.arange(n - mid), values.iloc[mid:])
        if mean_val != 0:
            out["acceleration"] = (s2 - s1) / abs(mean_val)

    return out

def compute_consistency(values):
    values = values.dropna()
    if len(values) < 3:
        return np.nan
    mean_val = values.mean()
    std_val  = values.std()
    if mean_val == 0 or np.isnan(mean_val):
        return np.nan
    return 1 / (1 + std_val / abs(mean_val))

HIST_METRICS = [
    ("totalRevenue",     "revenue"),
    ("ebitda",           "ebitda"),
    ("operatingMargins", "margin"),
    ("totalDebt",        "debt"),
    ("freeCashflow",     "fcf"),
    ("netIncome",        "earnings"),
    ("returnOnEquity",   "roe"),
]

all_trend_kpis = []
for _, prefix in HIST_METRICS:
    for suffix in ["trend", "r2", "cagr", "qoq", "accel"]:
        all_trend_kpis.append(f"{prefix}_{suffix}")
all_trend_kpis.append("earnings_consistency")

if os.path.exists(HISTORICAL_FILE):
    df_fund_hist = pd.read_parquet(HISTORICAL_FILE)
    df_fund_hist["report_date"] = pd.to_datetime(df_fund_hist["report_date"])
    for _col, _ in HIST_METRICS:
        if _col in df_fund_hist.columns:
            df_fund_hist[_col] = to_numeric_safe(df_fund_hist[_col])
    df_fund_hist = df_fund_hist.sort_values(["ticker", "report_date"])
    df_fund_hist = df_fund_hist.groupby("ticker").tail(8)   # últimos 8 trimestres
    
    # ── NUEVO: percentil de valuation actual vs la propia historia del ticker ──
    # Un PE "razonable vs sector" puede seguir estando caro/barato vs su propio
    # rango historico. Esto captura eso, algo que el scoring por sector no ve.
    def percentil_vs_historia_propia(group, col):
        serie = group[col].dropna()
        if len(serie) < 4:
            return np.nan
        valor_actual = serie.iloc[-1]
        return (serie < valor_actual).mean()  # 0 = mas barato de su historia, 1 = mas caro

    valuation_hist_results = {}
    for ticker, group in df_fund_hist.groupby("ticker"):
        fila_val = {}
        for col in ["trailingPE", "priceToBook", "enterpriseToEbitda"]:
            if col in group.columns:
                fila_val[f"{col}_vs_historia"] = percentil_vs_historia_propia(group, col)
            else:
                fila_val[f"{col}_vs_historia"] = np.nan
        valuation_hist_results[ticker] = fila_val

    df_valuation_hist = pd.DataFrame.from_dict(valuation_hist_results, orient="index").reset_index()
    df_valuation_hist.rename(columns={"index": "ticker"}, inplace=True)


    trend_results = {}
    for ticker, group in df_fund_hist.groupby("ticker"):
        row = {}
        for col, prefix in HIST_METRICS:
            if col not in group.columns:
                for suffix in ["trend", "r2", "cagr", "qoq", "accel"]:
                    row[f"{prefix}_{suffix}"] = np.nan
                continue
            stats = compute_full_stats(group[col])
            row[f"{prefix}_trend"] = stats["trend"]
            row[f"{prefix}_r2"]    = stats["r2"]
            row[f"{prefix}_cagr"]  = stats["cagr"]
            row[f"{prefix}_qoq"]   = stats["last_qoq"]
            row[f"{prefix}_accel"] = stats["acceleration"]

        row["earnings_consistency"] = compute_consistency(
            group["netIncome"] if "netIncome" in group.columns
            else pd.Series(dtype=float)
        )
        trend_results[ticker] = row

    df_trends = pd.DataFrame.from_dict(trend_results, orient="index").reset_index()
    df_trends.rename(columns={"index": "ticker"}, inplace=True)

    for col in df_trends.columns:
        if col != "ticker":
            df_trends[col] = pd.to_numeric(df_trends[col], errors="coerce")

    
    df     = df.merge(df_trends, on="ticker", how="left")
    df     = df.merge(df_valuation_hist, on="ticker", how="left")   # NUEVO
    n_hist = df_trends.drop(columns="ticker").notna().any(axis=1).sum()
    print(f"\n📈 KPIs históricos calculados para {n_hist} tickers "
          f"({len(HIST_METRICS) * 5 + 1} KPIs por ticker).")
else:
    for kpi in all_trend_kpis:
        df[kpi] = np.nan
    for kpi in ["trailingPE_vs_historia", "priceToBook_vs_historia", "enterpriseToEbitda_vs_historia"]:
        df[kpi] = np.nan   # NUEVO
    print("\n⚠  Sin histórico aún — KPIs de evolución en NaN.")

# ─────────────────────────────────────────────
# 11. WINSORIZATION + IMPUTACIÓN (sin cambios)
# ─────────────────────────────────────────────
def winsorize(s):
    s = pd.to_numeric(s, errors="coerce")
    if s.notna().sum() < 10:
        return s
    return s.clip(s.quantile(0.05), s.quantile(0.95))

def impute(df, col):
    s = pd.to_numeric(df[col], errors="coerce").copy()
    industry_med = df.groupby("industry")[col].transform(
        lambda x: pd.to_numeric(x, errors="coerce").median()
        if pd.to_numeric(x, errors="coerce").notna().sum() >= 3 else np.nan
    )
    sector_med = df.groupby("sector")[col].transform(
        lambda x: pd.to_numeric(x, errors="coerce").median()
        if pd.to_numeric(x, errors="coerce").notna().sum() >= 3 else np.nan
    )
    global_med = s.median()
    s = s.fillna(industry_med).fillna(sector_med).fillna(global_med)
    return pd.to_numeric(s, errors="coerce")

# ─────────────────────────────────────────────
# 12. SCORING CONFIG (sin cambios: no tocamos el modelo de scoring existente)
# ─────────────────────────────────────────────

CONFIG = {
    "valuation": {
        "trailingPE":         (True,  0.25),
        "forwardPE":          (True,  0.25),
        "priceToBook":        (True,  0.25),
        "enterpriseToEbitda": (True,  0.25),
        "weight": 0.14
    },
    "deep_value": {
        "graham_margin_of_safety": (False, 0.35),
        "fcf_yield":                (False, 0.35),
        "trailingPE_vs_historia":   (True,  0.30),
        "weight": 0.12
    },
    "profitability": {
        "returnOnEquity":   (False, 0.4),
        "profitMargins":    (False, 0.3),
        "operatingMargins": (False, 0.3),
        "weight": 0.15
    },
    "growth": {
        "revenueGrowth":  (False, 0.5),
        "earningsGrowth": (False, 0.5),
        "weight": 0.10
    },
    "financial": {
        "debtToEquity": (True,  0.5),
        "currentRatio": (False, 0.5),
        "weight": 0.12
    },
    "momentum_calidad": {
        "priceVs200dMA":          (False, 0.35),
        "rsi_distancia_zona_sana": (True,  0.35),
        "current_drawdown":        (False, 0.30),
        "weight": 0.13
    },
    "fundamental_momentum": {
        "revenue_trend":  (False, 0.15),
        "ebitda_trend":   (False, 0.15),
        "margin_trend":   (False, 0.10),
        "debt_trend":     (True,  0.10),
        "fcf_trend":      (False, 0.08),
        "roe_trend":      (False, 0.07),
        "revenue_r2":     (False, 0.08),
        "ebitda_r2":      (False, 0.07),
        "revenue_cagr":   (False, 0.08),
        "ebitda_cagr":    (False, 0.05),
        "revenue_accel":  (False, 0.04),
        "margin_accel":   (False, 0.03),
        "earnings_consistency": (False, 0.00),
        "weight": 0.18
    },
    "income": {
        "dividendYield": (False, 1.00),
        "weight": 0.06
    }
}

# ─────────────────────────────────────────────
# 13. SCORING POR SECTOR (sin cambios)
# ─────────────────────────────────────────────
def score(series, inverse):
    series = pd.to_numeric(series, errors="coerce")
    series = winsorize(series)
    r      = series.rank(pct=True, na_option="keep")
    if inverse:
        r = 1 - r
    return (r * 10).clip(0, 10)

all_metrics = []

for cat, cfg in CONFIG.items():
    cat_score = pd.Series(0.0, index=df.index)
    total_w   = 0.0

    for k, v in cfg.items():
        if k == "weight":
            continue
        inverse, w = v
        if k not in df.columns:
            continue

        df[k] = impute(df, k)

        s = df.groupby("sector")[k].transform(lambda x: score(x, inverse))
        s = pd.to_numeric(s, errors="coerce")

        df[f"score_{k}"] = s
        cat_score        = cat_score.add(s * w, fill_value=0)
        total_w         += w

        if k not in all_metrics:
            all_metrics.append(k)

    df[f"score_{cat}"] = (
        pd.to_numeric(cat_score, errors="coerce") / total_w
        if total_w > 0 else np.nan
    )

# ─────────────────────────────────────────────
# 14. SCORE FINAL (sin cambios) + clip defensivo agregado
# ─────────────────────────────────────────────
cat_scores   = []
total_weight = 0.0

for cat, cfg in CONFIG.items():
    col = f"score_{cat}"
    if col in df.columns:
        s = pd.to_numeric(df[col], errors="coerce")
        cat_scores.append(s * cfg["weight"])
        total_weight += cfg["weight"]

df["score_FINAL"] = pd.to_numeric(
    sum(cat_scores) / total_weight, errors="coerce"
)

# ─────────────────────────────────────────────
# 15. PENALIZACIÓN POR DATOS FALTANTES + MICROCAP
#     (agregado: clip final defensivo 0-10, no cambia el criterio original)
# ─────────────────────────────────────────────
valid        = df[all_metrics].apply(pd.to_numeric, errors="coerce").notna().sum(axis=1)
completeness = valid / len(all_metrics)
penalty      = completeness.clip(lower=0.3)

df["data_completeness"] = (completeness * 100).round(1)
df["score_FINAL_adj"]   = pd.to_numeric(
    df["score_FINAL"] * (0.7 + 0.3 * penalty), errors="coerce"
)

df.loc[df["liquidity_flag"], "score_FINAL_adj"] = (
    df.loc[df["liquidity_flag"], "score_FINAL_adj"] * 0.85
)

df["score_FINAL_adj"] = df["score_FINAL_adj"].clip(lower=0, upper=10)

# ─────────────────────────────────────────────
# 16. RANKING + LABEL — FIX: evita el IntCastingNaNError si hay NaN en score_FINAL_adj
# ─────────────────────────────────────────────
df["rank"] = df["score_FINAL_adj"].rank(ascending=False, method="min")
if df["rank"].isna().any():
    df["rank"] = df["rank"].fillna(df["rank"].max() + 1 if df["rank"].notna().any() else 1)
df["rank"] = df["rank"].astype(int)

def label(x):
    if pd.isna(x):    return "Sin datos"
    if x >= 8:        return "Excelente"
    if x >= 6.5:      return "Buena"
    if x >= 5:        return "Neutral"
    if x >= 3:        return "Débil"
    return "Evitar"

df["rating"] = df["score_FINAL_adj"].apply(label)

# ─────────────────────────────────────────────
# 17. OUTPUT SCREENER DIARIO (sin cambios, no se toca lo que usa Power BI)
# ─────────────────────────────────────────────
df.drop(columns=["mostRecentQuarter"], inplace=True, errors="ignore")

output_cols = [
    "ticker", "shortName", "sector", "industry",
    "rank", "score_FINAL_adj", "rating", "data_completeness",
    "score_valuation", "score_profitability", "score_growth",
    "score_financial", "score_momentum", "score_fundamental_momentum", "score_income",
    "revenue_trend", "ebitda_trend", "margin_trend",
    "debt_trend", "fcf_trend", "earnings_consistency",
    "revenue_r2", "ebitda_r2", "revenue_cagr", "ebitda_cagr",
    "revenue_qoq", "ebitda_qoq", "revenue_accel", "margin_accel",
    "lastPrice", "priceVs50dMA", "priceVs200dMA",
    "priceVs52wHigh", "priceVs52wLow", "position52w",
    "beta", "marketCap", "dividendYield", "liquidity_flag",
    "score_deep_value", "score_momentum_calidad",
    "graham_margin_of_safety", "fcf_yield", "analyst_upside",
    "trailingPE_vs_historia", "priceToBook_vs_historia",
    "rsi_14", "current_drawdown",
    "trailingPE", "forwardPE", "priceToBook", "enterpriseToEbitda",
    "returnOnEquity", "profitMargins", "operatingMargins",
    "revenueGrowth", "earningsGrowth",
    "debtToEquity", "currentRatio", "freeCashflow",
]
output_cols = [c for c in output_cols if c in df.columns]

df[output_cols].to_csv("Stock_Screener_PRO.csv", index=False)
print("✅ Stock_Screener_PRO.csv actualizado.")

# ─────────────────────────────────────────────
# 17B. HISTÓRICO DEL SCREENER — append con fecha (sin cambios)
# ─────────────────────────────────────────────
SCREENER_HISTORY_FILE = "Stock_Screener_History.parquet"

df_snapshot                  = df[output_cols].copy()
df_snapshot["snapshot_date"] = fetch_date


if os.path.exists(SCREENER_HISTORY_FILE):
    df_hist_screener = pd.read_parquet(SCREENER_HISTORY_FILE)
    df_hist_screener = df_hist_screener[
        df_hist_screener["snapshot_date"] != fetch_date
    ]

    # Saneamiento defensivo: por si el parquet historico quedo
    # contaminado con strings tipo "Infinity" de ejecuciones previas
    _cols_no_numericas = ["ticker", "shortName", "sector", "industry",
                           "rating", "snapshot_date", "liquidity_flag"]
    for _col in df_hist_screener.columns:
        if _col not in _cols_no_numericas:
            df_hist_screener[_col] = to_numeric_safe(df_hist_screener[_col])

    df_hist_screener = pd.concat(
        [df_hist_screener, df_snapshot], ignore_index=True
    )

else:
    df_hist_screener = df_snapshot

df_hist_screener = df_hist_screener.sort_values(
    ["snapshot_date", "rank"]
).reset_index(drop=True)

df_hist_screener.to_parquet(SCREENER_HISTORY_FILE, index=False)

n_fechas = df_hist_screener["snapshot_date"].nunique()
print(f"📅 Stock_Screener_History.parquet actualizado: "
      f"{n_fechas} días | "
      f"{df_hist_screener['snapshot_date'].min()} → "
      f"{df_hist_screener['snapshot_date'].max()}")


# ═══════════════════════════════════════════════════════════
# 17C. NUEVO BLOQUE — TENDENCIAS DE SECTOR/INDUSTRIA (archivo separado)
#     Calcula al nivel mas bajo (industry) y agrega hacia arriba (sector)
#     mediante promedio ponderado, para que ambas vistas sean consistentes.
#     No modifica ningun archivo existente.
# ═══════════════════════════════════════════════════════════
print("\n" + "="*60)
print("🏭 CALCULANDO TENDENCIAS DE SECTOR/INDUSTRIA (archivo nuevo)")
print("="*60)

SECTOR_INDUSTRY_HISTORY_FILE = "Sector_Industry_Trends.parquet"
MIN_TICKERS_POR_GRUPO = 2   # no calcular promedios sobre grupos con 1 solo ticker (poco representativo)

def calcular_metricas_industria(df_fuente):
    """
    Calcula metricas agregadas a nivel INDUSTRIA (nivel mas bajo de jerarquia).
    Se excluyen aqui los grupos con muy pocos tickers para no dar una falsa
    sensacion de robustez estadistica sobre un promedio de 1-2 empresas.
    """
    df_valido = df_fuente.dropna(subset=["sector", "industry"]).copy()

    agg = df_valido.groupby(["sector", "industry"]).agg(
        n_tickers            = ("ticker", "count"),
        beta_avg             = ("beta", "mean"),
        beta_median          = ("beta", "median"),
        pe_avg               = ("trailingPE", "mean"),
        pe_median            = ("trailingPE", "median"),
        forward_pe_avg       = ("forwardPE", "mean"),
        dividend_yield_avg   = ("dividendYield", "mean"),
        roe_avg              = ("returnOnEquity", "mean"),
        debt_to_equity_avg   = ("debtToEquity", "mean"),
        score_final_avg      = ("score_FINAL_adj", "mean"),
        score_final_median   = ("score_FINAL_adj", "median"),
        score_valuation_avg  = ("score_valuation", "mean"),
        score_momentum_avg   = ("score_momentum_calidad", "mean"),
        score_deep_value_avg = ("score_deep_value", "mean"),
        rank_avg             = ("rank", "mean"),
        market_cap_total     = ("marketCap", "sum"),
    ).reset_index()

    agg = agg[agg["n_tickers"] >= MIN_TICKERS_POR_GRUPO].copy()
    agg["nivel"] = "industry"
    agg["grupo"] = agg["industry"]
    return agg

def calcular_metricas_sector(df_industria):
    """
    Agrega el nivel SECTOR a partir del nivel INDUSTRIA ya calculado,
    usando promedio ponderado por n_tickers de cada industria.
    Garantiza consistencia: sector = agregado de sus industrias, nunca
    un calculo independiente sobre los tickers sueltos.
    """
    cols_a_ponderar = [
        "beta_avg", "beta_median", "pe_avg", "pe_median", "forward_pe_avg",
        "dividend_yield_avg", "roe_avg", "debt_to_equity_avg",
        "score_final_avg", "score_final_median", "score_valuation_avg",
        "score_momentum_avg", "score_deep_value_avg", "rank_avg",
    ]

    filas_sector = []
    for sector, sub in df_industria.groupby("sector"):
        n_total = sub["n_tickers"].sum()
        fila = {"sector": sector, "industry": np.nan, "n_tickers": n_total}
        for col in cols_a_ponderar:
            valores_validos = sub.dropna(subset=[col])
            if valores_validos.empty or valores_validos["n_tickers"].sum() == 0:
                fila[col] = np.nan
            else:
                fila[col] = (
                    (valores_validos[col] * valores_validos["n_tickers"]).sum()
                    / valores_validos["n_tickers"].sum()
                )
        fila["market_cap_total"] = sub["market_cap_total"].sum()
        filas_sector.append(fila)

    df_sector = pd.DataFrame(filas_sector)
    df_sector["nivel"] = "sector"
    df_sector["grupo"] = df_sector["sector"]
    return df_sector

# ── Calculo del snapshot de HOY ──
df_industria_hoy = calcular_metricas_industria(df)
df_sector_hoy    = calcular_metricas_sector(df_industria_hoy)

columnas_finales = [
    "sector", "industry", "nivel", "grupo", "n_tickers",
    "beta_avg", "beta_median", "pe_avg", "pe_median", "forward_pe_avg",
    "dividend_yield_avg", "roe_avg", "debt_to_equity_avg",
    "score_final_avg", "score_final_median", "score_valuation_avg",
    "score_momentum_avg", "score_deep_value_avg", "rank_avg", "market_cap_total",
]

df_snapshot_grupos = pd.concat(
    [df_industria_hoy[columnas_finales], df_sector_hoy[columnas_finales]],
    ignore_index=True
)
df_snapshot_grupos["snapshot_date"] = fetch_date

# ── Append al historico, con el mismo patron dedupe-por-fecha que ya usas en 17B ──
if os.path.exists(SECTOR_INDUSTRY_HISTORY_FILE):
    df_hist_grupos = pd.read_parquet(SECTOR_INDUSTRY_HISTORY_FILE)
    df_hist_grupos = df_hist_grupos[df_hist_grupos["snapshot_date"] != fetch_date]
    df_hist_grupos = pd.concat([df_hist_grupos, df_snapshot_grupos], ignore_index=True)
else:
    df_hist_grupos = df_snapshot_grupos

df_hist_grupos = df_hist_grupos.sort_values(["snapshot_date", "nivel", "sector", "industry"]).reset_index(drop=True)
df_hist_grupos.to_parquet(SECTOR_INDUSTRY_HISTORY_FILE, index=False)

n_industrias_hoy = (df_snapshot_grupos["nivel"] == "industry").sum()
n_sectores_hoy   = (df_snapshot_grupos["nivel"] == "sector").sum()
print(f"✅ {SECTOR_INDUSTRY_HISTORY_FILE} actualizado:")
print(f"   {n_industrias_hoy} industrias | {n_sectores_hoy} sectores | snapshot {fetch_date}")
print(f"   {df_hist_grupos['snapshot_date'].nunique()} fechas historicas en total")

# ─────────────────────────────────────────────
# 18. APPEND DIARIO → Actual_Stock.parquet (sin cambios)
# ─────────────────────────────────────────────
if os.path.exists(PRICES_FILE):
    df_existente = read_parquet_prices(PRICES_FILE)
    start_date   = df_existente.index.min().strftime("%Y-%m-%d")

    new_tickers = [t for t in tickers if t not in df_existente.columns]

    if new_tickers:
        print(f"\n🆕 {len(new_tickers)} tickers nuevos detectados: {new_tickers}")
        print(f"   Descargando histórico completo desde {start_date}...")
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
                df_existente.loc[fechas_overlap, col] = (
                    prices_new.loc[fechas_overlap, col].values
                )
            print(f"   ✅ Histórico incorporado para {len(new_tickers)} tickers nuevos.")

        except Exception as e:
            print(f"   ⚠  Error descargando histórico de nuevos tickers: {e}")

    todas_cols    = df_existente.columns.union(prices.columns)
    df_existente  = df_existente.reindex(columns=todas_cols)
    fechas_nuevas = prices.index.difference(df_existente.index)

    if len(fechas_nuevas) > 0:
        df_nuevas = prices.loc[fechas_nuevas].reindex(columns=todas_cols)
        df_final  = pd.concat([df_existente, df_nuevas]).sort_index()
        print(f"\n📈 {len(fechas_nuevas)} fechas nuevas agregadas.")
    else:
        df_final = df_existente
        print("\n✅ Sin fechas nuevas — parquet ya al día.")

    df_long = save_parquet_pbi(df_final, PRICES_FILE)

else:
    df_long = save_parquet_pbi(prices, PRICES_FILE)
    print(f"\n📊 Parquet creado desde cero: {len(prices)} filas.")

print(f"💾 Parquet guardado: {len(df_long):,} filas | "
      f"{df_long['Ticker'].nunique()} tickers | "
      f"{df_long['Date'].min()} → {df_long['Date'].max()}")

# ═══════════════════════════════════════════════════════════
# 18B. NUEVO BLOQUE — TENDENCIA SEMANAL (cruce de medias moviles)
#     Usa el HISTORICO COMPLETO ya guardado en Actual_Stock.parquet
#     (no los 6 meses de 'prices'), porque necesitamos ~45 semanas
#     minimo para una MA40 semanal confiable.
# ═══════════════════════════════════════════════════════════
print("\n📐 Calculando tendencia semanal (cruce de medias moviles)...")

MA_CORTA_SEMANAL       = 10
MA_LARGA_SEMANAL       = 40
MIN_SEMANAS_REQUERIDAS = MA_LARGA_SEMANAL + 5

precios_historico_completo = read_parquet_prices(PRICES_FILE)   # reusa tu funcion ya existente

tendencia_semanal_dict = {}

for t in data.keys():   # solo tickers con descarga exitosa hoy
    if t not in precios_historico_completo.columns:
        tendencia_semanal_dict[t] = {
            "tendencia_semanal_alcista": np.nan,
            "semanas_desde_golden_cross": np.nan,
            "semanas_desde_death_cross": np.nan,
            "señal_tendencia": "Sin datos de precio",
        }
        continue

    serie_diaria_t  = precios_historico_completo[t].dropna()
    serie_semanal_t = serie_diaria_t.resample("W").last().dropna()

    if len(serie_semanal_t) < MIN_SEMANAS_REQUERIDAS:
        tendencia_semanal_dict[t] = {
            "tendencia_semanal_alcista": np.nan,
            "semanas_desde_golden_cross": np.nan,
            "semanas_desde_death_cross": np.nan,
            "señal_tendencia": "Historial insuficiente",
        }
        continue

    ma_corta_sem   = serie_semanal_t.rolling(MA_CORTA_SEMANAL).mean()
    ma_larga_sem   = serie_semanal_t.rolling(MA_LARGA_SEMANAL).mean()
    diferencia_sem = ma_corta_sem - ma_larga_sem

    cruce_alcista = (diferencia_sem > 0) & (diferencia_sem.shift(1) <= 0)
    cruce_bajista = (diferencia_sem < 0) & (diferencia_sem.shift(1) >= 0)

    alcista_hoy = bool(ma_corta_sem.iloc[-1] > ma_larga_sem.iloc[-1])

    fechas_cruce_alcista = serie_semanal_t.index[cruce_alcista.fillna(False)]
    fechas_cruce_bajista = serie_semanal_t.index[cruce_bajista.fillna(False)]

    semanas_desde_golden = (
        int((serie_semanal_t.index[-1] - fechas_cruce_alcista[-1]).days / 7)
        if len(fechas_cruce_alcista) > 0 else np.nan
    )
    semanas_desde_death = (
        int((serie_semanal_t.index[-1] - fechas_cruce_bajista[-1]).days / 7)
        if len(fechas_cruce_bajista) > 0 else np.nan
    )

    if alcista_hoy:
        señal = "Golden Cross reciente" if (pd.notna(semanas_desde_golden) and semanas_desde_golden <= 4) else "Tendencia alcista establecida"
    else:
        señal = "Death Cross reciente" if (pd.notna(semanas_desde_death) and semanas_desde_death <= 4) else "Tendencia bajista establecida"

    tendencia_semanal_dict[t] = {
        "tendencia_semanal_alcista": alcista_hoy,
        "semanas_desde_golden_cross": semanas_desde_golden,
        "semanas_desde_death_cross": semanas_desde_death,
        "señal_tendencia": señal,
    }

n_con_señal = sum(1 for v in tendencia_semanal_dict.values() if v["señal_tendencia"] != "Historial insuficiente" and v["señal_tendencia"] != "Sin datos de precio")
print(f"   ✅ Tendencia semanal calculada para {n_con_señal}/{len(tendencia_semanal_dict)} tickers "
      f"(requiere ≥{MIN_SEMANAS_REQUERIDAS} semanas de historico)")

# ═══════════════════════════════════════════════════════════
# 19. NUEVO BLOQUE — KPIs AVANZADOS (archivo separado)
#     No modifica Stock_Screener_PRO.csv ni los parquet existentes.
#     Reutiliza info_completo (ya descargado) y prices (ya descargado).
# ═══════════════════════════════════════════════════════════
print("\n" + "="*60)
print("🧮 CALCULANDO KPIs AVANZADOS (archivo nuevo, separado de Power BI)")
print("="*60)

def calcular_piotroski_adj_(info):
    """
    Piotroski F-Score ADAPTADO (no el académico de 9 puntos).
    Usa solo 6 tests posibles con datos de snapshot único (sin balance
    de 2 años consecutivos, que requeriría .balance_sheet per-ticker).
    Se normaliza sobre 6 aunque falten tests individuales, para no
    penalizar por datos faltantes.
    """
    tests = {}
    roa = info.get("returnOnAssets")
    if roa is not None:
        tests["roa_positivo"] = 1 if roa > 0 else 0
    ocf = info.get("operatingCashflow")
    if ocf is not None:
        tests["ocf_positivo"] = 1 if ocf > 0 else 0
    ni = info.get("netIncome")
    if ocf is not None and ni is not None:
        tests["ocf_mayor_ni"] = 1 if ocf > ni else 0
    cr = info.get("currentRatio")
    if cr is not None:
        tests["current_ratio_sano"] = 1 if cr > 1 else 0
    qr = info.get("quickRatio")
    if qr is not None:
        tests["quick_ratio_sano"] = 1 if qr > 1 else 0
    gm = info.get("grossMargins")
    if gm is not None:
        tests["margen_bruto_positivo"] = 1 if gm > 0 else 0

    n_tests = len(tests)
    if n_tests == 0:
        return np.nan, 0, 0
    score_raw     = sum(tests.values())
    score_sobre_6 = round((score_raw / n_tests) * 6, 2)
    return score_sobre_6, score_raw, n_tests

def calcular_ratios_riesgo_(retornos_diarios, rf_anual=RISK_FREE_RATE_ANUAL,
                             min_obs=MIN_OBS_RATIOS_RIESGO):
    """
    Sharpe, Sortino y VaR historico 95% a partir de retornos diarios ya
    calculados sobre los precios que YA se descargaron en el paso 3.
    Cero llamadas de red adicionales.
    """
    out = dict(sharpe=np.nan, sortino=np.nan, var_95=np.nan)
    retornos = pd.Series(retornos_diarios).dropna()
    if len(retornos) < min_obs:
        return out

    ret_prom_anual = retornos.mean() * 252
    vol_anual      = retornos.std() * np.sqrt(252)
    if vol_anual and vol_anual > 0:
        out["sharpe"] = (ret_prom_anual - rf_anual) / vol_anual

    negativos = retornos[retornos < 0]
    if len(negativos) >= 2:
        downside_dev_anual = negativos.std() * np.sqrt(252)
        if downside_dev_anual and downside_dev_anual > 0:
            out["sortino"] = (ret_prom_anual - rf_anual) / downside_dev_anual

    out["var_95"] = retornos.quantile(0.05)
    return out

def calcular_dividend_growth_(serie_dividendos_por_anio):
    """
    A partir de la serie de dividendos anuales (ya descargada en bloque
    en el paso 3B), calcula años consecutivos de aumento y el crecimiento
    promedio interanual.
    """
    serie = serie_dividendos_por_anio.dropna()
    if len(serie) < 2:
        return 0, np.nan
    streak  = 0
    valores = serie.values
    for i in range(len(valores) - 1, 0, -1):
        if valores[i] > valores[i - 1]:
            streak += 1
        else:
            break
    crecimiento_prom = serie.pct_change().replace([np.inf, -np.inf], np.nan).dropna().mean()
    return streak, crecimiento_prom

# ---- Loop principal de KPIs avanzados: reusa info_completo y prices, sin red nueva ----
filas_avanzadas = []

for t in data.keys():   # solo tickers que ya tuvieron descarga exitosa en el paso 4
    info = info_completo.get(t, {})
    fila = {"ticker": t}

    # -- campos "gratis" del mismo info ya descargado --
    for attr in ADVANCED_ATTRIBUTES:
        fila[attr] = info.get(attr)

    # -- Piotroski adaptado --
    score_p, raw_p, n_tests_p = calcular_piotroski_adj_(info)
    fila["piotroski_score_adj"]   = score_p
    fila["piotroski_tests_ok"]    = raw_p
    fila["piotroski_tests_total"] = n_tests_p

    # -- analyst upside --
    target_mean = info.get("targetMeanPrice")
    precio_actual = last_price.get(t) if hasattr(last_price, "get") else None
    if precio_actual is None and t in last_price.index:
        precio_actual = last_price[t]
    if target_mean and precio_actual and precio_actual > 0:
        fila["analyst_upside"] = (target_mean / precio_actual) - 1
    else:
        fila["analyst_upside"] = np.nan

    # -- ratios de riesgo (Sharpe, Sortino, VaR) usando precios ya descargados --
    if t in prices.columns:
        serie_precios = prices[t].dropna()
        retornos_t    = serie_precios.pct_change().dropna()
        ratios        = calcular_ratios_riesgo_(retornos_t)
        fila["sharpe_ratio"]  = ratios["sharpe"]
        fila["sortino_ratio"] = ratios["sortino"]
        fila["var_95_diario"] = ratios["var_95"]
    else:
        fila["sharpe_ratio"]  = np.nan
        fila["sortino_ratio"] = np.nan
        fila["var_95_diario"] = np.nan

    # -- dividend growth streak (usa el bloque descargado en paso 3B) --
    if t in dividendos_por_ticker:
        streak, crecimiento = calcular_dividend_growth_(dividendos_por_ticker[t])
        fila["dividend_growth_streak"] = streak
        fila["dividend_growth_avg"]    = crecimiento
    else:
        fila["dividend_growth_streak"] = 0
        fila["dividend_growth_avg"]    = np.nan

    fila.update(tendencia_semanal_dict.get(t, {
        "tendencia_semanal_alcista": np.nan,
        "semanas_desde_golden_cross": np.nan,
        "semanas_desde_death_cross": np.nan,
        "señal_tendencia": "Sin datos de precio",
    }))

    filas_avanzadas.append(fila)
    
    # ══════════════════════════════════════════════════
    # GRUPO A: VALORACIÓN PROFUNDA
    # ══════════════════════════════════════════════════
    
    # A1: FCF Yield
    market_cap = info.get("marketCap")
    fcf        = info.get("freeCashflow")
    fila["fcf_yield"] = (
        fcf / market_cap
        if (fcf and market_cap and market_cap > 0) else np.nan
    )
    
    # A2: Price / FCF
    shares_out = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
    precio_t   = last_price[t] if t in last_price.index else np.nan
    if fcf and shares_out and shares_out > 0 and fcf > 0 and not np.isnan(precio_t):
        fila["price_to_fcf"] = precio_t / (fcf / shares_out)
    else:
        fila["price_to_fcf"] = np.nan
    
    # A3: Graham Number + Margin of Safety
    eps      = info.get("trailingEps")
    book_val = info.get("bookValue")
    if eps and book_val and eps > 0 and book_val > 0:
        graham = np.sqrt(22.5 * eps * book_val)
        fila["graham_number"]           = graham
        fila["graham_margin_of_safety"] = (graham / precio_t - 1) if not np.isnan(precio_t) and precio_t > 0 else np.nan
    else:
        fila["graham_number"]           = np.nan
        fila["graham_margin_of_safety"] = np.nan
    
    # A4: EV / Sales
    ev      = info.get("enterpriseValue")
    revenue = info.get("totalRevenue")
    fila["ev_to_sales"] = ev / revenue if (ev and revenue and revenue > 0) else np.nan
    
    # A5: Earnings Quality (OCF / Net Income)
    ocf = info.get("operatingCashflow")
    ni  = info.get("netIncome")
    fila["earnings_quality"] = ocf / ni if (ocf and ni and ni != 0) else np.nan
    
    # ══════════════════════════════════════════════════
    # GRUPO B: RIESGO AMPLIADO (usa prices ya en memoria)
    # ══════════════════════════════════════════════════
    
    if t in prices.columns:
        serie_p = prices[t].dropna()
    
        # B1: Max Drawdown + Drawdown actual
        rolling_max = serie_p.cummax()
        drawdown    = (serie_p - rolling_max) / rolling_max
        fila["max_drawdown"]      = drawdown.min()
        fila["current_drawdown"]  = float(drawdown.iloc[-1])
    
        # B2: Calmar Ratio
        n_years = len(serie_p) / 252
        if n_years > 0 and serie_p.iloc[0] > 0 and abs(fila["max_drawdown"]) > 0:
            cagr_p = (serie_p.iloc[-1] / serie_p.iloc[0]) ** (1 / n_years) - 1
            fila["calmar_ratio"] = cagr_p / abs(fila["max_drawdown"])
        else:
            fila["calmar_ratio"] = np.nan
    
        # B3: Volatilidad anualizada
        retornos_t = serie_p.pct_change().dropna()
        fila["volatility_annual"] = retornos_t.std() * np.sqrt(252)
    
        # B4: RSI 14 días
        delta     = serie_p.diff().dropna()
        ganan     = delta.clip(lower=0)
        pierden   = (-delta).clip(lower=0)
        avg_g     = ganan.ewm(alpha=1/14, min_periods=14).mean()
        avg_p     = pierden.ewm(alpha=1/14, min_periods=14).mean()
        rs        = avg_g / avg_p.replace(0, np.nan)
        rsi_serie = 100 - (100 / (1 + rs))
        fila["rsi_14"] = float(rsi_serie.iloc[-1]) if len(rsi_serie) > 0 else np.nan
    
        # B5: Momentum multi-período
        fila["momentum_1m"] = (serie_p.iloc[-1] / serie_p.iloc[-21] - 1)  if len(serie_p) >= 21  else np.nan
        fila["momentum_3m"] = (serie_p.iloc[-1] / serie_p.iloc[-63] - 1)  if len(serie_p) >= 63  else np.nan
        fila["momentum_6m"] = (serie_p.iloc[-1] / serie_p.iloc[-126] - 1) if len(serie_p) >= 126 else np.nan
    
    else:
        for campo in ["max_drawdown", "current_drawdown", "calmar_ratio",
                      "volatility_annual", "rsi_14",
                      "momentum_1m", "momentum_3m", "momentum_6m"]:
            fila[campo] = np.nan
    
    # ══════════════════════════════════════════════════
    # GRUPO C: SOLIDEZ FINANCIERA
    # ══════════════════════════════════════════════════
    
    # C1: Net Debt / EBITDA
    total_debt  = info.get("totalDebt") or 0
    total_cash  = info.get("totalCash") or 0
    ebitda_val  = info.get("ebitda")
    net_debt    = total_debt - total_cash
    fila["net_debt"]            = net_debt
    fila["net_debt_to_ebitda"]  = (
        net_debt / ebitda_val
        if (ebitda_val and ebitda_val > 0) else np.nan
    )
    
    # C2: ROIC
    ebit_val   = info.get("ebit")
    tax_rate   = info.get("effectiveTaxRate") or 0.21
    curr_liab  = info.get("totalCurrentLiabilities") or 0
    tot_assets = info.get("totalAssets")
    if ebit_val and tot_assets and (tot_assets - curr_liab) > 0:
        fila["roic"] = ebit_val * (1 - tax_rate) / (tot_assets - curr_liab)
    else:
        fila["roic"] = np.nan
    
    # C3: Asset Turnover
    fila["asset_turnover"] = (
        revenue / tot_assets
        if (revenue and tot_assets and tot_assets > 0) else np.nan
    )
    
    # C4: Interest Coverage
    ebit_v     = info.get("ebit")
    int_exp    = info.get("interestExpense")  # yfinance devuelve negativo
    if ebit_v and int_exp and int_exp < 0:
        fila["interest_coverage"] = ebit_v / abs(int_exp)
    else:
        fila["interest_coverage"] = np.nan
    
    # C5: Working Capital
    curr_assets = info.get("totalCurrentAssets")
    curr_liab_v = info.get("totalCurrentLiabilities")
    fila["working_capital"] = (
        curr_assets - curr_liab_v
        if (curr_assets and curr_liab_v) else np.nan
    )
    
    # ══════════════════════════════════════════════════
    # GRUPO D: SENTIMIENTO Y ANALISTAS
    # ══════════════════════════════════════════════════
    
    # D1: Analyst Conviction Score (consenso ponderado por cobertura)
    rec_mean   = info.get("recommendationMean")  # 1=Strong Buy ... 5=Strong Sell
    n_analysts = info.get("numberOfAnalystOpinions") or 0
    if rec_mean and n_analysts > 0:
        conviction_raw    = (5 - rec_mean) / 4          # 0-1, mayor = más alcista
        coverage_weight   = min(n_analysts / 20, 1.0)   # satura en 20 analistas
        fila["analyst_conviction"] = conviction_raw * coverage_weight
    else:
        fila["analyst_conviction"] = np.nan
    
    # D2: Short % Float
    shares_short = info.get("sharesShort")
    float_shares = info.get("floatShares") or info.get("sharesOutstanding")
    fila["short_pct_float"] = (
        shares_short / float_shares
        if (shares_short and float_shares and float_shares > 0) else np.nan
    )
    
    # D3: Beta ajustado Blume
    raw_beta = info.get("beta")
    fila["beta_adj"] = (0.67 * raw_beta + 0.33) if raw_beta is not None else np.nan


df_avanzado = pd.DataFrame(filas_avanzadas)

# Conversión numérica explícita (mismo patrón defensivo que el resto del script)
STR_COLS_AVANZADO = ["ticker", "recommendationKey", "señal_tendencia"]
for col in df_avanzado.columns:
    if col not in STR_COLS_AVANZADO:
        df_avanzado[col] = to_numeric_safe(df_avanzado[col])


df_avanzado.to_parquet(ADVANCED_METRICS_FILE, index=False)

print(f"✅ {ADVANCED_METRICS_FILE} generado: "
      f"{len(df_avanzado)} tickers | {len(df_avanzado.columns)} columnas")
print(f"   Piotroski adaptado calculado para "
      f"{df_avanzado['piotroski_score_adj'].notna().sum()} tickers")
print(f"   Sharpe/Sortino/VaR calculado para "
      f"{df_avanzado['sharpe_ratio'].notna().sum()} tickers "
      f"(requiere ≥{MIN_OBS_RATIOS_RIESGO} observaciones)")
print(f"   Dividend growth streak disponible para "
      f"{(df_avanzado['dividend_growth_streak'] > 0).sum()} tickers")

# ─────────────────────────────────────────────
# VALIDACION DEFENSIVA: evita que un CONFIG renombrado rompa el resumen final
# despues de que todo el trabajo pesado (11+ min) ya se hizo y los archivos
# ya se guardaron. Si falta una columna esperada, avisa pero NO frena el pipeline.
# ─────────────────────────────────────────────
columnas_top15_deseadas = [
    "rank", "ticker", "shortName", "score_FINAL_adj",
    "rating", "data_completeness",
    "score_valuation", "score_deep_value", "score_profitability",
    "score_momentum_calidad", "score_fundamental_momentum"
]
columnas_disponibles = [c for c in columnas_top15_deseadas if c in df.columns]
columnas_faltantes   = [c for c in columnas_top15_deseadas if c not in df.columns]

if columnas_faltantes:
    print(f"\n⚠  Columnas no encontradas para el resumen Top 15 (no critico, "
          f"los archivos YA se guardaron correctamente): {columnas_faltantes}")

top15 = df.sort_values("rank")[columnas_disponibles].head(15)

# ─────────────────────────────────────────────
# 20. RESUMEN CONSOLA (screener original, sin cambios)
# ─────────────────────────────────────────────
print("\n" + "="*60)
print("🏆 TOP 15 — RANKING FINAL")
print("="*60)


top15 = df.sort_values("rank")[
    ["rank", "ticker", "shortName", "score_FINAL_adj",
     "rating", "data_completeness",
     "score_valuation", "score_deep_value", "score_profitability",
     "score_momentum_calidad", "score_fundamental_momentum"]
].head(15)


print(top15.to_string(index=False))

print(f"\n📊 Distribución de ratings:")
print(df["rating"].value_counts().to_string())

print(f"\n📐 Completeness promedio de datos: "
      f"{df['data_completeness'].mean():.1f}%")
