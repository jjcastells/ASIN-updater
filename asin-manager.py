import streamlit as st
import pandas as pd
import re
from io import BytesIO

st.set_page_config(page_title="Gestor de ASINs - Campañas", page_icon="📦", layout="wide")
st.title("📦 Gestor de ASINs en Campañas")
st.caption("Filtra campañas y grupos, luego introduce lista de ASINs para activar/pausar/añadir. CSV final listo para descargar.")

# =====================
# Helpers
# =====================
def normalize_id(s):
    s = str(s).strip()
    s = re.sub(r"\.0$", "", s)  # elimina .0
    s = re.sub(r"[^\d]", "", s)  # solo dígitos
    return s

def procesar_asins(df_filtrado, lista_asins, accion):
    filas = []
    for asin in lista_asins:
        asin = asin.strip().upper()
        for _, row in df_filtrado.iterrows():
            filas.append({
                'Operación': accion,
                'ID de la campaña': normalize_id(row['ID de la campaña']),
                'ID del grupo de anuncios': normalize_id(row['ID del grupo de anuncios']),
                'ID del anuncio': normalize_id(row.get('ID del anuncio', '')),
                'SKU': row.get('SKU', ''),
                'ASIN (Solo informativo)': asin,
                'Nombre de la campaña (Solo informativo)': row.get('Nombre de la campaña (Solo informativo)', ''),
                'Nombre del grupo de anuncios (Solo informativo)': row.get('Nombre del grupo de anuncios (Solo informativo)', '')
            })
    return pd.DataFrame(filas)

# =====================
# Subir archivo Excel
# =====================
uploaded_file = st.file_uploader("📤 Sube tu archivo bulk de Amazon (Excel)", type=["xlsx"])
if uploaded_file:
    xls = pd.ExcelFile(uploaded_file)
    hojas = xls.sheet_names
    indice_default = 1 if len(hojas) > 1 else 0
    hoja_seleccionada = st.selectbox("Selecciona la hoja que contiene los anuncios", hojas, index=indice_default)
    
    df = pd.read_excel(xls, sheet_name=hoja_seleccionada, dtype=str)
    st.subheader("🔍 Vista previa del archivo (primeras 10 filas)")
    st.dataframe(df.head(10), use_container_width=True)

    # =====================
    # Filtros de campaña y ad group
    # =====================
    col1, col2 = st.columns(2)
    with col1:
        filtro_campania = st.text_input("🔎 Filtrar campañas (opcional)", placeholder="Ej: BR")
    with col2:
        filtro_grupo = st.text_input("📁 Filtrar grupos (opcional)", placeholder="Ej: EXACT")

    if 'df_ads_filtrado' not in st.session_state:
        st.session_state.df_ads_filtrado = pd.DataFrame()
    if 'filtrado_listo' not in st.session_state:
        st.session_state.filtrado_listo = False

    # =====================
    # Botón de filtrar campañas y grupos
    # =====================
    if st.button("🔎 Filtrar campañas y grupos"):
        entity_col = "Entidad"
        df_ads = df[df[entity_col].str.lower() == "anuncio de producto"].copy()

        if filtro_campania.strip():
            df_ads = df_ads[df_ads["Nombre de la campaña (Solo informativo)"]
                            .str.contains(re.escape(filtro_campania.strip()), case=False, na=False)]
        if filtro_grupo.strip():
            df_ads = df_ads[df_ads["Nombre del grupo de anuncios (Solo informativo)"]
                            .str.contains(re.escape(filtro_grupo.strip()), case=False, na=False)]

        st.session_state.df_ads_filtrado = df_ads
        st.session_state.filtrado_listo = True

        if df_ads.empty:
            st.warning("No se encontraron campañas o grupos que coincidan con los filtros.")
        else:
            st.subheader("📄 Vista previa de campañas y grupos filtrados")
            columnas_vista = ["Nombre de la campaña (Solo informativo)", "Nombre del grupo de anuncios (Solo informativo)"]
            resumen = df_ads[columnas_vista].drop_duplicates().reset_index(drop=True)
            st.dataframe(resumen, use_container_width=True)

    # =====================
    # Introducir ASINs y seleccionar acción
    # =====================
    st.subheader("📋 Introduce lista de ASINs")
    asins_text = st.text_area(
        "Pega ASINs (uno por línea, separados por comas o espacios)",
        height=150,
        placeholder="B0DD76X9L3\nB0DD79GXQX\nB0F3JXNZ85"
    )

    accion = st.selectbox(
        "🎯 Acción a aplicar a los ASIN listados",
        ["enabled", "paused", "create+enabled"]
    )

    # =====================
    # Botón de generar CSV
    # =====================

if st.button("✅ Validar ASINs y generar CSV para Bulk Changes"):
    if not st.session_state.filtrado_listo:
        st.error("Primero debes filtrar campañas y grupos.")
    elif not asins_text.strip():
        st.error("Debes introducir al menos un ASIN.")
    else:
        df_ads_filtrado = st.session_state.df_ads_filtrado
        lista_asins = re.split(r'[\n, ,]+', asins_text.strip())
        lista_asins = [a.upper() for a in lista_asins if a]

        # Construcción de filas para CSV
        filas_csv = []
        for _, row in df_ads_filtrado.iterrows():
            for asin in lista_asins:
                asin = asin.strip().upper()
                # Determinar State según acción
                if accion.lower() == "create+enabled":
                    state_val = "enabled"
                elif accion.lower() == "paused":
                    state_val = "paused"
                elif accion.lower() == "enabled":
                    state_val = "enabled"
                else:
                    state_val = accion  # fallback

                fila = {
                    "Product": "Sponsored Products",     # fijo
                    "Entity": "Product Ad",              # fijo
                    "Operation": "Update/Create",        # fijo
                    "Campaign ID": row.get("ID de la campaña", ""),
                    "Ad Group ID": row.get("ID del grupo de anuncios", ""),
                    "Ad ID (Read only)": "",             # siempre vacío
                    "State": state_val,
                    "ASIN": asin
                }
                filas_csv.append(fila)

        df_csv = pd.DataFrame(filas_csv)

        # Validación rápida: no permitir filas sin Campaign/Ad Group/ASIN
        if df_csv[['Campaign ID', 'Ad Group ID', 'ASIN']].isnull().any().any():
            st.error("❌ Hay valores vacíos en Campaign ID, Ad Group ID o ASIN. Revisa los filtros y la lista de ASINs.")
        else:
            csv_buffer = BytesIO()
            df_csv.to_csv(csv_buffer, sep=',', index=False, encoding='utf-8-sig')
            csv_buffer.seek(0)

            st.subheader("📄 Vista previa del CSV generado")
            st.dataframe(df_csv.head(20), use_container_width=True)

            st.download_button(
                label="⬇️ Descargar CSV Bulk Changes",
                data=csv_buffer,
                file_name="bulk_changes_product_ads.csv",
                mime="text/csv"
            )
