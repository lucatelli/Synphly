"""
Flagging of the raw data: deterministic pre-flagging, tfcrop on raw data, manual flags, AOFlagger.

Ported from v0.5 ``flagging.py`` (pre_flagging, tfcrop_raw, manual_flagging, run_aoflagger_sif,
run_aoflagger_nat).
"""
from __future__ import annotations

import logging
import os
import subprocess
import time

from ..calib.wrappers import get_chan_spws_map
from ..casa import flagdata, flagmanager
from . import _plots
from .autoflag import record_flags, report_flag
from .flagversions import save_flag_version

log = logging.getLogger(__name__)


def _run_command(command_to_execute):
    log.info("Executing: %s", ' '.join(command_to_execute))
    process = subprocess.Popen(command_to_execute, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, universal_newlines=True)
    stdout, stderr = process.communicate()
    log.info("stdout: %s", stdout)
    log.info("stderr: %s", stderr)
    return_code = process.returncode
    if return_code == 0:
        log.info(f"Strategy executed successfully. Output:\n{stdout}")
    else:
        log.critical(f"Error executing strategy. Return code: {return_code}\nError message: {stderr}")
        raise RuntimeError(f"{command_to_execute[0]} exited with return code {return_code}: {stderr.strip()[-500:]}")
    return return_code


def run_aoflagger_sif(ctx, vis):
    """Run AOFlagger from a singularity container (cfg.flagging.aoflagger_sif)."""
    container = ctx.cfg.flagging.aoflagger_sif
    aoflagger_strategy = ctx.cfg.flagging.aoflagger_strategy
    if not os.path.exists(container):
        # v0.5 failed here with a NameError (singularity_bind undefined); same outcome, clearer message.
        raise FileNotFoundError(f"AOflagger singularity container not found: {container!r}")
    log.info(f"Found {container}")
    singularity_bind = os.path.join(os.path.dirname(os.path.dirname(container)))
    log.info(f"You are binding singularity to {singularity_bind}")

    strategy = ['aoflagger', '-v', '-indirect-read', '-fields', '', '-strategy', aoflagger_strategy,
                vis]
    command_to_execute = ['singularity', 'exec', '-B', singularity_bind, container] + strategy
    # A failure raises: the run_aoflagger step is optional, so the pipeline records it as failed and continues
    # (v0.5 logged it here and the step looked successful).
    _run_command(command_to_execute)


def run_aoflagger_nat(ctx, vis):
    """Run a native AOFlagger installation (debugging only)."""
    report_verbosity = ctx.cfg.globals.report_verbosity
    if report_verbosity >= 2:
        log.info('Reporting data flagged before running aoflagger ...')
        summary_before_aoflagger = flagdata(vis=vis, mode='summary')
        report_flag(summary_before_aoflagger, 'field')

    command_to_execute = ['aoflagger', '-v', '-j', '6', '-direct-read', '-fields', '', '-strategy',
                          ctx.cfg.flagging.aoflagger_strategy, vis]
    _run_command(command_to_execute)     # raises on failure (optional step, see run_aoflagger_sif)
    if report_verbosity >= 2:
        log.info('Reporting data flagged after running aoflagger ...')
        summary_after_aoflagger = flagdata(vis=vis, mode='summary')
        report_flag(summary_after_aoflagger, 'field')


def tfcrop_raw(ctx, vis, field):
    cfg = ctx.cfg.flagging
    log.info("Running tfcrop on raw data.")

    log.info("Creating flag backup before tfcrop.")
    save_flag_version(vis, 'flags_before_tfcrop_init', 'Flagbackup before initial tfcrop.')

    summary_before_tfcrop = flagdata(vis=vis, mode='summary')
    report_flag(summary_before_tfcrop, 'field')

    flagdata(vis=vis, mode='tfcrop', field=field, display='', spw='',
             datacolumn='data', ntime=cfg.ntime, combinescans=cfg.combinescans,
             extendflags=False,
             freqfit='poly', maxnpieces=cfg.maxnpieces,
             timefit='line',
             timecutoff=cfg.tfcrop_timecutoff_cals,
             freqcutoff=cfg.tfcrop_freqcutoff_cals,
             winsize=cfg.winsize,
             action='apply', flagbackup=False, savepars=True
             )

    flagdata(vis=vis, mode='extend', field=field, spw='', display='report',
             growaround=True, flagnearfreq=False, flagneartime=False,
             ntime=cfg.ntime,
             action='apply', datacolumn='data', combinescans=False, flagbackup=False,
             growtime=80.0, growfreq=80.0, extendpols=True)

    summary_after_tfcrop = flagdata(vis=vis, mode='summary')
    record_flags(ctx, 'tfcrop_raw', summary_after_tfcrop)
    report_flag(summary_after_tfcrop, 'field')

    log.info("Creating flag backup after tfcrop.")
    save_flag_version(vis, 'flags_after_tfcrop_init', 'Flags after tfcrop on raw flagged data')


def manual_flagging(ctx, vis):
    manual_file = ctx.cfg.flagging.manual_file
    log.info(f' ++==>> Flagging using user supplied flagging file {manual_file}')
    try:
        flagdata(vis=vis, mode='list', inpfile=manual_file, flagbackup=False)
        versionname = 'manual_flagging_1'
        log.info(f'Creating new flagbackup file version {versionname}')
        save_flag_version(vis, versionname, 'First run of manual flagging.')

        summary_after_manual = flagdata(vis=vis, mode='summary')
        record_flags(ctx, 'manual_flags', summary_after_manual)
        if ctx.cfg.globals.report_verbosity >= 1:
            report_flag(summary_after_manual, 'field')
    except Exception as e:
        log.warning(f'Manual flagging with {manual_file!r} failed ({e}). Supply a valid manual flagging file')


# The intent selections of pre-flagging (v0.5 strings): (intent, reason/name, description). The pointing
# selection is used only when cfg.flagging.do_flag_pointing_scans is true. intent_flagging re-applies exactly
# these selections.
POINTING_SELECTION = ('*POINTING*', 'pointing', 'pointing')
OTHER_INTENT_SELECTIONS = (('UNSPECIFIED#UNSPECIFIED', 'UNSPECIFIED', 'UNSPECIFIED'),
                           ('*SYSTEM_CONFIGURATION*', 'SYSTEM_CONFIGURATION', 'SYSTEM_CONFIGURATION'))


def intent_selections(flagging_cfg) -> list:
    """[(intent, reason, description)] flagged by pre-flagging (and by intent_flagging)."""
    sel = [POINTING_SELECTION] if flagging_cfg.do_flag_pointing_scans else []
    return sel + list(OTHER_INTENT_SELECTIONS)


def _flag_intent(vis, intent, reason):
    flagdata(vis=vis, mode='manual', intent=intent,
             reason=reason, flagbackup=False, action='apply',
             name=reason)


def is_null_selection(exc: Exception) -> bool:
    """True for CASA's 'MSSelectionNullSelection : The selected table has zero rows.' (nothing to flag)."""
    msg = str(exc)
    return 'NullSelection' in msg or 'zero rows' in msg


def _null_selection_or_raise(exc, what):
    """A selection without rows (nothing to flag) is logged; any other error is re-raised (v0.5 logged every
    error of these pre-flagging commands and continued)."""
    if is_null_selection(exc):
        log.info(f"Nothing selected while {what} ({exc}).")
        return
    log.error(f"Exception {exc} while {what}")
    raise exc


def _quack(vis, interval, mode, field=None):
    kw = {} if field is None else {'field': field}
    flagdata(vis=vis, mode='quack', quackinterval=interval, quackmode=mode, **kw,
             reason='quack', flagbackup=False, action='apply', name='quack')


def pre_flagging(ctx, vis):
    """
    Pre-flagging of the data (v0.5 order): restore/save 'original_flags_import', autocorr, shadow,
    clip zeros, quack, save 'pre_flagging', edge channels (calibrators / science), pointing,
    UNSPECIFIED and SYSTEM_CONFIGURATION intents.
    """
    cfg = ctx.cfg.flagging
    report_verbosity = ctx.cfg.globals.report_verbosity
    plots_dir = ctx.paths.plots

    pre_flagging_starttime = time.time()

    if not os.path.exists(vis + '.flagversions/flags.original_flags_import/'):
        log.info('Creating flagbackup file for original ms')
        flagmanager(vis=vis, mode='save', versionname='original_flags_import',
                    comment='Original flags from import.')
    else:
        log.warning("--==>> Original flags exists. Are you reruning the code?")
        log.warning("++==>> Will restore the flags to the original state.")
        flagmanager(vis=vis, mode='restore', versionname='original_flags_import')

    log.info('Starting pre-flagging to the data.')

    summary_0 = flagdata(vis=vis, mode='summary')
    record_flags(ctx, 'original', summary_0)

    if report_verbosity >= 2:
        log.info('Reporting data flagged at start ...')
        report_flag(summary_0, 'field')

    _plots.plotants(ctx, vis=vis, logpos=True, figfile=plots_dir.rstrip('/') + '/' + '_plotant_log.pdf')
    _plots.plotants(ctx, vis=vis, logpos=False, figfile=plots_dir.rstrip('/') + '/' + '_plotant.pdf')

    try:
        log.info('Flagging autocorrelations')
        flagdata(vis=vis, mode='manual', autocorr=True,
                 reason='autocorr', flagbackup=False, action='apply',
                 name='autocorr')
    except Exception as e:
        _null_selection_or_raise(e, 'flagging autocorrelations')

    summary_autocorr = flagdata(vis=vis, mode='summary')
    record_flags(ctx, 'autocorr', summary_autocorr)

    if report_verbosity >= 2:
        log.info('Reporting flagged data after autocorr flagging...')
        report_flag(summary_autocorr, 'field')
    try:
        log.info('++==>> Shadow flagging the data')
        flagdata(vis=vis, mode='shadow', reason='shadow',
                 tolerance=10.0,  # tolerance 0.0m is too agressive
                 flagbackup=False, name='shadow', action='apply')
    except Exception as e:
        _null_selection_or_raise(e, 'shadow flagging')

    summary_2 = flagdata(vis=vis, mode='summary')
    record_flags(ctx, 'shadow', summary_2)

    if report_verbosity >= 2:
        log.info('++==>> Reporting data flagged after shadow flagging...')
        report_flag(summary_2, 'field')

    # flag zeros data (flagm data with zero values/amplitudes)
    try:
        log.info('Clipping the data')
        flagdata(vis=vis, mode='clip', correlation='ABS_ALL', clipzeros=True,
                 reason='clip', flagbackup=False, action='apply', name='clip')
    except Exception as e:
        _null_selection_or_raise(e, 'clipping')

    summary_4 = flagdata(vis=vis, mode='summary')
    record_flags(ctx, 'clip', summary_4)

    if report_verbosity >= 2:
        log.info('++==>> Reporting data flagged after clipping')
        report_flag(summary_4, 'field')

    # quack flagging (time for the antennas to settle on the source).
    # v0.5: 1 s at the beginning and 1 s at the end of every scan, all fields (the defaults).
    # The optional per-role extra quack (0 = off = v0.5) is measured from the scan boundary too,
    # so it is not cumulative with the all-fields quack: the larger interval wins.
    try:
        log.info('  ++==>> Quacking the data')
        _quack(vis, cfg.quack_interval_beg, 'beg')
        _quack(vis, cfg.quack_interval_endb, 'endb')
        if cfg.quack_extra_flux_beg > 0:
            log.info(f'  ++==>> Extra quack of {cfg.quack_extra_flux_beg} s (beg) on the flux calibrator')
            _quack(vis, cfg.quack_extra_flux_beg, 'beg', field=ctx.flux_calibrator)
        if cfg.quack_extra_phase_beg > 0:
            log.info(f'  ++==>> Extra quack of {cfg.quack_extra_phase_beg} s (beg) on the phase calibrators')
            _quack(vis, cfg.quack_extra_phase_beg, 'beg', field=ctx.phase_calibrator)
        if cfg.quack_extra_phase_endb > 0:
            log.info(f'  ++==>> Extra quack of {cfg.quack_extra_phase_endb} s (endb) on the phase calibrators')
            _quack(vis, cfg.quack_extra_phase_endb, 'endb', field=ctx.phase_calibrator)
    except Exception as e:
        _null_selection_or_raise(e, 'quacking')

    summary_5 = flagdata(vis=vis, mode='summary')
    record_flags(ctx, 'quack', summary_5)

    if report_verbosity >= 2:
        log.info('++==>> Reporting data flagged after quack flagging...')
        report_flag(summary_5, 'field')

    try:
        log.info('++==>> Creating new flagbackup file after pre-flagging.')
        save_flag_version(vis, 'pre_flagging', 'Pre-flags applied: Autocorr,clipping, quack, shadow.')
    except Exception as e:
        log.error(f"Exception {e} encountered while backing up flags")
        raise

    if cfg.do_flag_edge_channels_cals:
        log.info('Flagging edge channels for calibrators.')
        _, _, chan_spw_edge_flag = get_chan_spws_map(vis,
                                                     edge_channel_frac=cfg.edge_channel_frac,
                                                     edge_channel_flag_frac=cfg.edge_channel_flag_frac_cals,
                                                     compute_edge_for_flagging=True)
        flagdata(vis=vis, mode='manual', spw=chan_spw_edge_flag,
                 field=ctx.calibrators_all,
                 reason='edge_channels', flagbackup=False, action='apply',
                 name='edge_channels')

    if cfg.do_flag_edge_channels_science:
        log.info('Flagging edge channels for science sources.')
        _, _, chan_spw_edge_flag = get_chan_spws_map(vis,
                                                     edge_channel_frac=cfg.edge_channel_frac,
                                                     edge_channel_flag_frac=cfg.edge_channel_flag_frac_science,
                                                     compute_edge_for_flagging=True)
        flagdata(vis=vis, mode='manual', spw=chan_spw_edge_flag,
                 field=ctx.target,
                 reason='edge_channels', flagbackup=False, action='apply',
                 name='edge_channels')

    summary_edge = flagdata(vis=vis, mode='summary')
    record_flags(ctx, 'edge_channels', summary_edge)

    # Pointing scans (if cfg.do_flag_pointing_scans) are taken with offset antennas. When they share the name
    # of a calibrator (e.g. 12B-184, J1221+2813), a selection by name would pull them into the gain
    # calibration. UNSPECIFIED and SYSTEM_CONFIGURATION scans carry no usable data.
    for intent, reason, what in intent_selections(cfg):
        try:
            log.info(f'  ++==>> Flagging {what} scans')
            _flag_intent(vis, intent, reason)
        except Exception as e:
            if not is_null_selection(e):
                log.error(f'--==>> Flagging the {what} scans failed: {e}')
                raise
            log.info(f'--==>> No {what} scans found ({e}). Going to skip.')

    # Not done (dangerous): flagging intent='*CONFIG*'. Some older observations have config scans
    # attached to targets or calibrators. Check the data before enabling this.

    log.info('Total data after initial flagging')
    summary_pre_cal = flagdata(vis=vis, mode='summary')
    record_flags(ctx, 'pre_cal', summary_pre_cal)
    report_flag(summary_pre_cal, 'field')

    pre_flagging_time = time.time() - pre_flagging_starttime
    log.info(f"Initial flagging took {pre_flagging_time / 60:.2f} minutes")


def _total_flagged(summary):
    try:
        return float(summary['flagged']), float(summary['total'])
    except (KeyError, TypeError):
        fields = (summary or {}).get('field', {})
        return (float(sum(v['flagged'] for v in fields.values())),
                float(sum(v['total'] for v in fields.values())))


def intent_flagging(ctx, vis):
    """
    Re-apply the intent flags of pre-flagging (pointing if cfg.flagging.do_flag_pointing_scans, UNSPECIFIED,
    SYSTEM_CONFIGURATION; the same ``intent=`` selections) to the MS that is calibrated (03 issue 12).

    Runs right before initial_corrections, whatever the flagging switches, so that an ``.avg.ms`` re-made from
    an MS that never had pre-flagging still has these scans flagged. Idempotent: when pre-flagging ran before
    averaging, nothing changes. A selection without rows (CASA MSSelectionNullSelection) is normal and logged
    at INFO; any other error stops the step. The flag summaries before and after are recorded as
    'intent_flagging_before' / 'intent_flagging'.
    """
    log.info(f"Intent flagging of {vis}")
    summary_before = flagdata(vis=vis, mode='summary')
    record_flags(ctx, 'intent_flagging_before', summary_before)
    for intent, reason, what in intent_selections(ctx.cfg.flagging):
        try:
            log.info(f"  ++==>> Flagging {what} scans (intent='{intent}')")
            _flag_intent(vis, intent, reason)
        except Exception as e:
            if not is_null_selection(e):
                raise
            log.info(f"  No {what} scans in {vis} (no rows selected by intent='{intent}').")
    summary_after = flagdata(vis=vis, mode='summary')
    record_flags(ctx, 'intent_flagging', summary_after)
    (f0, total), (f1, _) = _total_flagged(summary_before), _total_flagged(summary_after)
    if f1 > f0:
        log.info(f"Intent flagging flagged {f1 - f0:.0f} more visibilities ({100 * f0 / total:.2f}% -> "
                 f"{100 * f1 / total:.2f}% flagged): these intents were not flagged in {vis} before.")
    else:
        pct = 100 * f1 / total if total else 0.0
        log.info(f"Intent flagging changed nothing ({pct:.2f}% flagged): already applied by pre-flagging.")
