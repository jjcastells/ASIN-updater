import pandas as pd
import re
from typing import List, Optional

def clean_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """Limpia nombres de columnas (espacios, caracteres especiales)."""
    df.columns = df.columns.str.strip().str.replace(r'[^\w\s]', '', regex=True)
    return df

def find_sheet_by_name(xls: pd.ExcelFile, keywords: List[str]) -> Optional[str]:
    """Busca una hoja que contenga alguna de las palabras clave en su nombre."""
    for sheet in xls.sheet_names:
        if any(kw.lower() in sheet.lower() for kw in keywords):
            return sheet
    return None

def procesar_bulk(
    archivo_bulk: str,
    lista_asins: List[str],
    filtro_campania: str,
    modo: str,  # 'update', 'create', 'update+create'
    accion: str,  # 'enabled' o 'paused'
    filtro_grupo: Optional[str] = None,
    archivo_salida: str = "output_bulk.csv"
):
    """
    Genera archivo de operaciones en bloque para activar/pausar/crear anuncios de producto.
    """
    # 1. Cargar archivo Excel (bulk de Amazon)
    xls = pd.ExcelFile(archivo_bulk)
    # Buscar la hoja de Sponsored Products (suele llamarse "Campañas de Sponsored Products" o similar)
    nombre_hoja = find_sheet_by_name(xls, ["sponsored products", "campañas de sponsored products"])
    if not nombre_hoja:
        raise ValueError("No se encontró una hoja de Sponsored Products en el archivo.")
    
    df = pd.read_excel(xls, sheet_name=nombre_hoja, dtype=str)
    df = clean_column_names(df)
    
    # 2. Filtrar por entidad "Anuncio de producto" (puede variar el nombre exacto)
    # Posibles nombres de columna para entidad: "Entidad", "Entity"
    col_entidad = next((c for c in df.columns if 'entidad' in c.lower()), None)
    if not col_entidad:
        raise ValueError("No se encontró columna de entidad.")
    
    df_ads = df[df[col_entidad].str.lower().str.contains('anuncio de producto', na=False)].copy()
    
    # 3. Filtrar por campaña (obligatorio)
    col_campania = next((c for c in df.columns if 'nombre de la campaña' in c.lower()), None)
    if not col_campania:
        raise ValueError("No se encontró columna de nombre de campaña.")
    
    mask_campania = df_ads[col_campania].str.contains(filtro_campania, case=False, na=False)
    df_filtrado = df_ads[mask_campania].copy()
    
    if df_filtrado.empty:
        raise ValueError(f"No se encontraron anuncios en campañas que contengan '{filtro_campania}'.")
    
    # 4. Obtener IDs de campaña y grupo (para posibles creaciones)
    col_campaign_id = next((c for c in df.columns if 'id de la campaña' in c.lower()), None)
    col_adgroup_id = next((c for c in df.columns if 'id del grupo de anuncios' in c.lower()), None)
    if not col_campaign_id or not col_adgroup_id:
        raise ValueError("No se encontraron columnas de ID de campaña o ID de grupo de anuncios.")
    
    # 5. Aplicar filtro adicional por grupo si se proporciona
    col_grupo = next((c for c in df.columns if 'nombre del grupo de anuncios' in c.lower()), None)
    if filtro_grupo and col_grupo:
        mask_grupo = df_filtrado[col_grupo].str.contains(filtro_grupo, case=False, na=False)
        df_filtrado = df_filtrado[mask_grupo].copy()
        if df_filtrado.empty:
            raise ValueError(f"No se encontraron anuncios en grupos que contengan '{filtro_grupo}'.")
    
    # 6. Preparar estructuras para update y create
    # Para update: necesitamos el ID del anuncio
    col_ad_id = next((c for c in df.columns if 'id del anuncio' in c.lower()), None)
    if not col_ad_id and modo in ['update', 'update+create']:
        raise ValueError("No se encontró columna de ID del anuncio. No se pueden hacer updates.")
    
    # Mapa de ASIN existentes en el filtro (con su ID de anuncio y grupo)
    asins_existentes = {}
    if col_ad_id:
        for _, row in df_filtrado.iterrows():
            asin = row.get('ASIN Solo informativo', '')  # columna típica
            if not asin:
                asin = row.get('ASIN', '')
            if asin and asin in lista_asins:
                asins_existentes[asin] = {
                    'ad_id': row[col_ad_id],
                    'campaign_id': row[col_campaign_id],
                    'ad_group_id': row[col_adgroup_id]
                }
    
    # Para create: necesitamos la lista de grupos destino (pueden ser varios)
    grupos_destino = set()
    if modo in ['create', 'update+create']:
        # Tomar todos los grupos únicos que cumplen el filtro
        for _, row in df_filtrado.iterrows():
            grupos_destino.add((row[col_campaign_id], row[col_adgroup_id]))
        if not grupos_destino:
            raise ValueError("No hay grupos de anuncios para crear los nuevos ASIN.")
    
    # 7. Generar filas de salida
    filas_salida = []
    
    # Operaciones update
    if modo in ['update', 'update+create']:
        for asin, info in asins_existentes.items():
            fila = {
                'Product': 'Sponsored Products',  # o el valor que corresponda, normalmente constante
                'Entity': 'Product Ad',
                'Operation': 'update',
                'Campaign ID': info['campaign_id'],
                'Ad Group ID': info['ad_group_id'],
                'Ad ID': info['ad_id'],
                'State': accion,
                'SKU': '',  # lo dejamos vacío
                'ASIN': asin
            }
            filas_salida.append(fila)
    
    # Operaciones create
    if modo in ['create', 'update+create']:
        asins_a_crear = set(lista_asins) - set(asins_existentes.keys())
        for asin in asins_a_crear:
            for (camp_id, group_id) in grupos_destino:
                fila = {
                    'Product': 'Sponsored Products',
                    'Entity': 'Product Ad',
                    'Operation': 'create',
                    'Campaign ID': camp_id,
                    'Ad Group ID': group_id,
                    'Ad ID': '',  # vacío para create
                    'State': accion,
                    'SKU': '',
                    'ASIN': asin
                }
                filas_salida.append(fila)
    
    if not filas_salida:
        print("No se generaron acciones. Revisa los filtros y la lista de ASIN.")
        return
    
    # 8. Crear DataFrame y guardar
    df_salida = pd.DataFrame(filas_salida)
    # Reordenar columnas para que sea legible
    columnas = ['Product', 'Entity', 'Operation', 'Campaign ID', 'Ad Group ID', 'Ad ID', 'State', 'SKU', 'ASIN']
    df_salida = df_salida[columnas]
    
    df_salida.to_csv(archivo_salida, sep=';', index=False, encoding='utf-8-sig')
    print(f"Archivo generado: {archivo_salida}")
    print(f"Total de operaciones: {len(df_salida)} (updates: {len(asins_existentes) if modo in ['update','update+create'] else 0}, creates: {len(asins_a_crear) * len(grupos_destino) if modo in ['create','update+create'] else 0})")

# ========= EJEMPLO DE USO =========
if __name__ == "__main__":
    # Parámetros de ejemplo (ajusta según tu caso)
    archivo = "bulk-afyvi7wpgete8-20260131-20260302-1772489876267.xlsx"
    mis_asins = ["B0DD76X9L3", "B0DD79GXQX", "B0F3JXNZ85", "B0FCYRQDSY"]  # lista real
    
    procesar_bulk(
        archivo_bulk=archivo,
        lista_asins=mis_asins,
        filtro_campania="(DE) SP | Hand Sanitizers | KW | NB",  # ejemplo
        modo="update+create",      # update, create, update+create
        accion="enabled",           # enabled o paused
        filtro_grupo=None,           # None o texto para filtrar grupos
        archivo_salida="acciones_bulk.csv"
    )