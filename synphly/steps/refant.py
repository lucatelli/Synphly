"""
Reference antenna selection (ported from v0.5 ``helper_functions.find_refant``).
"""
from __future__ import annotations

import logging

import numpy as np

from ..calib import tables as reg
from ..casa import gaincal, open_table
from . import _plots

log = logging.getLogger(__name__)


def find_refant(ctx, msfile, field, tablename):
    """
    This function comes from the e-MERLIN CASA Pipeline.
    https://github.com/e-merlin/eMERLIN_CASA_pipeline/blob/master/functions/eMCP_functions.py#L1501

    It finds the best reference antenna for calibration: solve per-scan phases on ``field`` and sort the
    antennas by their fraction of unflagged solutions. Returns a comma-separated antenna list.
    """
    # Find phase solutions per scan (reuse follows cfg.pipeline.reuse_tables):
    kw = dict(vis=msfile, caltable=tablename, field=field, refantmode='flex', solint='inf', minblperant=3,
              gaintype='G', calmode='p')
    rec = reg.new_record(ctx, tablename, 'refant', dict(task='gaincal', **{k: v for k, v in kw.items()
                                                                           if k != 'caltable'}),
                         stage='find_refant', solint='inf', fields=field, vis=msfile)
    if not reg.prepare(ctx, rec):
        gaincal(**kw)
    reg.check_solutions(ctx, rec)
    reg.write_record(ctx, rec)

    _plots.snr(ctx, tablename, cut_off=3.0)

    with open_table(tablename + '/ANTENNA') as tb:
        antenna_names = tb.getcol('NAME')
    with open_table(tablename) as tb:
        antenna_ids = tb.getcol('ANTENNA1')
        flags = tb.getcol('FLAG')
        snrs = tb.getcol('SNR')
    # Analyse number of good solutions:
    good_frac = []
    good_snrs = []
    for i, ant_id in enumerate(np.unique(antenna_ids)):
        cond = antenna_ids == ant_id
        f = flags[0, 0, :][cond]
        snr = snrs[0, 0, :][cond]
        frac = 1.0 * np.count_nonzero(~f) / len(f) * 100.
        snr_mean = np.nanmean(snr[~f])
        good_frac.append(frac)
        good_snrs.append(snr_mean)
    sort_idx = np.argsort(good_frac)[::-1]
    log.info(' ++==>> Antennas sorted by % of good solutions:')
    for i in sort_idx:
        log.info(' ++==>> {0:3}: {1:4.1f}, <SNR> = {2:4.1f}'.format(antenna_names[i],
                                                                good_frac[i],
                                                                good_snrs[i]))
    if good_frac[sort_idx[0]] < 90:
        log.info(' ++==>> Small fraction of good solutions with selected refant!')
        log.info(' ++==>> Please inspect antennas to select optimal refant')
        log.info(' ++==>> You may want to use refantmode="flex" in gaincal')
    pref_ant = antenna_names[sort_idx]
    pref_ant_list = ','.join(list(pref_ant))
    return pref_ant_list


def select_refant(ctx):
    """
    The v0.5 main.py ``do_refant`` block. ``cfg.calibrate.refant`` 'None' (or empty) -> automatic
    selection with find_refant; otherwise the configured list is used.
    Fixes 03 bug 1 (v0.5 left ``refant`` undefined when a refant was configured).
    """
    _refant = ctx.cfg.calibrate.refant
    refant = None if _refant in ('None', '') else _refant
    log.info("Selecting ref antenna.")
    if refant is None:
        log.info("No refant specified. Finding refant by fraction of good solutions.")
        tablename_refant = f"{ctx.paths.calibration}/find_refant.phase"
        ref_antenna = find_refant(ctx, msfile=ctx.vis_for_cal, field=ctx.calibrators_all,
                                  tablename=tablename_refant)
    else:
        log.info("Using refant specified in the config file.")
        ref_antenna = refant
    ctx.ref_antenna = ref_antenna
    ctx.ref_antenna_list = ref_antenna.split(',')
    log.info(f"Reference antenna(s): {ref_antenna}")
    return ref_antenna
