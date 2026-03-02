import streamlit as st
import pandas as pd
import re
import unicodedata
from io import BytesIO
from typing import List, Optional

# Configuración de la página
st.set_page_config(page_title="Gestor de Anuncios ASIN", page_icon="📦", layout="wide")
st.title("📦 Gestor de Anuncios por ASIN (Product Ads)")
st.caption("Activa, pausa, crea o sincroniza (Adapt) anuncios de producto en campañas de Sponsored Products.")

# =====================
# Funciones auxiliares (inspiradas en BidForest Lite)
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
        x = x.replace("\ufeff", "")   # BOM
        x = x.replace("\u200b", "")   # zero-width
        x = x.replace("\xa0", " ")    # NBSP -> space normal
        x = re.sub(r"\s+", " ", x)    # colapsa espacios múltiples
        return x.strip()

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [" ".join([str(c) for c in col if str(c) != "nan"]).strip() for col in df.columns]

    df.columns = [_clean(c) for c in df.columns]
    return df

def find_col(df: pd.DataFrame, options) -> str | None:
    if isinstance(options, str):
        options = [options]

    def norm(x: str) -> str:
        x = str(x)
        x = x.replace("\ufeff", "").replace("\u200b", "").replace("\xa0", " ")
        x = re.sub(r"\s+", " ", x).strip().lower()
        x = strip_accents(x)
        return x

    cols = list(df.columns)
    cols_norm = {norm(c): c for c in cols}

    for opt in options:
        optn = norm(opt)
        if optn in cols_norm:
            return cols_norm[optn]
        for cn, original in cols_norm.items():
            if cn.startswith(optn + "."):
                return original
    return None

def find_sheet_by_name(xls: pd.ExcelFile, keywords: List[str]) -> Optional[str]:
    """Busca una hoja que contenga alguna de las palabras clave en su nombre."""
    for sheet in xls.sheet_names:
        if any(kw.lower() in sheet.lower() for kw in keywords):
            return sheet
    return None

def procesar_bulk(
    df: pd.DataFrame,
    lista_asins: List[str],
    filtro_campania: str,
    modo: str,
    accion: str,  # 'enabled', 'paused' o 'adapt'
    filtro_grupo: Optional[str] = None
) -> pd.DataFrame:
    """
    Genera DataFrame con operaciones en bloque.
    """
    # 1. Filtrar por entidad "Anuncio de producto"
    col_entidad = find_col(df, ["Entidad", "Entity"])
    if not col_entidad:
        st.error("No se encontró columna de entidad.")
        return pd.DataFrame()
    
    mask_entidad = df[col_entidad].astype(str).str.lower().str.contains('anuncio de producto', na=False)
    df_ads = df[mask_entidad].copy()
    if df_ads.empty:
        st.error("No se encontraron filas de 'Anuncio de producto'.")
        return pd.DataFrame()
    
    # 2. Filtrar por campaña
    col_campania = find_col(df, ["Nombre de la campaña", "Campaign Name", "Nombre de la campaña (Solo informativo)"])
    if not col_campania:
        st.error("No se encontró columna de nombre de campaña.")
        return pd.DataFrame()
    
    mask_campania = df_ads[col_campania].astype(str).str.contains(filtro_campania, case=False, na=False)
    df_filtrado = df_ads[mask_campania].copy()
    if df_filtrado.empty:
        st.error(f"No se encontraron anuncios en campañas que contengan '{filtro_campania}'.")
        # Mostrar algunas campañas disponibles para depuración
        st.info("Campañas disponibles en el archivo (primeras 20):")
        st.write(df_ads[col_campania].dropna().unique()[:20])
        return pd.DataFrame()
    
    # 3. Filtrar por grupo si se indica
    col_grupo_nombre = find_col(df, ["Nombre del grupo de anuncios", "Ad Group Name", "Nombre del grupo de anuncios (Solo informativo)"])
    if filtro_grupo and col_grupo_nombre:
        mask_grupo = df_filtrado[col_grupo_nombre].astype(str).str.contains(filtro_grupo, case=False, na=False)
        df_filtrado = df_filtrado[mask_grupo].copy()
        if df_filtrado.empty:
            st.error(f"No se encontraron anuncios en grupos que contengan '{filtro_grupo}'.")
            return pd.DataFrame()
    
    # 4. Obtener IDs necesarios
    col_campaign_id = find_col(df, ["ID de la campaña", "Campaign ID"])
    col_adgroup_id = find_col(df, ["ID del grupo de anuncios", "Ad Group ID"])
    col_ad_id = find_col(df, ["ID del anuncio", "Ad ID"])
    col_asin = find_col(df, ["ASIN", "ASIN (Solo informativo)"])
    col_estado = find_col(df, ["Estado", "State"])
    
    if not all([col_campaign_id, col_adgroup_id, col_asin]):
        st.error("Faltan columnas esenciales (ID de campaña, ID de grupo o ASIN).")
        return pd.DataFrame()
    
    # Si vamos a actualizar, necesitamos ID del anuncio
    if modo in ['update', 'update+create'] and not col_ad_id:
        st.error("No se encontró columna de ID del anuncio. No se pueden realizar actualizaciones.")
        return pd.DataFrame()
    
    # Para el modo 'adapt' también necesitamos ID y estado actual
    if modo == 'adapt' and (not col_ad_id or not col_estado):
        st.error("El modo 'adapt' requiere columna de ID del anuncio y columna de estado actual.")
        return pd.DataFrame()
    
    # 5. Mostrar vista previa de la selección (campañas y grupos)
    st.subheader("🔍 Vista previa de la selección")
    resumen = df_filtrado.groupby([col_campania, col_grupo_nombre if col_grupo_nombre else 'Grupo']).size().reset_index(name='Nº anuncios')
    st.dataframe(resumen, use_container_width=True)
    
    # 6. Conteo de ASIN activos por grupo
    if col_estado:
        activos = df_filtrado[df_filtrado[col_estado].astype(str).str.lower().isin(['enabled', 'activada', 'activo'])]
        if not activos.empty:
            resumen_activos = activos.groupby([col_campania, col_grupo_nombre if col_grupo_nombre else 'Grupo']).size().reset_index(name='ASIN activos')
            st.subheader("📊 ASIN activos por grupo")
            st.dataframe(resumen_activos, use_container_width=True)
    
    # 7. Mapear ASIN existentes en el filtro con sus datos
    asins_existentes = {}
    for _, row in df_filtrado.iterrows():
        asin = str(row.get(col_asin, '')).strip()
        if asin:
            asins_existentes[asin] = {
                'ad_id': str(row.get(col_ad_id, '')).strip() if col_ad_id else '',
                'campaign_id': str(row.get(col_campaign_id, '')).strip(),
                'ad_group_id': str(row.get(col_adgroup_id, '')).strip(),
                'estado_actual': str(row.get(col_estado, '')).strip().lower() if col_estado else ''
            }
    
    # 8. Para create: grupos destino (todos los grupos únicos del filtro)
    grupos_destino = set()
    if modo in ['create', 'update+create', 'adapt']:
        for _, row in df_filtrado.iterrows():
            grupos_destino.add((
                str(row.get(col_campaign_id, '')).strip(),
                str(row.get(col_adgroup_id, '')).strip()
            ))
        if not grupos_destino:
            st.error("No hay grupos de anuncios para crear los nuevos ASIN.")
            return pd.DataFrame()
    
    # 9. Generar filas de salida según el modo
    filas = []
    
    if modo == 'adapt':
        # Conjunto de ASIN existentes en el filtro
        asins_filtro = set(asins_existentes.keys())
        asins_lista = set(lista_asins)
        
        # 9a. Actualizar los que están en la lista pero están pausados
        for asin in asins_lista.intersection(asins_filtro):
            info = asins_existentes[asin]
            if info['estado_actual'] in ['paused', 'en pausa']:
                filas.append({
                    'Product': 'Sponsored Products',
                    'Entity': 'Product Ad',
                    'Operation': 'update',
                    'Campaign ID': info['campaign_id'],
                    'Ad Group ID': info['ad_group_id'],
                    'Ad ID': info['ad_id'],
                    'State': 'enabled',
                    'SKU': '',
                    'ASIN': asin
                })
            # Si ya está activo, no se añade nada
        
        # 9b. Crear los que están en la lista pero no existen
        for asin in asins_lista - asins_filtro:
            for camp_id, group_id in grupos_destino:
                filas.append({
                    'Product': 'Sponsored Products',
                    'Entity': 'Product Ad',
                    'Operation': 'create',
                    'Campaign ID': camp_id,
                    'Ad Group ID': group_id,
                    'Ad ID': '',
                    'State': 'enabled',
                    'SKU': '',
                    'ASIN': asin
                })
        
        # 9c. Pausar los que existen en el filtro pero no están en la lista
        for asin in asins_filtro - asins_lista:
            info = asins_existentes[asin]
            if info['estado_actual'] not in ['paused', 'en pausa']:
                filas.append({
                    'Product': 'Sponsored Products',
                    'Entity': 'Product Ad',
                    'Operation': 'update',
                    'Campaign ID': info['campaign_id'],
                    'Ad Group ID': info['ad_group_id'],
                    'Ad ID': info['ad_id'],
                    'State': 'paused',
                    'SKU': '',
                    'ASIN': asin
                })
    
    else:  # modos originales: update, create, update+create
        # Updates
        if modo in ['update', 'update+create']:
            for asin, info in asins_existentes.items():
                if asin in lista_asins:
                    filas.append({
                        'Product': 'Sponsored Products',
                        'Entity': 'Product Ad',
                        'Operation': 'update',
                        'Campaign ID': info['campaign_id'],
                        'Ad Group ID': info['ad_group_id'],
                        'Ad ID': info['ad_id'],
                        'State': accion,
                        'SKU': '',
                        'ASIN': asin
                    })
        
        # Creates
        if modo in ['create', 'update+create']:
            asins_a_crear = set(lista_asins) - set(asins_existentes.keys())
            for asin in asins_a_crear:
                for camp_id, group_id in grupos_destino:
                    filas.append({
                        'Product': 'Sponsored Products',
                        'Entity': 'Product Ad',
                        'Operation': 'create',
                        'Campaign ID': camp_id,
                        'Ad Group ID': group_id,
                        'Ad ID': '',
                        'State': accion,
                        'SKU': '',
                        'ASIN': asin
                    })
    
    if not filas:
        st.warning("No se generaron acciones. Revisa los filtros y la lista de ASIN.")
        return pd.DataFrame()
    
    df_salida = pd.DataFrame(filas)
    # Ordenar columnas
    columnas = ['Product', 'Entity', 'Operation', 'Campaign ID', 'Ad Group ID', 'Ad ID', 'State', 'SKU', 'ASIN']
    df_salida = df_salida[columnas]
    return df_salida

# =====================
# Interfaz de usuario
# =====================
uploaded_file = st.file_uploader("📤 Sube tu archivo bulk de Amazon (Excel)", type=["xlsx"])

if uploaded_file is not None:
    # Cargar Excel
    xls = pd.ExcelFile(uploaded_file)
    
    # Detectar posibles hojas de Sponsored Products
    posibles = ["sponsored products", "campañas de sponsored products"]
    hoja_detectada = find_sheet_by_name(xls, posibles)
    
    if hoja_detectada:
        st.success(f"Hoja detectada automáticamente: {hoja_detectada}")
    else:
        st.warning("No se pudo detectar la hoja de Sponsored Products. Selecciona manualmente.")
    
    # Selector de hoja (permitir cambio manual)
    hojas = xls.sheet_names
    indice_default = hojas.index(hoja_detectada) if hoja_detectada in hojas else 0
    hoja_seleccionada = st.selectbox("Selecciona la hoja que contiene los anuncios", hojas, index=indice_default)
    
    # Leer la hoja seleccionada
    df = pd.read_excel(xls, sheet_name=hoja_seleccionada, dtype=str)
    df = clean_columns(df)
    
    st.subheader("🔍 Vista previa del archivo (primeras 20 filas)")
    st.dataframe(df.head(20), use_container_width=True)
    
    st.divider()
    
    # Parámetros de filtrado y acción
    col1, col2 = st.columns(2)
    with col1:
        filtro_campania = st.text_input("🔎 Texto para filtrar campañas (obligatorio)", placeholder="Ej: (ES) SP | Hand Sanitizer | KW | BR")
        filtro_grupo = st.text_input("📁 Texto para filtrar grupos (opcional)", placeholder="Ej: EXACT o BROAD (dejar vacío para todos)")
    with col2:
        modo = st.selectbox("⚙️ Modo de operación", ["update", "create", "update+create", "adapt"])
        # Para modos que no sean adapt, mostramos el selector de acción
        if modo != "adapt":
            accion = st.radio("🎯 Acción", ["enabled", "paused"], horizontal=True)
        else:
            accion = "adapt"  # placeholder, no se usa directamente
    
    # Lista de ASIN
    st.subheader("📋 Lista de ASIN a gestionar")
    asins_text = st.text_area("Introduce los ASIN (uno por línea)", height=150, placeholder="B0DD76X9L3\nB0DD79GXQX\nB0F3JXNZ85")
    
    if st.button("🚀 Generar archivo de operaciones", type="primary"):
        if not filtro_campania.strip():
            st.error("Debes introducir un filtro de campaña.")
            st.stop()
        if not asins_text.strip():
            st.error("Debes introducir al menos un ASIN.")
            st.stop()
        
        # Procesar lista de ASIN
        lista_asins = [asin.strip().upper() for asin in asins_text.splitlines() if asin.strip()]
        
        with st.spinner("Procesando..."):
            df_resultado = procesar_bulk(
                df=df,
                lista_asins=lista_asins,
                filtro_campania=filtro_campania.strip(),
                modo=modo,
                accion=accion if modo != "adapt" else "adapt",
                filtro_grupo=filtro_grupo.strip() if filtro_grupo.strip() else None
            )
        
        if not df_resultado.empty:
            st.success("✅ Archivo generado correctamente")
            st.subheader("📄 Vista previa de las operaciones")
            st.dataframe(df_resultado, use_container_width=True)
            
            # Convertir a CSV para descarga
            csv_buffer = BytesIO()
            df_resultado.to_csv(csv_buffer, sep=';', index=False, encoding='utf-8-sig')
            csv_buffer.seek(0)
            
            st.download_button(
                label="⬇️ Descargar archivo de operaciones (CSV)",
                data=csv_buffer,
                file_name="operaciones_asins.csv",
                mime="text/csv"
            )
