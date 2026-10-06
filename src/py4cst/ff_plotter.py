from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from matplotlib.axes import Axes
from matplotlib.cm import ScalarMappable
from matplotlib.figure import Figure
import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np


DEFAULT_ZOOM = 1.2
DEFAULT_COLORMAP = "turbo"


@dataclass
class PlotBounds:
    left: float
    right: float
    top: float
    bottom: float

    @classmethod
    def from_zoom(cls, zoom: float = DEFAULT_ZOOM) -> PlotBounds:
        margin = zoom - 1.0
        return cls(
            left=-margin,
            right=1.0 + margin,
            top=1.0 + margin,
            bottom=-margin,
        )


class FarFieldPlotter:
    def __init__(
        self,
        *,
        fig: Figure | None = None,
        ax: Axes | None = None,
        colormap: str = DEFAULT_COLORMAP,
        zoom: float = DEFAULT_ZOOM,
    ) -> None:
        self.fig, self.ax = self._resolve_figure_and_axes(fig, ax)
        self.colormap = colormap
        self.bounds = PlotBounds.from_zoom(zoom)

    @staticmethod
    def _resolve_figure_and_axes(
        fig: Figure | None,
        ax: Axes | None,
    ) -> tuple[Figure, Axes]:
        if ax is not None:
            ax_fig = ax.get_figure()

            if fig is not None and ax_fig is not fig:
                raise ValueError(
                    "The provided ax does not belong to the provided fig."
                )

            fig = ax_fig

        elif fig is not None:
            ax = fig.add_subplot(111, projection="3d")

        else:
            fig = plt.figure()
            ax = fig.add_subplot(111, projection="3d")

        if fig is None:
            raise RuntimeError("Could not determine figure from the supplied axes.")

        return fig, ax

    def set_bounding_box(
        self,
        *,
        left: float = 0.0,
        right: float = 1.0,
        top: float = 1.0,
        bottom: float = 0.0,
    ) -> None:
        self.bounds = PlotBounds(
            left=left,
            right=right,
            top=top,
            bottom=bottom,
        )

    def plot_linear(
        self,
        e_mag: np.ndarray,
        theta_deg: np.ndarray,
        phi_deg: np.ndarray,
        *,
        units: str | None = None,
        colormap: str | None = None,
    ) -> Any:
        e_mag = np.asarray(e_mag)
        theta_deg = np.asarray(theta_deg)
        phi_deg = np.asarray(phi_deg)
        e_mag, phi_deg = self._close_phi_seam(e_mag, phi_deg)
        radius = e_mag - np.min(e_mag)

        self._draw_reference_circles()
        self._draw_xyz_axes()

        return self._draw_surface(
            values=e_mag,
            theta_deg=theta_deg,
            phi_deg=phi_deg,
            radius=radius,
            units=units,
            colormap=colormap or self.colormap,
        )

    def plot_log(
        self,
        field: np.ndarray,
        theta_deg: np.ndarray,
        phi_deg: np.ndarray,
        dyn_range: float,
        *,
        units: str | None = None,
        colormap: str | None = None,
    ) -> Any:
        field_db = self._field_to_db(
            np.abs(field),
            dyn_range=dyn_range,
        )

        return self.plot_linear(
            field_db,
            theta_deg,
            phi_deg,
            units=units,
            colormap=colormap,
        )

    def show(self, **kwargs: Any) -> None:
        plt.show(**kwargs)

    def _draw_surface(
        self,
        *,
        values: np.ndarray,
        theta_deg: np.ndarray,
        phi_deg: np.ndarray,
        radius: np.ndarray,
        units: str | None,
        colormap: str,
    ) -> Any:
        phi_grid, theta_grid = np.meshgrid(phi_deg, theta_deg)

        theta_rad = np.deg2rad(theta_grid)
        phi_rad = np.deg2rad(phi_grid)

        radius_max = np.max(radius)
        if radius_max > 0:
            normalized_radius = radius / radius_max
        else:
            normalized_radius = np.zeros_like(radius)

        x, y, z = self._spherical_to_cartesian(
            theta_rad,
            phi_rad,
            normalized_radius,
        )

        surface = self.ax.plot_surface(
            x,
            y,
            z,
            cmap=colormap,
            edgecolor="none",
            rstride=1,
            cstride=1,
            antialiased=True,
            linewidth=0,
            zorder=0.5,
        )

        self.ax.set_aspect("equal")
        self.ax.set_axis_off()
        self.ax.grid(False)

        self.fig.tight_layout()
        self.fig.subplots_adjust(
            left=self.bounds.left,
            right=self.bounds.right,
            top=self.bounds.top,
            bottom=self.bounds.bottom,
        )

        self._add_colorbar(
            values,
            colormap=colormap,
            units=units,
        )

        return surface

    def _add_colorbar(
        self,
        values: np.ndarray,
        *,
        colormap: str,
        units: str | None,
    ) -> None:
        value_min = float(np.min(values))
        value_max = float(np.max(values))

        cmap = plt.get_cmap(colormap, 10)
        norm = mcolors.Normalize(
            vmin=value_min,
            vmax=value_max,
        )

        mappable = ScalarMappable(
            cmap=cmap,
            norm=norm,
        )

        colorbar = self.fig.colorbar(
            mappable=mappable,
            ax=self.ax,
            ticks=np.linspace(value_min, value_max, 10),
            shrink=0.55,
            pad=0.0,
            anchor=(-1.0, 0.5),
        )

        if units is not None:
            colorbar.ax.set_title(units, y=1.02)

    def _draw_reference_circles(
        self,
        radius: float = 1.05,
    ) -> None:
        angles = np.linspace(0.0, 2.0 * np.pi, 360)

        a = radius * np.cos(angles)
        b = radius * np.sin(angles)
        zero = np.zeros_like(angles)

        self.ax.plot(a, b, zero, linewidth=2, color="b", zorder=0)
        self.ax.plot(zero, a, b, linewidth=2, color="r", zorder=0)
        self.ax.plot(b, zero, a, linewidth=2, color="g", zorder=0)

    def _draw_xyz_axes(
        self,
        radius: float = 1.2,
    ) -> None:
        self.ax.plot(
            [0, radius],
            [0, 0],
            [0, 0],
            color="r",
            linewidth=1.5,
            zorder=0,
        )
        self.ax.plot(
            [0, 0],
            [0, radius],
            [0, 0],
            color="g",
            linewidth=1.5,
            zorder=0,
        )
        self.ax.plot(
            [0, 0],
            [0, 0],
            [0, radius],
            color="b",
            linewidth=1.5,
            zorder=0,
        )

        self.ax.text(
            1.1 * radius,
            0,
            0,
            "x",
            weight="bold",
            color="k",
        )
        self.ax.text(
            0,
            1.05 * radius,
            0,
            "y",
            weight="bold",
            color="k",
        )
        self.ax.text(
            0,
            0,
            1.05 * radius,
            "z",
            weight="bold",
            color="k",
        )

    @staticmethod
    def _close_phi_seam(
        values: np.ndarray,
        phi_deg: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray]:
        values_closed = np.concatenate(
            (values, values[:, :1]),
            axis=1,
        )

        phi_closed = np.concatenate(
            (phi_deg, [360.0]),
        )

        return values_closed, phi_closed

    @staticmethod
    def _spherical_to_cartesian(
        theta_rad: np.ndarray,
        phi_rad: np.ndarray,
        radius: np.ndarray,
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        x = radius * np.sin(theta_rad) * np.cos(phi_rad)
        y = radius * np.sin(theta_rad) * np.sin(phi_rad)
        z = radius * np.cos(theta_rad)

        return x, y, z

    @staticmethod
    def _field_to_db(
        field: np.ndarray,
        dyn_range: float,
        *,
        floor: float = 1e-7,
    ) -> np.ndarray:
        if dyn_range <= 0:
            raise ValueError("dyn_range must be greater than zero.")

        field = np.maximum(field, floor)
        field_db = 20.0 * np.log10(field)

        threshold = np.max(field_db) - dyn_range

        return np.maximum(field_db, threshold)
