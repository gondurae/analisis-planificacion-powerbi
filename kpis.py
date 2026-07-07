"""
KPIs / indicadores de cumplimiento de la planificación.

Toma la tabla del comparador y produce los indicadores agregados que
exige el enunciado del TFG: porcentajes de cumplimiento, desviación
media en días, número de actividades replanificadas e índice de
estabilidad de la planificación.

Los indicadores se pueden calcular:
- A nivel global, devolviendo un único diccionario.
- Desglosados por una columna (típicamente `project_id` o `phase`),
  devolviendo un DataFrame con una fila por grupo.

Definiciones operativas de los KPIs
-----------------------------------
- **% cumplidas en plazo**: de las actividades cuyo fin estaba previsto
  según el snapshot anterior (es decir, las clasificadas como cumplida
  o retrasada), qué fracción se completaron sin desplazarse más allá
  de la tolerancia.
- **% retrasadas**: actividades retrasadas dividido entre las que
  aparecen en ambos snapshots.
- **% adelantadas**: análogo para adelantadas.
- **Desviación media de retraso**: media de `delta_dias` sobre las
  retrasadas. Mide cuánto se desplazan las que se mueven.
- **Desviación media neta**: media signada de `delta_dias` sobre todas
  las comunes. Positiva = sesgo global hacia el retraso.
- **Nº replanificadas**: total de actividades cuya planificación ha
  cambiado entre snapshots (movidas + añadidas + canceladas).
- **Índice de estabilidad**: proporción de actividades comunes que NO
  se han movido más allá de la tolerancia. Rango [0, 1]: 1 indica
  planificación perfectamente estable; 0 indica que todo se mueve.
"""

from __future__ import annotations

import pandas as pd


# Categorías que existen en ambos snapshots (las "comunes")
CATEGORIAS_COMUNES = ["cumplida", "estable", "retrasada", "adelantada"]


def calcular_kpis_globales(df_comp: pd.DataFrame) -> dict:
    """Calcula los KPIs globales a partir de la tabla del comparador.

    Parameters
    ----------
    df_comp : DataFrame de salida del comparador, con la columna
        `categoria` y `delta_dias`.

    Returns
    -------
    dict con los conteos por categoría y los indicadores agregados.
    """
    counts = df_comp["categoria"].value_counts(dropna=False)

    def n(cat: str) -> int:
        return int(counts.get(cat, 0))

    n_total = len(df_comp)
    n_anadidas = n("anadida")
    n_canceladas = n("cancelada")
    n_cumplidas = n("cumplida")
    n_retrasadas = n("retrasada")
    n_adelantadas = n("adelantada")
    n_estables = n("estable")
    n_en_ambos = n_cumplidas + n_retrasadas + n_adelantadas + n_estables
    n_movidas = n_retrasadas + n_adelantadas
    n_no_movidas = n_cumplidas + n_estables

    def safe_pct(num: int, den: int) -> float:
        return float(100.0 * num / den) if den > 0 else 0.0

    pct_cumplidas_en_plazo = safe_pct(n_cumplidas, n_cumplidas + n_retrasadas)
    pct_retrasadas = safe_pct(n_retrasadas, n_en_ambos)
    pct_adelantadas = safe_pct(n_adelantadas, n_en_ambos)

    delta = df_comp["delta_dias"]
    delta_retraso = delta[df_comp["categoria"] == "retrasada"]
    desviacion_media_retraso = (
        float(delta_retraso.mean()) if len(delta_retraso) else 0.0
    )

    delta_comunes = delta[df_comp["categoria"].isin(CATEGORIAS_COMUNES)]
    desviacion_media_neta = (
        float(delta_comunes.mean()) if len(delta_comunes) else 0.0
    )

    n_replanificadas = n_movidas + n_anadidas + n_canceladas
    indice_estabilidad = (
        float(n_no_movidas / n_en_ambos) if n_en_ambos > 0 else 0.0
    )

    return {
        # Volumen
        "n_total": n_total,
        "n_en_ambos": n_en_ambos,
        "n_anadidas": n_anadidas,
        "n_canceladas": n_canceladas,
        # Categorías
        "n_cumplidas": n_cumplidas,
        "n_retrasadas": n_retrasadas,
        "n_adelantadas": n_adelantadas,
        "n_estables": n_estables,
        # KPIs
        "pct_cumplidas_en_plazo": pct_cumplidas_en_plazo,
        "pct_retrasadas": pct_retrasadas,
        "pct_adelantadas": pct_adelantadas,
        "desviacion_media_retraso_dias": desviacion_media_retraso,
        "desviacion_media_neta_dias": desviacion_media_neta,
        "n_replanificadas": n_replanificadas,
        "indice_estabilidad": indice_estabilidad,
    }


def calcular_kpis_por_grupo(
    df_comp: pd.DataFrame, columna_grupo: str
) -> pd.DataFrame:
    """Devuelve los KPIs desglosados por la columna indicada.

    Útil para responder "¿qué proyectos concentran los retrasos?"
    (columna_grupo='project_id') o "¿qué fases son más inestables?"
    (columna_grupo='phase').
    """
    resultados = []
    for grupo, sub in df_comp.groupby(columna_grupo, dropna=False):
        kpis = calcular_kpis_globales(sub)
        kpis[columna_grupo] = grupo
        resultados.append(kpis)

    if not resultados:
        return pd.DataFrame()

    df = pd.DataFrame(resultados)
    columnas = [columna_grupo] + [c for c in df.columns if c != columna_grupo]
    return (
        df[columnas]
        .sort_values(columna_grupo)
        .reset_index(drop=True)
    )


def calcular_kpis_por_proyecto(df_comp: pd.DataFrame) -> pd.DataFrame:
    """Atajo: KPIs desglosados por `project_id`."""
    return calcular_kpis_por_grupo(df_comp, "project_id")


def calcular_kpis_por_fase(df_comp: pd.DataFrame) -> pd.DataFrame:
    """Atajo: KPIs desglosados por `phase`."""
    return calcular_kpis_por_grupo(df_comp, "phase")


def imprimir_kpis(kpis: dict) -> str:
    """Devuelve una representación legible del diccionario de KPIs."""
    lineas = [
        "== Volumen ==",
        f"  Total actividades         : {kpis['n_total']:>6d}",
        f"  En ambos snapshots        : {kpis['n_en_ambos']:>6d}",
        f"  Añadidas                  : {kpis['n_anadidas']:>6d}",
        f"  Canceladas                : {kpis['n_canceladas']:>6d}",
        "",
        "== Categorías (de las comunes) ==",
        f"  Cumplidas en plazo        : {kpis['n_cumplidas']:>6d}",
        f"  Retrasadas                : {kpis['n_retrasadas']:>6d}",
        f"  Adelantadas               : {kpis['n_adelantadas']:>6d}",
        f"  Estables (sin cambio)     : {kpis['n_estables']:>6d}",
        "",
        "== KPIs ==",
        f"  % cumplidas en plazo      : {kpis['pct_cumplidas_en_plazo']:>6.2f} %",
        f"  % retrasadas              : {kpis['pct_retrasadas']:>6.2f} %",
        f"  % adelantadas             : {kpis['pct_adelantadas']:>6.2f} %",
        f"  Desv. media retraso       : {kpis['desviacion_media_retraso_dias']:>+6.2f} días",
        f"  Desv. media neta          : {kpis['desviacion_media_neta_dias']:>+6.2f} días",
        f"  Nº replanificadas         : {kpis['n_replanificadas']:>6d}",
        f"  Índice de estabilidad     : {kpis['indice_estabilidad']:>6.3f}",
    ]
    return "\n".join(lineas)
