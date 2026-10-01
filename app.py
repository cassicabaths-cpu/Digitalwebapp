from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from engine import solve_measurement
from io_utils import InputFormatError, parse_surface_cards, parse_well_data
from storage import HistoryStore

st.set_page_config(page_title="Análisis dinamométrico", page_icon="📈", layout="wide")

APP_DIR = Path(__file__).resolve().parent
DB_PATH = APP_DIR / "data" / "history.db"
store = HistoryStore(DB_PATH)


def card_figure(position, load, title: str):
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=position,
            y=load,
            mode="lines",
            hovertemplate="Posición: %{x:.3f} in<br>Carga: %{y:.3f} kips<extra></extra>",
        )
    )
    fig.update_layout(
        title=title,
        xaxis_title="Posición [in]",
        yaxis_title="Carga [kips]",
        margin=dict(l=20, r=20, t=50, b=20),
        height=460,
        showlegend=False,
    )
    return fig


def import_files(cards_file, wells_file):
    cards = parse_surface_cards(cards_file.getvalue(), cards_file.name)
    configs = parse_well_data(wells_file.getvalue(), wells_file.name)

    imported_ids = []
    skipped = []
    for (well_name, card_date), df in cards.items():
        cfg = configs.get(well_name)
        if cfg is None:
            skipped.append(well_name)
            continue

        measurement_id = store.upsert_measurement(
            well_name=well_name,
            card_date=card_date,
            surface_position=df["SurfacePosition_in"].to_numpy(float),
            surface_load=df["SurfaceLoad_kips"].to_numpy(float),
            config=cfg,
            source_cards=cards_file.name,
            source_config=wells_file.name,
        )
        imported_ids.append(measurement_id)

    return imported_ids, sorted(set(skipped))


def solve_and_store(measurement_id: int):
    measurement = store.get_measurement(measurement_id)
    if measurement is None:
        raise ValueError("No se encontró la medición seleccionada.")
    position, load, summary = solve_measurement(measurement)
    store.save_result(measurement_id, position, load, summary)
    return summary


def selected_result_csv(measurement: dict) -> bytes:
    data = {
        "SurfacePosition_in": measurement["surface_position"],
        "SurfaceLoad_kips": measurement["surface_load"],
    }
    if measurement["downhole_position"] is not None:
        data["DownholePosition_in"] = measurement["downhole_position"]
        data["DownholeLoad_kips"] = measurement["downhole_load"]
    return pd.DataFrame(data).to_csv(index=False).encode("utf-8")


def history_dataframe(measurements: list[dict]) -> pd.DataFrame:
    rows = []
    for m in measurements:
        summary = m.get("summary") or {}
        rows.append(
            {
                "Fecha": pd.to_datetime(m["card_date"]).strftime("%Y-%m-%d %H:%M:%S"),
                "Estado": "Calculada" if m.get("summary") else "Pendiente",
                "Carrera superficie [in]": summary.get("surface_stroke_in"),
                "Carrera fondo [in]": summary.get("downhole_stroke_in"),
                "Carga mín. fondo [kips]": summary.get("downhole_load_min_kips"),
                "Carga máx. fondo [kips]": summary.get("downhole_load_max_kips"),
            }
        )
    return pd.DataFrame(rows)


st.title("Análisis dinamométrico")

upload_col1, upload_col2 = st.columns(2)
with upload_col1:
    cards_file = st.file_uploader(
        "Carga y posición",
        type=["csv", "txt", "dat", "xlsx", "xls"],
    )
with upload_col2:
    wells_file = st.file_uploader(
        "Datos de pozos",
        type=["xlsx", "xls"],
    )

if st.button(
    "Calcular",
    type="primary",
    disabled=cards_file is None or wells_file is None,
    use_container_width=True,
):
    try:
        imported_ids, skipped = import_files(cards_file, wells_file)

        errors = []
        if imported_ids:
            progress = st.progress(0)
            status = st.empty()
            for i, measurement_id in enumerate(imported_ids, start=1):
                measurement = store.get_measurement(measurement_id)
                status.write(
                    f"Calculando {measurement['well_name']} — "
                    + pd.to_datetime(measurement["card_date"]).strftime("%Y-%m-%d %H:%M:%S")
                )
                try:
                    solve_and_store(measurement_id)
                except Exception as exc:
                    errors.append(
                        f"{measurement['well_name']} | {measurement['card_date']}: {exc}"
                    )
                progress.progress(i / len(imported_ids))
            status.empty()
            progress.empty()

        calculated = len(imported_ids) - len(errors)
        if calculated:
            st.success(
                f"Se procesaron {len(imported_ids)} mediciones y se generaron "
                f"{calculated} cartas de superficie y fondo."
            )
        elif imported_ids:
            st.error("Las mediciones se importaron, pero no se pudo generar ninguna carta de fondo.")

        if skipped:
            st.warning(
                "No se procesaron cartas sin configuración de pozo: "
                + ", ".join(skipped)
            )
        if errors:
            st.warning(f"{len(errors)} medición(es) presentaron error de cálculo.")
            with st.expander("Ver errores"):
                for err in errors:
                    st.write(err)
    except InputFormatError as exc:
        st.error(str(exc))
    except Exception as exc:
        st.error(f"No se pudieron procesar los archivos: {exc}")

wells = store.list_wells()
if not wells:
    st.info("Sube los dos archivos para comenzar.")
    st.stop()

st.divider()

# Cada pozo tiene su propio historial lógico y solo se muestran sus mediciones.
selected_well = st.selectbox("Pozo", wells)
measurements = store.list_measurements(selected_well)

head_col1, head_col2 = st.columns([3, 1])
with head_col1:
    st.subheader(f"Historial — {selected_well}")
with head_col2:
    st.metric("Mediciones", len(measurements))

st.dataframe(
    history_dataframe(measurements),
    use_container_width=True,
    hide_index=True,
)

measurement_labels = {
    f"{pd.to_datetime(m['card_date']).strftime('%Y-%m-%d %H:%M:%S')}"
    + ("  ✓" if m["summary"] else "  • pendiente"): m["id"]
    for m in measurements
}
selected_label = st.selectbox("Medición", list(measurement_labels.keys()))
measurement_id = measurement_labels[selected_label]
measurement = store.get_measurement(measurement_id)

calc_col, all_col, download_col, backup_col = st.columns(4)
with calc_col:
    calculate_selected = st.button(
        "Recalcular medición",
        type="primary",
        use_container_width=True,
    )

with all_col:
    calculate_well = st.button(
        "Recalcular historial del pozo",
        disabled=not bool(store.pending_ids(selected_well)),
        use_container_width=True,
    )

with download_col:
    st.download_button(
        "Descargar medición",
        data=selected_result_csv(measurement),
        file_name=f"{selected_well}_{measurement['card_date'].replace(':', '-')}.csv",
        mime="text/csv",
        use_container_width=True,
    )

with backup_col:
    st.download_button(
        "Descargar historial",
        data=store.db_bytes(),
        file_name="dynacard_history.db",
        mime="application/octet-stream",
        use_container_width=True,
    )

# Al pulsar Calcular, la carta de fondo se genera y se guarda inmediatamente.
if calculate_selected:
    try:
        with st.spinner("Calculando..."):
            solve_and_store(measurement_id)
        st.rerun()
    except Exception as exc:
        st.error(f"No se pudo calcular la carta: {exc}")

if calculate_well:
    pending = store.pending_ids(selected_well)
    if not pending:
        st.info("Este pozo no tiene mediciones pendientes.")
    else:
        progress = st.progress(0)
        status = st.empty()
        errors = []
        for i, mid in enumerate(pending, start=1):
            m = store.get_measurement(mid)
            status.write(
                "Calculando "
                + pd.to_datetime(m["card_date"]).strftime("%Y-%m-%d %H:%M:%S")
            )
            try:
                solve_and_store(mid)
            except Exception as exc:
                errors.append(f"{m['card_date']}: {exc}")
            progress.progress(i / len(pending))
        status.empty()
        progress.empty()
        if errors:
            st.warning(f"Se completó con {len(errors)} error(es).")
            with st.expander("Ver errores"):
                for err in errors:
                    st.write(err)
        else:
            st.success(f"Se calcularon {len(pending)} mediciones de {selected_well}.")
        st.rerun()

# Recargar por si el estado cambió tras alguna operación anterior.
measurement = store.get_measurement(measurement_id)

surface_col, downhole_col = st.columns(2)
with surface_col:
    st.plotly_chart(
        card_figure(
            measurement["surface_position"],
            measurement["surface_load"],
            "Carta de superficie",
        ),
        use_container_width=True,
    )

with downhole_col:
    if measurement["downhole_position"] is not None:
        st.plotly_chart(
            card_figure(
                measurement["downhole_position"],
                measurement["downhole_load"],
                "Carta de fondo",
            ),
            use_container_width=True,
        )
    else:
        st.subheader("Carta de fondo")
        st.info("La carta de fondo no está disponible para esta medición. Puedes recalcularla.")

summary = measurement.get("summary")
if summary:
    st.subheader("Resultados")
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Carrera superficie", f"{summary['surface_stroke_in']:.2f} in")
    m2.metric("Carrera fondo", f"{summary['downhole_stroke_in']:.2f} in")
    m3.metric("Carga mín. superficie", f"{summary['surface_load_min_kips']:.2f} kips")
    m4.metric("Carga máx. superficie", f"{summary['surface_load_max_kips']:.2f} kips")
    m5.metric("Carga mín. fondo", f"{summary['downhole_load_min_kips']:.2f} kips")
    m6.metric("Carga máx. fondo", f"{summary['downhole_load_max_kips']:.2f} kips")
