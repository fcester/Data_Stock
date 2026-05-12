# Total_Stock.py
import pandas as pd
import os

PRICES_FILE = "Actual_Stock.parquet"
HIST_CSV    = "Historical_Stock (1).csv"   # ← nombre correcto
ACTUAL_CSV  = "Actual_Stock.csv"

# ─────────────────────────────────────────────
# FUNCIONES
# ─────────────────────────────────────────────
def load_csv_prices(filepath):
    print(f"   📂 Cargando {filepath}...")
    try:
        df = pd.read_csv(filepath, index_col=0)

        if df.empty or len(df.columns) == 0:
            print(f"      ⚠  Vacío o sin columnas — se omite.")
            return None

        df.index = pd.to_datetime(df.index, utc=False, errors="coerce")
        df.index.name = "Date"
        df = df[df.index.notna()].sort_index()
        df.columns = df.columns.str.strip()
        df = df.apply(pd.to_numeric, errors="coerce")
        df = df.dropna(how="all")

        if df.empty:
            print(f"      ⚠  Sin filas válidas tras limpieza — se omite.")
            return None

        print(f"      ✅ {len(df)} filas | "
              f"{df.index[0].date()} → {df.index[-1].date()} | "
              f"{df.shape[1]} tickers")
        return df

    except pd.errors.EmptyDataError:
        print(f"      ⚠  Archivo completamente vacío — se omite.")
        return None
    except Exception as e:
        print(f"      ❌ Error inesperado: {e}")
        return None

def merge_price_frames(*frames):
    combined = pd.concat(frames, axis=0)
    combined = combined[~combined.index.duplicated(keep="last")]
    all_cols = frames[0].columns
    for f in frames[1:]:
        all_cols = all_cols.union(f.columns)
    return combined.reindex(columns=all_cols).sort_index()

# ─────────────────────────────────────────────
# CARGAR ARCHIVOS
# ─────────────────────────────────────────────
print("📥 Cargando archivos fuente...")

frames_to_merge = []

for csv_file in [HIST_CSV, ACTUAL_CSV]:
    if not os.path.exists(csv_file):
        print(f"   ⚠  {csv_file} no encontrado — se omite.")
        continue
    df_loaded = load_csv_prices(csv_file)
    if df_loaded is not None:
        frames_to_merge.append(df_loaded)

if not frames_to_merge:
    print("\n❌ Ningún archivo fuente válido. Abortando.")
    exit(1)

# ─────────────────────────────────────────────
# MERGE
# ─────────────────────────────────────────────
print(f"\n🔀 Procesando {len(frames_to_merge)} archivo(s) válido(s)...")

df_merged = merge_price_frames(*frames_to_merge) if len(frames_to_merge) > 1 else frames_to_merge[0]

# ─────────────────────────────────────────────
# RESUMEN
# ─────────────────────────────────────────────
print(f"\n📐 Resultado:")
print(f"   Filas totales  : {len(df_merged)}")
print(f"   Tickers totales: {df_merged.shape[1]}")
print(f"   Rango completo : {df_merged.index[0].date()} → {df_merged.index[-1].date()}")

# ─────────────────────────────────────────────
# GUARDAR
# ─────────────────────────────────────────────
df_merged.to_parquet(PRICES_FILE, index=True)
size_kb = os.path.getsize(PRICES_FILE) / 1024
print(f"\n✅ {PRICES_FILE} guardado ({size_kb:.0f} KB)")

# ─────────────────────────────────────────────
# VERIFICACIÓN
# ─────────────────────────────────────────────
print("\n🔎 Verificación:")
df_check = pd.read_parquet(PRICES_FILE)
print(f"   Filas    : {len(df_check)}")
print(f"   Tickers  : {df_check.shape[1]}")
print(f"   Desde    : {df_check.index[0].date()}")
print(f"   Hasta    : {df_check.index[-1].date()}")
print(f"   Primeras columnas: {df_check.columns[:5].tolist()}")
print("\n🎉 Listo. Verifica el resultado y elimina Total_Stock.py del repo.")
