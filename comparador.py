"""
Comparador de planificaciones consecutivas.

Recibe dos snapshots canónicos (la salida de `cargar_snapshot` del módulo
de ingesta) y produce una tabla unificada donde cada fila es una
actividad y la columna `categoria` indica qué le ha pasado entre el
snapshot "antes" y el "después".

Definiciones operativas de las categorías
-----------------------------------------
Las siete categorías que el sistema asigna a cada actividad son:

- **añadida**: existe en el snapshot "después" y no en el "antes".
- **cancelada**: existía en el "antes" y ya no está en el "después".
- **retrasada**: está en ambos, y su fecha de fin se ha desplazado hacia
  adelante más de `tolerancia_dias` días.
- **adelantada**: está en ambos, y su fecha de fin se ha desplazado hacia
  atrás más de `tolerancia_dias` días.
- **cumplida**: está en ambos, su fecha de fin estaba prevista para una
  fecha anterior o igual a la del snapshot "después" (es decir, ya tocaba
  estar terminada) y no se ha movido más allá de la tolerancia.
- **estable**: está en ambos, no se ha movido más allá de la tolerancia,
  pero su fecha de fin sigue siendo futura respecto al snapshot "después"
  (todavía no le tocaba terminar).

- **sin_fecha**: está en ambos snapshots, pero falta la fecha de fin en
  alguno de ellos y `delta_dias` no es calculable.

La separación cumplida / estable permite distinguir "lo que sí se ha
entregado a tiempo" de "lo que aún no le tocaba moverse".
"""

from __future__ import annotations

import pandas as pd


# Orden canónico de categorías (útil para `value_counts` y gráficas)
CATEGORIAS = [
    "anadida",
    "cancelada",
    "retrasada",
    "adelantada",
    "cumplida",
    "estable",
    "sin_fecha",
]


def comparar(
    df_antes: pd.DataFrame,
    df_despues: pd.DataFrame,
    tolerancia_dias: int = 1,
    fecha_snapshot_despues: pd.Timestamp | str | None = None,
) -> pd.DataFrame:
    """Empareja dos snapshots y categoriza cada actividad.

    Parameters
    ----------
    df_antes, df_despues : DataFrames canónicos (de `cargar_snapshot`).
    tolerancia_dias : holgura en días por debajo de la cual un movimiento
        de la fecha de fin se considera "ruido" y no un retraso/adelanto
        real. Por defecto 1 día.
    fecha_snapshot_despues : fecha de referencia del snapshot "después".
        Sirve para distinguir actividades que ya tocaba terminar
        (candidatas a "cumplida") de las que aún no (candidatas a
        "estable"). Si no se indica, se usa la fecha de hoy.

    Returns
    -------
    DataFrame con una fila por actividad y las columnas:
        activity_key, project_id, activity_id, project_name,
        activity_name, phase, es_hito, categoria, delta_dias,
        finish_antes, finish_despues, qty.

    `delta_dias` es la diferencia en días entre `finish_despues` y
    `finish_antes` (positivo = retraso, negativo = adelanto). Es NaN
    para actividades añadidas o canceladas.
    """
    # --- Validaciones de unicidad de la clave ---
    if df_antes["activity_key"].duplicated().any():
        raise ValueError("df_antes contiene activity_key duplicadas")
    if df_despues["activity_key"].duplicated().any():
        raise ValueError("df_despues contiene activity_key duplicadas")

    # --- Fecha de referencia ---
    if fecha_snapshot_despues is None:
        fecha_ref = pd.Timestamp.today().normalize()
    else:
        fecha_ref = pd.Timestamp(fecha_snapshot_despues).normalize()

    # --- Outer merge sobre la clave estable ---
    columnas_arrastradas = [
        "activity_key",
        "project_id",
        "activity_id",
        "project_name",
        "activity_name",
        "phase",
        "level",
        "product_type",
        "finish",
        "es_hito",
        "qty",
    ]
    m = df_antes[columnas_arrastradas].merge(
        df_despues[columnas_arrastradas],
        on="activity_key",
        how="outer",
        suffixes=("_antes", "_despues"),
        indicator=True,
    )

    # --- Delta en días (NaN si una de las fechas falta) ---
    # Forzamos tipo datetime explícitamente: si alguno de los snapshots
    # viene vacío, las columnas de fecha llegan como 'object'/'float' y la
    # resta fallaría. Con to_datetime quedan como datetime aunque estén
    # vacías, de modo que la resta y el accesor .dt siempre funcionan.
    m["finish_antes"] = pd.to_datetime(m["finish_antes"], errors="coerce")
    m["finish_despues"] = pd.to_datetime(m["finish_despues"], errors="coerce")
    m["delta_dias"] = (m["finish_despues"] - m["finish_antes"]).dt.days

    # --- Categorización ---
    en_ambos = m["_merge"] == "both"
    delta_valido = m["delta_dias"].notna()
    movida_retraso = en_ambos & delta_valido & (m["delta_dias"] > tolerancia_dias)
    movida_adelanto = en_ambos & delta_valido & (m["delta_dias"] < -tolerancia_dias)
    dentro_tolerancia = en_ambos & delta_valido & (m["delta_dias"].abs() <= tolerancia_dias)
    finish_pasado = m["finish_despues"].notna() & (m["finish_despues"] <= fecha_ref)
    # Caso borde: en ambos snapshots pero sin delta calculable (alguna
    # fecha de fin ausente). No se puede determinar cumplimiento.
    sin_fecha = en_ambos & ~delta_valido

    m["categoria"] = pd.NA
    m.loc[m["_merge"] == "right_only", "categoria"] = "anadida"
    m.loc[m["_merge"] == "left_only", "categoria"] = "cancelada"
    m.loc[movida_retraso, "categoria"] = "retrasada"
    m.loc[movida_adelanto, "categoria"] = "adelantada"
    m.loc[dentro_tolerancia & finish_pasado, "categoria"] = "cumplida"
    m.loc[dentro_tolerancia & ~finish_pasado, "categoria"] = "estable"
    m.loc[sin_fecha, "categoria"] = "sin_fecha"

    # --- Consolidación de campos descriptivos: preferir el "después" ---
    # combine_first toma el valor de la columna principal y, si está
    # vacío, el de la columna alternativa. Así el resultado tiene un
    # único valor por campo, sin sufijos.
    for col in [
        "project_id",
        "activity_id",
        "project_name",
        "activity_name",
        "phase",
        "level",
        "product_type",
        "es_hito",
        "qty",
    ]:
        m[col] = m[f"{col}_despues"].combine_first(m[f"{col}_antes"])

    columnas_finales = [
        "activity_key",
        "project_id",
        "activity_id",
        "project_name",
        "activity_name",
        "phase",
        "level",
        "product_type",
        "es_hito",
        "categoria",
        "delta_dias",
        "finish_antes",
        "finish_despues",
        "qty",
    ]
    resultado = m[columnas_finales].copy()
    resultado.attrs["tolerancia_dias"] = tolerancia_dias
    resultado.attrs["fecha_snapshot_despues"] = str(fecha_ref.date())
    return resultado


def resumen_categorias(df_comp: pd.DataFrame) -> pd.Series:
    """Cuentas por categoría, en el orden canónico de `CATEGORIAS`."""
    counts = df_comp["categoria"].value_counts(dropna=False)
    return counts.reindex(CATEGORIAS, fill_value=0)
