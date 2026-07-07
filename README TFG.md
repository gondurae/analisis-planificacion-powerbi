# Herramienta de análisis de planificación con integración en Power BI

Trabajo Fin de Grado — Grado en Ingeniería en Sistemas de Telecomunicación (EIF, Universidad Rey Juan Carlos), desarrollado en Thales Alenia Space España.

Compara dos exportaciones semanales consecutivas de **Oracle Primavera P6** (Excel), clasifica cada actividad según su evolución (añadida, cancelada, retrasada, adelantada, cumplida, estable o sin fecha), calcula KPIs de cumplimiento y estabilidad, analiza los hitos de entrega (fase SHIP) y exporta un modelo de datos en estrella (13 CSV) listo para **Power BI**.

## Uso rápido

```bash
pip install pandas openpyxl
python analizar_powerbi.py antes.xlsx despues.xlsx resultados/
```

Argumentos: `antes.xlsx` y `despues.xlsx` (snapshots de dos semanas consecutivas), carpeta de salida (opcional, por defecto `resultados/`) y tolerancia en días (opcional, por defecto `1`). Los CSV generados se cargan en Power BI Desktop (configuración regional es-ES); con el `.pbix` ya construido basta con **Inicio → Actualizar**.

El manual de instalación y uso completo está en el Anexo A de la memoria.

## Estructura

| Módulo | Responsabilidad |
|---|---|
| `analizar_powerbi.py` | Orquestador del flujo completo (punto de entrada). |
| `ingesta.py` | Lectura y normalización de los Excel de Primavera P6. |
| `comparador.py` | Emparejamiento por `activity_key` y clasificación en 7 categorías. |
| `kpis.py` | Indicadores globales y desglosados por proyecto/fase. |
| `hitos.py` | Análisis de hitos de entrega (SHIP) y métrica de días-hito. |
| `analisis_departamento.py` | Desgloses por familia de fase, nivel y cruce fase-nivel. |
| `exportador_powerbi.py` | Modelo en estrella → 13 CSV (sep=';', decimal=',', UTF-8 BOM). |
| `generador_sinteticos.py` | Snapshots sintéticos con verdad conocida. |
| `validacion.py` | Suite de validación (4 escenarios canónicos). |

## Validación

```bash
python -c "from validacion import ejecutar_suite, imprimir_resultados; print(imprimir_resultados(ejecutar_suite('ruta/al/snapshot_base.xlsx', 'sinteticos/')))"
```

Los cuatro escenarios (sin cambios, tranquila, típica y caótica) deben pasar 4/4.

## Autor

Gonzalo Durá Esteban · Tutor académico: Ángel Álvaro Sánchez · Tutora de empresa: Laura Delgado Hurtado
