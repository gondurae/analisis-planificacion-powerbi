"""
Script orquestador del sistema de análisis de planificación.

Flujo:
    Excel "antes" + Excel "después" → ingesta → comparador → CSVs Power BI

A diferencia del orquestador anterior (que producía PNG + CSVs), esta
versión está acoplada únicamente a la capa de presentación Power BI.
Matplotlib no se importa: el motor Python solo procesa y vuelca tablas.

Uso:
    python analizar_powerbi.py                                   # demo con sintético
    python analizar_powerbi.py antes.xlsx despues.xlsx
    python analizar_powerbi.py antes.xlsx despues.xlsx salida/
    python analizar_powerbi.py antes.xlsx despues.xlsx salida/ 2

Argumentos (posicionales):
    1. antes.xlsx   : snapshot de la semana anterior (export de Primavera P6)
    2. despues.xlsx : snapshot de la semana posterior
    3. salida/      : carpeta donde volcar los CSV (opcional; por defecto 'resultados/')
    4. tolerancia   : días de tolerancia del comparador (opcional; por defecto 1)
"""

from __future__ import annotations

import sys
from pathlib import Path

from comparador import comparar
from exportador_powerbi import exportar_modelo_powerbi
from generador_sinteticos import generar_snapshot_sintetico
from hitos import imprimir_resumen_hitos, resumen_hitos
from ingesta import cargar_snapshot, resumen_snapshot
from kpis import calcular_kpis_globales, imprimir_kpis


def ejecutar_analisis(
    ruta_antes: Path,
    ruta_despues: Path,
    directorio_salida: Path,
    tolerancia_dias: int = 1,
) -> None:
    """Ejecuta el flujo completo y vuelca el modelo Power BI."""
    directorio_salida.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print("SISTEMA DE ANÁLISIS DE PLANIFICACIÓN")
    print("=" * 72)
    print(f"\nSnapshot antes  : {ruta_antes}")
    print(f"Snapshot después: {ruta_despues}")
    print(f"Tolerancia      : {tolerancia_dias} días")
    print(f"Salida          : {directorio_salida}\n")

    print("[1/4] Ingesta...")
    df_antes = cargar_snapshot(ruta_antes)
    df_despues = cargar_snapshot(ruta_despues)
    print(f"      antes:   {resumen_snapshot(df_antes)['actividades']} actividades")
    print(f"      después: {resumen_snapshot(df_despues)['actividades']} actividades")

    print("\n[2/4] Comparando...")
    df_comp = comparar(df_antes, df_despues, tolerancia_dias=tolerancia_dias)

    print("\n[3/4] Resumen del análisis:")
    print(imprimir_kpis(calcular_kpis_globales(df_comp)))
    print()
    print(imprimir_resumen_hitos(resumen_hitos(df_comp)))

    print("\n[4/4] Exportando modelo Power BI...")
    rutas = exportar_modelo_powerbi(df_comp, directorio_salida)
    for nombre, info in rutas.items():
        print(f"      → {nombre}.csv ({info['filas']} filas)")

    informe = (
        "INFORME DE ANÁLISIS DE PLANIFICACIÓN\n"
        + "=" * 72 + "\n\n"
        f"Snapshot antes  : {ruta_antes}\n"
        f"Snapshot después: {ruta_despues}\n"
        f"Tolerancia      : {tolerancia_dias} días\n\n"
        + imprimir_kpis(calcular_kpis_globales(df_comp)) + "\n\n"
        + imprimir_resumen_hitos(resumen_hitos(df_comp)) + "\n"
    )
    (directorio_salida / "informe.txt").write_text(informe, encoding="utf-8")

    print(f"\nListo. Los CSVs están en: {directorio_salida.resolve()}")
    print("Ábrelos desde Power BI Desktop con: Inicio → Obtener datos → Texto/CSV\n")


def main() -> int:
    if len(sys.argv) >= 3:
        ruta_antes = Path(sys.argv[1])
        ruta_despues = Path(sys.argv[2])
        for ruta in (ruta_antes, ruta_despues):
            if not ruta.exists():
                print(f"ERROR: no se encuentra el fichero '{ruta}'.")
                print("Uso: python analizar_powerbi.py antes.xlsx despues.xlsx [salida/] [tolerancia]")
                return 1
        directorio = Path(sys.argv[3]) if len(sys.argv) >= 4 else Path("resultados")
        tolerancia = int(sys.argv[4]) if len(sys.argv) >= 5 else 1
    else:
        print("Modo demo: generando snapshot sintético sobre el base...\n")
        ruta_antes = Path("data/snapshot_base.xlsx")
        ruta_despues = Path("data/snapshot_sintetico_demo.xlsx")
        generar_snapshot_sintetico(
            ruta_base=ruta_antes,
            ruta_salida=ruta_despues,
            seed=42,
        )
        directorio = Path("resultados/demo")
        tolerancia = 1

    ejecutar_analisis(ruta_antes, ruta_despues, directorio, tolerancia)
    return 0


if __name__ == "__main__":
    sys.exit(main())
