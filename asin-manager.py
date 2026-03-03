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
        "campaign name",
        "campaign name (informational only)",
        "campaign name (read only)",
        "nombre de la campaña",
        "nombre de la campaña (solo informativo)",
        "nombre de campaña"
    ],
    "campaign_id": [
        "campaign id",
        "campaign id (informational only)",
        "campaign id (read only)",
        "id de la campaña",
        "id de campaña"
    ],
    "ad_group_name": [
        "ad group name",
        "ad group name (informational only)",
        "nombre del grupo de anuncios",
        "nombre del grupo de anuncios (solo informativo)",
        "nombre de grupo de anuncios"
    ],
    "ad_group_id": [
        "ad group id",
        "ad group id (informational only)",
        "adgroup id",
        "id del grupo de anuncios",
        "id de grupo de anuncios"
    ],
    "ad_id": [
        "ad id",
        "ad id (informational only)",
        "id del anuncio"
    ],
    "asin": [
        "asin",
        "asin (informational only)",
        "asin (solo informativo)"
    ],
    "state": [
        "state",
        "status",
        "ad status",
        "estado"
    ]
}

# =====================
# Preferencias de columna para filtrado
# =====================
FILTER_PREFERENCE = {
    "campaign_name": ["Nombre de la campaña (Solo informativo)", "Nombre de la campaña"],
    "ad_group_name": ["Nombre del grupo de anuncios (Solo informativo)", "Nombre del grupo de anuncios"]
}

# =====================
# Funciones de normalización
# =====================
def strip_accents(s: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", str(s))
        if not unicodedata.combining(ch)
    )

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
    Devuelve la columna que se usará para filtrar, priorizando 'solo informativo'
    """
    for preferred in FILTER_PREFERENCE.get(key, []):
        for k, v in column_map.items():
            if v == preferred:
                return v
    return column_map.get(key)

def find_sheet_by_name(xls: pd.ExcelFile, keywords: List[str]) -> Optional[str]:
    for sheet in xls.sheet_names:
        if any(kw.lower() in sheet.lower() for kw in keywords):
            return sheet
    return None

def procesar_bulk(
    df: pd.DataFrame,
    lista_asins: List[str],
    filtro_campania: str,
    modo: str,
    accion: str,
    filtro_grupo: Optional[str] = None
) -> pd.DataFrame:
    column_map = build_column_map(df)
    st.write("**Mapa de columnas detectado:**", column_map)

    col_entidad = column_map.get("entity")
    col_campaign_id = column_map.get("campaign_id")
    col_adgroup_id = column_map.get("ad_group_id")
    col_ad_id = column_map.get("ad_id")
    col_asin = column_map.get("asin")
    col_estado = column_map.get("state")

    # Columna de filtrado prioritario
    col_campania = select_filter_column(column_map, "campaign_name")
    col_grupo_nombre = select_filter_column(column_map, "ad_group_name")

    st.write("**Columnas usadas para filtrar:**")
    st.write({"campaign_name": col_campania, "ad_group_name": col_grupo_nombre})

    required = ["entity", "campaign_name", "campaign_id", "ad_group_id", "asin"]
    missing = [k for k in required if k not in column_map or not column_map[k]]
    if missing:
        st.error(f"Faltan columnas esenciales en el archivo: {missing}")
        return pd.DataFrame()

    # Filtrar solo anuncios de producto
    mask_entidad = df[col_entidad].astype(str).str.lower().str.contains(
        r"product\s*ad|anuncio\s*de\s*producto",
        na=False,
        regex=True
    )
    df_ads = df[mask_entidad].copy()
    if df_ads.empty:
        st.error("No se encontraron filas de 'Anuncio de producto'.")
        return pd.DataFrame()

    # Filtrar por campaña si se proporcionó
    if filtro_campania.strip():
        mask_campania = df_ads[col_campania].astype(str).str.contains(
            re.escape(filtro_campania),
            case=False,
            na=False,
            regex=True
        )
        df_ads = df_ads[mask_campania].copy()
        if df_ads.empty:
            st.error(f"No se encontraron campañas que contengan '{filtro_campania}'.")
            return pd.DataFrame()

    # Filtrar por grupo si se proporcionó
    if filtro_grupo and col_grupo_nombre:
        mask_grupo = df_ads[col_grupo_nombre].astype(str).str.contains(
            re.escape(filtro_grupo),
            case=False,
            na=False,
            regex=True
        )
        df_ads = df_ads[mask_grupo].copy()
        if df_ads.empty:
            st.error(f"No se encontraron grupos que contengan '{filtro_grupo}'.")
            return pd.DataFrame()

    # Vista previa campañas/adgroups
    st.subheader("🔍 Vista previa de campañas y grupos")
    resumen = df_ads.groupby([col_campania, col_grupo_nombre]).size().reset_index(name='Nº anuncios')
    st.dataframe(resumen, use_container_width=True)

    return df_ads  # devolvemos solo las filas filtradas, sin ASIN todavía

# =====================
# Interfaz de usuario
# =====================
uploaded_file = st.file_uploader("📤 Sube tu archivo bulk de Amazon (Excel)", type=["xlsx"])

if uploaded_file:
    xls = pd.ExcelFile(uploaded_file)
    st.write("Hojas disponibles en el archivo:", xls.sheet_names)
    hoja_detectada = find_sheet_by_name(xls, ["sponsored products", "campañas de sponsored products"])
    hoja_seleccionada = st.selectbox(
        "Selecciona la hoja que contiene los anuncios",
        xls.sheet_names,
        index=xls.sheet_names.index(hoja_detectada) if hoja_detectada in xls.sheet_names else 0
    )
    df = pd.read_excel(xls, sheet_name=hoja_seleccionada, dtype=str)
    df = clean_columns(df)
    st.subheader("🔍 Vista previa del archivo (primeras 20 filas)")
    st.dataframe(df.head(20), use_container_width=True)

    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        filtro_campania = st.text_input("🔎 Texto para filtrar campañas (opcional)")
        filtro_grupo = st.text_input("📁 Texto para filtrar grupos (opcional)")
    with col2:
        modo = st.selectbox("⚙️ Modo de operación", ["update", "create", "update+create", "adapt"])
        if modo != "adapt":
            accion = st.radio("🎯 Acción", ["enabled", "paused"], horizontal=True)
        else:
            accion = "adapt"

    if st.button("🔎 Filtrar campañas y grupos"):
        df_filtrado = procesar_bulk(
            df=df,
            lista_asins=[],  # no usamos ASIN en esta etapa
            filtro_campania=filtro_campania,
            modo=modo,
            accion=accion,
            filtro_grupo=filtro_grupo
        )
