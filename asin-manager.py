import streamlit as st
import pandas as pd
import re
import unicodedata
from io import BytesIO
from typing import List

st.set_page_config(page_title="Gestor de ASINs - Campañas", page_icon="📦", layout="wide")
st.title("📦 Gestor de ASINs en Campañas")
st.caption("Filtra campañas y grupos, luego introduce lista de ASINs para activar/pausar/añadir. CSV final listo para descargar.")

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
    df.columns = [strip_accents(str(c)).strip() for c in df.columns]
    return df

def procesar_asins(df_filtrado: pd.DataFrame, campaign_col: str, adgroup_col: str, lista_asins: List[str], accion: str) -> pd.DataFrame:
    """
    Genera DataFrame con las operaciones según lista de ASINs y acción seleccionada.
    """
    filas = []
    # Usar solo columnas existentes
    columnas_validas = [c for c in [campaign_col, adgroup_col] if c in df_filtrado.columns]
    if not columnas_validas:
        return pd.DataFrame()  # Si no hay columnas válidas, devolvemos vacío

    grupos_destino = df_filtrado[columnas_validas].drop_duplicates().values.tolist()
    
    for asin in lista_asins:
        asin = asin.strip().upper()
        for grupo in grupos_destino:
            fila = {
                'Product': 'Sponsored Products',
                'Entity': 'Product Ad',
                'Operation': accion,
                'ASIN': asin
            }
            # Mapear campañas y grupos solo si existen
            if campaign_col in df_filtrado.columns:
                fila['Campaign Name'] = grupo[0]
            if adgroup_col in df_filtrado.columns:
                fila['Ad Group Name'] = grupo[1] if len(grupo) > 1 else ''
            filas.append(fila)
    return pd.DataFrame(filas)

# =====================
# Interfaz de usuario
# =====================
uploaded_file = st.file_uploader("📤 Sube tu archivo bulk de Amazon (Excel)", type=["xlsx"])

if uploaded_file:
    xls = pd.ExcelFile(uploaded_file)
    st.write("Hojas disponibles en el archivo:", xls.sheet_names)
    
    posibles = ["sponsored products", "campañas de sponsored products"]
    hoja_detectada = next((s for s in xls.sheet_names if any(k.lower() in s.lower() for k in posibles)), None)
    
    hojas = xls.sheet_names
    indice_default = hojas.index(hoja_detectada) if hoja_detectada in hojas else 0
    hoja_seleccionada = st.selectbox("Selecciona la hoja que contiene los anuncios", hojas, index=indice_default)
    
    df = pd.read_excel(xls, sheet_name=hoja_seleccionada, dtype=str)
    df = clean_columns(df)
    
    st.subheader("🔍 Vista previa del archivo (primeras 10 filas)")
    st.dataframe(df.head(10), use_container_width=True)
    
    # =====================
    # Configuración de filtros
    # =====================
    col1, col2 = st.columns(2)
    with col1:
        filtro_campania = st.text_input("🔎 Texto para filtrar campañas (opcional)", placeholder="Ej: BR")
    with col2:
        filtro_grupo = st.text_input("📁 Texto para filtrar grupos (opcional)", placeholder="Ej: EXACT")
    
    # Botón de filtrar
    if st.button("🔎 Filtrar campañas y grupos"):
        entity_col = "Entidad"
        if entity_col not in df.columns:
            st.error(f"No se encontró la columna '{entity_col}' en el archivo.")
        else:
            mask_entity = df[entity_col].str.lower().str.contains("anuncio de producto", na=False)
            df_ads = df[mask_entity].copy()
            
            if df_ads.empty:
                st.error("No se encontraron filas de 'Anuncio de producto'.")
            else:
                # Detectar columnas seguras
                posibles_campaign = ["Nombre de la campaña (Solo informativo)", "Nombre de la campaña"]
                posibles_adgroup = ["Nombre del grupo de anuncios (Solo informativo)", "Nombre del grupo de anuncios"]
                
                campaign_col = next((c for c in posibles_campaign if c in df_ads.columns), None)
                adgroup_col = next((c for c in posibles_adgroup if c in df_ads.columns), None)
                
                if not campaign_col and not adgroup_col:
                    st.error("No se encontraron columnas de campaña ni grupo en el archivo.")
                else:
                    # Filtros opcionales
                    if filtro_campania.strip() and campaign_col:
                        df_ads = df_ads[df_ads[campaign_col].str.contains(re.escape(filtro_campania.strip()), case=False, na=False)]
                    if filtro_grupo.strip() and adgroup_col:
                        df_ads = df_ads[df_ads[adgroup_col].str.contains(re.escape(filtro_grupo.strip()), case=False, na=False)]
                    
                    if df_ads.empty:
                        st.warning("No se encontraron campañas o grupos que coincidan con los filtros.")
                    else:
                        st.subheader("📄 Vista previa de campañas y grupos filtrados")
                        
                        # Forzar las columnas en el orden deseado
                        columnas_deseadas = [
                            "Nombre de la campaña (Solo informativo)",
                            "Nombre del grupo de anuncios (Solo informativo)"
                        ]
                        
                        # Crear DataFrame seguro rellenando columnas ausentes con cadena vacía
                        resumen = pd.DataFrame()
                        for col in columnas_deseadas:
                            if col in df_ads.columns:
                                resumen[col] = df_ads[col]
                            else:
                                resumen[col] = ""  # Si no existe la columna, poner vacío

# Eliminar duplicados y resetear índice
resumen = resumen.drop_duplicates().reset_index(drop=True)
st.dataframe(resumen, use_container_width=True)
                        
                        # =====================
                        # Etapa 2: introducir ASINs y seleccionar acción
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
                        
                        if st.button("✅ Validar ASINs y generar vista previa"):
                            if not asins_text.strip():
                                st.error("Debes introducir al menos un ASIN.")
                            else:
                                # Parseamos ASINs
                                lista_asins = re.split(r'[\n, ]+', asins_text.strip())
                                lista_asins = [a.upper() for a in lista_asins if a]
                                
                                df_resultado = procesar_asins(df_ads, campaign_col, adgroup_col, lista_asins, accion)
                                
                                if df_resultado.empty:
                                    st.warning("No se pudieron generar acciones. Revisa las columnas y los filtros.")
                                else:
                                    st.subheader("📄 Vista previa de acciones a generar")
                                    st.dataframe(df_resultado, use_container_width=True)
                                    
                                    # Botón de descarga CSV
                                    csv_buffer = BytesIO()
                                    df_resultado.to_csv(csv_buffer, sep=';', index=False, encoding='utf-8-sig')
                                    csv_buffer.seek(0)
                                    
                                    st.download_button(
                                        label="⬇️ Descargar archivo de operaciones (CSV)",
                                        data=csv_buffer,
                                        file_name="operaciones_asins.csv",
                                        mime="text/csv"
                                    )
