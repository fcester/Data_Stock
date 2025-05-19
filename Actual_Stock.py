import pandas as pd
import yfinance as yf
from datetime import datetime
import os

# Leer tickers desde CSV
tickers_df = pd.read_csv("Tickers.csv")
tickers = tickers_df["ticker"].dropna().tolist()

# Obtener fecha de hoy
hoy = datetime.today().strftime('%Y-%m-%d')

# Descargar datos
df = yf.download(tickers, start=hoy, end=hoy, auto_adjust=True)['Close']
df.index = [hoy]
df = df[tickers]

# Archivo destino
file_name = "Actual_Stock.csv"

# Si ya existe, agregar nueva fila si es necesario
if os.path.exists(file_name) and os.path.getsize(file_name) > 0:
    df_existente = pd.read_csv(file_name, index_col=0)
    if hoy not in df_existente.index:
        df_final = pd.concat([df_existente, df])
        df_final.to_csv(file_name)
        print("📈 Datos actualizados.")
    else:
        print("✅ Ya existen datos para hoy.")
else:
    df.to_csv(file_name)
    print("📊 Archivo creado.")
