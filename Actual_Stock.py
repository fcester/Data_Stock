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
# 3. FUNDAMENTALES
# ─────────────────────────────────────────────
ATTRIBUTES = [
    "shortName","sector","industry",
    "trailingPE","forwardPE","priceToBook","enterpriseToEbitda",
    "returnOnEquity","profitMargins","operatingMargins",
    "revenueGrowth","earningsGrowth",
    "debtToEquity","currentRatio","freeCashflow",
    "fiftyDayAverage","twoHundredDayAverage"
]

data = {}
for t in tickers:
    try:
        info = yf.Ticker(t).info
        data[t] = {a: info.get(a) for a in ATTRIBUTES}
    except:
        continue

df = pd.DataFrame.from_dict(data, orient="index").reset_index()
df.rename(columns={"index":"ticker"}, inplace=True)

# ─────────────────────────────────────────────
# 4. LIMPIEZA
# ─────────────────────────────────────────────
num_cols = df.select_dtypes(include=np.number).columns
df[num_cols] = df[num_cols].apply(pd.to_numeric, errors="coerce")

# ─────────────────────────────────────────────
# 5. FEATURES
# ─────────────────────────────────────────────
df["lastPrice"] = df["ticker"].map(last_price)
df["priceVs50dMA"] = df["lastPrice"]/df["fiftyDayAverage"] - 1
df["priceVs200dMA"] = df["lastPrice"]/df["twoHundredDayAverage"] - 1

# ─────────────────────────────────────────────
# 6. WINSORIZATION
# ─────────────────────────────────────────────
def winsorize(s):
    if s.notna().sum() < 10:
        return s
    return s.clip(s.quantile(0.05), s.quantile(0.95))

# ─────────────────────────────────────────────
# 7. IMPUTACIÓN JERÁRQUICA (TU VERSIÓN)
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
# 8. SCORING CONFIG
# ─────────────────────────────────────────────
CONFIG = {
    "valuation": {
        "trailingPE": (True, 0.25),
        "forwardPE": (True, 0.25),
        "priceToBook": (True, 0.25),
        "enterpriseToEbitda": (True, 0.25),
        "weight": 0.25
    },
    "profitability": {
        "returnOnEquity": (False, 0.4),
        "profitMargins": (False, 0.3),
        "operatingMargins": (False, 0.3),
        "weight": 0.25
    },
    "growth": {
        "revenueGrowth": (False, 0.5),
        "earningsGrowth": (False, 0.5),
        "weight": 0.2
    },
    "financial": {
        "debtToEquity": (True, 0.5),
        "currentRatio": (False, 0.5),
        "weight": 0.15
    },
    "momentum": {
        "priceVs50dMA": (False, 0.5),
        "priceVs200dMA": (False, 0.5),
        "weight": 0.15
    }
}

# ─────────────────────────────────────────────
# 9. SCORING POR SECTOR
# ─────────────────────────────────────────────
def score(series, inverse):
    series = winsorize(series)
    r = series.rank(pct=True)
    if inverse:
        r = 1 - r
    return (r*10).clip(0,10)

all_metrics = []
for cat, cfg in CONFIG.items():
    if cat == "weight": continue
    cat_score = 0
    total_w = 0

    for k, v in cfg.items():
        if k == "weight": continue

        inverse, w = v

        if k in df.columns:
            imp = impute(df, k)
            s = df.groupby("sector")[imp.name].transform(lambda x: score(x, inverse))
            df[f"score_{k}"] = s

            cat_score += s * w
            total_w += w
            all_metrics.append(k)

    if total_w > 0:
        df[f"score_{cat}"] = cat_score / total_w
    else:
        df[f"score_{cat}"] = np.nan

# ─────────────────────────────────────────────
# 10. SCORE FINAL
# ─────────────────────────────────────────────
cat_scores = []
total_weight = 0

for cat, cfg in CONFIG.items():
    if f"score_{cat}" in df.columns:
        cat_scores.append(df[f"score_{cat}"] * cfg["weight"])
        total_weight += cfg["weight"]

df["score_FINAL"] = sum(cat_scores) / total_weight

# ─────────────────────────────────────────────
# 11. PENALIZACIÓN (MEJORADA)
# ─────────────────────────────────────────────
valid = df[all_metrics].notna().sum(axis=1)
total = len(all_metrics)

completeness = valid / total
penalty = completeness.clip(lower=0.3)

df["score_FINAL_adj"] = df["score_FINAL"] * (0.7 + 0.3 * penalty)

# ─────────────────────────────────────────────
# 12. RANKING + LABEL
# ─────────────────────────────────────────────
df["rank"] = df["score_FINAL_adj"].rank(ascending=False)

def label(x):
    if x >= 8: return "Excelente"
    if x >= 6.5: return "Buena"
    if x >= 5: return "Neutral"
    if x >= 3: return "Débil"
    return "Evitar"

df["rating"] = df["score_FINAL_adj"].apply(label)

# ─────────────────────────────────────────────
# 13. OUTPUT
# ─────────────────────────────────────────────
df.to_csv("Stock_Screener_PRO.csv", index=False)

print("\n🏆 TOP 15")
print(df.sort_values("rank")[["ticker","score_FINAL_adj","rating","rank"]].head(15))
