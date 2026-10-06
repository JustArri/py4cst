from ..cst import Results
from . import SParameter
import numpy as np
from typing import Optional
from collections.abc import Callable

class SMatrices:
    def __init__(
        self,
        results: Results,
        num_ports: int,
        tree_item_name: Optional[Callable[[float, float], str]] = None
    ) -> None:
        self.s_param = SParameter(results)
        self.num_ports = num_ports
        self.tree_item_name = tree_item_name

    def get_num_samples(self, run_id: int = 0) -> int:
        if self.tree_item_name is None:
            self.s_param.select_by_indices((1,1), run_id)
        else:
            self.s_param.select_by_name(self.tree_item_name(1, 1))
        return self.s_param.get_num_samples()

    def get_frequencies(self, run_id: int = 0) -> list[float]:
        if self.tree_item_name is None:
            self.s_param.select_by_indices((1,1), run_id)
        else:
            self.s_param.select_by_name(self.tree_item_name(1, 1))
        return self.s_param.get_frequencies()

    def get_matrices(self, run_id: int = 0):
        num_samples = self.get_num_samples(run_id)
        s_mat = np.zeros((self.num_ports, self.num_ports, num_samples), dtype=complex)
        for j in range(1,self.num_ports+1):
            for i in range(1,self.num_ports+1):
                if self.tree_item_name is None:
                    self.s_param.select_by_indices((j,i), run_id)
                else:
                    self.s_param.select_by_name(self.tree_item_name(j,i))
                s_mat[j-1, i-1] = self.s_param.get_values()
        return s_mat
