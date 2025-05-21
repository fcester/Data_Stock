import pandas as pd
import yfinance as yf
from datetime import datetime
import os

# Leer tickers desde CSV
tickers_df = pd.read_csv("Tickers.csv")
tickers = tickers_df["ticker"].dropna().tolist()
tickers_dict = tickers_df["ticker"].dropna().todict()


# Descargar datos últimos 5 días
df = yf.download(tickers, period="5d", interval="1d", auto_adjust=True)['Close']

# Tomar solo la última fila disponible (último cierre)
df = df.tail(1)

---
for ticker_look in tickers_dict:
    ticker_yf = yf.Ticker(ticker_look)
    temp = ticker_yf.info
    
    # Lista de atributos que te interesan
    attributes_of_interest = [
        "marketCap", "trailingPE", 
        "forwardPE", "beta", "trailingEps"
    ]
    
    # Crear un diccionario con solo los atributos deseados
    filtered_data = {attr: temp.get(attr) for attr in attributes_of_interest}
    
    ticker_info = pd.DataFrame([filtered_data]) # Crear un DataFrame directamente
    dow_stats[ticker_look] = ticker_info

all_stats_info = pd.concat(dow_stats, keys=dow_stats.keys(), names=['ticker', 'Index'])
---
# Archivo destino
file_info_name = "Stock_Info.csv"
file_name = "Actual_Stock.csv"
all_stats_info.to_csv(file_info_name)

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

