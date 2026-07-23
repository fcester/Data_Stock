import pandas as pd

# Reemplaza con tus rutas de archivo reales
archivo_parquet = 'Actual_Stock.parquet'
archivo_csv = 'Actual_Stock.csv'

# Lee el archivo Parquet y lo exporta a CSV
df = pd.read_parquet(archivo_parquet)
df.to_csv(archivo_csv, index=False)
print(f'¡Archivo convertido exitosamente a {archivo_csv}!')
