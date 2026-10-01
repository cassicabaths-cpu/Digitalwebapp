from __future__ import annotations

import numpy as np

from dm_core import EverittJenningsSolver, RodString, Survey

IN2M = 0.0254
FT2M = 0.3048
KIP2N = 4448.2216152605
PSI2PA = 6894.757293168
LBPFT3_TO_KGPM3 = 16.01846337396014
M2IN = 1.0 / IN2M
N2KIP = 1.0 / KIP2N
COMMIT = "fad4a6a1a99207a17a7a5816cab4bdddc06c613a"


def _num(value, default=None):
    if value is None or value == "":
        return default
    try:
        x = float(value)
        return x if np.isfinite(x) else default
    except Exception:
        return default


def _bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "si", "sí"}


def solve_measurement(measurement: dict):
    cfg = measurement["config"]
    well = cfg["well"]
    rods_cfg = cfg["rods"]

    diam_in = np.asarray([_num(r.get("Diameter_in")) for r in rods_cfg], dtype=float)
    length_ft = np.asarray([_num(r.get("Length_ft")) for r in rods_cfg], dtype=float)
    if np.any(~np.isfinite(diam_in)) or np.any(diam_in <= 0):
        raise ValueError("RodString: Diameter_in debe ser positivo para todos los tramos.")
    if np.any(~np.isfinite(length_ft)) or np.any(length_ft <= 0):
        raise ValueError("RodString: Length_ft debe ser positivo para todos los tramos.")

    weight_pf = np.asarray([_num(r.get("Weight_lb_ft"), np.nan) for r in rods_cfg], dtype=float)
    modulus_psi = np.asarray([_num(r.get("Modulus_psi"), 30_000_000.0) for r in rods_cfg], dtype=float)
    coupling_in = np.asarray([_num(r.get("CouplingOD_in"), np.nan) for r in rods_cfg], dtype=float)

    density_lbft3 = np.full(len(diam_in), 490.0)
    mask = np.isfinite(weight_pf) & (weight_pf > 0)
    density_lbft3[mask] = weight_pf[mask] * 576.0 / (np.pi * diam_in[mask] ** 2)
    coupling_m = np.where(
        np.isfinite(coupling_in) & (coupling_in > 0),
        coupling_in * IN2M,
        diam_in * IN2M * 1.5,
    )

    rods = RodString(
        diameters=diam_in * IN2M,
        lengths=length_ft * FT2M,
        densities=density_lbft3 * LBPFT3_TO_KGPM3,
        moduli=modulus_psi * PSI2PA,
        coupling_diameters=coupling_m,
    )

    survey = None
    srows = cfg.get("survey") or []
    if srows:
        md = np.asarray([_num(r.get("MD_ft")) for r in srows], dtype=float)
        inc = np.asarray([_num(r.get("Inclination_deg"), 0.0) for r in srows], dtype=float)
        azi = np.asarray([_num(r.get("Azimuth_deg"), 0.0) for r in srows], dtype=float)
        valid = np.isfinite(md) & np.isfinite(inc) & np.isfinite(azi)
        if valid.sum() >= 2:
            order = np.argsort(md[valid])
            survey = Survey(
                measured_depth=md[valid][order] * FT2M,
                inclination=np.deg2rad(inc[valid][order]),
                azimuth=np.deg2rad(azi[valid][order]),
            )

    damping = None
    damping_mode = str(well.get("DampingMode") or "auto").strip().lower()
    if damping_mode in {"explicit", "explicito", "explícito"}:
        up = np.asarray([_num(r.get("DampingUp_1_s"), np.nan) for r in rods_cfg], dtype=float)
        dn = np.asarray([_num(r.get("DampingDown_1_s"), np.nan) for r in rods_cfg], dtype=float)
        if not (np.all(np.isfinite(up)) and np.all(np.isfinite(dn))):
            raise ValueError("Damping explícito: faltan coeficientes up/down en RodString.")
        damping = np.concatenate([up, dn])

    spm = _num(well.get("SPM"))
    pump_diam = _num(well.get("PumpDiameter_in"))
    tubing_id = _num(well.get("TubingID_in"))
    if not spm or spm <= 0:
        raise ValueError("SPM debe ser positivo.")
    if not pump_diam or pump_diam <= 0:
        raise ValueError("PumpDiameter_in debe ser positivo.")
    if not tubing_id or tubing_id <= 0:
        raise ValueError("TubingID_in debe ser positivo.")

    fluid_density = _num(well.get("FluidDensity_lb_ft3"), 62.4)
    viscosity_cp = _num(well.get("Viscosity_cp"), 10.0)
    n_nodes = int(_num(well.get("Nodes"), 100))
    friction = _num(well.get("FrictionCoefficient"), 0.0)
    include_gravity = _bool(well.get("IncludeGravity"), False)
    smooth_window = int(_num(well.get("SmoothWindow"), 21))
    smooth_order = int(_num(well.get("SmoothOrder"), 5))
    remove_jumps = _bool(well.get("RemoveInterfaceJumps"), True)

    surface_position_in = np.asarray(measurement["surface_position"], dtype=float)
    surface_load_kips = np.asarray(measurement["surface_load"], dtype=float)

    solver = EverittJenningsSolver(
        n_nodes=n_nodes,
        viscosity=viscosity_cp * 1e-3,
        friction_coefficient=friction,
        include_gravity=include_gravity,
        smooth_window=smooth_window,
        smooth_order=smooth_order,
        remove_interface_jumps=remove_jumps,
    )
    card = solver.solve(
        position=surface_position_in * IN2M,
        load=surface_load_kips * KIP2N,
        rods=rods,
        strokes_per_minute=spm,
        pump_diameter=pump_diam * IN2M,
        tubing_id=tubing_id * IN2M,
        fluid_density=fluid_density * LBPFT3_TO_KGPM3,
        survey=survey,
        damping=damping,
    )

    dh_pos = np.asarray(card.position, dtype=float) * M2IN
    dh_load = np.asarray(card.load, dtype=float) * N2KIP
    if not (np.all(np.isfinite(dh_pos)) and np.all(np.isfinite(dh_load))):
        raise ValueError("El solver produjo valores no finitos.")

    summary = {
        "solver": "DigitalModel Everitt-Jennings",
        "source_commit": COMMIT,
        "points": int(len(dh_pos)),
        "spm": float(spm),
        "surface_stroke_in": float(np.ptp(surface_position_in)),
        "surface_load_min_kips": float(np.min(surface_load_kips)),
        "surface_load_max_kips": float(np.max(surface_load_kips)),
        "downhole_stroke_in": float(np.ptp(dh_pos)),
        "downhole_load_min_kips": float(np.min(dh_load)),
        "downhole_load_max_kips": float(np.max(dh_load)),
        "pump_diameter_in": float(pump_diam),
        "tubing_id_in": float(tubing_id),
        "fluid_density_lb_ft3": float(fluid_density),
        "viscosity_cp": float(viscosity_cp),
        "n_nodes": int(n_nodes),
        "damping_mode": damping_mode,
    }
    return dh_pos, dh_load, summary
