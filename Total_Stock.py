# migrate_to_parquet.py
# Ejecutar UNA SOLA VEZ localmente para construir el Actual_Stock.parquet unificado.
# Después de verificar el resultado, eliminar este archivo del repo.

import pandas as pd
import os

PRICES_FILE       = "Actual_Stock.parquet"
HIST_CSV          = "Historical_Stock_backup.csv"
ACTUAL_CSV        = "Actual_Stock.csv"

# ─────────────────────────────────────────────
# FUNCIONES
# ─────────────────────────────────────────────
def load_csv_prices(filepath):
    print(f"   📂 Cargando {filepath}...")
    df = pd.read_csv(filepath, index_col=0)
    df.index = pd.to_datetime(df.index, utc=False, errors="coerce")
    df.index.name = "Date"
    df = df[df.index.notna()].sort_index()
    df.columns = df.columns.str.strip()
    df = df.apply(pd.to_numeric, errors="coerce")
    print(f"      ✅ {len(df)} filas | "
          f"{df.index[0].date()} → {df.index[-1].date()} | "
          f"{df.shape[1]} tickers")
    return df

def merge_price_frames(*frames):
    combined = pd.concat(frames, axis=0)
    combined = combined[~combined.index.duplicated(keep="last")]
    all_cols = frames[0].columns
    for f in frames[1:]:
        all_cols = all_cols.union(f.columns)
    return combined.reindex(columns=all_cols).sort_index()

# ─────────────────────────────────────────────
# VALIDAR ARCHIVOS FUENTE
# ─────────────────────────────────────────────
print("🔍 Verificando archivos fuente...")

missing = [f for f in [HIST_CSV, ACTUAL_CSV]
           if not os.path.exists(f) or os.stat(f).st_size == 0]

if missing:
    print(f"❌ Archivos no encontrados o vacíos: {missing}")
    print("   Verifica que estén en el mismo directorio que este script.")
    exit(1)

# ─────────────────────────────────────────────
# CARGAR AMBOS CSVs
# ─────────────────────────────────────────────
print("\n📥 Cargando archivos...")
df_hist   = load_csv_prices(HIST_CSV)
df_actual = load_csv_prices(ACTUAL_CSV)

# ─────────────────────────────────────────────
# DETECTAR SOLAPAMIENTO
# ─────────────────────────────────────────────
overlap = df_hist.index.intersection(df_actual.index)
solo_hist   = df_hist.index.difference(df_actual.index)
solo_actual = df_actual.index.difference(df_hist.index)

print(f"\n📊 Análisis de fechas:")
print(f"   Historical_Stock_backup.csv : {len(df_hist)} filas")
print(f"   Actual_Stock.csv            : {len(df_actual)} filas")
print(f"   Fechas solapadas            : {len(overlap)} "
      f"(se usará el valor de Actual_Stock.csv)")
print(f"   Solo en Historical          : {len(solo_hist)}")
print(f"   Solo en Actual              : {len(solo_actual)}")

# ─────────────────────────────────────────────
# MERGE
# ─────────────────────────────────────────────
print("\n🔀 Uniendo tablas...")
df_merged = merge_price_frames(df_hist, df_actual)

print(f"\n📐 Resultado del merge:")
print(f"   Filas totales  : {len(df_merged)}")
print(f"   Tickers totales: {df_merged.shape[1]}")
print(f"   Rango completo : {df_merged.index[0].date()} → {df_merged.index[-1].date()}")
print(f"   NaN totales    : {df_merged.isna().sum().sum():,} "
      f"({df_merged.isna().mean().mean():.1%} del total)")

# ─────────────────────────────────────────────
# GUARDAR — sobreescribe el parquet existente
# ─────────────────────────────────────────────
df_merged.to_parquet(PRICES_FILE, index=True)

size_kb = os.path.getsize(PRICES_FILE) / 1024
print(f"\n✅ {PRICES_FILE} guardado correctamente ({size_kb:.0f} KB)")

# ─────────────────────────────────────────────
# VERIFICACIÓN FINAL
# ─────────────────────────────────────────────
print("\n🔎 Verificación — leyendo el parquet generado:")
df_check = pd.read_parquet(PRICES_FILE)
print(f"   Filas    : {len(df_check)}")
print(f"   Tickers  : {df_check.shape[1]}")
print(f"   Desde    : {df_check.index[0].date()}")
print(f"   Hasta    : {df_check.index[-1].date()}")
print(f"   Primeras columnas: {df_check.columns[:5].tolist()}")
print("\n🎉 Migración completada. Ya puedes eliminar migrate_to_parquet.py del repo.")
