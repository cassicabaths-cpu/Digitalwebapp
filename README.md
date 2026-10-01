# Análisis Dinamométrico

Aplicación Streamlit para convertir cartas de superficie en cartas de fondo con el solver Everitt–Jennings de DigitalModel.

## Archivos de entrada

La interfaz recibe dos archivos.

### 1. Carga y posición
CSV, TXT o Excel con estas columnas:

- `WellName`
- `CardDate`
- `Point`
- `SurfacePosition_in`
- `SurfaceLoad_kips`

Puede contener múltiples pozos y múltiples fechas por pozo.

### 2. Datos de pozos
Excel con las hojas `Wells` y `RodString`; la hoja `Survey` es opcional.

#### Wells
Columnas mínimas:
- `WellName`
- `SPM`
- `PumpDiameter_in`
- `TubingID_in`
- `FluidDensity_lb_ft3`
- `Viscosity_cp`

Columnas opcionales:
- `Nodes`
- `FrictionCoefficient`
- `IncludeGravity`
- `SmoothWindow`
- `SmoothOrder`
- `RemoveInterfaceJumps`
- `DampingMode` (`auto` o `explicit`)

#### RodString
Columnas mínimas:
- `WellName`
- `Section`
- `Diameter_in`
- `Length_ft`

Columnas opcionales:
- `Weight_lb_ft`
- `Modulus_psi`
- `CouplingOD_in`
- `DampingUp_1_s`
- `DampingDown_1_s`

#### Survey (opcional)
- `WellName`
- `MD_ft`
- `Inclination_deg`
- `Azimuth_deg`

## Historial

Cada medición se guarda por `WellName + CardDate` en `data/history.db`. Si se vuelve a importar la misma combinación, se actualizan los datos y se invalida el cálculo anterior.

En un servidor con disco persistente, el historial queda conservado en SQLite. En Streamlit Community Cloud el disco local no se considera almacenamiento permanente entre reinicios o redespliegues; la interfaz incluye descarga del archivo de respaldo. Para persistencia permanente en la nube conviene conectar una base de datos externa en la siguiente etapa.

## Ejecución

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Ejemplos

- `examples/surface_cards_20_wells.csv`
- `examples/well_data_20_wells.xlsx`

## Núcleo numérico

Basado en `vamseeachanta/digitalmodel`, solver Everitt–Jennings, commit `fad4a6a1a99207a17a7a5816cab4bdddc06c613a`.
DigitalModel se distribuye bajo licencia MIT.
