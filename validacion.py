"""
Suite de validación del sistema con casos sintéticos.

Define un conjunto de escenarios con "verdad conocida" (los cambios que
introduce el generador) y verifica que el comparador los detecta
exactamente. Es la evidencia empírica del capítulo de validación de la
memoria.

Cada caso ejecuta:
1. Generar un snapshot sintético con parámetros concretos.
2. Cargar ambos snapshots (base y sintético) por la ingesta.
3. Comparar con tolerancia 0 (cualquier movimiento cuenta).
4. Verificar que los conteos por categoría coinciden con la verdad
   inyectada.

Si el sistema funciona, los 4 escenarios deben pasar al 100%.
"""

from __future__ import annotations

from pathlib import Path

from comparador import comparar, resumen_categorias
from generador_sinteticos import generar_snapshot_sintetico
from ingesta import cargar_snapshot


def ejecutar_caso(
    nombre: str,
    ruta_base: str | Path,
    ruta_salida_sintetico: str | Path,
    parametros_generador: dict,
    tolerancia_comparador: int = 0,
) -> dict:
    """Ejecuta un caso individual y devuelve el diagnóstico."""
    verdad = generar_snapshot_sintetico(
        ruta_base=ruta_base,
        ruta_salida=ruta_salida_sintetico,
        **parametros_generador,
    )

    df_antes = cargar_snapshot(ruta_base)
    df_despues = cargar_snapshot(ruta_salida_sintetico)
    df_comp = comparar(df_antes, df_despues, tolerancia_dias=tolerancia_comparador)
    detectado = resumen_categorias(df_comp)

    esperado = {
        "retrasada":  len(verdad["retrasadas"]),
        "adelantada": len(verdad["adelantadas"]),
        "cancelada":  len(verdad["canceladas"]),
        "anadida":    len(verdad["anadidas"]),
    }
    detectado_dict = {k: int(detectado[k]) for k in esperado}
    ok = all(detectado_dict[k] == esperado[k] for k in esperado)

    return {
        "nombre": nombre,
        "parametros": parametros_generador,
        "esperado": esperado,
        "detectado": detectado_dict,
        "ok": ok,
    }


# Casos canónicos: cubrir el espectro de "calma" a "caos"
CASOS_CANONICOS = [
    ("Sin cambios", {
        "pct_retrasadas": 0.0, "pct_adelantadas": 0.0,
        "pct_canceladas": 0.0, "n_anadidas": 0, "seed": 1,
    }),
    ("Semana tranquila", {
        "pct_retrasadas": 0.05, "pct_adelantadas": 0.01,
        "pct_canceladas": 0.005, "n_anadidas": 5, "seed": 2,
    }),
    ("Semana típica", {
        "pct_retrasadas": 0.15, "pct_adelantadas": 0.03,
        "pct_canceladas": 0.01, "n_anadidas": 20, "seed": 3,
    }),
    ("Semana caótica", {
        "pct_retrasadas": 0.40, "pct_adelantadas": 0.05,
        "pct_canceladas": 0.03, "n_anadidas": 50, "seed": 4,
    }),
]


def ejecutar_suite(
    ruta_base: str | Path,
    directorio_salida: str | Path,
) -> list[dict]:
    """Ejecuta la suite canónica de validación y devuelve los resultados."""
    directorio_salida = Path(directorio_salida)
    directorio_salida.mkdir(parents=True, exist_ok=True)

    resultados = []
    for nombre, params in CASOS_CANONICOS:
        nombre_fichero = nombre.lower().replace(" ", "_")
        for con, sin in zip("áéíóúñ", "aeioun"):
            nombre_fichero = nombre_fichero.replace(con, sin)
        ruta_sint = directorio_salida / f"sintetico_{nombre_fichero}.xlsx"
        resultado = ejecutar_caso(nombre, ruta_base, ruta_sint, params)
        resultados.append(resultado)

    return resultados


def imprimir_resultados(resultados: list[dict]) -> str:
    """Representación legible de los resultados de la suite."""
    lineas = [
        "",
        "=" * 72,
        "SUITE DE VALIDACIÓN",
        "=" * 72,
    ]
    for r in resultados:
        marca = "✓ OK  " if r["ok"] else "✗ FAIL"
        lineas.append(f"\n[{marca}] {r['nombre']}")
        for cat in ["retrasada", "adelantada", "cancelada", "anadida"]:
            esp = r["esperado"][cat]
            det = r["detectado"][cat]
            chk = "✓" if esp == det else "✗"
            lineas.append(
                f"    {chk} {cat:11s}: esperado={esp:>5d}  detectado={det:>5d}"
            )

    n_ok = sum(1 for r in resultados if r["ok"])
    lineas.append("")
    lineas.append("=" * 72)
    lineas.append(f"RESULTADO: {n_ok}/{len(resultados)} casos pasados")
    lineas.append("=" * 72)
    return "\n".join(lineas)
