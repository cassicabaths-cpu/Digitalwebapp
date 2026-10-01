# DigitalModel Dynacard Web

Interfaz web ligera para convertir una carta dinamométrica de superficie a carta de fondo con el núcleo Everitt–Jennings de **DigitalModel**.

## Qué usa del archivo de entrada

Solo las dos columnas que selecciones como **posición de superficie** y **carga de superficie**. Cualquier columna de Pump Card / Downhole Card presente en el archivo se ignora para el cálculo.

## Uso inmediato en tu navegador

### Opción A — Streamlit Community Cloud
1. Sube esta carpeta a un repositorio GitHub.
2. En `share.streamlit.io`, selecciona el repositorio y `app.py`.
3. Pulsa Deploy.

### Opción B — En tu ordenador, pero usando navegador
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```
Streamlit abrirá la app en el navegador.

## Entradas
- Carta de superficie: CSV/TXT/XLSX.
- Sarta: diámetro, longitud; opcionalmente peso por pie, módulo elástico y coupling OD.
- SPM.
- Pump diameter.
- Tubing ID.
- Densidad y viscosidad de fluido.
- Survey opcional.
- Damping: estimación física de DigitalModel (recomendado) o coeficientes explícitos en 1/s.

## Defaults y convenciones
- Internamente todo se convierte a SI.
- Si no se da peso/ft, usa 490 lb/ft³ para la densidad de varilla.
- Si no se da módulo, usa 30,000,000 psi.
- Si no se da coupling OD, usa 1.5 × rod OD.
- Si no hay survey, se usa pozo vertical.
- `include_gravity=False` por defecto, igual que el solver actual de DigitalModel.
- Savitzky–Golay: ventana 21, orden 5.

## Procedencia
El núcleo `dm_core` conserva las ecuaciones y defaults relevantes de:
`vamseeachanta/digitalmodel`, commit `fad4a6a1a99207a17a7a5816cab4bdddc06c613a`, módulo Everitt–Jennings.
La aceleración opcional con Numba se omitió para simplificar el despliegue web; las ecuaciones no cambian.

DigitalModel: MIT License, Copyright (c) 2022 Vamsee Achanta.
