"""
synphly.plotting: pure-python (matplotlib, Agg) diagnostic plots.

Submodules import casatools lazily, so ``import synphly.plotting`` works
without CASA.

  visibilities  make_plots_stages_py, plot_uvwave, plot_uv_coverage
  caltables     calibration_table_plot, make_plot_snr, read_caltable,
                detect_table_type
  flags         plot_flag_stats, calculate_percentages, plot_category_data
  fluxes        plot_setjy_model, plot_bootstrap_fluxes, spw_fluxes_from_dict
  plotants      plotants
"""

from .visibilities import make_plots_stages_py, plot_uvwave, plot_uv_coverage
from .caltables import (calibration_table_plot, make_plot_snr, read_caltable,
                        detect_table_type)
from .flags import plot_flag_stats, calculate_percentages, plot_category_data
from .fluxes import plot_setjy_model, plot_bootstrap_fluxes, spw_fluxes_from_dict
from .plotants import plotants

__all__ = [
    'make_plots_stages_py', 'plot_uvwave', 'plot_uv_coverage',
    'calibration_table_plot', 'make_plot_snr', 'read_caltable', 'detect_table_type',
    'plot_flag_stats', 'calculate_percentages', 'plot_category_data',
    'plot_setjy_model', 'plot_bootstrap_fluxes', 'spw_fluxes_from_dict',
    'plotants',
]
