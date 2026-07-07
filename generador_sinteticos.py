"""
Generador de snapshots sintéticos para validación del sistema.

Toma un fichero Excel canónico (el snapshot "base") y produce un nuevo
fichero Excel que simula "la semana siguiente": algunas actividades se
retrasan, alguna se adelanta, alguna se cancela y se añaden actividades
nuevas.

Los cambios se aplican con una semilla aleatoria fija para que el
resultado sea reproducible y los casos de validación tengan una verdad
conocida: sabes exactamente qué se cambió, así puedes verificar que
el comparador lo detecta correctamente.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import numpy as np
import pandas as pd


# Nombres de columna del Excel original (deben coincidir exactamente)
COL_PROJECT_ID = "Project ID"
COL_ACTIVITY_ID = "Activity ID"
COL_FINISH_CLEAN = "Finish sin*/A"
COL_START_CLEAN = "start sin*/A"
COL_ACTIVITY_NAME = "Activity Name"


def generar_snapshot_sintetico(
    ruta_base: str | Path,
    ruta_salida: str | Path,
    pct_retrasadas: float = 0.15,
    pct_adelantadas: float = 0.03,
    pct_canceladas: float = 0.01,
    n_anadidas: int = 20,
    max_dias_retraso: int = 14,
    max_dias_adelanto: int = 5,
    seed: int = 42,
) -> dict:
    """Genera un snapshot sintético modificado a partir de uno base.

    Lee el Excel base, aplica modificaciones controladas con la semilla
    indicada, y escribe el resultado en `ruta_salida`. Devuelve un
    diccionario con la "verdad conocida" de los cambios aplicados:
    qué actividades se retrasaron (y cuántos días), cuáles se
    adelantaron, cuáles se cancelaron, cuáles se añadieron.

    Parameters
    ----------
    ruta_base : ruta al Excel original (snapshot "antes").
    ruta_salida : ruta donde se escribe el Excel modificado.
    pct_retrasadas : proporción de actividades cuya fecha de fin se
        empuja hacia adelante (0.15 = 15% por defecto).
    pct_adelantadas : proporción de actividades que se adelantan (3%).
    pct_canceladas : proporción de actividades eliminadas (1%).
    n_anadidas : número absoluto de actividades nuevas a añadir.
    max_dias_retraso : tope superior de empuje para retrasos.
    max_dias_adelanto : tope superior de adelanto.
    seed : semilla aleatoria para reproducibilidad.

    Returns
    -------
    dict con las claves 'retrasadas', 'adelantadas', 'canceladas',
    'anadidas' — la verdad conocida del experimento.
    """
    # Suprimimos warnings de openpyxl por seriales de fecha fuera de rango
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df = pd.read_excel(ruta_base)

    rng = np.random.default_rng(seed)

    # Coerce la columna de fechas: lo que no sea una fecha válida queda como NaT.
    # IMPORTANTE: dayfirst=True para que '11-03-26' se interprete como
    # 11 de marzo (formato europeo DD-MM-YY del Excel original) y no
    # como 11 de noviembre (formato americano por defecto de pandas).
    with warnings.catch_warnings():
        # El parseo elemento a elemento de fechas mixtas emite un UserWarning
        # informativo de pandas; el comportamiento es el deseado (dayfirst).
        warnings.simplefilter("ignore", UserWarning)
        df[COL_FINISH_CLEAN] = pd.to_datetime(
            df[COL_FINISH_CLEAN], errors="coerce", dayfirst=True
        )

    # Solo modificamos filas con Finish válido y claves no nulas
    mask_validas = (
        df[COL_FINISH_CLEAN].notna()
        & df[COL_PROJECT_ID].notna()
        & df[COL_ACTIVITY_ID].notna()
    )
    indices_validos = df.index[mask_validas].to_numpy()
    n = len(indices_validos)

    # Reparto sin solape: barajamos y partimos
    indices_revueltos = rng.permutation(indices_validos)
    n_cancel = int(n * pct_canceladas)
    n_retraso = int(n * pct_retrasadas)
    n_adelanto = int(n * pct_adelantadas)

    idx_cancel = indices_revueltos[:n_cancel]
    idx_retraso = indices_revueltos[n_cancel : n_cancel + n_retraso]
    idx_adelanto = indices_revueltos[
        n_cancel + n_retraso : n_cancel + n_retraso + n_adelanto
    ]

    verdad = {
        "retrasadas": [],   # lista de (activity_key, dias_movidos)
        "adelantadas": [],
        "canceladas": [],   # lista de activity_key
        "anadidas": [],
    }

    # --- Retrasos ---
    for i in idx_retraso:
        dias = int(rng.integers(1, max_dias_retraso + 1))
        fecha_orig = pd.Timestamp(df.at[i, COL_FINISH_CLEAN])
        df.at[i, COL_FINISH_CLEAN] = fecha_orig + pd.Timedelta(days=dias)
        verdad["retrasadas"].append((
            f"{df.at[i, COL_PROJECT_ID]}||{df.at[i, COL_ACTIVITY_ID]}",
            dias,
        ))

    # --- Adelantos ---
    for i in idx_adelanto:
        dias = int(rng.integers(1, max_dias_adelanto + 1))
        fecha_orig = pd.Timestamp(df.at[i, COL_FINISH_CLEAN])
        df.at[i, COL_FINISH_CLEAN] = fecha_orig - pd.Timedelta(days=dias)
        verdad["adelantadas"].append((
            f"{df.at[i, COL_PROJECT_ID]}||{df.at[i, COL_ACTIVITY_ID]}",
            dias,
        ))

    # --- Cancelaciones (guardar claves antes de borrar) ---
    for i in idx_cancel:
        verdad["canceladas"].append(
            f"{df.at[i, COL_PROJECT_ID]}||{df.at[i, COL_ACTIVITY_ID]}"
        )
    df = df.drop(index=idx_cancel).reset_index(drop=True)

    # --- Altas: copiamos filas existentes como plantilla y cambiamos ID + nombre + fecha ---
    # Altas: usamos filas existentes como plantilla. Limitamos el número
    # solicitado al de filas disponibles para no exceder la población al
    # muestrear sin reemplazo (caso borde con n_anadidas muy grande).
    n_anadidas_efectivo = min(n_anadidas, len(df))
    indices_template = rng.choice(df.index, size=n_anadidas_efectivo, replace=False)
    nuevas_filas = []
    for k, i in enumerate(indices_template):
        nueva = df.loc[i].copy()
        nuevo_id = f"NEW_{seed}_{k:03d}"
        nueva[COL_ACTIVITY_ID] = nuevo_id
        nueva[COL_ACTIVITY_NAME] = f"[SINTETICA] {nueva[COL_ACTIVITY_NAME]}"
        fecha_orig = pd.Timestamp(nueva[COL_FINISH_CLEAN])
        nueva[COL_FINISH_CLEAN] = fecha_orig + pd.Timedelta(
            days=int(rng.integers(7, 30))
        )
        nuevas_filas.append(nueva)
        verdad["anadidas"].append(f"{nueva[COL_PROJECT_ID]}||{nuevo_id}")

    df = pd.concat([df, pd.DataFrame(nuevas_filas)], ignore_index=True)

    # --- Escritura ---
    ruta_salida = Path(ruta_salida)
    ruta_salida.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(ruta_salida, index=False)

    return verdad


def resumen_verdad(verdad: dict) -> dict:
    """Devuelve un resumen numérico de los cambios aplicados."""
    return {
        "retrasadas": len(verdad["retrasadas"]),
        "adelantadas": len(verdad["adelantadas"]),
        "canceladas": len(verdad["canceladas"]),
        "anadidas": len(verdad["anadidas"]),
        "dias_retraso_medio": (
            float(np.mean([d for _, d in verdad["retrasadas"]]))
            if verdad["retrasadas"] else 0.0
        ),
    }
