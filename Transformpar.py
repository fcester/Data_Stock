import pandas as pd

# Rutas de los archivos
archivo_parquet = 'Actual_Stock.parquet'
archivo_csv = 'Actual_stock_filtrado.csv'

# Leer el archivo Parquet
df = pd.read_parquet(archivo_parquet)

# Convertir la columna de fecha a datetime
df['Date'] = pd.to_datetime(df['Date'])

# Filtrar desde el 1 de enero de 2025
df = df[df['Date'] >= '2025-01-01']

# Exportar a CSV
df.to_csv(archivo_csv, index=False)

print(f'¡Archivo convertido exitosamente a {archivo_csv}!')
