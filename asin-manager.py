import streamlit as st
import pandas as pd
import re
import unicodedata
from io import BytesIO
from typing import List, Optional

st.set_page_config(page_title="Gestor de Anuncios ASIN", page_icon="📦", layout="wide")
st.title("📦 Gestor de Anuncios por ASIN (Product Ads)")
st.caption("Activa, pausa, crea o sincroniza (Adapt) anuncios de producto en campañas de Sponsored Products.")

# =====================
# ESQUEMA CENTRALIZADO DE COLUMNAS
# =====================
COLUMN_SCHEMA = {
    "entity": ["entity", "entidad"],
    "campaign_name": [
        "campaign name", "nombre de la campaña", "nombre de la campaña (solo informativo)"
    ],
    "campaign_id": ["campaign id", "id de la campaña"],
    "ad_group_name": [
        "ad group name", "nombre del grupo de anuncios", "nombre del grupo de anuncios (solo informativo)"
    ],
    "ad_group_id": ["ad group id", "id del grupo de anuncios"],
    "ad_id": ["ad id", "id del anuncio"],
    "asin": ["asin", "asin (solo informativo)"],
    "state": ["state", "status", "estado"]
}

FILTER_PREFERENCE = {
    "campaign_name": ["solo informativo", "nombre de la campaña", "campaign name"],
    "ad_group_name": ["solo informativo", "nombre del grupo de anuncios", "ad group name"]
}

# =====================
# Funciones de normalización
# =====================
def strip_accents(s: str) -> str:
    return "".join(ch for ch in unicodedata.normalize("NFKD", str(s)) if not unicodedata.combining(ch))

def clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    def _clean(x):
        x = str(x)
        x = x.replace("\ufeff", "").replace("\u200b", "").replace("\xa0", " ")
        x = re.sub(r"\s+", " ", x).strip()
        return x
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [" ".join([str(c) for c in col if str(c) != "nan"]).strip() for col in df.columns]
    df.columns = [_clean(c) for c in df.columns]
    return df

def normalizar_estado(estado: str) -> str:
    if not isinstance(estado, str):
        return "unknown"
    estado = strip_accents(estado).lower().strip()
    if "enable" in estado or "activ" in estado:
        return "enabled"
    if "paus" in estado:
        return "paused"
    if "archiv" in estado:
        return "archived"
    return "unknown"

def build_column_map(df: pd.DataFrame) -> dict:
    def norm(x):
        x = strip_accents(str(x)).lower()
        x = x.replace("\ufeff", "").replace("\u200b", "").replace("\xa0", " ")
        x = re.sub(r"\s+", " ", x).strip()
        return x
    normalized_cols = {norm(c): c for c in df.columns}
    column_map = {}
    for key, options in COLUMN_SCHEMA.items():
        for opt in options:
            opt_norm = norm(opt)
            if opt_norm in normalized_cols:
                column_map[key] = normalized_cols[opt_norm]
                break
    return column_map

def select_filter_column(column_map, key):
    """
    Selecciona columna para filtrar dando prioridad a 'Solo informativo'.
    """
    preferidos = FILTER_PREFERENCE.get(key, [])
    for pref in preferidos:
        for real_col in column_map.values():
            if pref.lower() in real_col.lower():
                return real_col
    return column_map.get(key)

def find_sheet_by_name(xls: pd.ExcelFile, keywords: List[str]) -> Optional[str]:
    for sheet in xls.sheet_names:
        if any(kw.lower() in sheet.lower() for kw in keywords):
            return sheet
    return None

# =====================
# Lógica de filtrado y vista previa
# =====================
def filtrar_bulk(df: pd.DataFrame, filtro_campania: str, filtro_grupo: Optional[str] = None) -> pd.DataFrame:
    column_map = build_column_map(df)
    col_entidad = column_map.get("entity")
    col_campania = select_filter_column(column_map, "campaign_name")
    col_grupo_nombre = select_filter_column(column_map, "ad_group_name")

    st.write("Columnas usadas para filtrar:")
    st.write({"campaign_name": col_campania, "ad_group_name": col_grupo_nombre})

    if not col_entidad or not col_campania or not col_grupo_nombre:
        st.error("Faltan columnas esenciales para filtrar.")
        return pd.DataFrame()

    # Filtrar por entidad 'Anuncio de producto'
    mask_entidad = df[col_entidad].astype(str).str.lower().str.contains("product ad|anuncio de producto", regex=True)
    df_ads = df[mask_entidad].copy()
    if df_ads.empty:
        st.error("No se encontraron filas de 'Anuncio de producto'.")
        return pd.DataFrame()

    # Filtrar por campaña si se proporciona texto
    if filtro_campania:
        mask_campania = df_ads[col_campania].astype(str).str.contains(re.escape(filtro_campania), case=False, regex=True)
        df_ads = df_ads[mask_campania].copy()
        if df_ads.empty:
            st.error(f"No se encontraron campañas que contengan '{filtro_campania}'.")
            return pd.DataFrame()

    # Filtrar por grupo si se proporciona texto
    if filtro_grupo:
        mask_grupo = df_ads[col_grupo_nombre].astype(str).str.contains(re.escape(filtro_grupo), case=False, regex=True)
        df_ads = df_ads[mask_grupo].copy()
        if df_ads.empty:
            st.error(f"No se encontraron grupos que contengan '{filtro_grupo}'.")
            return pd.DataFrame()

    # Vista previa: solo campañas y adgroups
    st.subheader("🔍 Vista previa de campañas y grupos a accionar")
    resumen = df_ads.groupby([col_campania, col_grupo_nombre]).size().reset_index(name="Nº anuncios")
    st.dataframe(resumen, use_container_width=True)

    return df_ads

# =====================
# Interfaz de usuario
# =====================
uploaded_file = st.file_uploader("📤 Sube tu archivo bulk de Amazon (Excel)", type=["xlsx"])
if uploaded_file:
    xls = pd.ExcelFile(uploaded_file)
    hoja_detectada = find_sheet_by_name(xls, ["sponsored products", "campañas de sponsored products"])
    hoja_seleccionada = st.selectbox("Selecciona la hoja", xls.sheet_names, index=0 if not hoja_detectada else xls.sheet_names.index(hoja_detectada))
    df = pd.read_excel(xls, sheet_name=hoja_seleccionada, dtype=str)
    df = clean_columns(df)
    st.subheader("🔍 Vista previa del archivo (primeras 20 filas)")
    st.dataframe(df.head(20), use_container_width=True)

    filtro_campania = st.text_input("🔎 Texto para filtrar campañas (opcional)")
    filtro_grupo = st.text_input("📁 Texto para filtrar grupos (opcional)")

    if st.button("Filtrar campañas y grupos"):
        df_filtrado = filtrar_bulk(df, filtro_campania.strip(), filtro_grupo.strip())
        if not df_filtrado.empty:
            st.success("Filtro aplicado correctamente.")
