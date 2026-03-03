import streamlit as st
import pandas as pd
import re
import unicodedata
from io import BytesIO
from typing import List, Optional

st.set_page_config(page_title="Gestor de Anuncios ASIN", page_icon="📦", layout="wide")
st.title("📦 Gestor Profesional de Product Ads")

# =============================
# UTILIDADES
# =============================

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

def es_product_ad(valor):
    if not isinstance(valor, str):
        return False
    v = strip_accents(clean_text(valor)).lower()
    return (
        "product ad" in v or
        "productad" in v or
        "anuncio de producto" in v
    )

def parse_asins(texto):
    texto = texto.replace(",", " ")
    tokens = texto.split()
    return list({t.strip().upper() for t in tokens if t.strip()})

# =============================
# COLUMNAS
# =============================

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
    "asin": [
        "asin",
        "asin (informational only)",
        "asin (solo informativo)"
    ],
    "ad_id": [
        "ad id",
        "ad id (informational only)",
        "id del anuncio"
    ],
    "state": [
        "state",
        "ad status",
        "status",
        "estado"
    ]
}

def build_column_map(df):
    """
    Construye un mapeo de nombres canónicos a nombres reales de columna.
    Primero intenta coincidencia exacta después de normalizar.
    Si no, busca que la opción normalizada sea subcadena del nombre de columna normalizado.
    """
    def norm(x):
        return strip_accents(clean_text(x)).lower()

    normalized = {norm(c): c for c in df.columns}
    col_map = {}

    for key, options in COLUMN_SCHEMA.items():
        # Primero búsqueda exacta
        found = None
        for opt in options:
            opt_norm = norm(opt)
            if opt_norm in normalized:
                found = normalized[opt_norm]
                break
        if found:
            col_map[key] = found
            continue

        # Si no, búsqueda por subcadena (que la opción esté contenida en el nombre de columna)
        for col_norm, original in normalized.items():
            for opt in options:
                opt_norm = norm(opt)
                if opt_norm in col_norm:
                    col_map[key] = original
                    break
            if key in col_map:
                break

    return col_map

# =============================
# UPLOAD
# =============================

uploaded_file = st.file_uploader("📤 Sube tu bulk de Amazon", type=["xlsx"])

if uploaded_file:
    xls = pd.ExcelFile(uploaded_file)
    hojas = xls.sheet_names
    
    # Seleccionar por defecto la segunda hoja (asumiendo que es "Camp. Sponsored products")
    indice_por_defecto = 1 if len(hojas) > 1 else 0
    hoja_seleccionada = st.selectbox("Selecciona la hoja que contiene los anuncios", hojas, index=indice_por_defecto)
    
    df = pd.read_excel(xls, sheet_name=hoja_seleccionada, dtype=str)
    df.columns = [clean_text(c) for c in df.columns]
    
    column_map = build_column_map(df)
    required = ["entity", "campaign_name", "campaign_id", "ad_group_name", "ad_group_id", "asin"]
    missing = [k for k in required if k not in column_map]
    if missing:
        st.error(f"Faltan columnas esenciales: {missing}")
        st.write("Columnas detectadas en el archivo:", df.columns.tolist())
        st.write("Mapa de columnas generado:", column_map)
        st.stop()
    
    col_entity = column_map["entity"]
    col_campaign = column_map["campaign_name"]
    col_campaign_id = column_map["campaign_id"]
    col_group = column_map["ad_group_name"]
    col_group_id = column_map["ad_group_id"]
    col_asin = column_map["asin"]
    col_ad_id = column_map.get("ad_id")
    col_state = column_map.get("state")

    # =============================
    # FASE 1 — FILTRO ESTRUCTURAL
    # =============================

    st.header("1️⃣ Filtrar estructura")

    filtro_campania = st.text_input("Texto campaña (opcional)")
    filtro_grupo = st.text_input("Texto grupo (opcional)")

    if st.button("🔎 Filtrar estructura"):

        df_ads = df[df[col_entity].apply(es_product_ad)].copy()

        if filtro_campania.strip():
            df_ads = df_ads[
                df_ads[col_campaign]
                .astype(str)
                .str.contains(re.escape(filtro_campania.strip()), case=False, na=False)
            ]

        if filtro_grupo.strip():
            df_ads = df_ads[
                df_ads[col_group]
                .astype(str)
                .str.contains(re.escape(filtro_grupo.strip()), case=False, na=False)
            ]

        if df_ads.empty:
            st.warning("No se encontraron coincidencias.")
            st.stop()

        estructura = df_ads[
            [col_campaign, col_campaign_id, col_group, col_group_id]
        ].drop_duplicates()

        st.session_state["estructura"] = estructura
        st.session_state["df_filtrado"] = df_ads

        st.success("Filtro aplicado correctamente.")
        st.dataframe(estructura, use_container_width=True)

    # =============================
    # FASE 2 — VALIDAR FILTRO
    # =============================

    if "estructura" in st.session_state:

        st.header("2️⃣ Validar estructura")

        if st.button("✅ Validar filtro"):
            st.session_state["estructura_validada"] = True
            st.success("Estructura validada.")

    # =============================
    # FASE 3 — GESTIÓN ASIN
    # =============================

    if st.session_state.get("estructura_validada"):

        st.header("3️⃣ Gestión de ASIN")

        texto_asins = st.text_area(
            "Pega ASIN (uno por línea, separados por coma o espacio)",
            height=150
        )

        accion = st.selectbox(
            "Acción a realizar",
            [
                "Activar ASIN listados",
                "Pausar ASIN listados",
                "Añadir y activar ASIN listados",
                "Activar listados y pausar el resto"
            ]
        )

        if st.button("🔍 Validar acción"):

            lista_asins = parse_asins(texto_asins)

            if not lista_asins:
                st.error("Introduce al menos un ASIN.")
                st.stop()

            df_filtrado = st.session_state["df_filtrado"]

            # Mapear ASIN existentes
            existentes = df_filtrado[col_asin].astype(str).str.upper().unique()

            acciones = []

            for asin in lista_asins:
                subset = df_filtrado[
                    df_filtrado[col_asin].astype(str).str.upper() == asin
                ]

                if not subset.empty:
                    for _, row in subset.iterrows():
                        acciones.append({
                            "Campaign": row[col_campaign],
                            "Ad Group": row[col_group],
                            "ASIN": asin,
                            "Acción": accion
                        })
                else:
                    if "Añadir" in accion:
                        for _, row in st.session_state["estructura"].iterrows():
                            acciones.append({
                                "Campaign": row[col_campaign],
                                "Ad Group": row[col_group],
                                "ASIN": asin,
                                "Acción": "Crear y activar"
                            })

            if not acciones:
                st.warning("No se generaron acciones.")
                st.stop()

            df_preview = pd.DataFrame(acciones)

            st.session_state["preview"] = df_preview

            st.subheader("4️⃣ Vista previa de acciones")
            st.dataframe(df_preview, use_container_width=True)

    # =============================
    # FASE 5 — GENERAR CSV
    # =============================

    if "preview" in st.session_state:

        if st.button("🚀 Generar archivo final"):

            df_export = st.session_state["preview"]

            buffer = BytesIO()
            df_export.to_csv(buffer, sep=";", index=False, encoding="utf-8-sig")
            buffer.seek(0)

            st.download_button(
                "⬇️ Descargar CSV",
                buffer,
                "operaciones_asins.csv",
                "text/csv"
            )
