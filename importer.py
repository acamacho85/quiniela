import re
import requests
from bs4 import BeautifulSoup
import pandas as pd
from io import StringIO
import numpy as np
from datetime import datetime
import sqlite3

DB_PATH = "database.db"
# -------------------------------------------------------------------
# Map de meses en español
# -------------------------------------------------------------------
MESES = {
    "enero":1, "febrero":2, "marzo":3, "abril":4, "mayo":5, "junio":6,
    "julio":7, "agosto":8, "septiembre":9, "octubre":10, "noviembre":11, "diciembre":12
}

# -------------------------------------------------------------------
# Limpieza de numeros texto a numericos
# -------------------------------------------------------------------
def clean_numeric_column(series):
    pd.set_option('future.no_silent_downcasting', True)  # Opt-in al nuevo comportamiento
    return (
        series.astype(str)
        .str.replace(r"\s+", "", regex=True)
        .str.replace(r"[^\d.]", "", regex=True)
        .replace("", np.nan)
        .astype(float)
    )

# -------------------------------------------------------------------
# Parsear y normalizar fecha y hora
# -------------------------------------------------------------------
def parse_fecha_hora(fecha_str, hora_str, anio=2025):
    if not fecha_str or not hora_str:
        return None
    fecha_clean = re.sub(r"\[.*?\]", "", fecha_str).replace("\u200b","").strip()
    m = re.match(r"(\d{1,2})\s+de\s+(\w+)", fecha_clean, re.IGNORECASE)
    if not m: return None
    dia, mes_txt = m.groups()
    mes = MESES.get(mes_txt.lower())
    if not mes: return None
    try:
        hora_dt = datetime.strptime(hora_str.strip(), "%H:%M").time()
    except Exception:
        return None
    dt_completo = datetime(anio, mes, int(dia), hora_dt.hour, hora_dt.minute)
    return dt_completo.strftime("%Y-%m-%d %H:%M:%S")

# -------------------------------------------------------------------
# Exportar datos a SQLite
# -------------------------------------------------------------------
def save_df_to_sqlite(df, db_path, table_name, if_exists="replace"):
    with sqlite3.connect(db_path) as conn:
        df.to_sql(table_name, conn, if_exists=if_exists, index=False)

# -------------------------------------------------------------------
# Cargar datos desde Wikipedia
# -------------------------------------------------------------------
# URL de la página
url = "https://es.wikipedia.org/wiki/Torneo_Apertura_2025_(M%C3%A9xico)"

# Encabezado para simular un navegador
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/115.0 Safari/537.36"
}

# Obtener el HTML
response = requests.get(url, headers=headers)

# Definir las class que pueden tener las tablas.
def has_all_classes(tag, required_classes):
    tag_classes = tag.get("class", [])
    return set(required_classes).issubset(set(tag_classes))

required = ["mw-collapsible", "wikitable"]
soup = BeautifulSoup(response.text, "html.parser")
# Buscar todas las tablas de jornadas
tables = soup.find_all(lambda tag: has_all_classes(tag, required))

# Procesar cada tabla
jornadas = []
for idx, table in enumerate(tables, start=1):
    df = pd.read_html(StringIO(str(table)))[0]
    
    # Suponiendo que ya tienes el DataFrame llamado df
    html_table = df.to_html(classes="table table-striped table-bordered", index=False)
    soup2 = BeautifulSoup(html_table, "html.parser")
    table = soup2.find("table")

    # 🏷️ Extraer el nombre de la jornada
    jornada_th = table.find("th", colspan=True)
    jornada_nombre = jornada_th.get_text(strip=True) if jornada_th else "Jornada desconocida"

    # 📊 Convertir la tabla HTML a DataFrame
    df = pd.read_html(StringIO(str(table)))[0]

    jornada = df.columns[0][0]  # Extrae 'Jornada 1' del primer nivel
    df.columns = df.columns.get_level_values(1)  # Limpia los nombres
    df["Jornada"] = jornada  # Agrega como nueva columna

    df.rename(columns={
        "Unnamed: 7_level_1": "Amonestados",
        "Unnamed: 8_level_1": "Expulsados"
    }, inplace=True)
    df["Amonestados"] = df["Amonestados"].fillna(0).astype(int)
    df["Expulsados"] = df["Expulsados"].fillna(0).astype(int)

    df["Espectadores"] = clean_numeric_column(df["Espectadores"])
    df["Espectadores"] = df["Espectadores"].fillna(0).astype(int)
    df["FechaHora"] = df.apply(lambda row: parse_fecha_hora(row["Fecha"], row["Hora"], anio=2025), axis=1)
    jornadas.append(df)

df_final = pd.concat(jornadas, ignore_index=True)
with sqlite3.connect("database.db") as conn:
    df_final.to_sql("jornadas", conn, if_exists="replace", index=True, index_label="id")
