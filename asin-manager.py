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
# ESQUEMA CENTRALIZADO
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
    "ad_id": ["ad id", "ad id (informational only)", "id del anuncio"],
    "asin": ["asin", "asin (informational only)", "asin (solo informativo)"],
    "state": ["state", "status", "ad status", "estado"]
}

# =====================
# Normalización
# =====================
def strip_accents(s: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", str(s))
        if not unicodedata.combining(ch)
    )

def clean_text(s: str) -> str:
    if not isinstance(s, str):
        return ""
    s = s.replace("\ufeff", "").replace("\u200b", "").replace("\xa0", " ")
    s = re.sub(r"\s+", " ", s)
    return strip_accents(s).lower().strip()

def clean_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [" ".join([str(c) for c in col if str(c) != "nan"]).strip() for col in df.columns]
    df.columns = [clean_text(c) for c in df.columns]
    return df

def normalizar_estado(estado: str) -> str:
    estado = clean_text(estado)
    if "enable" in estado or "activ" in estado:
        return "enabled"
    if "paus" in estado:
        return "paused"
    if "archiv" in estado:
        return "archived"
    return "unknown"

def build_column_map(df: pd.DataFrame) -> dict:
    normalized_cols = {clean_text(c): c for c in df.columns}
    column_map = {}

    for key, options in COLUMN_SCHEMA.items():
        for opt in options:
            if clean_text(opt) in normalized_cols:
                column_map[key] = normalized_cols[clean_text(opt)]
                break

    return column_map

# =====================
# FUNCIÓN PRINCIPAL
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

    st.write("Filas iniciales:", len(df))

    # =====================
    # FILTRO ENTIDAD ROBUSTO
    # =====================
    def es_product_ad(valor):
        v = clean_text(valor)
        return (
            "product ad" in v or
            "productad" in v or
            "anuncio de producto" in v
        )

    df_ads = df[df[col_entidad].apply(es_product_ad)].copy()

    st.write("Filas tras filtro entidad:", len(df_ads))

    if df_ads.empty:
        st.error("No se encontraron filas tipo Product Ad.")
        st.write("Valores únicos en columna entidad:")
        st.write(df[col_entidad].unique()[:20])
        return pd.DataFrame()

    st.write("Primeros 20 nombres campaña:")
    st.write(df_ads[col_campania].dropna().astype(str).unique()[:20])

    # =====================
    # FILTRO CAMPAÑA
    # =====================
    pattern = re.escape(filtro_campania.strip().lower())

    df_ads["_camp_norm"] = df_ads[col_campania].astype(str).apply(clean_text)

    df_filtrado = df_ads[
        df_ads["_camp_norm"].str.contains(pattern, na=False)
    ].copy()

    st.write("Filas tras filtro campaña:", len(df_filtrado))

    if df_filtrado.empty:
        st.error(f"No se encontraron campañas con '{filtro_campania}'.")
        return pd.DataFrame()

    # =====================
    # FILTRO GRUPO
    # =====================
    if filtro_grupo and col_grupo_nombre:
        pattern_grupo = re.escape(filtro_grupo.strip().lower())
        df_filtrado["_grupo_norm"] = df_filtrado[col_grupo_nombre].astype(str).apply(clean_text)

        df_filtrado = df_filtrado[
            df_filtrado["_grupo_norm"].str.contains(pattern_grupo, na=False)
        ].copy()

        st.write("Filas tras filtro grupo:", len(df_filtrado))

        if df_filtrado.empty:
            st.error("No se encontraron grupos con ese texto.")
            return pd.DataFrame()

    # =====================
    # RESUMEN
    # =====================
    st.subheader("🔍 Vista previa selección")
    if col_grupo_nombre:
        resumen = df_filtrado.groupby([col_campania, col_grupo_nombre]).size().reset_index(name="Nº anuncios")
    else:
        resumen = df_filtrado.groupby([col_campania]).size().reset_index(name="Nº anuncios")

    st.dataframe(resumen, use_container_width=True)

    # =====================
    # MAPEAR EXISTENTES
    # =====================
    asins_existentes = {}

    for _, row in df_filtrado.iterrows():
        asin = str(row[col_asin]).strip().upper()
        if not asin:
            continue

        info = {
            "ad_id": str(row.get(col_ad_id, "")).strip() if col_ad_id else "",
            "campaign_id": str(row[col_campaign_id]).strip(),
            "ad_group_id": str(row[col_adgroup_id]).strip(),
            "estado_actual": normalizar_estado(row.get(col_estado, "")) if col_estado else "unknown"
        }

        asins_existentes.setdefault(asin, []).append(info)

    grupos_destino = set(
        (str(row[col_campaign_id]).strip(), str(row[col_adgroup_id]).strip())
        for _, row in df_filtrado.iterrows()
    )

    filas = []

    # =====================
    # LÓGICA OPERATIVA
    # =====================
    if modo == "adapt":
        asins_lista = set(lista_asins)
        asins_filtro = set(asins_existentes.keys())

        for asin in asins_lista & asins_filtro:
            for info in asins_existentes[asin]:
                if info["estado_actual"] == "paused":
                    filas.append({
                        "Product": "Sponsored Products",
                        "Entity": "Product Ad",
                        "Operation": "update",
                        "Campaign ID": info["campaign_id"],
                        "Ad Group ID": info["ad_group_id"],
                        "Ad ID": info["ad_id"],
                        "State": "enabled",
                        "SKU": "",
                        "ASIN": asin
                    })

        for asin in asins_lista - asins_filtro:
            for camp_id, group_id in grupos_destino:
                filas.append({
                    "Product": "Sponsored Products",
                    "Entity": "Product Ad",
                    "Operation": "create",
                    "Campaign ID": camp_id,
                    "Ad Group ID": group_id,
                    "Ad ID": "",
                    "State": "enabled",
                    "SKU": "",
                    "ASIN": asin
                })

        for asin in asins_filtro - asins_lista:
            for info in asins_existentes[asin]:
                if info["estado_actual"] == "enabled":
                    filas.append({
                        "Product": "Sponsored Products",
                        "Entity": "Product Ad",
                        "Operation": "update",
                        "Campaign ID": info["campaign_id"],
                        "Ad Group ID": info["ad_group_id"],
                        "Ad ID": info["ad_id"],
                        "State": "paused",
                        "SKU": "",
                        "ASIN": asin
                    })

    else:
        if modo in ["update", "update+create"]:
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

        if modo in ["create", "update+create"]:
            for asin in set(lista_asins) - set(asins_existentes.keys()):
                for camp_id, group_id in grupos_destino:
                    filas.append({
                        "Product": "Sponsored Products",
                        "Entity": "Product Ad",
                        "Operation": "create",
                        "Campaign ID": camp_id,
                        "Ad Group ID": group_id,
                        "Ad ID": "",
                        "State": accion,
                        "SKU": "",
                        "ASIN": asin
                    })

    if not filas:
        st.warning("No se generaron acciones.")
        return pd.DataFrame()

    df_salida = pd.DataFrame(filas)
    columnas = ["Product", "Entity", "Operation", "Campaign ID", "Ad Group ID", "Ad ID", "State", "SKU", "ASIN"]
    return df_salida[columnas]
