import streamlit as st
import pandas as pd
import re
import unicodedata
from io import BytesIO

st.set_page_config(page_title="ASIN Campaign Manager", layout="wide")
st.title("📦 ASIN Campaign Manager")

# =====================================================
# FUNCIONES AUXILIARES
# =====================================================

def clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [
        re.sub(r"\s+", " ",
               str(c)
               .replace("\ufeff", "")
               .replace("\u200b", "")
               .replace("\xa0", " ")
        ).strip()
        for c in df.columns
    ]
    return df

def detect_column(df, possible_names):
    for name in possible_names:
        if name in df.columns:
            return name
    return None

def parse_asins(text):
    raw = re.split(r'[\n,; ]+', text.strip())
    return sorted(list(set([a.upper() for a in raw if a.strip()])))

# =====================================================
# CARGA DE ARCHIVO
# =====================================================

uploaded_file = st.file_uploader("📤 Sube tu archivo bulk (Excel)", type=["xlsx"])

if uploaded_file:

    df = pd.read_excel(uploaded_file, dtype=str)
    df = clean_columns(df)

    st.subheader("📋 Columnas detectadas")
    st.write(list(df.columns))

    # Detectar columnas correctamente
    campaign_col = detect_column(df, [
        "Nombre de la campaña (Solo informativo)",
        "Nombre de la campaña"
    ])

    adgroup_col = detect_column(df, [
        "Nombre del grupo de anuncios (Solo informativo)",
        "Nombre del grupo de anuncios"
    ])

    entity_col = detect_column(df, [
        "Entidad",
        "Entity"
    ])

    asin_col = detect_column(df, [
        "ASIN",
        "Sku",
        "SKU"
    ])

    st.write("Columnas usadas:")
    st.write({
        "campaign": campaign_col,
        "ad_group": adgroup_col,
        "entity": entity_col,
        "asin": asin_col
    })

    if not all([campaign_col, adgroup_col, entity_col]):
        st.error("No se detectaron correctamente las columnas necesarias.")
        st.stop()

    # =====================================================
    # ETAPA 1 — FILTRO CAMPAÑAS Y AD GROUPS
    # =====================================================

    st.header("1️⃣ Filtrar campañas y grupos")

    filtro_campania = st.text_input("🔎 Texto para filtrar campañas (opcional)")
    filtro_grupo = st.text_input("📁 Texto para filtrar grupos (opcional)")

    if st.button("📌 Aplicar filtros"):

        df_ads = df[df[entity_col].str.lower().str.contains(
            r"product\s*ad|anuncio\s*de\s*producto",
            regex=True,
            na=False
        )].copy()

        if filtro_campania.strip():
            df_ads = df_ads[df_ads[campaign_col].str.contains(
                re.escape(filtro_campania.strip()),
                case=False,
                na=False
            )]

        if filtro_grupo.strip():
            df_ads = df_ads[df_ads[adgroup_col].str.contains(
                re.escape(filtro_grupo.strip()),
                case=False,
                na=False
            )]

        if df_ads.empty:
            st.warning("No se encontraron campañas con esos filtros.")
            st.stop()

        resumen = df_ads[[campaign_col, adgroup_col]].drop_duplicates()
        st.success(f"Se encontraron {len(resumen)} combinaciones campaña/ad group.")
        st.dataframe(resumen, use_container_width=True)

        # Guardamos en sesión para etapa 2
        st.session_state["df_filtrado"] = df_ads
        st.session_state["campaign_col"] = campaign_col
        st.session_state["adgroup_col"] = adgroup_col
        st.session_state["asin_col"] = asin_col

    # =====================================================
    # ETAPA 2 — LISTA DE ASINS Y ACCIÓN
    # =====================================================

    if "df_filtrado" in st.session_state:

        st.header("2️⃣ Introducir lista de ASINs")

        asins_text = st.text_area(
            "Pega ASINs (uno por línea, separados por coma o espacio)",
            height=150
        )

        accion = st.selectbox(
            "🎯 Acción a aplicar",
            [
                "Activar (enabled)",
                "Pausar (paused)",
                "Crear y activar (create+enabled)"
            ]
        )

        if st.button("🚀 Generar vista previa"):

            if not asins_text.strip():
                st.error("Debes introducir al menos un ASIN.")
                st.stop()

            lista_asins = parse_asins(asins_text)

            df_filtrado = st.session_state["df_filtrado"]
            campaign_col = st.session_state["campaign_col"]
            adgroup_col = st.session_state["adgroup_col"]
            asin_col = st.session_state["asin_col"]

            combinaciones = df_filtrado[[campaign_col, adgroup_col]].drop_duplicates()

            filas = []

            for asin in lista_asins:
                for _, row in combinaciones.iterrows():

                    operation = "update"
                    state = "enabled"

                    if "Pausar" in accion:
                        state = "paused"

                    if "Crear" in accion:
                        operation = "create"

                    filas.append({
                        "Product": "Sponsored Products",
                        "Entity": "Product Ad",
                        "Operation": operation,
                        campaign_col: row[campaign_col],
                        adgroup_col: row[adgroup_col],
                        "ASIN": asin,
                        "State": state
                    })

            df_resultado = pd.DataFrame(filas)

            st.subheader("📄 Vista previa de operaciones")
            st.dataframe(df_resultado, use_container_width=True)

            # =====================================================
            # DESCARGA CSV
            # =====================================================

            buffer = BytesIO()
            df_resultado.to_csv(buffer, index=False, sep=";", encoding="utf-8-sig")
            buffer.seek(0)

            st.download_button(
                "⬇️ Descargar CSV para Amazon",
                buffer,
                file_name="bulk_operaciones_asins.csv",
                mime="text/csv"
            )
