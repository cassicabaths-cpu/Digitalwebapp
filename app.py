from __future__ import annotations
import io, json, re
from pathlib import Path
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from dm_core import EverittJenningsSolver, RodString, Survey

IN2M = 0.0254
FT2M = 0.3048
LB2N = 4.4482216152605
KIP2N = 4448.2216152605
PSI2PA = 6894.757293168
LBPFT3_TO_KGPM3 = 16.01846337396014
M2IN = 1/IN2M
N2LB = 1/LB2N
N2KIP = 1/KIP2N
COMMIT = "fad4a6a1a99207a17a7a5816cab4bdddc06c613a"

st.set_page_config(page_title="DigitalModel Dynacard", page_icon="📈", layout="wide")
st.title("DigitalModel Dynacard — carta de superficie → carta de fondo")
st.caption("Web UI sobre el solver Everitt–Jennings de DigitalModel. La carta de bomba de referencia NO participa en el cálculo.")

@st.cache_data
def read_uploaded(raw: bytes, name: str):
    ext = Path(name).suffix.lower()
    if ext in (".xlsx", ".xls"):
        xls = pd.ExcelFile(io.BytesIO(raw))
        return {s: pd.read_excel(io.BytesIO(raw), sheet_name=s) for s in xls.sheet_names}
    text = raw.decode("utf-8", errors="ignore")
    if ext in (".txt", ".dat"):
        lines=[l for l in text.splitlines() if l.strip()]
        header=None
        if lines and lines[0].lstrip().startswith("#"):
            header=re.split(r"\t+|\s{2,}", lines[0].lstrip()[1:].strip())
            body="\n".join(lines[1:])
            df=pd.read_csv(io.StringIO(body), sep=r"\s+|\t+|,|;", engine="python", header=None)
            if header and len(header)==df.shape[1]: df.columns=header
            else: df.columns=[f"col_{i+1}" for i in range(df.shape[1])]
            return {"data":df}
    try:
        return {"data": pd.read_csv(io.BytesIO(raw), sep=None, engine="python")}
    except Exception:
        return {"data": pd.read_csv(io.BytesIO(raw), header=None)}

def suggest_col(cols, words):
    cols=list(cols)
    for c in cols:
        s=str(c).lower()
        if all(w in s for w in words): return c
    return cols[0] if cols else None

with st.sidebar:
    st.header("1. Carta de superficie")
    uploaded = st.file_uploader("CSV / TXT / XLSX", type=["csv","txt","dat","xlsx","xls"])
    use_demo = st.checkbox("Usar caso de ejemplo incluido", value=uploaded is None)

if uploaded:
    tables=read_uploaded(uploaded.getvalue(), uploaded.name)
elif use_demo:
    demo_path=Path(__file__).parent/"examples"/"surface_card_example.csv"
    tables={"data":pd.read_csv(demo_path)}
else:
    tables={}

if not tables:
    st.info("Carga una carta de superficie o activa el ejemplo.")
    st.stop()

with st.sidebar:
    sheet=st.selectbox("Hoja / tabla", list(tables.keys()))
df=tables[sheet].copy()
df=df.dropna(how="all")

with st.sidebar:
    cols=list(df.columns)
    pos_default=suggest_col(cols,["surface","position"])
    load_default=suggest_col(cols,["surface","load"])
    pos_col=st.selectbox("Columna posición superficie", cols, index=cols.index(pos_default) if pos_default in cols else 0)
    load_col=st.selectbox("Columna carga superficie", cols, index=cols.index(load_default) if load_default in cols else min(1,len(cols)-1))
    pos_unit=st.selectbox("Unidad posición", ["in","m"], index=0)
    load_unit=st.selectbox("Unidad carga", ["kips","lbf","N"], index=0)

pos=pd.to_numeric(df[pos_col],errors="coerce")
load=pd.to_numeric(df[load_col],errors="coerce")
valid=pos.notna() & load.notna()
pos=pos[valid].to_numpy(float); load=load[valid].to_numpy(float)

if len(pos)<4:
    st.error("La carta necesita al menos 4 pares numéricos posición/carga.")
    st.stop()

surface_position_m = pos*IN2M if pos_unit=="in" else pos
if load_unit=="kips": surface_load_n=load*KIP2N
elif load_unit=="lbf": surface_load_n=load*LB2N
else: surface_load_n=load

st.subheader("2. Sarta de varillas")
default_rods=pd.DataFrame({
    "diameter_in":[1.000,0.875,0.750,1.500,0.875],
    "length_ft":[2191,2600,3400,150,750],
    "weight_lb_ft":[np.nan]*5,
    "modulus_psi":[30_000_000.0]*5,
    "coupling_od_in":[np.nan]*5,
    "damping_up_1_s":[np.nan]*5,
    "damping_down_1_s":[np.nan]*5,
})
rod_df=st.data_editor(default_rods, num_rows="dynamic", use_container_width=True, hide_index=True)
rod_df=rod_df.dropna(subset=["diameter_in","length_ft"])
if len(rod_df)==0:
    st.error("Define al menos un tramo de varillas."); st.stop()

c1,c2,c3,c4=st.columns(4)
with c1:
    spm=st.number_input("SPM",min_value=0.01,value=6.642,step=0.1,format="%.4f")
    pump_diam_in=st.number_input("Diámetro de bomba [in]",min_value=0.1,value=1.50,step=0.05)
with c2:
    tubing_id_in=st.number_input("Tubing ID [in]",min_value=0.2,value=2.441,step=0.01)
    fluid_density_lbft3=st.number_input("Densidad fluido [lb/ft³]",min_value=1.0,value=62.4,step=0.5)
with c3:
    viscosity_cp=st.number_input("Viscosidad [cP]",min_value=0.0,value=10.0,step=1.0)
    n_nodes=st.number_input("Nodos espaciales",min_value=10,max_value=800,value=100,step=10)
with c4:
    damping_mode=st.selectbox("Damping",["DigitalModel: estimar automáticamente","Explícito por tramo (1/s)"])
    include_gravity=st.checkbox("Activar términos de desviación/gravedad",value=False)

with st.expander("Opciones avanzadas"):
    a1,a2,a3,a4=st.columns(4)
    friction=a1.number_input("Coef. fricción Coulomb",min_value=0.0,value=0.0,step=0.01)
    smooth_window=a2.number_input("Savitzky–Golay window",min_value=0,value=21,step=2)
    smooth_order=a3.number_input("Orden Savitzky–Golay",min_value=1,value=5,step=1)
    remove_jumps=a4.checkbox("Promediar saltos en interfaces",value=True)
    survey_file=st.file_uploader("Survey opcional CSV/XLSX: MD [ft], inclination [deg], azimuth [deg]",type=["csv","xlsx","xls"],key="survey")

# Construir RodString siguiendo la lógica del adapter de DigitalModel:
# densidad efectiva por weight/ft si existe; si no, 490 lb/ft3.
diam_in=rod_df["diameter_in"].astype(float).to_numpy()
length_ft=rod_df["length_ft"].astype(float).to_numpy()
weight_pf=pd.to_numeric(rod_df.get("weight_lb_ft"),errors="coerce").to_numpy()
modulus_psi=pd.to_numeric(rod_df.get("modulus_psi"),errors="coerce").fillna(30_000_000.0).to_numpy()
coupling_in=pd.to_numeric(rod_df.get("coupling_od_in"),errors="coerce").to_numpy()

density_lbft3=np.full(len(diam_in),490.0)
mask=np.isfinite(weight_pf) & (weight_pf>0)
density_lbft3[mask]=weight_pf[mask]*576.0/(np.pi*diam_in[mask]**2)
coupling_m=np.where(np.isfinite(coupling_in)&(coupling_in>0),coupling_in*IN2M,diam_in*IN2M*1.5)
rods=RodString(
    diameters=diam_in*IN2M,
    lengths=length_ft*FT2M,
    densities=density_lbft3*LBPFT3_TO_KGPM3,
    moduli=modulus_psi*PSI2PA,
    coupling_diameters=coupling_m,
)

survey=None
if survey_file is not None:
    if survey_file.name.lower().endswith((".xlsx",".xls")):
        sdf=pd.read_excel(survey_file)
    else: sdf=pd.read_csv(survey_file)
    if sdf.shape[1] < 3:
        st.error("El survey necesita 3 columnas: MD, inclinación y azimut."); st.stop()
    survey=Survey(
        measured_depth=pd.to_numeric(sdf.iloc[:,0],errors="coerce").dropna().to_numpy()*FT2M,
        inclination=np.deg2rad(pd.to_numeric(sdf.iloc[:,1],errors="coerce").dropna().to_numpy()),
        azimuth=np.deg2rad(pd.to_numeric(sdf.iloc[:,2],errors="coerce").dropna().to_numpy()),
    )

damping=None
if damping_mode.startswith("Explícito"):
    up=pd.to_numeric(rod_df["damping_up_1_s"],errors="coerce").to_numpy()
    dn=pd.to_numeric(rod_df["damping_down_1_s"],errors="coerce").to_numpy()
    if not (np.all(np.isfinite(up)) and np.all(np.isfinite(dn))):
        st.error("En modo explícito, rellena damping_up_1_s y damping_down_1_s para cada tramo."); st.stop()
    damping=np.concatenate([up,dn])

st.subheader("3. Ejecutar")
if st.button("Calcular carta de fondo",type="primary",use_container_width=True):
    try:
        solver=EverittJenningsSolver(
            n_nodes=int(n_nodes), viscosity=viscosity_cp*1e-3,
            friction_coefficient=friction, include_gravity=include_gravity,
            smooth_window=int(smooth_window), smooth_order=int(smooth_order),
            remove_interface_jumps=remove_jumps,
        )
        card=solver.solve(
            position=surface_position_m, load=surface_load_n, rods=rods,
            strokes_per_minute=spm, pump_diameter=pump_diam_in*IN2M,
            tubing_id=tubing_id_in*IN2M,
            fluid_density=fluid_density_lbft3*LBPFT3_TO_KGPM3,
            survey=survey, damping=damping,
        )
        out=pd.DataFrame({
            "point":np.arange(len(card.position)),
            "surface_position_in":surface_position_m*M2IN,
            "surface_load_kips":surface_load_n*N2KIP,
            "downhole_position_in":card.position*M2IN,
            "downhole_load_kips":card.load*N2KIP,
        })
        stroke=float(np.ptp(out.downhole_position_in)); lmin=float(out.downhole_load_kips.min()); lmax=float(out.downhole_load_kips.max())
        m1,m2,m3,m4=st.columns(4)
        m1.metric("Puntos",len(out)); m2.metric("Carrera fondo",f"{stroke:.3f} in")
        m3.metric("Carga mínima",f"{lmin:.3f} kips"); m4.metric("Carga máxima",f"{lmax:.3f} kips")
        fig=go.Figure()
        fig.add_trace(go.Scatter(x=out.downhole_position_in,y=out.downhole_load_kips,mode="lines",name="Carta de fondo"))
        fig.update_layout(xaxis_title="Posición fondo [in]",yaxis_title="Carga fondo [kips]",height=560)
        st.plotly_chart(fig,use_container_width=True)
        with st.expander("Ver puntos calculados"):
            st.dataframe(out,use_container_width=True,height=420)
        summary={
            "solver":"DigitalModel Everitt-Jennings minimal extract",
            "source_commit":COMMIT,"points":len(out),"spm":spm,
            "pump_diameter_in":pump_diam_in,"tubing_id_in":tubing_id_in,
            "fluid_density_lb_ft3":fluid_density_lbft3,"viscosity_cp":viscosity_cp,
            "n_nodes":int(n_nodes),"damping_mode":damping_mode,
            "stroke_in":stroke,"load_min_kips":lmin,"load_max_kips":lmax,
        }
        d1,d2=st.columns(2)
        d1.download_button("Descargar resultados CSV",out.to_csv(index=False).encode(),"downhole_card.csv","text/csv",use_container_width=True)
        d2.download_button("Descargar resumen JSON",json.dumps(summary,indent=2).encode(),"downhole_summary.json","application/json",use_container_width=True)
        # Sanity warnings
        surf_stroke=float(np.ptp(surface_position_m*M2IN))
        if stroke > 2.0*max(surf_stroke,1e-9):
            st.warning("La carrera de fondo supera 2× la carrera superficial. Revisa unidades, sarta, SPM y damping.")
        if not np.all(np.isfinite(card.position)) or not np.all(np.isfinite(card.load)):
            st.error("El solver produjo valores no finitos. Revisa geometría y damping.")
    except Exception as e:
        st.exception(e)

st.divider()
st.caption(f"Núcleo numérico basado en DigitalModel commit {COMMIT}. DigitalModel se distribuye bajo licencia MIT. Esta interfaz no sustituye validación de campo ni criterio de ingeniería.")
