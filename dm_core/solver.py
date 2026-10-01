"""Minimal web-app extract of DigitalModel's Everitt-Jennings solver.
Source logic: vamseeachanta/digitalmodel,
commit fad4a6a1a99207a17a7a5816cab4bdddc06c613a,
src/digitalmodel/marine_ops/artificial_lift/dynacard/everitt_jennings/solver.py
MIT License, Copyright (c) 2022 Vamsee Achanta.

The numerical equations and defaults below follow that solver. Numba acceleration
is intentionally omitted; this changes speed only, not the equations.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import numpy as np
from scipy.signal import savgol_filter
from .damping import estimate_damping_profile

DEFAULT_NUM_NODES = 100
DEFAULT_SAVGOL_WINDOW = 21
DEFAULT_SAVGOL_ORDER = 5
STEEL_MODULUS_PA = 2.07e11
STEEL_DENSITY_KG_M3 = 7850.0
WATER_DENSITY_KG_M3 = 998.2
GRAVITY_M_S2 = 9.80665

@dataclass
class RodString:
    diameters: np.ndarray
    lengths: np.ndarray
    densities: Optional[np.ndarray] = None
    moduli: Optional[np.ndarray] = None
    coupling_diameters: Optional[np.ndarray] = None

    def __post_init__(self):
        self.diameters = np.asarray(self.diameters, dtype=np.float64)
        self.lengths = np.asarray(self.lengths, dtype=np.float64)
        n = len(self.diameters)
        if n == 0 or len(self.lengths) != n:
            raise ValueError("rod diameters and lengths must have equal nonzero length")
        if np.any(self.diameters <= 0) or np.any(self.lengths <= 0):
            raise ValueError("rod diameters and lengths must be positive")
        if self.densities is None:
            self.densities = np.full(n, STEEL_DENSITY_KG_M3)
        if self.moduli is None:
            self.moduli = np.full(n, STEEL_MODULUS_PA)
        if self.coupling_diameters is None:
            self.coupling_diameters = self.diameters * 1.5
        self.densities = np.asarray(self.densities, dtype=np.float64)
        self.moduli = np.asarray(self.moduli, dtype=np.float64)
        self.coupling_diameters = np.asarray(self.coupling_diameters, dtype=np.float64)

    @property
    def total_length(self):
        return float(np.sum(self.lengths))

    @property
    def areas(self):
        return np.pi * (self.diameters / 2.0) ** 2

@dataclass
class Survey:
    measured_depth: np.ndarray
    inclination: np.ndarray
    azimuth: np.ndarray
    inclination_gradient: Optional[np.ndarray] = None
    azimuth_gradient: Optional[np.ndarray] = None

    @classmethod
    def vertical(cls, total_length: float):
        md = np.array([0.0, total_length], dtype=np.float64)
        z = np.zeros(2, dtype=np.float64)
        return cls(md, z.copy(), z.copy(), z.copy(), z.copy())

    def __post_init__(self):
        self.measured_depth = np.asarray(self.measured_depth, dtype=np.float64)
        self.inclination = np.asarray(self.inclination, dtype=np.float64)
        self.azimuth = np.asarray(self.azimuth, dtype=np.float64)
        if self.inclination_gradient is None:
            self.inclination_gradient = np.gradient(self.inclination, self.measured_depth)
        if self.azimuth_gradient is None:
            self.azimuth_gradient = np.gradient(self.azimuth, self.measured_depth)
        self.inclination_gradient = np.asarray(self.inclination_gradient, dtype=np.float64)
        self.azimuth_gradient = np.asarray(self.azimuth_gradient, dtype=np.float64)

    def phi(self, s): return np.interp(s, self.measured_depth, self.inclination)
    def d_phi(self, s): return np.interp(s, self.measured_depth, self.inclination_gradient)
    def d_psi(self, s): return np.interp(s, self.measured_depth, self.azimuth_gradient)

@dataclass
class Simulation:
    u: np.ndarray = field(default_factory=lambda: np.empty(0))
    f: np.ndarray = field(default_factory=lambda: np.empty(0))
    taper_lengths: np.ndarray = field(default_factory=lambda: np.empty(0))
    n_tap: int = 0
    rod_length: float = 0.0
    areas: np.ndarray = field(default_factory=lambda: np.empty(0))
    rho_a: np.ndarray = field(default_factory=lambda: np.empty(0))
    buoyant_rho_a: np.ndarray = field(default_factory=lambda: np.empty(0))
    moduli: np.ndarray = field(default_factory=lambda: np.empty(0))
    damping: np.ndarray = field(default_factory=lambda: np.empty(0))
    densities: np.ndarray = field(default_factory=lambda: np.empty(0))
    wave_speed: np.ndarray = field(default_factory=lambda: np.empty(0))
    volume: float = 0.0
    weight: float = 0.0
    buoyant_weight: float = 0.0
    gravity: float = GRAVITY_M_S2
    friction: float = 0.0
    n_x: int = DEFAULT_NUM_NODES
    n_t: int = 0
    period: float = 0.0
    dt: float = 0.0
    dx: float = 0.0
    x: np.ndarray = field(default_factory=lambda: np.empty(0))
    t: np.ndarray = field(default_factory=lambda: np.empty(0))
    up_dn: int = 0
    boundary: np.ndarray = field(default_factory=lambda: np.empty(0))
    cumulative_buoyant: np.ndarray = field(default_factory=lambda: np.empty(0))
    interfaces: np.ndarray = field(default_factory=lambda: np.empty(0, dtype=int))

@dataclass
class Coefficients:
    moduli: np.ndarray = field(default_factory=lambda: np.empty(0))
    areas: np.ndarray = field(default_factory=lambda: np.empty(0))
    rho_a: np.ndarray = field(default_factory=lambda: np.empty(0))
    buoyant_rho_a: np.ndarray = field(default_factory=lambda: np.empty(0))
    damping: np.ndarray = field(default_factory=lambda: np.empty(0))
    phi: np.ndarray = field(default_factory=lambda: np.empty(0))
    d_phi: np.ndarray = field(default_factory=lambda: np.empty(0))
    d_psi: np.ndarray = field(default_factory=lambda: np.empty(0))

def _section_cuts(lengths):
    cuts = np.zeros(len(lengths) + 1, dtype=np.float64)
    cuts[1:] = np.cumsum(lengths)
    return cuts

def build_simulation(position, load, rods, strokes_per_minute,
                     fluid_density=WATER_DENSITY_KG_M3, damping=None,
                     friction_coefficient=0.0, n_nodes=DEFAULT_NUM_NODES,
                     gravity=GRAVITY_M_S2):
    position = np.asarray(position, dtype=np.float64)
    load = np.asarray(load, dtype=np.float64)
    if len(position) != len(load) or len(position) < 4:
        raise ValueError("surface position/load must have equal length >= 4")
    if strokes_per_minute <= 0:
        raise ValueError("SPM must be positive")
    sim = Simulation()
    sim.u = -position.copy()
    sim.f = load.copy()
    sim.gravity = gravity
    sim.friction = friction_coefficient
    sim.taper_lengths = rods.lengths
    sim.n_tap = len(rods.lengths)
    sim.rod_length = rods.total_length
    sim.areas = rods.areas
    sim.densities = rods.densities
    sim.moduli = rods.moduli
    sim.rho_a = rods.densities * rods.areas
    sim.buoyant_rho_a = (rods.densities - fluid_density) * rods.areas
    sim.damping = np.zeros(2 * sim.n_tap) if damping is None else np.asarray(damping, dtype=np.float64)
    sim.volume = float(np.sum(sim.taper_lengths * sim.areas))
    sim.weight = float(np.sum(sim.rho_a * sim.taper_lengths))
    sim.buoyant_weight = (sim.weight - sim.volume * fluid_density) * gravity
    sim.wave_speed = np.sqrt(sim.moduli / sim.densities)
    sim.n_x = int(n_nodes)
    sim.n_t = len(sim.f)
    sim.period = 60.0 / strokes_per_minute
    sim.t = np.linspace(0.0, sim.period, sim.n_t)
    sim.dt = sim.t[1] - sim.t[0]
    sim.x = np.linspace(0.0, sim.rod_length, sim.n_x)
    sim.dx = sim.x[1] - sim.x[0]
    cuts = _section_cuts(sim.taper_lengths)
    sim.cumulative_buoyant = np.zeros(sim.n_x)
    for i in range(len(cuts) - 1):
        remaining_length = np.clip(cuts[i+1] - np.maximum(sim.x, cuts[i]), 0.0, sim.taper_lengths[i])
        sim.cumulative_buoyant += sim.buoyant_rho_a[i] * gravity * remaining_length
    sim.up_dn = int(np.mean(np.where(sim.u == np.min(sim.u))[0]))
    sim.boundary = sim.f - sim.buoyant_weight
    return sim

def build_coefficients(sim, survey):
    coeff = Coefficients()
    cuts = _section_cuts(sim.taper_lengths)
    n_x, n_t = sim.n_x, sim.n_t
    for name, values in (("moduli",sim.moduli),("areas",sim.areas),("rho_a",sim.rho_a),("buoyant_rho_a",sim.buoyant_rho_a)):
        matrix = np.full((n_x,n_t), np.nan)
        for i in range(len(cuts)-1):
            mask = (cuts[i] <= sim.x) & (sim.x <= cuts[i+1])
            matrix[mask,:] = values[i]
        setattr(coeff,name,matrix)
    damping = np.reshape(sim.damping, (2, sim.n_tap)).T
    coeff.damping = np.empty((n_x,n_t))
    for i in range(len(cuts)-1):
        lo = np.searchsorted(sim.x,cuts[i])
        hi = np.searchsorted(sim.x,cuts[i+1],side="right")
        coeff.damping[lo:hi,:sim.up_dn] = damping[i,0]
        coeff.damping[lo:hi,sim.up_dn:] = damping[i,1]
    phi = survey.phi(sim.x); dphi = survey.d_phi(sim.x); dpsi = survey.d_psi(sim.x)
    coeff.phi = np.repeat(phi[:,None],n_t,axis=1)
    coeff.d_phi = np.repeat(dphi[:,None],n_t,axis=1)
    coeff.d_psi = np.repeat(dpsi[:,None],n_t,axis=1)
    return coeff

def initial_matrix(sim, coeff):
    solution = np.empty((sim.n_x,sim.n_t))
    solution[0,:] = sim.u
    ea_dx = coeff.moduli[0,:] * coeff.areas[0,:] / sim.dx
    solution[1,:] = solution[0,:] + sim.boundary / ea_dx
    return solution

def _normal_force_per_length(rho_a, gravity, phi, d_phi, d_psi, axial_force):
    gravity_normal = rho_a * gravity * np.sin(phi)
    curvature_normal = axial_force * d_phi
    azimuth_normal = axial_force * d_psi * np.sin(phi)
    return np.sqrt((gravity_normal + curvature_normal)**2 + azimuth_normal**2)

def _march(u,n_x,n_t,dt,dx,lam,rho_a,buoyant_rho_a,remaining_buoyant,g,c,e_mod,area,phi,d_phi,d_psi,muteg):
    for i in range(1,n_x-1):
        for j in range(1,n_t-1):
            ea_plus = (e_mod[i+1,j]*area[i+1,j] + e_mod[i,j]*area[i,j]) / 2.0
            ea_minus = (e_mod[i-1,j]*area[i-1,j] + e_mod[i,j]*area[i,j]) / 2.0
            rho_a_ij = rho_a[i,j]; bra = buoyant_rho_a[i,j]; rho_a_c = rho_a[i,j] * c[i,j]
            delta = u[i,j+1] - u[i,j]
            sign = 1.0 if delta > 0 else (-1.0 if delta < 0 else 0.0)
            c1 = (rho_a_ij/ea_plus)*(dx/dt)**2
            c2 = (rho_a_c/ea_plus)*dx**2/dt
            c3 = (lam*sign/ea_plus)*dx**2
            c4 = (bra/ea_plus)*dx**2
            reduced = ea_minus*(u[i,j]-u[i-1,j])/dx
            axial = reduced + remaining_buoyant[i]
            qn = _normal_force_per_length(bra,g,phi[i,j],d_phi[i,j],d_psi[i,j],axial)
            u[i+1,j] = (u[i,j] + (ea_minus/ea_plus)*u[i,j] - (ea_minus/ea_plus)*u[i-1,j]
                        + c1*(u[i,j+1]-2*u[i,j]+u[i,j-1])
                        + c2*(u[i,j+1]-u[i,j-1])/2.0
                        + c3*qn*muteg - c4*g*(np.cos(phi[i,j])-1.0)*muteg)
        ea_plus = (e_mod[i+1,0]*area[i+1,0] + e_mod[i,0]*area[i,0]) / 2.0
        ea_minus = (e_mod[i-1,0]*area[i-1,0] + e_mod[i,0]*area[i,0]) / 2.0
        rho_a_ij = rho_a[i,0]; bra = buoyant_rho_a[i,0]; rho_a_c = rho_a[i,0]*c[i,0]
        c1 = (rho_a_ij/ea_plus)*(dx/dt)**2; c2=(rho_a_c/ea_plus)*dx**2/dt
        delta = u[i,1]-u[i,0]; sign = 1.0 if delta>0 else (-1.0 if delta<0 else 0.0)
        c3=(lam*sign/ea_plus)*dx**2; c4=(bra/ea_plus)*dx**2
        reduced=ea_minus*(u[i,0]-u[i-1,0])/dx; axial=reduced+remaining_buoyant[i]
        qn=_normal_force_per_length(bra,g,phi[i,0],d_phi[i,0],d_psi[i,0],axial)
        u[i+1,0] = (u[i,0] + (ea_minus/ea_plus)*u[i,0] - (ea_minus/ea_plus)*u[i-1,0]
                    + c1*(u[i,1]-2*u[i,0]+u[i,n_t-2]) + c2*(u[i,1]-u[i,n_t-2])/2.0
                    + c3*qn*muteg - c4*g*(np.cos(phi[i,0])-1.0)*muteg)
        u[i+1,n_t-1] = u[i+1,0]
    load = np.empty(n_t)
    alpha=e_mod[n_x-1,0]*area[n_x-1,0]/(2*dx)
    load[0]=alpha*(3*u[n_x-1,0]-4*u[n_x-2,0]+u[n_x-3,0]); load[n_t-1]=load[0]
    for j in range(1,n_t-1):
        load[j]=(e_mod[n_x-1,j]*area[n_x-1,j]/dx)*(u[n_x-1,j]-u[n_x-2,j])
    return u, -u[n_x-1,:], load

def _full_load(u,moduli,areas,dx):
    full=np.empty_like(u); full[0]=0.0
    for i in range(1,u.shape[0]): full[i]=(moduli[i]*areas[i]/dx)*(u[i]-u[i-1])
    return full

@dataclass
class DownholeCard:
    position: np.ndarray
    load: np.ndarray
    full_position: Optional[np.ndarray]=None
    full_load: Optional[np.ndarray]=None
    simulation: Optional[Simulation]=None
    @property
    def stroke(self): return float(np.max(self.position)-np.min(self.position))
    @property
    def load_range(self): return float(np.max(self.load)-np.min(self.load))

class EverittJenningsSolver:
    def __init__(self,n_nodes=DEFAULT_NUM_NODES,viscosity=0.01,friction_coefficient=0.0,
                 include_gravity=False,smooth_window=DEFAULT_SAVGOL_WINDOW,
                 smooth_order=DEFAULT_SAVGOL_ORDER,remove_interface_jumps=True):
        self.n_nodes=int(n_nodes); self.viscosity=float(viscosity)
        self.friction_coefficient=float(friction_coefficient); self.include_gravity=bool(include_gravity)
        self.smooth_window=int(smooth_window); self.smooth_order=int(smooth_order)
        self.remove_interface_jumps=bool(remove_interface_jumps)

    def solve(self,position,load,rods,strokes_per_minute,pump_diameter,tubing_id,
              fluid_density=WATER_DENSITY_KG_M3,survey=None,damping=None):
        if survey is None: survey=Survey.vertical(rods.total_length)
        if damping is None:
            damping=estimate_damping_profile(rods.diameters,rods.coupling_diameters,rods.lengths,
                                             rods.densities,pump_diameter,tubing_id,self.viscosity)
        sim=build_simulation(position,load,rods,strokes_per_minute,fluid_density,damping,
                             self.friction_coefficient,self.n_nodes)
        coeff=build_coefficients(sim,survey); u=initial_matrix(sim,coeff)
        muteg=1.0 if self.include_gravity else 0.0
        u,dh_position,dh_load=_march(u,sim.n_x,sim.n_t,sim.dt,sim.dx,sim.friction,
            coeff.rho_a,coeff.buoyant_rho_a,sim.cumulative_buoyant,sim.gravity,coeff.damping,
            coeff.moduli,coeff.areas,coeff.phi,coeff.d_phi,coeff.d_psi,muteg)
        if self.smooth_window and self.smooth_window > self.smooth_order:
            window=min(self.smooth_window,len(dh_load))
            if window%2==0: window-=1
            if window>self.smooth_order: dh_load=savgol_filter(dh_load,window,self.smooth_order)
        dh_load[sim.n_t-1]=dh_load[0]; dh_position[sim.n_t-1]=dh_position[0]
        full_position=-u
        full_load=_full_load(u,coeff.moduli,coeff.areas,sim.dx)+sim.cumulative_buoyant.reshape(-1,1)
        full_load[0,:]=sim.f
        interfaces=np.where(np.abs(np.diff(coeff.areas[:,0]))>1e-14)[0]+1; sim.interfaces=interfaces
        if self.remove_interface_jumps and len(interfaces)>0:
            if interfaces[-1]==len(full_load)-1: interfaces[-1]-=1
            full_load[interfaces,:]=(full_load[interfaces-1,:]+full_load[interfaces+1,:])/2.0
        return DownholeCard(dh_position,dh_load,full_position,full_load,sim)
