import pandas as pd
import yfinance as yf
from datetime import datetime
import os

# Leer tickers desde CSV
tickers_df = pd.read_csv("Tickers.csv", encoding='utf-8', errors='ignore')
tickers = tickers_df["ticker"].dropna().tolist()

# Descargar datos últimos 5 días
df = yf.download(tickers, period="5d", interval="1d", auto_adjust=True)['Close']

# Tomar solo la última fila disponible (último cierre)
df = df.tail(1)

# Archivo destino
file_name = "Actual_Stock.csv"

if os.path.exists(file_name) and os.path.getsize(file_name) > 0:
    df_existente = pd.read_csv(file_name, index_col=0)

    # Si la fecha del nuevo dato no está en el archivo, lo agrego
    fecha_nueva = df.index[0]
    if fecha_nueva not in df_existente.index:
        df_final = pd.concat([df_existente, df])
        df_final.to_csv(file_name)
        print("📈 Datos actualizados.")
    else:
        print("✅ Ya existen datos para esa fecha.")
else:
    df.to_csv(file_name)
    print("📊 Archivo creado.")

