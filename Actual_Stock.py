import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime

# ─────────────────────────────────────────────
# 1. CONFIG
# ─────────────────────────────────────────────
tickers = pd.read_csv("Tickers.csv")["ticker"].dropna().tolist()

# ─────────────────────────────────────────────
# 2. PRECIOS
# ─────────────────────────────────────────────
prices = yf.download(tickers, period="6mo", progress=False)["Close"]

if isinstance(prices, pd.Series):
    prices = prices.to_frame(name=tickers[0])

last_price = prices.iloc[-1]

# ─────────────────────────────────────────────
# 3. FUNDAMENTALES (.info)
# ─────────────────────────────────────────────
ATTRIBUTES = [
    "shortName", "sector", "industry",
    "trailingPE", "forwardPE", "priceToBook", "enterpriseToEbitda",
    "returnOnEquity", "profitMargins", "operatingMargins",
    "revenueGrowth", "earningsGrowth",
    "debtToEquity", "currentRatio", "freeCashflow",
    "fiftyDayAverage", "twoHundredDayAverage",
    # Nuevos atributos para enriquecer el análisis
    "ebitda", "totalRevenue", "totalDebt", "totalCash",
    "operatingCashflow", "grossProfits", "marketCap",
    "returnOnAssets", "ebitdaMargins", "grossMargins",
]

data = {}
for t in tickers:
    try:
        info = yf.Ticker(t).info
        data[t] = {a: info.get(a) for a in ATTRIBUTES}
    except Exception:
        continue

df = pd.DataFrame.from_dict(data, orient="index").reset_index()
df.rename(columns={"index": "ticker"}, inplace=True)

# ─────────────────────────────────────────────
# 4. ESTADOS FINANCIEROS HISTÓRICOS
# ─────────────────────────────────────────────
def get_financial_history(ticker_symbol: str) -> pd.DataFrame:
    """
    Descarga income statement, balance sheet y cash flow
    (anual y quarterly) y los retorna en formato long:
    ticker | period_type | date | metric | value
    """
    ticker_yf = yf.Ticker(ticker_symbol)
    statements = {
        "income_annual":     ticker_yf.income_stmt,
        "income_quarterly":  ticker_yf.quarterly_income_stmt,
        "balance_annual":    ticker_yf.balance_sheet,
        "balance_quarterly": ticker_yf.quarterly_balance_sheet,
        "cashflow_annual":   ticker_yf.cashflow,
        "cashflow_quarterly":ticker_yf.quarterly_cashflow,
    }
    frames = []
    for period_type, df_stmt in statements.items():
        if df_stmt is None or df_stmt.empty:
            continue
        df_long = df_stmt.stack(future_stack=True).reset_index()
        df_long.columns = ["metric", "date", "value"]
        df_long["ticker"] = ticker_symbol
        df_long["period_type"] = period_type
        frames.append(df_long[["ticker", "period_type", "date", "metric", "value"]])
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def compute_derived_metrics(ticker_symbol: str, df_hist: pd.DataFrame) -> dict:
    """
    A partir de los estados financieros históricos calcula métricas
    derivadas para enriquecer el scoring:

    Crecimiento (CAGR y YoY):
      - revenue_cagr_3y     : CAGR de Total Revenue en 3 años
      - ebitda_growth_yoy   : variación YoY del EBITDA (anual)
      - fcf_growth_yoy      : variación YoY del Free Cash Flow
      - gross_profit_growth : variación YoY del Gross Profit

    Calidad:
      - fcf_margin          : FCF / Revenue (último año)
      - fcf_to_net_income   : FCF / Net Income (calidad de earnings)
      - gross_margin_trend  : pendiente del margen bruto en los últimos 4 años
      - capex_to_revenue    : CapEx / Revenue (eficiencia de inversión)

    Deuda y cobertura:
      - net_debt_to_ebitda  : (Deuda Total - Caja) / EBITDA
      - interest_coverage   : EBIT / Interest Expense
      - net_debt            : Total Debt - Total Cash

    Retorno:
      - roic                : EBIT*(1-tax_rate) / (Equity + Net Debt)
                              (aproximación con datos disponibles)
    """
    metrics = {}

    if df_hist.empty:
        return metrics

    def get_series(period_type: str, metric_name: str) -> pd.Series:
        """Extrae una serie temporal para un statement/métrica dados."""
        subset = df_hist[
            (df_hist["ticker"] == ticker_symbol) &
            (df_hist["period_type"] == period_type) &
            (df_hist["metric"] == metric_name)
        ].copy()
        if subset.empty:
            return pd.Series(dtype=float)
        subset["date"] = pd.to_datetime(subset["date"])
        return subset.set_index("date")["value"].sort_index().dropna()

    # ── Series anuales principales ──────────────────────────
    rev  = get_series("income_annual", "Total Revenue")
    ebit = get_series("income_annual", "EBIT")
    ebitda_s = get_series("income_annual", "EBITDA")
    ni   = get_series("income_annual", "Net Income")
    gp   = get_series("income_annual", "Gross Profit")

    # Balance sheet anual
    total_debt   = get_series("balance_annual", "Total Debt")
    cash         = get_series("balance_annual", "Cash And Cash Equivalents")
    equity       = get_series("balance_annual", "Stockholders Equity")

    # Cash flow anual
    fcf_s        = get_series("cashflow_annual", "Free Cash Flow")
    capex_s      = get_series("cashflow_annual", "Capital Expenditure")
    interest_exp = get_series("income_annual", "Interest Expense")

    # ── Revenue CAGR 3 años ─────────────────────────────────
    if len(rev) >= 4:
        r_new = rev.iloc[-1]
        r_old = rev.iloc[-4]
        if r_old and r_old > 0:
            metrics["revenue_cagr_3y"] = (r_new / r_old) ** (1 / 3) - 1

    # ── EBITDA growth YoY ───────────────────────────────────
    if len(ebitda_s) >= 2:
        e_new = ebitda_s.iloc[-1]
        e_old = ebitda_s.iloc[-2]
        if e_old and e_old != 0:
            metrics["ebitda_growth_yoy"] = (e_new - e_old) / abs(e_old)

    # ── FCF growth YoY ─────────────────────────────────────
    if len(fcf_s) >= 2:
        f_new = fcf_s.iloc[-1]
        f_old = fcf_s.iloc[-2]
        if f_old and f_old != 0:
            metrics["fcf_growth_yoy"] = (f_new - f_old) / abs(f_old)

    # ── Gross profit growth YoY ────────────────────────────
    if len(gp) >= 2:
        g_new = gp.iloc[-1]
        g_old = gp.iloc[-2]
        if g_old and g_old != 0:
            metrics["gross_profit_growth"] = (g_new - g_old) / abs(g_old)

    # ── FCF Margin ─────────────────────────────────────────
    if len(fcf_s) >= 1 and len(rev) >= 1:
        rev_last = rev.iloc[-1]
        if rev_last and rev_last > 0:
            metrics["fcf_margin"] = fcf_s.iloc[-1] / rev_last

    # ── FCF / Net Income (calidad de earnings) ─────────────
    if len(fcf_s) >= 1 and len(ni) >= 1:
        ni_last = ni.iloc[-1]
        if ni_last and ni_last != 0:
            metrics["fcf_to_net_income"] = fcf_s.iloc[-1] / abs(ni_last)

    # ── Gross margin trend (pendiente lineal) ───────────────
    if len(rev) >= 3 and len(gp) >= 3:
        gm = (gp / rev).dropna()
        if len(gm) >= 3:
            x = np.arange(len(gm))
            slope = np.polyfit(x, gm.values, 1)[0]
            metrics["gross_margin_trend"] = slope

    # ── CapEx / Revenue ─────────────────────────────────────
    if len(capex_s) >= 1 and len(rev) >= 1:
        rev_last = rev.iloc[-1]
        if rev_last and rev_last > 0:
            # CapEx suele ser negativo en Yahoo Finance
            metrics["capex_to_revenue"] = abs(capex_s.iloc[-1]) / rev_last

    # ── Net Debt to EBITDA ──────────────────────────────────
    if len(total_debt) >= 1 and len(cash) >= 1 and len(ebitda_s) >= 1:
        nd = total_debt.iloc[-1] - cash.iloc[-1]
        eb = ebitda_s.iloc[-1]
        metrics["net_debt"] = nd
        if eb and eb > 0:
            metrics["net_debt_to_ebitda"] = nd / eb

    # ── Interest Coverage (EBIT / Interest Expense) ─────────
    if len(ebit) >= 1 and len(interest_exp) >= 1:
        ie = interest_exp.iloc[-1]
        if ie and ie != 0:
            metrics["interest_coverage"] = ebit.iloc[-1] / abs(ie)

    # ── ROIC aproximado ─────────────────────────────────────
    # ROIC = EBIT * (1 - tax_approx) / Invested Capital
    # tax_approx = 0.21, Invested Capital = Equity + Net Debt
    if (len(ebit) >= 1 and len(equity) >= 1 and
            "net_debt" in metrics and equity.iloc[-1] not in (None, 0)):
        ebit_last = ebit.iloc[-1]
        nopat = ebit_last * (1 - 0.21)
        invested_capital = equity.iloc[-1] + metrics["net_debt"]
        if invested_capital and invested_capital > 0:
            metrics["roic"] = nopat / invested_capital

    return metrics


# ─── Descargar y calcular métricas históricas para todos los tickers ───
print("⏳ Descargando estados financieros históricos...")
financial_records = []
derived_metrics_list = []

for t in tickers:
    try:
        df_hist = get_financial_history(t)
        financial_records.append(df_hist)
        derived = compute_derived_metrics(t, df_hist)
        derived["ticker"] = t
        derived_metrics_list.append(derived)
    except Exception as e:
        print(f"  ⚠️  {t}: {e}")
        continue

# Guardar histórico completo
if financial_records:
    df_history_all = pd.concat(financial_records, ignore_index=True)
    df_history_all.to_csv("Financial_History.csv", index=False)
    print("✅ Financial_History.csv guardado.")

# Unir métricas derivadas al dataframe principal
if derived_metrics_list:
    df_derived = pd.DataFrame(derived_metrics_list)
    df = df.merge(df_derived, on="ticker", how="left")
    print(f"✅ {len(df_derived.columns)-1} métricas históricas incorporadas al screening.")

# ─────────────────────────────────────────────
# 5. LIMPIEZA
# ─────────────────────────────────────────────
num_cols = df.select_dtypes(include=np.number).columns
df[num_cols] = df[num_cols].apply(pd.to_numeric, errors="coerce")

# ─────────────────────────────────────────────
# 6. FEATURES DE PRECIO
# ─────────────────────────────────────────────
df["lastPrice"] = df["ticker"].map(last_price)
df["priceVs50dMA"] = df["lastPrice"] / df["fiftyDayAverage"] - 1
df["priceVs200dMA"] = df["lastPrice"] / df["twoHundredDayAverage"] - 1

# ─────────────────────────────────────────────
# 7. WINSORIZATION
# ─────────────────────────────────────────────
def winsorize(s):
    if s.notna().sum() < 10:
        return s
    return s.clip(s.quantile(0.05), s.quantile(0.95))

# ─────────────────────────────────────────────
# 8. IMPUTACIÓN JERÁRQUICA
# ─────────────────────────────────────────────
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
# 9. SCORING CONFIG (expandida con métricas históricas)
# ─────────────────────────────────────────────
# Formato por métrica: (inverse, weight_dentro_de_categoria)
# inverse=True  → menor valor es mejor (ej: PE bajo = más barato)
# inverse=False → mayor valor es mejor (ej: ROE alto = mejor)

CONFIG = {
    "valuation": {
        # Métricas originales
        "trailingPE":          (True,  0.20),
        "forwardPE":           (True,  0.20),
        "priceToBook":         (True,  0.15),
        "enterpriseToEbitda":  (True,  0.20),
        # Nuevas métricas históricas
        "net_debt_to_ebitda":  (True,  0.25),   # Deuda neta / EBITDA: menos es mejor
        "weight": 0.25
    },
    "profitability": {
        # Métricas originales
        "returnOnEquity":      (False, 0.20),
        "profitMargins":       (False, 0.15),
        "operatingMargins":    (False, 0.15),
        # Nuevas métricas históricas
        "fcf_margin":          (False, 0.20),    # Margen FCF: mayor = mejor calidad de earnings
        "roic":                (False, 0.20),    # ROIC: retorno sobre capital invertido
        "fcf_to_net_income":   (False, 0.10),    # FCF/NI > 1 indica earnings de alta calidad
        "weight": 0.25
    },
    "growth": {
        # Métricas originales
        "revenueGrowth":       (False, 0.20),
        "earningsGrowth":      (False, 0.20),
        # Nuevas métricas históricas
        "revenue_cagr_3y":     (False, 0.25),    # CAGR 3 años: más robusto que el YoY puntual
        "ebitda_growth_yoy":   (False, 0.15),
        "fcf_growth_yoy":      (False, 0.10),
        "gross_profit_growth": (False, 0.10),
        "weight": 0.20
    },
    "financial_health": {
        # Métricas originales
        "debtToEquity":        (True,  0.25),
        "currentRatio":        (False, 0.20),
        # Nuevas métricas históricas
        "interest_coverage":   (False, 0.30),    # EBIT/InterestExp: mayor = más solvente
        "gross_margin_trend":  (False, 0.25),    # Tendencia del margen bruto (positiva = mejor)
        "weight": 0.15
    },
    "efficiency": {
        # Nuevas métricas históricas
        "capex_to_revenue":    (True,  0.50),    # CapEx/Rev: menor = más eficiente en inversión
        "gross_margin_trend":  (False, 0.50),    # Expansión de margen = mejora operativa
        "weight": 0.10
    },
    "momentum": {
        # Métricas originales
        "priceVs50dMA":        (False, 0.50),
        "priceVs200dMA":       (False, 0.50),
        "weight": 0.05
    }
}

# ─────────────────────────────────────────────
# 10. SCORING POR SECTOR
# ─────────────────────────────────────────────
def score(series, inverse):
    series = winsorize(series)
    r = series.rank(pct=True)
    if inverse:
        r = 1 - r
    return (r * 10).clip(0, 10)

all_metrics = []

for cat, cfg in CONFIG.items():
    if cat == "weight":
        continue
    cat_score = 0
    total_w = 0

    for k, v in cfg.items():
        if k == "weight":
            continue

        inverse, w = v

        if k in df.columns:
            imp = impute(df, k)
            # Score relativo dentro del sector
            s = df.groupby("sector")[imp].transform(lambda x: score(x, inverse))
            df[f"score_{k}"] = s

            cat_score += s * w
            total_w += w
            all_metrics.append(k)

    if total_w > 0:
        df[f"score_{cat}"] = cat_score / total_w
    else:
        df[f"score_{cat}"] = np.nan

# ─────────────────────────────────────────────
# 11. SCORE FINAL PONDERADO
# ─────────────────────────────────────────────
cat_scores = []
total_weight = 0

for cat, cfg in CONFIG.items():
    score_col = f"score_{cat}"
    if score_col in df.columns:
        cat_scores.append(df[score_col] * cfg["weight"])
        total_weight += cfg["weight"]

df["score_FINAL"] = sum(cat_scores) / total_weight

# ─────────────────────────────────────────────
# 12. PENALIZACIÓN POR DATOS FALTANTES
# ─────────────────────────────────────────────
# Las métricas históricas nuevas pueden tener más NaN,
# por eso se penaliza más suavemente (0.6 base en vez de 0.7)
valid = df[all_metrics].notna().sum(axis=1)
total = len(all_metrics)

completeness = valid / total
penalty = completeness.clip(lower=0.3)

df["score_FINAL_adj"] = df["score_FINAL"] * (0.6 + 0.4 * penalty)

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
# 14. OUTPUT
# ─────────────────────────────────────────────

# Columnas de scores individuales para auditoría
score_cols = [c for c in df.columns if c.startswith("score_")]
output_cols = (
    ["ticker", "shortName", "sector", "industry", "lastPrice",
     "score_FINAL", "score_FINAL_adj", "rank", "rating"]
    + [f"score_{cat}" for cat in CONFIG if f"score_{cat}" in df.columns]
    + score_cols
)
# Quitar duplicados manteniendo orden
seen = set()
output_cols = [c for c in output_cols if not (c in seen or seen.add(c))]

df.to_csv("Stock_Screener_PRO.csv", index=False)

print("\n🏆 TOP 15")
cols_display = ["ticker", "shortName", "sector", "score_FINAL_adj",
                "score_valuation", "score_profitability", "score_growth",
                "score_financial_health", "score_efficiency", "score_momentum",
                "rating", "rank"]
cols_display = [c for c in cols_display if c in df.columns]
print(df.sort_values("rank")[cols_display].head(15).to_string(index=False))

print("\n📊 DISTRIBUCIÓN DE RATINGS")
print(df["rating"].value_counts())
