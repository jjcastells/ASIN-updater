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
# ESQUEMA CENTRALIZADO DE COLUMNAS (versión exhaustiva)
# Incluye TODAS las variantes reales observadas en bulks de Amazon EU/US
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
        "nombre de la campaña (solo informativo)",
        "nombre de campaña",
        "campaign name (informational only)",  # duplicado pero explícito
        "campaign name (solo informativo)"      # mezcla
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
    """
    Construye un diccionario que mapea claves canónicas a nombres reales de columna.
    Normalización: lower case, sin acentos, sin BOM/NBSP, espacios simples.
    ¡Los paréntesis se conservan!
    """
    def norm(x):
        x = strip_accents(str(x)).lower()
        x = x.replace("\ufeff", "").replace("\u200b", "").replace("\xa0", " ")
        x = re.sub(r"\s+", " ", x).strip()
        return x

    # Guardamos también los nombres originales para depuración
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

def procesar_bulk(
    df: pd.DataFrame,
    lista_asins: List[str],
    filtro_campania: str,
    modo: str,
    accion: str,
    filtro_grupo: Optional[str] = None
) -> pd.DataFrame:
    """
    Genera DataFrame con operaciones en bloque.
    """
    # 1. Obtener mapeo de columnas y mostrar (debug)
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

    # Mostrar nombres reales para verificación
    st.write("**Nombres reales de columnas encontradas:**")
    st.write({k: v for k, v in column_map.items() if v})

    # Validar columnas esenciales
    required = ["entity", "campaign_name", "campaign_id", "ad_group_id", "asin"]
    missing = [k for k in required if k not in column_map]
    if missing:
        st.error(f"Faltan columnas esenciales en el archivo: {missing}")
        return pd.DataFrame()

    # 2. Filtrar por entidad "Product Ad" (más tolerante)
    mask_entidad = df[col_entidad].astype(str).str.lower().str.contains(
        r"product\s*ad|anuncio\s*de\s*producto",
        na=False,
        regex=True
    )
    df_ads = df[mask_entidad].copy()
    if df_ads.empty:
        st.error("No se encontraron filas de 'Anuncio de producto' o 'Product Ad'.")
        return pd.DataFrame()

    # Mostrar valores de campaña para depuración (usando la columna correcta)
    st.write("**Primeros 20 valores de campaña (después de filtro de entidad):**")
    unique_campaigns = df_ads[col_campania].dropna().astype(str).unique()[:20]
    st.write(unique_campaigns)

    # 3. Filtrar por campaña
    try:
        pattern = re.escape(filtro_campania)
    except:
        pattern = filtro_campania
    st.write(f"**Patrón de búsqueda:** '{pattern}' (escapado)")

    mask_campania = df_ads[col_campania].astype(str).str.contains(
        pattern, case=False, na=False, regex=True
    )
    df_filtrado = df_ads[mask_campania].copy()

    if df_filtrado.empty:
        st.error(f"No se encontraron anuncios en campañas que contengan '{filtro_campania}'.")
        st.info("Campañas disponibles en el archivo (primeras 20):")
        st.write(unique_campaigns)
        return pd.DataFrame()

    # 4. Filtrar por grupo si se indica
    if filtro_grupo and col_grupo_nombre:
        mask_grupo = df_filtrado[col_grupo_nombre].astype(str).str.contains(
            re.escape(filtro_grupo), case=False, na=False, regex=True
        )
        df_filtrado = df_filtrado[mask_grupo].copy()
        if df_filtrado.empty:
            st.error(f"No se encontraron anuncios en grupos que contengan '{filtro_grupo}'.")
            return pd.DataFrame()

    # 5. Vista previa de la selección
    st.subheader("🔍 Vista previa de la selección")
    if col_grupo_nombre:
        resumen = df_filtrado.groupby([col_campania, col_grupo_nombre]).size().reset_index(name='Nº anuncios')
    else:
        resumen = df_filtrado.groupby([col_campania]).size().reset_index(name='Nº anuncios')
    st.dataframe(resumen, use_container_width=True)

    # 6. Conteo de ASIN activos por grupo
    if col_estado:
        estados_activos = ['enabled', 'activada', 'activo']
        mask_activo = df_filtrado[col_estado].astype(str).str.lower().str.strip().isin(estados_activos)
        activos = df_filtrado[mask_activo].copy()
        if not activos.empty:
            if col_grupo_nombre:
                resumen_activos = activos.groupby([col_campania, col_grupo_nombre]).size().reset_index(name='ASIN activos')
            else:
                resumen_activos = activos.groupby([col_campania]).size().reset_index(name='ASIN activos')
            st.subheader("📊 ASIN activos por grupo")
            st.dataframe(resumen_activos, use_container_width=True)

    # 7. Mapear ASIN existentes (pueden estar en múltiples grupos)
    asins_existentes = {}
    for _, row in df_filtrado.iterrows():
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

    # 8. Grupos destino para creates
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

    # 9. Generar filas de salida (sin cambios)
    filas = []

    if modo == 'adapt':
        asins_lista = set(lista_asins)
        asins_filtro = set(asins_existentes.keys())

        for asin in asins_lista.intersection(asins_filtro):
            for info in asins_existentes[asin]:
                if info['estado_actual'] == 'paused':
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

        for asin in asins_filtro - asins_lista:
            for info in asins_existentes[asin]:
                if info['estado_actual'] == 'enabled':
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

    else:
        if modo in ['update', 'update+create']:
            for asin, lista_info in asins_existentes.items():
                if asin in lista_asins:
                    for info in lista_info:
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
    columnas = ['Product', 'Entity', 'Operation', 'Campaign ID', 'Ad Group ID', 'Ad ID', 'State', 'SKU', 'ASIN']
    df_salida = df_salida[columnas]
    return df_salida

# =====================
# Interfaz de usuario
# =====================
uploaded_file = st.file_uploader("📤 Sube tu archivo bulk de Amazon (Excel)", type=["xlsx"])

if uploaded_file is not None:
    xls = pd.ExcelFile(uploaded_file)
    st.write("Hojas disponibles en el archivo:", xls.sheet_names)

    posibles = ["sponsored products", "campañas de sponsored products"]
    hoja_detectada = find_sheet_by_name(xls, posibles)

    if hoja_detectada:
        st.success(f"Hoja detectada automáticamente: {hoja_detectada}")
    else:
        st.warning("No se pudo detectar la hoja de Sponsored Products. Selecciona manualmente.")

    hojas = xls.sheet_names
    indice_default = hojas.index(hoja_detectada) if hoja_detectada in hojas else 0
    hoja_seleccionada = st.selectbox("Selecciona la hoja que contiene los anuncios", hojas, index=indice_default)

    df = pd.read_excel(xls, sheet_name=hoja_seleccionada, dtype=str)
    df = clean_columns(df)

    st.subheader("🔍 Vista previa del archivo (primeras 20 filas)")
    st.dataframe(df.head(20), use_container_width=True)

    st.divider()

    col1, col2 = st.columns(2)
    with col1:
        filtro_campania = st.text_input("🔎 Texto para filtrar campañas (obligatorio)", placeholder="Ej: (ES) SP | Hand Sanitizer | KW | BR")
        filtro_grupo = st.text_input("📁 Texto para filtrar grupos (opcional)", placeholder="Ej: EXACT o BROAD (dejar vacío para todos)")
    with col2:
        modo = st.selectbox("⚙️ Modo de operación", ["update", "create", "update+create", "adapt"])
        if modo != "adapt":
            accion = st.radio("🎯 Acción", ["enabled", "paused"], horizontal=True)
        else:
            accion = "adapt"

    st.subheader("📋 Lista de ASIN a gestionar")
    asins_text = st.text_area("Introduce los ASIN (uno por línea)", height=150, placeholder="B0DD76X9L3\nB0DD79GXQX\nB0F3JXNZ85")

    if st.button("🚀 Generar archivo de operaciones", type="primary"):
        if not filtro_campania.strip():
            st.error("Debes introducir un filtro de campaña.")
            st.stop()
        if not asins_text.strip():
            st.error("Debes introducir al menos un ASIN.")
            st.stop()

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

            csv_buffer = BytesIO()
            df_resultado.to_csv(csv_buffer, sep=';', index=False, encoding='utf-8-sig')
            csv_buffer.seek(0)

            st.download_button(
                label="⬇️ Descargar archivo de operaciones (CSV)",
                data=csv_buffer,
                file_name="operaciones_asins.csv",
                mime="text/csv"
            )
