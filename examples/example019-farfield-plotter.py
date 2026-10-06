from py4cst.cst import Interface
from py4cst.cst.wrappers import FarfieldPlot
from py4cst.results import ASCIIFarfieldExporter
from py4cst.ff_plotter import FarFieldPlotter
from py4cst import farfield_utils

ifc = Interface(start_mode=Interface.StartMode.ExistingOrNew)
proj = ifc.get_active_project()

ffexp = ASCIIFarfieldExporter()
ffexp.set_plot_mode(FarfieldPlot.PlotMode.EFIELD)
farfield_name = 'farfield (f=f0) [1]'
ffexp.prepare(proj, farfield_name)

ff = ffexp.get_abs()
theta = farfield_utils.get_theta_vec_deg(ff)
phi = farfield_utils.get_phi_vec_deg(ff)

plotter = FarFieldPlotter()
plotter.plot_log(ff, theta, phi, dyn_range=40.0, units='dB(V/m)')
plotter.show()
