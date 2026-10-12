"""
Working directory setup and data import (ported from v0.5 ``helper_functions.py``:
set_working_dir, import_data).
"""
from __future__ import annotations

import logging
import os
import time

from ..casa import hanningsmooth, importasdm, open_ms

log = logging.getLogger(__name__)


def set_working_dir(ctx):
    """Create the working directory and its flags/, calibration/ and plots/ sub-directories."""
    working_directory = ctx.paths.working_directory
    if not os.path.exists(working_directory):
        log.info(f"{working_directory} does not exist, making one")
        os.makedirs(working_directory)
    else:
        log.info(f"Working directory {working_directory} already exists")

    for folder in [ctx.paths.flags, ctx.paths.calibration, ctx.paths.plots]:
        if not os.path.exists(folder):
            log.info(f"Dir {folder} does not exist. Will create one")
            os.makedirs(folder)
        else:
            log.info(f"Dir {folder} exists. Will not create one")


def import_data(ctx):
    """
    Make the measurement set from the SDM (if it does not exist), optionally Hanning-smooth it, and
    write the listobs file. Returns the MS to calibrate (``vis`` or ``<vis>_hs.ms``).
    Raises if importasdm or hanningsmooth fails (v0.5 logged and continued; 03 bug 11).
    """
    vis = ctx.vis
    asdm_file = ctx.cfg.globals.asdm_file
    importasdm_starttime = time.time()
    if not os.path.exists(vis):
        try:
            log.info(f"Making {vis}")
            importasdm(asdm=asdm_file, vis=vis,
                       process_syspower=True, process_caldevice=True, process_pointing=True,
                       process_flags=True, applyflags=True, savecmds=True, flagbackup=True,
                       verbose=True, with_pointing_correction=True,
                       outfile=vis.replace('.ms', '.flagonline.txt'))
        except Exception as e:
            log.critical(f"{vis} not made due to error:{e}")
            raise
    else:
        log.info(f"{vis} exists, will not make a new one")

    if ctx.cfg.globals.do_hanning:
        vis_hs = vis.replace('.ms', '_hs.ms')
        if not os.path.exists(vis_hs):
            try:
                log.info(f"Running Hanning smoothing on {vis}")
                hanningsmooth(vis=vis, outputvis=vis_hs)
                log.info(f"Hanning smoothing done on {vis}")
                log.info("Setting to vis file to Hanning smoothed version [*_hs.ms]")
                vis_for_cal = vis_hs
            except Exception as e:
                log.critical(f"Error {e} occurred when running hanningsmooth.")
                raise
        else:
            log.info(f"{vis_hs} exists. Will not run hanningsmooth")
            vis_for_cal = vis_hs
    else:
        vis_for_cal = vis

    # Writes the verbose output of listobs
    listfile = vis_for_cal.replace(".ms", "_listobs.txt")
    if os.path.exists(listfile):
        log.info(f"Listobs file {listfile} exists")
    else:
        try:
            log.info(f"Making {listfile}")
            with open_ms(vis_for_cal) as ms:
                ms.summary(verbose=True, listfile=listfile)
            if os.path.isfile(listfile):
                log.info("A file containing listobs output is saved.")
            else:
                log.info("The listobs output was not saved in a .list file. Please check the CASA log.")
        except Exception as e:     # the listobs text file is informational only
            log.warning(f"Error {e} occurred when making the listobs file {listfile} (not needed by the run)")

    importasdm_endtime = time.time()
    log.info(f"Exec time for data handle/conversion took "
             f"{(importasdm_endtime - importasdm_starttime) / 60:.2f} minutes")
    return vis_for_cal
