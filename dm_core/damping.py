"""Minimal extract of DigitalModel Everitt-Jennings damping logic.
Source: vamseeachanta/digitalmodel, commit fad4a6a1a99207a17a7a5816cab4bdddc06c613a.
MIT License, Copyright (c) 2022 Vamsee Achanta.
"""
from math import log, pi
from typing import Tuple
import numpy as np

COUPLING_RATIO_FLOOR = 0.381
MIN_VISCOSITY_PA_S = 0.001
DEFAULT_VISCOSITY_PA_S = 0.01


def estimate_damping_coeff(od_rod: float, od_connect: float, od_pump: float,
                            id_well: float, mu: float, l_tap: float,
                            ro_rod: float) -> Tuple[float, float]:
    if od_rod <= 0.0 or id_well <= 0.0:
        raise ValueError("rod OD and tubing ID must be positive")
    if id_well <= od_rod:
        raise ValueError("tubing ID must exceed rod OD")

    a_rod = pi * od_rod ** 2 / 4.0
    a_well = pi * id_well ** 2 / 4.0
    m = id_well / od_rod
    b1 = (m ** 2 - 1.0) / (2.0 * log(m)) - 1.0
    b2 = m ** 4 - 1.0 - (m ** 2 - 1.0) ** 2 / log(m)
    b3 = 1.0 / log(m)
    m2 = od_pump / od_rod + 1.0e-6

    coupling_ratio = od_connect / id_well
    if coupling_ratio <= COUPLING_RATIO_FLOOR:
        raise ValueError(
            f"coupling OD / bore ID = {coupling_ratio:.4f} is at or below "
            f"{COUPLING_RATIO_FLOOR}; verify tubing ID and coupling OD"
        )

    clearance = id_well / 2.0 - od_rod / 2.0
    coupling_base = 1.3e4 * mu * (coupling_ratio - COUPLING_RATIO_FLOOR) ** 2.57 / clearance
    k_c1 = coupling_base * (2.77 - 1.69 * (m ** 2 - 1.0) / (m2 ** 2 - 1.0))
    k_c2 = coupling_base * (2.77 + 1.69 * (m ** 2 - 1.0))

    n1 = (
        pi * mu * (b3 + 4 * b1 ** 2 / b2)
        + 4 * mu * pi * (m2 ** 2 - 1) ** 2 / b2
        - 8 * pi * mu * (m2 ** 2 - 1) * b1 / b2
    )
    n2 = (
        pi * mu * (b3 + 4 * b1 ** 2 / b2)
        + 4 * mu * pi / b2
        + 8 * pi * mu * b1 / b2
    )
    coupling_scale = (a_well - a_rod) / (2.0 * (m ** 2 - 1.0) ** 2 * l_tap)
    n3 = coupling_scale * (m2 ** 2 - 1.0) ** 2 * k_c1
    n4 = coupling_scale * k_c2
    normaliser = ro_rod * a_rod
    return (n1 + n3) / normaliser, (n2 + n4) / normaliser


def estimate_damping_profile(rod_diameters: np.ndarray,
                             coupling_diameters: np.ndarray,
                             taper_lengths: np.ndarray,
                             rod_densities: np.ndarray,
                             pump_diameter: float,
                             tubing_id: float,
                             viscosity: float) -> np.ndarray:
    n_tap = len(taper_lengths)
    if not (len(rod_diameters) == len(coupling_diameters) == len(rod_densities) == n_tap):
        raise ValueError("per-section arrays must have equal length")
    mu = viscosity if viscosity > MIN_VISCOSITY_PA_S else DEFAULT_VISCOSITY_PA_S
    coefficients = np.empty(2 * n_tap, dtype=np.float64)
    for i in range(n_tap):
        c_up, c_dn = estimate_damping_coeff(
            rod_diameters[i], coupling_diameters[i], pump_diameter,
            tubing_id, mu, taper_lengths[i], rod_densities[i]
        )
        coefficients[i] = c_up
        coefficients[i + n_tap] = c_dn
    return coefficients
