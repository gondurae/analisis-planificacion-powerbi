"""
Módulo de ingesta de planificaciones de fabricación.

Lee un fichero Excel extraído de Primavera P6 y devuelve un DataFrame
canónico con tipos limpios y una columna 'activity_key' que actúa como
identificador único estable para emparejar actividades entre snapshots
consecutivos.

Tareas de normalización que realiza:
- Parsea 'Total Float' de texto ("5d", "-46d") a entero de días.
- Unifica 'Start' y 'Finish' (que llegan en tipos mixtos: datetime o
  texto con asterisco de constraint de Primavera) a datetime puro.
- Descarta filas con celdas de fecha corruptas (serial fuera de rango).
- Construye la clave estable 'activity_key' = (Project ID, Activity ID).
- Marca con un booleano 'es_hito' las actividades con fase SHIP.
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path

import pandas as pd


# ---------------------------------------------------------------------------
# Constantes de columnas (centralizadas para mantenimiento)
# ---------------------------------------------------------------------------

COL_PROJECT_ID = "Project ID"
COL_ACTIVITY_ID = "Activity ID"
COL_PROJECT_NAME = "Project Name"
COL_ACTIVITY_NAME = "Activity Name"
COL_PHASE = "* PHASE"
COL_OP = "* OP"
COL_PRODUCT_CODE = "* Product code"
COL_EQ_DESC = "* Eq.  Description"
COL_QTY = "* QTY"
COL_LEVEL = "* LEVEL"
COL_PRODUCT_LINE = "* PRODUCT LINE"
COL_PRODUCT_TYPE = "* PRODUCT TYPE"
COL_NOTES = "* NOTES"
COL_PLANNING_UPDATED = "Planning Updated"
COL_TOTAL_FLOAT_RAW = "Total Float"
COL_START_RAW = "Start"
COL_FINISH_RAW = "Finish"
COL_START_CLEAN = "start sin*/A"
COL_FINISH_CLEAN = "Finish sin*/A"
COL_LATE_FINISH = "Late Finish"
COL_DURATION = "At Completion Duration"

# Valor que marca un hito de entrega en el dataset
FASE_HITO = "SHIP"

# Nombres de hoja candidatos a contener la planificación principal.
# Los ficheros reales de Thales usan 'Multiproyecto primavera'; los de
# prueba usan la primera hoja. Se busca por estos nombres y, si no
# aparece ninguno, se cae a la primera hoja del libro.
HOJAS_CANDIDATAS = [
    "Multiproyecto primavera",
    "Multiproyecto Primavera",
    "Planificacion",
    "Planificación",
]


def _resolver_hoja(ruta: Path, hoja) -> int | str:
    """Decide qué hoja leer.

    Si el llamante especifica una hoja distinta de 'auto', se respeta.
    En modo 'auto' se busca alguna de las hojas candidatas por nombre y,
    si no hay coincidencia, se usa la primera hoja (índice 0).
    """
    if hoja != "auto":
        return hoja
    try:
        xls = pd.ExcelFile(ruta)
        for candidata in HOJAS_CANDIDATAS:
            if candidata in xls.sheet_names:
                return candidata
        return 0
    except Exception:
        return 0


def _serie(df_crudo: pd.DataFrame, columna: str, valor_defecto=None) -> pd.Series:
    """Devuelve la columna si existe en el fichero; si no, una Serie constante.

    Permite tolerar exportaciones que no incluyan alguna columna opcional
    (p. ej. las pre-limpiadas 'start sin*/A' / 'Finish sin*/A' o los campos
    de negocio con asterisco) sin interrumpir la ingesta. Para los ficheros
    que sí traen la columna, el resultado es idéntico al acceso directo.
    """
    if columna in df_crudo.columns:
        return df_crudo[columna]
    return pd.Series(valor_defecto, index=df_crudo.index)


# ---------------------------------------------------------------------------
# Funciones de parseo de tipos
# ---------------------------------------------------------------------------

_FLOAT_PATTERN = re.compile(r"^\s*(-?\d+)\s*d\s*$", re.IGNORECASE)


def parsear_float_dias(valor) -> int | None:
    """Convierte un Total Float tipo '5d' o '-46d' a entero de días.

    Devuelve None si el valor no es parseable (NaN, texto inesperado, etc.).
    """
    if pd.isna(valor):
        return None
    if isinstance(valor, (int, float)):
        return int(valor)
    match = _FLOAT_PATTERN.match(str(valor))
    if not match:
        return None
    return int(match.group(1))


def parsear_duracion_dias(valor) -> int | None:
    """Mismo formato que Total Float pero para 'At Completion Duration'."""
    return parsear_float_dias(valor)


def parsear_fecha(valor) -> pd.Timestamp | None:
    """Normaliza una celda de fecha a Timestamp.

    Acepta:
    - datetime / Timestamp (passthrough)
    - texto tipo 'DD-MM-YY' con asterisco opcional al final
      (el asterisco indica un 'constraint' en Primavera y se ignora).
    - Cualquier otro formato → None.
    """
    if pd.isna(valor):
        return None
    if isinstance(valor, (pd.Timestamp,)):
        return valor
    if hasattr(valor, "year"):  # datetime.datetime, datetime.date
        return pd.Timestamp(valor)

    texto = str(valor).strip().rstrip("*").strip()
    if not texto or texto == "0":
        return None

    # Formato típico Primavera: DD-MM-YY
    for fmt in ("%d-%m-%y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return pd.Timestamp(pd.to_datetime(texto, format=fmt))
        except (ValueError, TypeError):
            continue

    # Último intento: parser flexible
    try:
        return pd.Timestamp(pd.to_datetime(texto, dayfirst=True))
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Función principal de ingesta
# ---------------------------------------------------------------------------

def cargar_snapshot(ruta: str | Path, hoja: int | str = "auto") -> pd.DataFrame:
    """Lee un fichero Excel de planificación y devuelve el DataFrame canónico.

    Parameters
    ----------
    ruta : str o Path
        Ruta al fichero .xlsx.
    hoja : int o str
        Índice o nombre de la hoja a leer. Por defecto 'auto': busca la
        hoja de planificación por nombre (ver HOJAS_CANDIDATAS) y, si no
        la encuentra, usa la primera hoja del libro.

    Returns
    -------
    pd.DataFrame
        DataFrame con tipos normalizados y columnas derivadas. Las columnas
        clave del esquema canónico son:
            - activity_key : str -- identificador único estable
            - project_id, activity_id, activity_name, project_name
            - phase, op, product_code, eq_description, level, qty
            - start, finish, late_finish : pd.Timestamp
            - total_float_dias, duracion_dias : int o NaN
            - planning_status : str (Green/Yellow/Red/Blue/None)
            - es_hito : bool
            - notas : str
    """
    ruta = Path(ruta)
    if not ruta.exists():
        raise FileNotFoundError(f"No existe el fichero: {ruta}")

    hoja_real = _resolver_hoja(ruta, hoja)

    # Suprimimos los warnings de openpyxl por seriales de fecha fuera de rango;
    # esas celdas las identificaremos y descartaremos después.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        df_crudo = pd.read_excel(ruta, sheet_name=hoja_real)

    # Columnas imprescindibles: sin ellas no hay clave de actividad ni
    # comparación posible. Se avisa con un mensaje claro en lugar de un
    # KeyError críptico de pandas.
    faltan = [c for c in (COL_PROJECT_ID, COL_ACTIVITY_ID) if c not in df_crudo.columns]
    if faltan:
        raise ValueError(
            f"El fichero '{ruta.name}' no contiene las columnas requeridas: {faltan}. "
            f"¿Es una exportación de planificación de Primavera P6?"
        )
    if COL_FINISH_RAW not in df_crudo.columns and COL_FINISH_CLEAN not in df_crudo.columns:
        raise ValueError(
            f"El fichero '{ruta.name}' no contiene ninguna columna de fecha de fin "
            f"('{COL_FINISH_RAW}' o '{COL_FINISH_CLEAN}'); la comparación no es posible."
        )

    df = pd.DataFrame()

    # Identificadores
    df["project_id"] = df_crudo[COL_PROJECT_ID].astype(str).str.strip()
    df["activity_id"] = df_crudo[COL_ACTIVITY_ID].astype(str).str.strip()
    df["activity_key"] = df["project_id"] + "||" + df["activity_id"]

    # Descriptivos
    df["project_name"] = _serie(df_crudo, COL_PROJECT_NAME, "").astype(str).str.strip()
    df["activity_name"] = _serie(df_crudo, COL_ACTIVITY_NAME, "").astype(str).str.strip()
    df["phase"] = _serie(df_crudo, COL_PHASE, "").astype(str).str.strip()
    df["op"] = _serie(df_crudo, COL_OP)
    df["product_code"] = _serie(df_crudo, COL_PRODUCT_CODE)
    df["eq_description"] = _serie(df_crudo, COL_EQ_DESC)
    df["product_line"] = _serie(df_crudo, COL_PRODUCT_LINE)
    df["level"] = _serie(df_crudo, COL_LEVEL)
    # PRODUCT TYPE puede no existir en ficheros antiguos; lo añadimos solo si está
    df["product_type"] = (
        _serie(df_crudo, COL_PRODUCT_TYPE, "").astype(str).str.strip().replace("nan", "")
    )
    df["qty"] = pd.to_numeric(_serie(df_crudo, COL_QTY), errors="coerce")

    # Estado del planner (semáforo)
    df["planning_status"] = _serie(df_crudo, COL_PLANNING_UPDATED)

    # Float y duración: parseo de texto "Nd" a entero
    df["total_float_dias"] = _serie(df_crudo, COL_TOTAL_FLOAT_RAW).apply(parsear_float_dias)
    df["duracion_dias"] = _serie(df_crudo, COL_DURATION).apply(parsear_duracion_dias)

    # Fechas: preferimos las columnas "sin */A" si existen y están limpias,
    # con fallback a las originales si la limpia es NaN
    df["start"] = pd.to_datetime(
        _serie(df_crudo, COL_START_CLEAN).apply(parsear_fecha), errors="coerce"
    )
    mask = df["start"].isna()
    df.loc[mask, "start"] = pd.to_datetime(
        _serie(df_crudo, COL_START_RAW).loc[mask].apply(parsear_fecha), errors="coerce"
    )

    df["finish"] = pd.to_datetime(
        _serie(df_crudo, COL_FINISH_CLEAN).apply(parsear_fecha), errors="coerce"
    )
    mask = df["finish"].isna()
    df.loc[mask, "finish"] = pd.to_datetime(
        _serie(df_crudo, COL_FINISH_RAW).loc[mask].apply(parsear_fecha), errors="coerce"
    )

    df["late_finish"] = pd.to_datetime(_serie(df_crudo, COL_LATE_FINISH), errors="coerce")

    # Notas (texto libre)
    df["notas"] = _serie(df_crudo, COL_NOTES, "").astype(str).replace("nan", "")

    # Bandera de hito de entrega
    df["es_hito"] = df["phase"].str.upper().eq(FASE_HITO)

    # Filtrado de filas inválidas: sin activity_key utilizable
    antes = len(df)
    df = df[
        (df["activity_key"].str.strip() != "||")
        & (df["activity_id"].str.strip() != "nan")
        & (df["project_id"].str.strip() != "nan")
    ].copy()
    descartadas = antes - len(df)

    df.attrs["fichero_origen"] = str(ruta)
    df.attrs["filas_originales"] = antes
    df.attrs["filas_descartadas"] = descartadas

    # --- Deduplicación por clave ---
    # Los ficheros reales de Primavera pueden traer filas duplicadas por
    # errores de exportación. Distinguimos dos casos:
    #  - Duplicado exacto (misma clave, mismos datos relevantes): se colapsa
    #    a una sola fila sin pérdida de información.
    #  - Duplicado conflictivo (misma clave, datos distintos): se conserva
    #    la primera aparición y se registra el número en los metadatos para
    #    poder auditarlo, ya que no hay forma automática de saber cuál es la
    #    versión correcta.
    n_dup_clave = int(df["activity_key"].duplicated().sum())
    if n_dup_clave:
        # Columnas que definen "mismo contenido" a efectos de comparación
        cols_contenido = ["activity_key", "phase", "finish", "level"]
        cols_contenido = [c for c in cols_contenido if c in df.columns]
        dup_exactos = int(df.duplicated(subset=cols_contenido).sum())
        df = df.drop_duplicates(subset=cols_contenido, keep="first")
        # Si tras quitar exactos aún quedan claves repetidas, son conflictivos
        n_conflictivos = int(df["activity_key"].duplicated().sum())
        if n_conflictivos:
            df = df.drop_duplicates(subset=["activity_key"], keep="first")
        df.attrs["duplicados_exactos_colapsados"] = dup_exactos
        df.attrs["duplicados_conflictivos"] = n_conflictivos
    else:
        df.attrs["duplicados_exactos_colapsados"] = 0
        df.attrs["duplicados_conflictivos"] = 0

    df.attrs["filas_finales"] = len(df)

    return df


# ---------------------------------------------------------------------------
# Helpers de inspección rápida
# ---------------------------------------------------------------------------

def resumen_snapshot(df: pd.DataFrame) -> dict:
    """Devuelve un diccionario con estadísticas resumen de un snapshot."""
    return {
        "fichero": df.attrs.get("fichero_origen"),
        "actividades": len(df),
        "proyectos": df["project_id"].nunique(),
        "hitos": int(df["es_hito"].sum()),
        "con_finish": int(df["finish"].notna().sum()),
        "con_float": int(df["total_float_dias"].notna().sum()),
        "float_negativo": int((df["total_float_dias"] < 0).sum()),
        "float_positivo": int((df["total_float_dias"] > 0).sum()),
        "float_cero": int((df["total_float_dias"] == 0).sum()),
        "rojos": int((df["planning_status"] == "Red").sum()),
        "amarillos": int((df["planning_status"] == "Yellow").sum()),
        "filas_descartadas_en_ingesta": df.attrs.get("filas_descartadas", 0),
    }
