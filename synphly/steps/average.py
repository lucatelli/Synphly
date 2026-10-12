"""
Time/channel averaging before calibration (ported from v0.5 ``helper_functions.average_ms``).
"""
from __future__ import annotations

import logging
import os
import shutil

import numpy as np

from ..casa import listobs, mstransform, open_msmd

log = logging.getLogger(__name__)


def average_ms(ctx, vis, time_avg=True, channel_avg=False,
               usewtspectrum=False, regridms=False):
    """
    Average ``vis`` in time (cfg.average.timebin_avg) and/or channels (cfg.average.chan_out_avg
    output channels per spw) into ``<vis>.avg.ms``. Returns the averaged MS path.
    """
    timebin_avg = ctx.cfg.average.timebin_avg
    chan_out_avg = ctx.cfg.average.chan_out_avg

    vis_for_cal_avg = vis.replace('.ms', '.avg.ms')
    vis_avg_time_temp = None
    vis_avg_chan_temp = None
    if not os.path.exists(vis_for_cal_avg):
        if time_avg:
            vis_avg_time_temp = vis.replace('.ms', '.avgtime_temp.ms')
            log.info(f" ++==>> Averaging data to {timebin_avg} before calibration.")
            mstransform(vis=vis,
                        outputvis=vis_avg_time_temp,
                        datacolumn='data', correlation='RR,LL',
                        keepflags=True,
                        usewtspectrum=usewtspectrum,
                        regridms=regridms,
                        timeaverage=True,
                        timebin=timebin_avg)
        if channel_avg:
            vis_avg_chan_temp = vis.replace('.ms', '.avgchan_temp.ms')
            vis_temp = vis_avg_time_temp if time_avg else vis
            log.info(f" ++==>> Averaging data in frequency to {chan_out_avg} "
                     f"channels before calibration.")
            with open_msmd(vis_temp) as msmd:
                bandwidth = msmd.bandwidths()
                nspw = len(bandwidth)
                chan_freqs_all = np.empty(nspw, dtype=object)
                spws_freq = np.zeros(nspw)
                for nch in range(nspw):
                    chan_freqs_all[nch] = msmd.chanfreqs(nch)
                    spws_freq[nch] = np.nanmean(chan_freqs_all[nch])
            shapes = np.asarray([arr.shape[0] for arr in chan_freqs_all])
            chan_width_avg = list((shapes / chan_out_avg).astype(int))

            mstransform(vis=vis_temp,
                        outputvis=vis_avg_chan_temp,
                        datacolumn='data', correlation='RR,LL',
                        keepflags=True,
                        usewtspectrum=usewtspectrum,
                        regridms=regridms,
                        chanaverage=True,
                        chanbin=chan_width_avg)
        if time_avg and channel_avg:
            log.info(f" ++==>> Data averaged to {timebin_avg} and {chan_out_avg} "
                     f"output channels.")
            shutil.move(vis_avg_chan_temp, vis_for_cal_avg)
            shutil.rmtree(vis_avg_time_temp)
        if time_avg and not channel_avg:
            log.info(f" ++==>> Data averaged to {timebin_avg} seconds.")
            shutil.move(vis_avg_time_temp, vis_for_cal_avg)
        if not time_avg and channel_avg:
            log.info(f" ++==>> Data averaged to {chan_out_avg} output channels.")
            shutil.move(vis_avg_chan_temp, vis_for_cal_avg)
    else:
        log.info(f" --==>> Averaged ms {vis_for_cal_avg} already exists.")
    listfile_avg = vis_for_cal_avg.replace(".ms", "_listobs.txt")
    log.info(f" ++==>> Generating listobs file from averaged data: {listfile_avg}")
    listobs(vis=vis_for_cal_avg, listfile=listfile_avg, overwrite=True)
    return vis_for_cal_avg


def average(ctx):
    """The v0.5 main.py ``do_average`` block: reuse ``<vis_for_cal>.avg.ms`` if it exists."""
    vis_for_cal_avg = ctx.vis_for_cal.replace('.ms', '.avg.ms')
    if not os.path.exists(vis_for_cal_avg):
        vis_for_cal_avg = average_ms(ctx, vis=ctx.vis_for_cal,
                                     time_avg=ctx.cfg.average.time_avg,
                                     channel_avg=ctx.cfg.average.channel_avg)
    else:
        log.info(f" --==>> Averaged ms {vis_for_cal_avg} already exists.")
    ctx.vis_for_cal = vis_for_cal_avg
    return vis_for_cal_avg
