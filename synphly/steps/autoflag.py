"""
Automatic flagging of calibrated data (clip, rflag, tfcrop) and flag reporting.

Ported from v0.5 ``flagging.py`` (clip_data, run_rflag, apply_tfcrop, report_flag).
"""
from __future__ import annotations

import logging
import os

from ..casa import flagdata, flagmanager

log = logging.getLogger(__name__)


def report_flag(summary, axis):
    log.info("  ++==>> Reporting flag statistics.")
    try:
        for id, stats in summary[axis].items():
            log.info('%s %s: %5.1f percent flagged' % (
                axis, id, 100. * stats['flagged'] / stats['total']))
    except Exception as e:
        log.info(f"Exception {e} while reporting flags")


def record_flags(ctx, key, summary):
    """Store a flagdata summary in ``ctx.flag_data_steps[key]`` (as v0.5) and the per-field fractions
    in ``ctx.flag_fractions[key]`` (persisted)."""
    ctx.flag_data_steps[key] = summary.copy()
    try:
        ctx.flag_fractions[key] = {f: (s['flagged'] / s['total'] if s['total'] else 0.0)
                                   for f, s in summary.get('field', {}).items()}
    except (AttributeError, KeyError, TypeError) as e:
        log.debug(f"Could not compute the flag fractions for {key}: {e}")


def clip_data(ctx, vis, field,
              datacolumn='data', clipminmax=(0, 20),
              i=1):
    log.info(" ++==>> Flagging the data with clip mode...")
    log.info(f"        Clipping data in the range {clipminmax}")
    log.info(f" ++==>> Fields to be flagged: {field}")
    flagdata(vis=vis, mode='clip', field=field, spw='',
             datacolumn=datacolumn, clipzeros=True, clipoutside=True,
             extendflags=False,
             clipminmax=list(clipminmax),
             action='apply', flagbackup=False, savepars=False)
    flagdata(vis=vis, mode='extend', field=field, spw='',
             action='apply', datacolumn=datacolumn,
             combinescans=False, flagbackup=False,
             growtime=75.0, growfreq=75.0, extendpols=True)
    summary_after_clip_corrected = flagdata(vis=vis, mode='summary')
    record_flags(ctx, f'clip_corrected_{i}', summary_after_clip_corrected)


def run_rflag(ctx, vis, field, datacolumn_to_flag='corrected',
              timedevscale=4.0, freqdevscale=5.0,
              versionname='applycal_before_rflag',
              i=1):
    log.info("Running rflag")

    if os.path.exists(f"{vis}.flagversions/flags.{versionname}/"):
        log.info(f" --==>> Restoring flags from {vis}.flagversions/flags.{versionname}/")
        flagmanager(vis=vis, mode='restore', versionname=versionname)
    else:
        log.info('    ** Creating flag backup before rflag...')
        flagmanager(vis=vis, mode='save',
                    versionname=versionname,
                    comment='Applycal before rflag.')

    summary_before_rflag = flagdata(vis=vis, mode='summary')
    report_flag(summary_before_rflag, 'field')

    try:
        log.info(f" ++==>> Flagging column {datacolumn_to_flag}")
        flagdata(vis=vis, mode='rflag', field=field, spw='', display='report',
                 datacolumn=datacolumn_to_flag, ntime='scan', combinescans=False,
                 extendflags=False, winsize=5, maxnpieces=5,
                 timedevscale=timedevscale, freqdevscale=freqdevscale,
                 flagnearfreq=False, flagneartime=False, growaround=False,
                 action='apply', flagbackup=False, savepars=True
                 )

        flagdata(vis=vis, field=field, spw='',
                 datacolumn=datacolumn_to_flag, ntime='scan',
                 mode='extend', action='apply', display='report',
                 flagbackup=False, growtime=80.0,
                 growfreq=80.0, extendpols=True)
    except Exception as e:
        # (v0.5 logged this and continued, leaving the data unflagged without any other sign)
        log.error(f"Exception {e} occurred while running flagdata (rflag) on field(s) {field} of {vis}")
        raise

    summary_after_rflag = flagdata(vis=vis, mode='summary')
    record_flags(ctx, f'cal_rflag_{i}', summary_after_rflag)
    report_flag(summary_after_rflag, 'field')


def apply_tfcrop(ctx, vis, field, datacolumn_to_flag='corrected',
                 winsize=5, maxnpieces=5,
                 timecutoff=4.0, freqcutoff=4.0,
                 versionname='applycal_before_tfcrop',
                 i=1):
    log.info("  ++==>> Applying tfcrop...")
    log.info(f"  ++==>> Using {datacolumn_to_flag} column for flagging")
    log.info("  ++==>> Creating flag backup before tfcrop...")

    if os.path.exists(f"{vis}.flagversions/flags.{versionname}/"):
        log.info(f" --==>> Restoring flags from {vis}.flagversions/flags.{versionname}/")
        flagmanager(vis=vis, mode='restore', versionname=versionname)
    else:
        log.info(' ++==>> Creating flag backup before tfcrop...')
        flagmanager(vis=vis, mode='save',
                    versionname=versionname,
                    comment='Applycal before tfcrop.')

    summary_before_tfcrop = flagdata(vis=vis, mode='summary')
    report_flag(summary_before_tfcrop, 'field')

    if datacolumn_to_flag == 'residual' or datacolumn_to_flag == 'RESIDUAL':
        log.info(" ++==>> The residual column is selected for flagging. Setting freqfit to line.")
        freqfit = 'line'
    else:
        freqfit = 'poly'

    flagdata(vis=vis, mode='tfcrop', field=field, spw='',
             datacolumn=datacolumn_to_flag, ntime='scan', combinescans=False,
             extendflags=False, winsize=winsize, maxnpieces=maxnpieces,
             flagnearfreq=False,
             flagneartime=False, growaround=True,
             timecutoff=timecutoff, freqcutoff=freqcutoff,
             freqfit=freqfit,
             action='apply', flagbackup=False, savepars=False,
             )
    log.info('  ++==>> Extending flags from tfcrop...')
    flagdata(vis=vis, field=field, spw='',
             datacolumn=datacolumn_to_flag, ntime='scan',
             mode='extend', action='apply', display='report',
             flagbackup=False, growtime=80.0, growaround=True,
             growfreq=80.0, extendpols=False)

    summary_after_tfcrop = flagdata(vis=vis, mode='summary')
    record_flags(ctx, f'cal_tfcrop_{i}', summary_after_tfcrop)
    report_flag(summary_after_tfcrop, 'field')


def flag_calibrators(ctx, i):
    """The v0.5 main.py block run after cal_phases_amplitudes(i): tfcrop or rflag on the calibrators."""
    cfg = ctx.cfg.flagging
    if cfg.cals_flag_mode_strategy == 'tfcrop':
        apply_tfcrop(ctx, vis=ctx.vis_for_cal, field=ctx.calibrators_all,
                     datacolumn_to_flag=cfg.cals_datacolumn_to_flag,
                     timecutoff=cfg.tfcrop_timecutoff_cals,
                     freqcutoff=cfg.tfcrop_freqcutoff_cals,
                     versionname=f'tfcrop_gains_apply_{i}',
                     i=i)
    if cfg.cals_flag_mode_strategy == 'rflag':
        run_rflag(ctx, vis=ctx.vis_for_cal, field=ctx.calibrators_all,
                  datacolumn_to_flag=cfg.cals_datacolumn_to_flag,
                  timedevscale=cfg.rflag_timedevscale_cals,
                  freqdevscale=cfg.rflag_freqdevscale_cals,
                  versionname=f'rflag_gains_apply_{i}',
                  i=i)


def flag_science(ctx):
    """The v0.5 main.py ``do_flag_science`` block (flagging part): tfcrop or rflag on the targets."""
    cfg = ctx.cfg.flagging
    if cfg.science_flag_mode_strategy == 'tfcrop':
        apply_tfcrop(ctx, vis=ctx.vis_for_cal, field=ctx.target,
                     datacolumn_to_flag=cfg.science_datacolumn_to_flag,
                     timecutoff=cfg.tfcrop_timecutoff_science,
                     freqcutoff=cfg.tfcrop_freqcutoff_science,
                     versionname='tfcrop_science',
                     i='final')
    if cfg.science_flag_mode_strategy == 'rflag':
        run_rflag(ctx, vis=ctx.vis_for_cal, field=ctx.target,
                  datacolumn_to_flag=cfg.science_datacolumn_to_flag,
                  timedevscale=cfg.rflag_timedevscale_science,
                  freqdevscale=cfg.rflag_freqdevscale_science,  # v0.5 passed the time threshold (03 bug 2)
                  versionname='rflag_science',
                  i='final')


def report_science_flags(ctx):
    log.info(' ++==> Reporting data flagged final.')
    summary_final = flagdata(vis=ctx.vis_for_cal, mode='summary', field=ctx.target)
    report_flag(summary_final, 'field')
