"""
A-priori calibration tables: antenna positions, gain curve, opacity (ported from v0.5
``calibrate.initial_corrections``). Requantiser (rq) and switched power (swpow) stay off, as in v0.5.
"""
from __future__ import annotations

import logging
import os
import shutil
import time

from ..calib import tables as reg
from ..casa import gencal, open_msmd, plotweather

log = logging.getLogger(__name__)


def _gencal(ctx, vis, caltable, stage, **kw):
    """gencal through the table registry (reuse policy cfg.pipeline.reuse_tables). gencal does not depend on
    the flags, so the input hash has no flag fingerprint."""
    params = dict(task='gencal', vis=vis, **kw)
    rec = reg.new_record(ctx, caltable, 'init', params, stage=stage, vis=vis, flag_fp='')
    if not reg.prepare(ctx, rec):
        gencal(vis=vis, caltable=caltable, **kw)
    if os.path.exists(caltable):
        reg.write_record(ctx, rec)


def _require_table(caltable, what):
    if not os.path.exists(caltable):
        raise RuntimeError(f"gencal did not produce the {what} table {caltable}")


def initial_corrections(ctx, vis):
    """Returns (init_tables, init_tables_dict). Table reuse follows cfg.pipeline.reuse_tables (v0.5: reuse
    whenever the file exists)."""
    initial_corrections_starttime = time.time()

    calibration_dir = ctx.paths.calibration
    plots_dir = ctx.paths.plots

    if not os.path.exists(calibration_dir):
        log.warning("Calibration dir must be specified")

    init_tables = []
    init_tables_dict = {}

    # antenna positions (appended only if gencal produced a table)
    caltable = f"{calibration_dir}/{os.path.basename(vis.replace('.ms', '_antpos.tb'))}"
    # Optional (as v0.5): gencal produces no table when there are no corrections, and it needs the online
    # antenna-position database. A failure is a warning in the run report, not an error.
    try:
        log.info("Generating cal solutions for antenna positions")
        _gencal(ctx, vis, caltable, 'antpos', caltype='antpos')
        if os.path.exists(caltable):
            init_tables.append(caltable)
            init_tables_dict['antpos'] = caltable
        else:
            log.info("No antenna position corrections (gencal produced no table).")
    except Exception as e:
        msg = f"Antenna position corrections not applied: gencal(caltype='antpos') failed ({e})."
        log.warning(msg)
        ctx.warnings.append(msg)

    # gain curves (required: a failure stops the step; v0.5 logged it and calibrated without the gain curve)
    caltable = f"{calibration_dir}/{os.path.basename(vis.replace('.ms', '_gaincurve.tb'))}"
    log.info("Generating cal solutions for gaincurves")
    try:
        _gencal(ctx, vis, caltable, 'gaincurve', caltype='gc')
        _require_table(caltable, 'gaincurve')
    except Exception as e:
        log.critical(f"Exception {e} while generating {caltable}")
        raise
    init_tables.append(caltable)
    init_tables_dict['gaincurve'] = caltable

    # NB: Implement tec corrections -- for low frequencies
    with open_msmd(vis) as msmd:
        bandwidth = msmd.bandwidths()
        nspw = len(bandwidth)
    spws = []
    for i in range(0, nspw):
        spws.append(str(i))
    all_spw = ', '.join(spws)

    # opacities (required: a failure stops the step; v0.5 logged it and calibrated without the opacity table)
    log.info("Generating cal tables for opacities")
    weather_plot = vis + '_weather.pdf'
    try:
        myTau = plotweather(vis=vis, seasonal_weight=0.5, doPlot=True, plotName=weather_plot)
    except Exception as e:
        log.critical(f"Exception {e} while running plotweather")
        raise
    # v0.5: os.system(f'mv {weather_plot} {plots_dir}') (a failure never stopped the step)
    try:
        if os.path.exists(weather_plot):
            shutil.move(weather_plot, os.path.join(plots_dir, os.path.basename(weather_plot)))
    except OSError as e:
        log.warning(f"Could not move {weather_plot} to {plots_dir}: {e}")
    caltable = f"{calibration_dir}/{os.path.basename(vis.replace('.ms', '_opacity.tb'))}"
    log.info(f"Generating weather caltable {caltable}")
    try:
        _gencal(ctx, vis, caltable, 'opacity', caltype='opac', spw=all_spw, parameter=myTau)
        _require_table(caltable, 'opacity')
    except Exception as e:
        log.critical(f"Exception {e} while generating cal for opacity")
        raise
    init_tables.append(caltable)
    init_tables_dict['opacity'] = caltable

    initial_corrections_time = time.time() - initial_corrections_starttime
    log.info(f"Initial calibrations took {initial_corrections_time / 60:.2f} minutes")
    return init_tables, init_tables_dict
