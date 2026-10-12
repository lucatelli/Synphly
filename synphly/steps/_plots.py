"""
Optional plotting calls made by the steps.

Every function here respects the ``[plotting]`` switches, imports ``synphly.plotting`` lazily, and never
raises: a failed plot logs a warning and the pipeline continues.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def _backend(ctx) -> str:
    return getattr(ctx.cfg.plotting, 'plot_backend', 'python')


def _enabled(ctx, switch: str = '') -> bool:
    if _backend(ctx) == 'none':
        return False
    if switch:
        return bool(getattr(ctx.cfg.plotting, switch, True))
    return True


def caltable(ctx, table, table_type, xaxis='time', yaxis='phase', fields='', stage='calibration'):
    """Replacement of the v0.5 ``calibration_table_plot`` call sites (same table_type/xaxis/yaxis)."""
    if not _enabled(ctx, 'plot_caltables'):
        return
    try:
        from ..plotting.caltables import calibration_table_plot
        calibration_table_plot(table, ctx.paths.plots, stage=stage, table_type=table_type,
                               xaxis=xaxis, yaxis=yaxis, fields=fields,
                               minsnr=ctx.cfg.calibrate.minsnr, backend=_backend(ctx))
    except Exception as e:
        log.warning(f" --==>> Could not plot table {table} ({xaxis} vs {yaxis}): {e}")


def snr(ctx, caltable_path, cut_off=3.0):
    if not _enabled(ctx, 'plot_caltables'):
        return
    try:
        from ..plotting.caltables import make_plot_snr
        make_plot_snr(caltable_path, cut_off=cut_off)
    except Exception as e:
        log.warning(f" --==>> Error plotting SNR for table {caltable_path}: {e}")


def plot_fields(ctx, ids):
    """
    FIELDS labels for ``make_plots_stages_py`` from a list of field ID strings.

    The plotting module uses the label both as the field selection and in the file name
    (``..._field_{label}_{kind}.jpg``). v0.5 passed field NAMES, so the label is the field name whenever
    that is safe: the plotting resolver matches a name exactly first, so a name that belongs to a single
    field ID selects exactly that ID. A name shared by several IDs (e.g. a dropped pointing/system-config
    duplicate) would re-select the dropped IDs; for those the ID string is passed instead (file name
    ``field_<ID>``) so that the plot shows only the field that was calibrated.
    """
    from .ms_info import field_model
    try:
        fm = field_model(ctx)
    except RuntimeError:
        return [str(i) for i in ids]
    dup = fm.duplicates()
    out = []
    for i in ids:
        name = fm.records[int(i)].name
        out.append(str(i) if name in dup else name)
    return out


def visibilities(ctx, vis, stage, kind, FIELDS, extra_plot=True):
    if not _enabled(ctx, 'plot_visibilities'):
        return
    try:
        from ..plotting.visibilities import make_plots_stages_py
        make_plots_stages_py(vis=vis, stage=stage, kind=kind, FIELDS=FIELDS,
                             working_directory=ctx.paths.working_directory,
                             extra_plot=extra_plot)
    except Exception as e:
        log.warning(f" --==>> Visibility plots '{kind}' failed: {e}")


def flag_stats(ctx):
    if not _enabled(ctx, 'plot_flag_stats'):
        return
    try:
        from ..plotting.flags import plot_flag_stats
        plot_flag_stats(ctx.flag_data_steps, ctx.paths.plots)
    except Exception as e:
        log.warning(f" --==>> Flag statistics plot failed: {e}")


def setjy_model(ctx, freqs_ghz, fluxes_jy, source_name, outfile):
    if not _enabled(ctx):
        return
    try:
        from ..plotting.fluxes import plot_setjy_model
        log.info("Plotting the fluxes against frequency.")
        plot_setjy_model(freqs_ghz, fluxes_jy, source_name, outfile)
    except Exception as e:
        log.warning(f"Flux plot not generated due to: {e}")


def bootstrap_fluxes(ctx, fluxdict, field_names_by_id, outfile, spw_freqs_hz=None):
    if not _enabled(ctx):
        return
    try:
        from ..plotting.fluxes import plot_bootstrap_fluxes
        log.info("Plotting the bootstrap fluxes against frequency.")
        if spw_freqs_hz is None:
            plot_bootstrap_fluxes(fluxdict, field_names_by_id, outfile)
        else:
            plot_bootstrap_fluxes(fluxdict, field_names_by_id, outfile, spw_freqs_hz=spw_freqs_hz)
    except Exception as e:
        log.warning(f"Flux plot not generated due to: {e}")


def plotants(ctx, vis, logpos, figfile):
    """casatasks.plotants (antenna layout), as called in v0.5 pre_flagging."""
    if not _enabled(ctx):
        return
    try:
        from ..casa import plotants as _plotants
        _plotants(vis=vis, logpos=logpos, figfile=figfile)
    except Exception as e:
        log.warning(f" --==>> plotants failed: {e}")
