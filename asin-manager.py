import streamlit as st
import pandas as pd
import re
import unicodedata
from io import BytesIO
from typing import List, Optional

# =====================
# CONFIG STREAMLIT
# =====================
st.set_page_config(page_title="Gestor de Anuncios ASIN", page_icon="📦", layout="wide")
st.title("📦 Gestor de Anuncios por ASIN (Product Ads)")
st.caption("Activa, pausa, crea o sincroniza (Adapt) anuncios de producto en campañas de Sponsored Products.")

# =====================
# COLUMN SCHEMA ROBUSTO
# =====================
COLUMN_SCHEMA = {
    "entity": [
        "entity",
        "entidad"
    ],
    "campaign_name": [
        "campaign name",
        "campaign name (informational only)",
        "campaign name (read only)",
        "nombre de la campaña",
        "nombre de la campaña (solo informativo)"
    ],
    "campaign_id": [
        "campaign id",
        "campaign id (informational only)",
        "campaign id (read only)",
        "id de la campaña"
    ],
    "ad_group_name": [
        "ad group name",
        "ad group name (informational only)",
        "nombre del grupo de anuncios",
        "nombre del grupo de anuncios (solo informativo)"
    ],
    "ad_group_id": [
        "ad group id",
        "ad group id (informational only)",
        "adgroup id",
        "id del grupo de anuncios"
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
# FUNCIONES DE NORMALIZACIÓN
# =====================
def strip_accents(s: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", str(s))
        if not unicodedata.combining(ch)
    )

def clean_text(s: str) -> str:
    s = str(s)
    s = s.replace("\ufeff", "").replace("\u200b", "").replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s

def clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [" ".join([str(c) for c in col if str(c) != "nan"]).strip() for col in df.columns]
    df.columns = [clean_text(c) for c in df.columns]
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
    """
    Construye un diccionario que mapea claves canónicas a nombres reales de columna.
    """
    def norm(x):
        return strip_accents(clean_text(x)).lower()

    normalized = {norm(c): c for c in df.columns}
    col_map = {}

    for key, options in COLUMN_SCHEMA.items():
        for col_norm, original in normalized.items():
            for opt in options:
                if norm(opt) == col_norm:
                    col_map[key] = original
                    break
            if key in col_map:
                break

    return col_map

def find_sheet_by_name(xls: pd.ExcelFile, keywords: List[str]) -> Optional[str]:
    for sheet in xls.sheet_names:
        if any(kw.lower() in sheet.lower() for kw in keywords):
            return sheet
    return None

# =====================
# PROCESAR BULK
# =====================
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
    col_campania = column_map.get("campaign_name")
    col_campaign_id = column_map.get("campaign_id")
    col_grupo_nombre = column_map.get("ad_group_name")
    col_adgroup_id = column_map.get("ad_group_id")
    col_ad_id = column_map.get("ad_id")
    col_asin = column_map.get("asin")
    col_estado = column_map.get("state")

    required = ["entity", "campaign_name", "campaign_id", "ad_group_id", "asin"]
    missing = [k for k in required if k not in column_map]

    if missing:
        st.error(f"Faltan columnas esenciales: {missing}")
        st.write("Columnas detectadas:", df.columns.tolist())
        st.write("Column map generado:", column_map)
        st.stop()

    # =====================
    # FILTRO ENTITY
    # =====================
    mask_entidad = df[col_entidad].astype(str).str.lower().str.contains(
        r"product\s*ad|anuncio\s*de\s*producto",
        na=False,
        regex=True
    )
    df_ads = df[mask_entidad].copy()
    if df_ads.empty:
        st.error("No se encontraron filas de 'Anuncio de producto'.")
        st.stop()

    # =====================
    # FILTRO CAMPANIA
    # =====================
    if filtro_campania.strip():
        mask_campania = df_ads[col_campania].astype(str).str.contains(
            re.escape(filtro_campania), case=False, na=False, regex=True
        )
        df_ads = df_ads[mask_campania].copy()
        if df_ads.empty:
            st.warning(f"No se encontraron campañas que contengan '{filtro_campania}'.")

    # =====================
    # FILTRO GRUPO
    # =====================
    if filtro_grupo and col_grupo_nombre:
        mask_grupo = df_ads[col_grupo_nombre].astype(str).str.contains(
            re.escape(filtro_grupo), case=False, na=False, regex=True
        )
        df_ads = df_ads[mask_grupo].copy()
        if df_ads.empty:
            st.warning(f"No se encontraron grupos que contengan '{filtro_grupo}'.")

    # =====================
    # VISTA PREVIA CAMPANAS Y GRUPOS
    # =====================
    st.subheader("🔍 Vista previa de campañas y grupos a accionar")
    if col_grupo_nombre:
        resumen = df_ads.groupby([col_campania, col_grupo_nombre]).size().reset_index(name='Nº anuncios')
    else:
        resumen = df_ads.groupby([col_campania]).size().reset_index(name='Nº anuncios')
    st.dataframe(resumen, use_container_width=True)

    # =====================
    # ETAPA ASIN
    # =====================
    asins_existentes = {}
    for _, row in df_ads.iterrows():
        asin = str(row.get(col_asin, '')).strip()
        if asin:
            info = {
                'ad_id': str(row.get(col_ad_id, '')).strip() if col_ad_id else '',
                'campaign_id': str(row.get(col_campaign_id, '')).strip(),
                'ad_group_id': str(row.get(col_adgroup_id, '')).strip(),
                'estado_actual': normalizar_estado(row.get(col_estado, ''))
            }
            if asin not in asins_existentes:
                asins_existentes[asin] = []
            asins_existentes[asin].append(info)

    return df_ads, asins_existentes  # Retornamos dataframe filtrado y diccionario ASIN

# =====================
# INTERFAZ DE USUARIO
# =====================
uploaded_file = st.file_uploader("📤 Sube tu archivo bulk de Amazon (Excel)", type=["xlsx"])

if uploaded_file is not None:
    xls = pd.ExcelFile(uploaded_file)
    st.write("Hojas disponibles en el archivo:", xls.sheet_names)

    posibles = ["sponsored products", "campañas de sponsored products"]
    hoja_detectada = find_sheet_by_name(xls, posibles)

    hoja_seleccionada = st.selectbox(
        "Selecciona la hoja que contiene los anuncios",
        xls.sheet_names,
        index=xls.sheet_names.index(hoja_detectada) if hoja_detectada else 0
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
        if st.button("🔍 Filtrar"):
            df_filtrado, asins_existentes = procesar_bulk(
                df, [], filtro_campania, modo="preview", accion="", filtro_grupo=filtro_grupo
            )

    with col2:
        asins_text = st.text_area("Introduce los ASIN (uno por línea o separados por comas/espacios)", height=150)
        modo_accion = st.selectbox(
            "⚙️ Acción sobre ASIN",
            [
                "Activar ASIN listados",
                "Pausar ASIN listados",
                "Añadir y activar ASIN listados",
                "Activar listados y pausar resto"
            ]
        )
        if st.button("✅ Validar lista de ASIN"):
            lista_asins = re.split(r"[\n, ]+", asins_text.strip())
            lista_asins = [a.strip().upper() for a in lista_asins if a.strip()]
            st.write("ASIN validados:", lista_asins)
