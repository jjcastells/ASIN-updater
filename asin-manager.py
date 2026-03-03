import streamlit as st
import pandas as pd
import re
from io import BytesIO

st.set_page_config(page_title="Gestor de ASINs - Campañas", page_icon="📦", layout="wide")
st.title("📦 Gestor de ASINs en Campañas")
st.caption("Filtra campañas y grupos, luego introduce lista de ASINs para activar/pausar/añadir. CSV final listo para descargar.")

# =====================
# Función para generar operaciones
# =====================
def procesar_asins(df_filtrado, lista_asins, accion):
    filas = []
    for asin in lista_asins:
        asin = asin.strip().upper()
        for _, row in df_filtrado.iterrows():
            filas.append({
                'Operación': accion,
                'ID de la campaña': row['ID de la campaña'],
                'ID del grupo de anuncios': row['ID del grupo de anuncios'],
                'ID del anuncio': row['ID del anuncio'],
                'SKU': row['SKU'],
                'ASIN (Solo informativo)': asin,
                'Nombre de la campaña (Solo informativo)': row['Nombre de la campaña (Solo informativo)'],
                'Nombre del grupo de anuncios (Solo informativo)': row['Nombre del grupo de anuncios (Solo informativo)']
            })
    return pd.DataFrame(filas)

# =====================
# Subir archivo Excel
# =====================
uploaded_file = st.file_uploader("📤 Sube tu archivo bulk de Amazon (Excel)", type=["xlsx"])
if uploaded_file:
    xls = pd.ExcelFile(uploaded_file)
    
    # Selector de hoja con valor por defecto en la segunda hoja
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

    # =====================
    # Inicializar session_state
    # =====================
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
    # Botón de generar vista previa y CSV
    # =====================
    if st.button("✅ Validar ASINs y generar vista previa"):
        if not st.session_state.filtrado_listo:
            st.error("Primero debes filtrar campañas y grupos.")
        elif not asins_text.strip():
            st.error("Debes introducir al menos un ASIN.")
        else:
            df_ads_filtrado = st.session_state.df_ads_filtrado
            lista_asins = re.split(r'[\n, ]+', asins_text.strip())
            lista_asins = [a.upper() for a in lista_asins if a]

            df_resultado = procesar_asins(df_ads_filtrado, lista_asins, accion)

            if df_resultado.empty:
                st.warning("No se pudieron generar acciones. Revisa las columnas y los filtros.")
            else:
                # Guardar en session_state para persistencia
                st.session_state.df_resultado = df_resultado
                st.session_state.accion = accion

                # --- Vista previa ---
                st.subheader("📄 Vista previa de acciones a generar")
                st.dataframe(df_resultado, use_container_width=True)

                # =========================
                # Generación del CSV para Amazon con validación
                # =========================
                df_csv = df_resultado.copy()
                df_csv['Product'] = 'Sponsored Products'
                df_csv['Entity'] = 'Product Ad'
                df_csv['Operation'] = accion
                df_csv['Campaign ID'] = df_csv['ID de la campaña']
                df_csv['Ad Group ID'] = df_csv['ID del grupo de anuncios']
                df_csv['Ad ID'] = df_csv['ID del anuncio']

                columnas_amazon = ['Product', 'Entity', 'Operation', 'Campaign ID', 'Ad Group ID', 'Ad ID']
                df_csv = df_csv[columnas_amazon]

                # =========================
                # Función de validación antes de exportar
                # =========================
                def validar_para_amazon(df_csv):
                    # 1️⃣ Verificar que no haya valores vacíos en columnas obligatorias
                    if df_csv[columnas_amazon].isnull().any().any():
                        st.error("❌ Error: Hay valores vacíos en columnas obligatorias. Revisa IDs y filas.")
                        return False

                    # 2️⃣ Verificar que Campaign ID, Ad Group ID y Ad ID sean enteros
                    for col in ['Campaign ID', 'Ad Group ID', 'Ad ID']:
                        if not df_csv[col].apply(lambda x: str(x).isdigit()).all():
                            st.error(f"❌ Error: La columna '{col}' debe contener solo números enteros.")
                            return False

                    # 3️⃣ Limpiar espacios extra
                    df_csv[columnas_amazon] = df_csv[columnas_amazon].applymap(lambda x: str(x).strip())

                    return True

                # =========================
                # Exportar CSV solo si pasa validación
                # =========================
                if validar_para_amazon(df_csv):
                    csv_buffer = BytesIO()
                    df_csv.to_csv(csv_buffer, sep=',', index=False, encoding='utf-8-sig')
                    csv_buffer.seek(0)

                    st.download_button(
                        label="⬇️ Descargar archivo de operaciones (CSV)",
                        data=csv_buffer,
                        file_name="operaciones_asins.csv",
                        mime="text/csv"
                    )
