"""
Exportación del resultado de la comparación al modelo de datos
para visualización interactiva en Power BI.

Diseño en esquema en estrella
-----------------------------
- fact_actividades: tabla de hechos. Una fila por actividad comparada.
                    Incluye phase, familia_fase, level y product_type para
                    poder segmentar por dimensiones de negocio en Power BI.
- dim_proyecto:     dimensión de proyecto, una fila por project_id.
- dim_fase:         dimensión de fase, una fila por phase.
- dim_categoria:    dimensión de categoría (cumplida, retrasada, etc.),
                    con orden de presentación y código de color.
- kpis_globales:    tabla de un único registro con los indicadores
                    agregados, lista para alimentar tarjetas KPI.
- kpis_proyecto:    KPIs precalculados por proyecto.
- kpis_fase:        KPIs precalculados por fase.
- hitos_proyecto:   resumen de hitos por proyecto.
- analisis_fase:    retraso agregado por familia de fase (proceso).
- analisis_nivel:   retraso agregado por nivel de producto.
- analisis_fase_nivel: tabla cruzada fase x nivel (mapa de calor).

Convenciones para Power BI
--------------------------
- Codificación: UTF-8 con BOM (Power BI lo prefiere para reconocer
  caracteres especiales en español).
- Separador de campos: punto y coma (;), estándar CSV en locale español.
- Separador decimal: coma (,). Así Power BI español no corrompe los
  decimales al cargar.
- Fechas: formato ISO 8601 (YYYY-MM-DD) para evitar ambigüedades.
- Nombres de columna: en español, sin tildes ni espacios (snake_case)
  para que las medidas DAX sean cómodas de escribir.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from analisis_departamento import (
    analisis_cruzado_fase_nivel,
    analisis_por_fase,
    analisis_por_nivel,
)
from hitos import hitos_por_proyecto
from kpis import (
    calcular_kpis_globales,
    calcular_kpis_por_fase,
    calcular_kpis_por_proyecto,
)


# Configuración de la dimensión de categorías:
# orden de presentación y color asociado (formato hex sin almohadilla,
# Power BI lo acepta así o con almohadilla).
CATEGORIAS_DIM = pd.DataFrame([
    {"categoria": "cumplida",   "orden": 1, "color_hex": "#2ECC71",
     "descripcion": "Actividad terminada en plazo, sin movimiento"},
    {"categoria": "estable",    "orden": 2, "color_hex": "#95A5A6",
     "descripcion": "Sin cambios, fecha de fin aún futura"},
    {"categoria": "adelantada", "orden": 3, "color_hex": "#3498DB",
     "descripcion": "Fecha de fin movida hacia atrás"},
    {"categoria": "retrasada",  "orden": 4, "color_hex": "#E74C3C",
     "descripcion": "Fecha de fin movida hacia adelante"},
    {"categoria": "anadida",    "orden": 5, "color_hex": "#F39C12",
     "descripcion": "Aparece en el snapshot posterior y no en el anterior"},
    {"categoria": "cancelada",  "orden": 6, "color_hex": "#34495E",
     "descripcion": "Existía en el snapshot anterior y desaparece"},
    {"categoria": "sin_fecha",  "orden": 7, "color_hex": "#BDC3C7",
     "descripcion": "Presente en ambos snapshots pero sin fecha de fin comparable"},
])


def _exportar_csv(df: pd.DataFrame, ruta: Path) -> None:
    """Vuelca un DataFrame a CSV con las convenciones para Power BI (locale ES).

    Se usa el formato regional español para que Power BI Desktop en español
    lo cargue correctamente sin pasos de conversión de tipo:
    - sep=';'      : punto y coma como separador de campos (estándar CSV ES).
    - decimal=','  : coma como separador decimal.
    - encoding utf-8-sig (con BOM) para los acentos.
    - fechas en ISO 8601.

    Con esto, los decimales (porcentajes, índices, desviaciones) entran como
    números reales en Power BI sin que el tipado automático los corrompa.
    """
    df.to_csv(
        ruta,
        index=False,
        sep=";",
        decimal=",",
        encoding="utf-8-sig",
        date_format="%Y-%m-%d",
    )


def construir_fact_actividades(df_comp: pd.DataFrame) -> pd.DataFrame:
    """Tabla de hechos: una fila por actividad comparada.

    Es la tabla central del modelo. Power BI relaciona desde aquí hacia
    las dimensiones por las claves project_id, phase y categoria.
    """
    columnas = [
        "activity_key", "project_id", "activity_id",
        "activity_name", "phase", "level", "product_type", "categoria",
        "es_hito", "delta_dias",
        "finish_antes", "finish_despues",
        "qty",
    ]
    fact = df_comp[columnas].copy()

    # Coherencia con dim_fase: los NaN se etiquetan como '(sin fase)' para
    # que la relación a la dimensión funcione en Power BI. Sin este paso,
    # las 100+ filas con phase NaN quedarían como "blank" sin enlazar.
    fact["phase"] = fact["phase"].fillna("(sin fase)")

    # Familia de fase (prefijo antes del punto): dimensión de "departamento"
    # MFCT.INSP y MFCT.AOI comparten familia MFCT. Útil para agrupar en BI.
    fact["familia_fase"] = fact["phase"].astype(str).str.split(".").str[0]

    # Normalizar level y product_type vacíos para que las relaciones enlacen
    fact["level"] = fact["level"].fillna("(sin asignar)").replace("", "(sin asignar)")
    fact["product_type"] = fact["product_type"].fillna("(sin asignar)").replace("", "(sin asignar)")

    # Métricas derivadas útiles para DAX simple
    fact["dias_retraso"] = fact["delta_dias"].clip(lower=0)
    fact["dias_adelanto"] = (-fact["delta_dias"]).clip(lower=0)
    fact["es_retrasada"] = (fact["categoria"] == "retrasada").astype(int)
    fact["es_adelantada"] = (fact["categoria"] == "adelantada").astype(int)
    fact["es_cumplida"] = (fact["categoria"] == "cumplida").astype(int)
    fact["es_anadida"] = (fact["categoria"] == "anadida").astype(int)
    fact["es_cancelada"] = (fact["categoria"] == "cancelada").astype(int)

    return fact


def construir_dim_proyecto(df_comp: pd.DataFrame) -> pd.DataFrame:
    """Dimensión de proyecto: una fila por project_id."""
    dim = (
        df_comp[["project_id", "project_name"]]
        .dropna(subset=["project_id"])
        .drop_duplicates(subset=["project_id"])
        .sort_values("project_id")
        .reset_index(drop=True)
    )
    # n_actividades del proyecto en el snapshot comparado
    cuentas = df_comp.groupby("project_id").size().rename("n_actividades")
    dim = dim.merge(cuentas, on="project_id", how="left")
    return dim


def construir_dim_fase(df_comp: pd.DataFrame) -> pd.DataFrame:
    """Dimensión de fase: una fila por phase (incluye 'sin fase' para NaN)."""
    fases = df_comp["phase"].fillna("(sin fase)").unique()
    dim = pd.DataFrame({"phase": sorted(fases)})
    cuentas = (
        df_comp.assign(phase=df_comp["phase"].fillna("(sin fase)"))
        .groupby("phase")
        .size()
        .rename("n_actividades")
    )
    dim = dim.merge(cuentas, on="phase", how="left")
    return dim


def construir_kpis_globales_tabla(df_comp: pd.DataFrame) -> pd.DataFrame:
    """Convierte el dict de KPIs globales en una tabla de una fila.

    Power BI lee mejor las tarjetas si los KPIs son columnas de una tabla
    plana. Una sola fila, una columna por KPI.
    """
    kpis = calcular_kpis_globales(df_comp)
    return pd.DataFrame([kpis])


def construir_dim_familia_fase(df_comp: pd.DataFrame) -> pd.DataFrame:
    """Dimensión de familia de fase (departamento/proceso).

    Extrae el prefijo de la fase (MFCT, ACC, CAL...) como dimensión
    independiente, para poder segmentar el dashboard por proceso.
    """
    fam = (
        df_comp["phase"].fillna("(sin fase)").astype(str).str.split(".").str[0]
    )
    valores = sorted(fam.unique())
    dim = pd.DataFrame({"familia_fase": valores})
    cuentas = fam.value_counts().rename("n_actividades")
    dim = dim.merge(cuentas, left_on="familia_fase", right_index=True, how="left")
    return dim


def construir_dim_nivel(df_comp: pd.DataFrame) -> pd.DataFrame:
    """Dimensión de nivel de producto (PBA, MODULO, EQUIPMENT...)."""
    niveles = (
        df_comp["level"].fillna("(sin asignar)").replace("", "(sin asignar)")
    )
    dim = pd.DataFrame({"level": sorted(niveles.unique())})
    cuentas = niveles.value_counts().rename("n_actividades")
    dim = dim.merge(cuentas, left_on="level", right_index=True, how="left")
    return dim


def construir_hitos_proyecto(df_comp: pd.DataFrame) -> pd.DataFrame:
    """Resumen de hitos por proyecto, ya con la métrica días-hito."""
    return hitos_por_proyecto(df_comp)


def exportar_modelo_powerbi(
    df_comp: pd.DataFrame,
    directorio_salida: str | Path,
) -> dict:
    """Vuelca el modelo completo a CSVs en el directorio indicado.

    Devuelve un diccionario con las rutas escritas y el número de filas
    de cada tabla, útil para logging y verificación.
    """
    directorio_salida = Path(directorio_salida)
    directorio_salida.mkdir(parents=True, exist_ok=True)

    tablas = {
        "fact_actividades": construir_fact_actividades(df_comp),
        "dim_proyecto":     construir_dim_proyecto(df_comp),
        "dim_fase":         construir_dim_fase(df_comp),
        "dim_familia_fase": construir_dim_familia_fase(df_comp),
        "dim_nivel":        construir_dim_nivel(df_comp),
        "dim_categoria":    CATEGORIAS_DIM.copy(),
        "kpis_globales":    construir_kpis_globales_tabla(df_comp),
        "kpis_proyecto":    calcular_kpis_por_proyecto(df_comp),
        "kpis_fase":        calcular_kpis_por_fase(df_comp),
        "hitos_proyecto":   construir_hitos_proyecto(df_comp),
        # Análisis por departamento (dimensiones de negocio)
        "analisis_fase":    analisis_por_fase(df_comp),
        "analisis_nivel":   analisis_por_nivel(df_comp),
        "analisis_fase_nivel": analisis_cruzado_fase_nivel(df_comp),
    }

    rutas = {}
    for nombre, df in tablas.items():
        ruta = directorio_salida / f"{nombre}.csv"
        _exportar_csv(df, ruta)
        rutas[nombre] = {"ruta": str(ruta), "filas": len(df)}

    return rutas
