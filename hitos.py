"""
Análisis de hitos de entrega.

Toma la tabla del comparador y centra el análisis sobre las
actividades marcadas como hito (`es_hito = True`, lo que en este
sistema equivale a `phase = 'SHIP'`). Responde a las dos preguntas
operativas clave del enunciado:

1. ¿Cuáles son los hitos de entrega retrasados, ordenados de mayor a
   menor impacto?
2. ¿Qué proyectos concentran ese impacto?

Definición operativa de "impacto"
---------------------------------
El impacto de un hito retrasado es **el número de días que se ha
desplazado su fecha de fin entre el snapshot "antes" y el "después"**,
es decir, la columna `delta_dias` directamente. Esta definición es
intencionadamente sencilla y se justifica en la memoria: una
ponderación adicional por cantidad (QTY) o criticidad del proyecto
sería una mejora natural, pero introduciría parámetros subjetivos y se
deja como línea futura.
"""

from __future__ import annotations

import pandas as pd


def analizar_hitos(df_comp: pd.DataFrame) -> pd.DataFrame:
    """Devuelve la tabla de hitos del comparador, ordenada por impacto.

    El orden es por `delta_dias` descendente: los más retrasados
    arriba, los adelantados al final, los hitos sin movimiento o
    cancelados/añadidos con NaN al final.
    """
    hitos = df_comp[df_comp["es_hito"] == True].copy()  # noqa: E712
    return hitos.sort_values(
        "delta_dias", ascending=False, na_position="last"
    ).reset_index(drop=True)


def ranking_hitos_retrasados(
    df_comp: pd.DataFrame, n: int | None = None
) -> pd.DataFrame:
    """Top N hitos retrasados, ordenados de mayor a menor impacto.

    Si `n` es None, devuelve todos los hitos retrasados.
    """
    hitos = df_comp[
        (df_comp["es_hito"] == True)  # noqa: E712
        & (df_comp["categoria"] == "retrasada")
    ].copy()
    hitos = hitos.sort_values("delta_dias", ascending=False).reset_index(drop=True)
    return hitos.head(n) if n is not None else hitos


def resumen_hitos(df_comp: pd.DataFrame) -> dict:
    """Estadísticas globales sobre los hitos del comparador."""
    hitos = df_comp[df_comp["es_hito"] == True]  # noqa: E712
    total = len(hitos)
    if total == 0:
        return {"n_hitos": 0}

    counts = hitos["categoria"].value_counts(dropna=False)

    def n(cat: str) -> int:
        return int(counts.get(cat, 0))

    n_retrasados = n("retrasada")
    delta_retraso = hitos.loc[
        hitos["categoria"] == "retrasada", "delta_dias"
    ]

    return {
        "n_hitos_total": total,
        "n_hitos_retrasados": n_retrasados,
        "n_hitos_adelantados": n("adelantada"),
        "n_hitos_cumplidos": n("cumplida"),
        "n_hitos_estables": n("estable"),
        "n_hitos_anadidos": n("anadida"),
        "n_hitos_cancelados": n("cancelada"),
        "pct_hitos_retrasados": float(100.0 * n_retrasados / total),
        "dias_retraso_medio": (
            float(delta_retraso.mean()) if len(delta_retraso) else 0.0
        ),
        "dias_retraso_maximo": (
            float(delta_retraso.max()) if len(delta_retraso) else 0.0
        ),
        "dias_retraso_total": (
            float(delta_retraso.sum()) if len(delta_retraso) else 0.0
        ),
    }


def hitos_por_proyecto(df_comp: pd.DataFrame) -> pd.DataFrame:
    """Agregación por proyecto: hitos totales, retrasados e impacto.

    Devuelve un DataFrame con una fila por proyecto que tenga hitos,
    ordenado por `dias_retraso_total` descendente — útil directamente
    para hacer un gráfico tipo Pareto de "proyectos con más impacto".
    """
    hitos = df_comp[df_comp["es_hito"] == True]  # noqa: E712
    if len(hitos) == 0:
        return pd.DataFrame()

    filas = []
    for proj, sub in hitos.groupby("project_id", dropna=False):
        retrasados = sub[sub["categoria"] == "retrasada"]
        filas.append({
            "project_id": proj,
            "project_name": (
                sub["project_name"].dropna().iloc[0]
                if sub["project_name"].notna().any()
                else None
            ),
            "n_hitos": len(sub),
            "n_retrasados": len(retrasados),
            "pct_retrasados": (
                100.0 * len(retrasados) / len(sub) if len(sub) > 0 else 0.0
            ),
            "dias_retraso_medio": (
                float(retrasados["delta_dias"].mean())
                if len(retrasados) else 0.0
            ),
            "dias_retraso_maximo": (
                float(retrasados["delta_dias"].max())
                if len(retrasados) else 0.0
            ),
            "dias_retraso_total": (
                float(retrasados["delta_dias"].sum())
                if len(retrasados) else 0.0
            ),
        })

    return (
        pd.DataFrame(filas)
        .sort_values("dias_retraso_total", ascending=False)
        .reset_index(drop=True)
    )


def imprimir_resumen_hitos(resumen: dict) -> str:
    """Representación legible del resumen de hitos."""
    if resumen.get("n_hitos", 0) == 0 and "n_hitos_total" not in resumen:
        return "No hay hitos en la comparación."

    lineas = [
        "== Volumen de hitos ==",
        f"  Hitos totales             : {resumen['n_hitos_total']:>6d}",
        f"  Retrasados                : {resumen['n_hitos_retrasados']:>6d}",
        f"  Adelantados               : {resumen['n_hitos_adelantados']:>6d}",
        f"  Cumplidos en plazo        : {resumen['n_hitos_cumplidos']:>6d}",
        f"  Estables                  : {resumen['n_hitos_estables']:>6d}",
        f"  Añadidos                  : {resumen['n_hitos_anadidos']:>6d}",
        f"  Cancelados                : {resumen['n_hitos_cancelados']:>6d}",
        "",
        "== Impacto agregado de retrasos ==",
        f"  % hitos retrasados        : {resumen['pct_hitos_retrasados']:>6.2f} %",
        f"  Retraso medio             : {resumen['dias_retraso_medio']:>+6.2f} días",
        f"  Retraso máximo            : {resumen['dias_retraso_maximo']:>+6.0f} días",
        f"  Retraso acumulado total   : {resumen['dias_retraso_total']:>+6.0f} días-hito",
    ]
    return "\n".join(lineas)
