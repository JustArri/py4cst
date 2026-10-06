from py4cst.cst import Interface, Results
from py4cst.results import SMatrices
import matplotlib.pyplot as plt
import numpy as np

ifc = Interface(start_mode=Interface.StartMode.ExistingOrNew)
proj = ifc.get_active_project()
results = Results(proj.get_file_name())

# We will export matrices of S11, S12, S21 and S22 parameters as a numpy array
#  -> we need to specify the number of S-parameters (= 2)
s_mat_exporter = SMatrices(results, 2)

# We can also specify tree_item_name lambda to generate custom tree item names:
# s_mat_exporter = SMatrices(results, 2, tree_item_name=lambda a, b: f'S{a},{b}')

f = s_mat_exporter.get_frequencies()
s_mat = s_mat_exporter.get_matrices()

# Be aware the indices in the resulting matrices start from 0, not 1 !
s11 = s_mat[0, 0, :]
s12 = s_mat[0, 1, :]
s21 = s_mat[1, 0, :]
s22 = s_mat[1, 1, :]

plt.plot(f, 20*np.log10(np.abs(s11)))
plt.plot(f, 20*np.log10(np.abs(s12)))
plt.plot(f, 20*np.log10(np.abs(s21)))
plt.plot(f, 20*np.log10(np.abs(s22)))
plt.legend(['S11', 'S12', 'S21', 'S22'])
plt.ylabel('S-Parameter (dB)')
plt.xlabel('Frequency (GHz)')
plt.show()
