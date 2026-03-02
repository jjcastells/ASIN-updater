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
        "nombre de campaña",
        "campaign name (solo informativo)"
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
# NORMALIZACIÓN
# =====================

def strip_accents(s: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", str(s))
        if not unicodedata.combining(ch)
    )

def clean_text(x):
    x = str(x)
    x = x.replace("\ufeff", "").replace("\u200b", "").replace("\xa0", " ")
    x = re.sub(r"\s+", " ", x).strip()
    return x

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
    def norm(x):
        return strip_accents(clean_text(x)).lower()

    normalized_cols = {norm(c): c for c in df.columns}
    column_map = {}

    for key, options in COLUMN_SCHEMA.items():
        for opt in options:
            opt_norm = norm(opt)
            if opt_norm in normalized_cols:
                column_map[key] = normalized_cols[opt_norm]
                break

    return column_map

def find_sheet_by_name(xls: pd.ExcelFile, keywords: List[str]) -> Optional[str]:
    for sheet in xls.sheet_names:
        if any(kw.lower() in sheet.lower() for kw in keywords):
            return sheet
    return None

# =====================
# FILTRO ROBUSTO ENTITY
# =====================

def es_product_ad(valor):
    if not isinstance(valor, str):
        return False
    v = strip_accents(clean_text(valor)).lower()
    return (
        "product ad" in v
        or "productad" in v
        or "anuncio de producto" in v
    )

# =====================
# PROCESAMIENTO PRINCIPAL
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

    required = ["entity", "campaign_name", "campaign_id", "ad_group_id", "asin"]
    missing = [k for k in required if k not in column_map]
    if missing:
        st.error(f"Faltan columnas esenciales: {missing}")
        return pd.DataFrame()

    col_entidad = column_map["entity"]
    col_campania = column_map["campaign_name"]
    col_campaign_id = column_map["campaign_id"]
    col_grupo_nombre = column_map.get("ad_group_name")
    col_adgroup_id = column_map["ad_group_id"]
    col_ad_id = column_map.get("ad_id")
    col_asin = column_map["asin"]
    col_estado = column_map.get("state")

    # Limpieza preventiva
    for col in [col_entidad, col_campania, col_asin]:
        df[col] = df[col].apply(clean_text)

    # 1️⃣ Filtrar Product Ads
    mask_entidad = df[col_entidad].apply(es_product_ad)
    df_ads = df[mask_entidad].copy()

    st.write("Filas tras filtro entidad:", len(df_ads))

    if df_ads.empty:
        st.error("No se encontraron filas Product Ad.")
        st.write("Valores únicos de entidad:", df[col_entidad].unique()[:20])
        return pd.DataFrame()

    st.write("Primeras campañas detectadas:", df_ads[col_campania].unique()[:20])

    # 2️⃣ Filtrar campaña
    pattern = re.escape(filtro_campania.strip())
    mask_campania = df_ads[col_campania].str.contains(pattern, case=False, na=False)
    df_filtrado = df_ads[mask_campania].copy()

    st.write("Filas tras filtro campaña:", len(df_filtrado))

    if df_filtrado.empty:
        st.error(f"No se encontraron campañas con '{filtro_campania}'")
        st.write("Campañas disponibles:", df_ads[col_campania].unique()[:20])
        return pd.DataFrame()

    # 3️⃣ Filtro grupo
    if filtro_grupo and col_grupo_nombre:
        pattern_grupo = re.escape(filtro_grupo.strip())
        df_filtrado = df_filtrado[
            df_filtrado[col_grupo_nombre].str.contains(pattern_grupo, case=False, na=False)
        ]

    if df_filtrado.empty:
        st.error("No quedaron anuncios tras filtro de grupo.")
        return pd.DataFrame()

    # 4️⃣ Vista previa
    if col_grupo_nombre:
        resumen = df_filtrado.groupby([col_campania, col_grupo_nombre]).size().reset_index(name='Nº anuncios')
    else:
        resumen = df_filtrado.groupby([col_campania]).size().reset_index(name='Nº anuncios')

    st.subheader("🔍 Vista previa selección")
    st.dataframe(resumen, use_container_width=True)

    # 5️⃣ Mapear ASIN existentes
    asins_existentes = {}

    for _, row in df_filtrado.iterrows():
        asin = str(row[col_asin]).strip().upper()
        if not asin:
            continue

        info = {
            "campaign_id": str(row[col_campaign_id]).strip(),
            "ad_group_id": str(row[col_adgroup_id]).strip(),
            "ad_id": str(row[col_ad_id]).strip() if col_ad_id else "",
            "estado_actual": normalizar_estado(row[col_estado]) if col_estado else "unknown"
        }

        asins_existentes.setdefault(asin, []).append(info)

    grupos_destino = {
        (str(r[col_campaign_id]).strip(), str(r[col_adgroup_id]).strip())
        for _, r in df_filtrado.iterrows()
    }

    filas = []

    if modo == "update":
        for asin in lista_asins:
            if asin in asins_existentes:
                for info in asins_existentes[asin]:
                    filas.append({
                        "Product": "Sponsored Products",
                        "Entity": "Product Ad",
                        "Operation": "update",
                        "Campaign ID": info["campaign_id"],
                        "Ad Group ID": info["ad_group_id"],
                        "Ad ID": info["ad_id"],
                        "State": accion,
                        "SKU": "",
                        "ASIN": asin
                    })

    if not filas:
        st.warning("No se generaron acciones.")
        return pd.DataFrame()

    df_salida = pd.DataFrame(filas)
    return df_salida[
        ["Product","Entity","Operation","Campaign ID","Ad Group ID","Ad ID","State","SKU","ASIN"]
    ]

# =====================
# INTERFAZ
# =====================

uploaded_file = st.file_uploader("📤 Sube tu archivo bulk de Amazon (Excel)", type=["xlsx"])

if uploaded_file:
    xls = pd.ExcelFile(uploaded_file)
    hoja = find_sheet_by_name(xls, ["sponsored products"]) or xls.sheet_names[0]
    df = pd.read_excel(xls, sheet_name=hoja, dtype=str)
    df = clean_columns(df)

    st.dataframe(df.head(20))

    filtro_campania = st.text_input("🔎 Texto para filtrar campañas (obligatorio)")
    modo = st.selectbox("Modo", ["update"])
    accion = st.radio("Acción", ["enabled","paused"])
    asins_text = st.text_area("ASIN (uno por línea)")

    if st.button("Generar"):
        lista_asins = [a.strip().upper() for a in asins_text.splitlines() if a.strip()]

        df_resultado = procesar_bulk(
            df,
            lista_asins,
            filtro_campania,
            modo,
            accion
        )

        if not df_resultado.empty:
            st.dataframe(df_resultado)
