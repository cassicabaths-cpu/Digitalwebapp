from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable

import pandas as pd


CARD_COLUMNS = [
    "WellName",
    "CardDate",
    "Point",
    "SurfacePosition_in",
    "SurfaceLoad_kips",
]

WELL_COLUMNS = [
    "WellName",
    "SPM",
    "PumpDiameter_in",
    "TubingID_in",
    "FluidDensity_lb_ft3",
    "Viscosity_cp",
]

ROD_COLUMNS = [
    "WellName",
    "Section",
    "Diameter_in",
    "Length_ft",
]


class InputFormatError(ValueError):
    pass


def _read_tabular(raw: bytes, name: str) -> pd.DataFrame:
    ext = Path(name).suffix.lower()
    if ext in {".xlsx", ".xls"}:
        return pd.read_excel(io.BytesIO(raw))
    if ext in {".csv", ".txt", ".dat"}:
        try:
            return pd.read_csv(io.BytesIO(raw), sep=None, engine="python")
        except Exception as exc:
            raise InputFormatError(f"No se pudo leer {name}: {exc}") from exc
    raise InputFormatError(f"Formato no soportado: {ext}")


def _require_columns(df: pd.DataFrame, required: Iterable[str], label: str) -> None:
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise InputFormatError(
            f"{label}: faltan columnas requeridas: {', '.join(missing)}"
        )


def parse_surface_cards(raw: bytes, name: str) -> Dict[tuple[str, str], pd.DataFrame]:
    """Return cards keyed by (well name, ISO card date)."""
    df = _read_tabular(raw, name).dropna(how="all")
    _require_columns(df, CARD_COLUMNS, "Archivo de cartas")

    work = df[CARD_COLUMNS].copy()
    work["WellName"] = work["WellName"].astype(str).str.strip()
    work["CardDate"] = pd.to_datetime(work["CardDate"], errors="coerce")
    work["Point"] = pd.to_numeric(work["Point"], errors="coerce")
    work["SurfacePosition_in"] = pd.to_numeric(
        work["SurfacePosition_in"], errors="coerce"
    )
    work["SurfaceLoad_kips"] = pd.to_numeric(
        work["SurfaceLoad_kips"], errors="coerce"
    )
    work = work.dropna(
        subset=["WellName", "CardDate", "Point", "SurfacePosition_in", "SurfaceLoad_kips"]
    )

    if work.empty:
        raise InputFormatError("El archivo de cartas no contiene registros válidos.")

    cards: Dict[tuple[str, str], pd.DataFrame] = {}
    for (well, dt), grp in work.groupby(["WellName", "CardDate"], sort=True):
        grp = grp.sort_values("Point").reset_index(drop=True)
        if len(grp) < 4:
            raise InputFormatError(
                f"{well} / {dt}: la carta tiene menos de 4 puntos."
            )
        iso = pd.Timestamp(dt).isoformat()
        cards[(str(well), iso)] = grp
    return cards


def parse_well_data(raw: bytes, name: str):
    """Parse a workbook with Wells, RodString and optional Survey sheets."""
    ext = Path(name).suffix.lower()
    if ext not in {".xlsx", ".xls"}:
        raise InputFormatError("El archivo de datos de pozos debe ser Excel (.xlsx).")

    xls = pd.ExcelFile(io.BytesIO(raw))
    required_sheets = {"Wells", "RodString"}
    missing_sheets = sorted(required_sheets.difference(xls.sheet_names))
    if missing_sheets:
        raise InputFormatError(
            "Faltan hojas requeridas: " + ", ".join(missing_sheets)
        )

    wells = pd.read_excel(io.BytesIO(raw), sheet_name="Wells").dropna(how="all")
    rods = pd.read_excel(io.BytesIO(raw), sheet_name="RodString").dropna(how="all")
    survey = (
        pd.read_excel(io.BytesIO(raw), sheet_name="Survey").dropna(how="all")
        if "Survey" in xls.sheet_names
        else pd.DataFrame()
    )

    _require_columns(wells, WELL_COLUMNS, "Hoja Wells")
    _require_columns(rods, ROD_COLUMNS, "Hoja RodString")

    wells["WellName"] = wells["WellName"].astype(str).str.strip()
    rods["WellName"] = rods["WellName"].astype(str).str.strip()
    if not survey.empty and "WellName" in survey.columns:
        survey["WellName"] = survey["WellName"].astype(str).str.strip()

    configs = {}
    for _, row in wells.iterrows():
        well = str(row["WellName"]).strip()
        if not well:
            continue
        row_dict = {k: _python_scalar(v) for k, v in row.to_dict().items()}
        rod_grp = rods.loc[rods["WellName"] == well].copy()
        if rod_grp.empty:
            raise InputFormatError(f"{well}: no tiene tramos en la hoja RodString.")
        rod_grp["Section"] = pd.to_numeric(rod_grp["Section"], errors="coerce")
        rod_grp = rod_grp.sort_values("Section")
        rod_records = [
            {k: _python_scalar(v) for k, v in r.items()}
            for r in rod_grp.to_dict(orient="records")
        ]

        survey_records = []
        if not survey.empty:
            needed = {"WellName", "MD_ft", "Inclination_deg", "Azimuth_deg"}
            if not needed.issubset(survey.columns):
                raise InputFormatError(
                    "Hoja Survey: se requieren WellName, MD_ft, Inclination_deg y Azimuth_deg."
                )
            sgrp = survey.loc[survey["WellName"] == well].copy()
            if not sgrp.empty:
                sgrp["MD_ft"] = pd.to_numeric(sgrp["MD_ft"], errors="coerce")
                sgrp = sgrp.sort_values("MD_ft")
                survey_records = [
                    {k: _python_scalar(v) for k, v in r.items()}
                    for r in sgrp.to_dict(orient="records")
                ]

        configs[well] = {
            "well": row_dict,
            "rods": rod_records,
            "survey": survey_records,
        }

    if not configs:
        raise InputFormatError("No se encontraron pozos válidos en la hoja Wells.")
    return configs


def _python_scalar(value):
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            pass
    return value
