# Digitalwebapp

Aplicación web para análisis dinamométrico de pozos mediante el solver Everitt–Jennings de DigitalModel.

## Flujo

1. Cargar un archivo con las cartas de superficie de uno o muchos pozos.
2. Cargar un Excel con los datos de configuración de los pozos.
3. Importar/actualizar.
4. Seleccionar un pozo para ver exclusivamente su historial.
5. Seleccionar una medición y pulsar **Calcular**. La carta de fondo se genera y se guarda en esa medición.
6. También se puede calcular todo el historial pendiente del pozo seleccionado.

## Archivo de cartas

Columnas requeridas:

- `WellName`
- `CardDate`
- `Point`
- `SurfacePosition_in`
- `SurfaceLoad_kips`

## Archivo de datos de pozos

Excel con hojas:

- `Wells`
- `RodString`
- `Survey` opcional

## Historial

Cada medición se identifica mediante `WellName + CardDate`. La interfaz muestra el historial filtrado por pozo, por lo que las mediciones de un pozo no se mezclan con las de otro.

Los resultados calculados incluyen y almacenan la carta de fondo correspondiente a cada medición.

## Motor

El núcleo `dm_core` implementa el solver Everitt–Jennings basado en DigitalModel.
