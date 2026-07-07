"""
Análisis de cumplimiento por dimensiones de negocio.

Mientras que kpis.py calcula indicadores globales y hitos.py se centra en
los hitos de entrega, este módulo descompone el retraso por las dimensiones
organizativas del proceso de fabricación:

- phase  : la familia/proceso (MFCT, ACC, CAL, TEST, KIT...). Responde a
           "¿qué tipo de trabajo se retrasa más?".
- level  : el nivel de producto (PBA, EQUIPO, MODULO...). Responde a
           "¿qué tipo de pieza acumula más retraso?".

El objetivo es pasar de "el 21% de actividades se retrasa" a "los ensayos
de aceptación sobre módulos son el punto caliente", que es información
accionable para la planificación.

Cada función agrupa las actividades comparadas y calcula, por grupo:
- n_total           : actividades del grupo presentes en ambos snapshots.
- n_retrasadas      : cuántas se han retrasado.
- pct_retrasadas    : proporción de retraso dentro del grupo (normalizada,
                      para no confundir volumen con tasa de retraso).
- dias_retraso_total: suma de días de retraso acumulados en el grupo.
- retraso_medio     : días medios de retraso entre las retrasadas del grupo.

La distinción entre pct_retrasadas (tasa) y n_retrasadas (volumen) es
deliberada: un departamento grande puede tener muchas retrasadas por puro
tamaño; la tasa corrige ese efecto y permite comparar departamentos de
distinto tamaño en igualdad de condiciones.
"""

from __future__ import annotations

import pandas as pd


def _agregar_por(df_comp: pd.DataFrame, columna: str) -> pd.DataFrame:
    """Agrega métricas de cumplimiento por la columna indicada.

    Solo considera actividades presentes en ambos snapshots (las que tienen
    una categoría de movimiento bien definida); las añadidas/canceladas no
    entran en el cálculo de tasa de retraso porque no tienen un "antes y
    después" comparable.
    """
    # Universo: actividades comunes (excluye añadidas, canceladas, sin_fecha)
    comunes = df_comp[
        df_comp["categoria"].isin(["cumplida", "estable", "retrasada", "adelantada"])
    ].copy()

    # Etiqueta de grupo: rellenamos vacíos para no perder filas en el groupby
    grupo = comunes[columna].fillna("(sin asignar)").replace("", "(sin asignar)")
    comunes = comunes.assign(_grupo=grupo)

    filas = []
    for nombre_grupo, sub in comunes.groupby("_grupo"):
        n_total = len(sub)
        retrasadas = sub[sub["categoria"] == "retrasada"]
        n_retrasadas = len(retrasadas)
        dias_total = float(retrasadas["delta_dias"].sum()) if n_retrasadas else 0.0
        retraso_medio = float(retrasadas["delta_dias"].mean()) if n_retrasadas else 0.0
        filas.append({
            columna: nombre_grupo,
            "n_total": n_total,
            "n_retrasadas": n_retrasadas,
            "pct_retrasadas": round(100 * n_retrasadas / n_total, 2) if n_total else 0.0,
            "dias_retraso_total": round(dias_total, 1),
            "retraso_medio": round(retraso_medio, 1),
        })

    resultado = pd.DataFrame(filas)
    if not resultado.empty:
        resultado = resultado.sort_values("dias_retraso_total", ascending=False).reset_index(drop=True)
    return resultado


def analisis_por_fase(df_comp: pd.DataFrame) -> pd.DataFrame:
    """Retraso agregado por fase/proceso (familia del campo phase).

    Usa el prefijo de la fase (antes del punto) como familia: 'MFCT.INSP'
    y 'MFCT.AOI' se agrupan ambas bajo 'MFCT'. Así el análisis es por
    departamento/proceso, no por cada subactividad.
    """
    df = df_comp.copy()
    df["familia_fase"] = (
        df["phase"].fillna("(sin fase)").astype(str).str.split(".").str[0]
    )
    return _agregar_por(df, "familia_fase")


def analisis_por_fase_detalle(df_comp: pd.DataFrame) -> pd.DataFrame:
    """Retraso agregado por fase completa (sin agrupar por familia).

    Mantiene 'MFCT.INSP', 'MFCT.AOI', etc. separadas, para el análisis
    fino de qué subactividad concreta es el cuello de botella.
    """
    return _agregar_por(df_comp, "phase")


def analisis_por_nivel(df_comp: pd.DataFrame) -> pd.DataFrame:
    """Retraso agregado por nivel de producto (PBA, EQUIPO, MODULO...)."""
    return _agregar_por(df_comp, "level")


def analisis_cruzado_fase_nivel(df_comp: pd.DataFrame) -> pd.DataFrame:
    """Tabla cruzada fase × nivel con el retraso acumulado.

    Devuelve un DataFrame largo (tidy) con una fila por combinación
    (familia_fase, level) que tenga actividades, con sus métricas. Es la
    materia prima para un mapa de calor en Power BI: ver de un vistazo qué
    intersección proceso×pieza concentra el retraso.
    """
    df = df_comp.copy()
    df["familia_fase"] = (
        df["phase"].fillna("(sin fase)").astype(str).str.split(".").str[0]
    )
    comunes = df[
        df["categoria"].isin(["cumplida", "estable", "retrasada", "adelantada"])
    ].copy()
    comunes["level"] = comunes["level"].fillna("(sin asignar)").replace("", "(sin asignar)")

    filas = []
    for (fase, nivel), sub in comunes.groupby(["familia_fase", "level"]):
        n_total = len(sub)
        retrasadas = sub[sub["categoria"] == "retrasada"]
        n_retrasadas = len(retrasadas)
        dias_total = float(retrasadas["delta_dias"].sum()) if n_retrasadas else 0.0
        filas.append({
            "familia_fase": fase,
            "level": nivel,
            "n_total": n_total,
            "n_retrasadas": n_retrasadas,
            "pct_retrasadas": round(100 * n_retrasadas / n_total, 2) if n_total else 0.0,
            "dias_retraso_total": round(dias_total, 1),
        })

    resultado = pd.DataFrame(filas)
    if not resultado.empty:
        resultado = resultado.sort_values("dias_retraso_total", ascending=False).reset_index(drop=True)
    return resultado


def imprimir_analisis(df_analisis: pd.DataFrame, titulo: str, top: int = 10) -> str:
    """Formatea un análisis para impresión en consola."""
    lineas = [titulo, "=" * len(titulo)]
    if df_analisis.empty:
        lineas.append("(sin datos)")
        return "\n".join(lineas)
    cols = df_analisis.columns.tolist()
    etiqueta = cols[0]
    lineas.append(
        f"{etiqueta:>16s}  {'n_tot':>6s}  {'n_retr':>6s}  {'%retr':>6s}  {'días_tot':>9s}"
    )
    for _, r in df_analisis.head(top).iterrows():
        lineas.append(
            f"{str(r[etiqueta])[:16]:>16s}  {int(r['n_total']):>6d}  "
            f"{int(r['n_retrasadas']):>6d}  {r['pct_retrasadas']:>5.1f}%  "
            f"{r['dias_retraso_total']:>9.0f}"
        )
    return "\n".join(lineas)
