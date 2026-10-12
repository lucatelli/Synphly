"""
Visibility re-weighting with statwt (the v0.5 main.py ``do_run_statwt`` block).
"""
from __future__ import annotations

import logging

from ..casa import statwt

log = logging.getLogger(__name__)


def run_statwt(ctx, vis):
    timebin = ctx.cfg.calibrate.statwt_timebin
    statalg = ctx.cfg.calibrate.statwt_statalg
    log.info(" ++==> Running statwt on calibrated data.")
    log.info(f"     - timebin: {timebin}.")
    log.info(f"     - statalg: {statalg}.")
    statwt(vis=vis, preview=False,
           datacolumn='corrected',
           timebin=timebin, statalg=statalg)
