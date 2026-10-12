"""
Bandpass calibration chain on the bandpass calibrator (ported from v0.5 ``calibrate.bandpass_cal``).

Solves (all field=bandpass_calibrator, refant=ctx.ref_antenna, refantmode='strict'):
K (spw_skip_edge) -> G p -> G ap -> G ap inf -> B (three variants). Applies init+K+p+ap+B_ap_inf to the
bandpass calibrator and returns the transfer list init+K+B_ap_inf.
"""
from __future__ import annotations

import logging
import os

from ..calib.tables import flag_fingerprint
from ..calib.wrappers import get_chan_spws_map, run_bandpass, run_gaincal
from ..casa import applycal, clearcal, delmod, flagdata, flagmanager
from . import _plots
from .autoflag import record_flags, report_flag
from .flagversions import save_flag_version
from .setjy_fluxcal import DELMOD_NOTE, restore_models_after_clearcal

log = logging.getLogger(__name__)


def require_refant(ctx):
    if not ctx.ref_antenna:
        raise RuntimeError("No reference antenna set (ctx.ref_antenna is empty). Enable "
                           "calibrate.do_refant or run the refant step first.")
    return ctx.ref_antenna


def bandpass_cal(ctx, i=1, calwt=False):
    """
    Returns (gaintables_apply_BP, gainfield_bandpass_apply, gain_tables_BP_dict,
    gaintables_apply_BP_dict, gainfields_apply_BP_dict) as v0.5, and stores the tables and apply lists in
    ``ctx.bp_tables[str(i)]`` / ``ctx.apply_lists[str(i)]['bp_self'|'transfer']``.

    Table reuse follows cfg.pipeline.reuse_tables (synphly.calib.tables); v0.5's ``overwrite`` argument is
    replaced by it. (v0.5 had a ``do_plots`` argument calling an undefined ``check_bandpass_plots``; it was never used and
    is dropped.)
    """
    c = ctx.cfg.calibrate
    vis_for_cal = ctx.vis_for_cal
    bandpass_calibrator = ctx.bandpass_calibrator
    ref_antenna = require_refant(ctx)
    init_tables = list(ctx.init_tables)
    caldir = ctx.paths.calibration

    spw_skip_edge, spw_central = get_chan_spws_map(vis=vis_for_cal,
                                                   edge_channel_frac=ctx.cfg.flagging.edge_channel_frac)

    if os.path.exists(vis_for_cal + '.flagversions/flags.before_bandpass_init_' + str(i) + '/'):
        log.info(f"Restoring flags from {vis_for_cal}.flagversions/flags.before_bandpass_init_{i}/")
        flagmanager(vis=vis_for_cal, mode='restore', versionname='before_bandpass_init_' + str(i))
        clearcal(vis=vis_for_cal)
        # Removes the on-the-fly model only; MODEL_DATA is not cleared (scr=False), as in v0.5. It keeps the
        # models written earlier (setjy of the flux calibrator and, after a gain pass, the bootstrapped
        # setjy(standard='fluxscale') models); reset_transfer_models resets the secondary calibrators to 1 Jy at
        # the start of the gain step (03 issue 14).
        delmod(vis=vis_for_cal, otf=True, scr=False)
        log.info(DELMOD_NOTE)
        # clearcal reset MODEL_DATA to 1 Jy for every field, including the flux calibrator: put back the models a
        # fresh run has at this point (otherwise every bootstrapped flux of a re-run is wrong; v0.5 bug).
        restore_models_after_clearcal(ctx, vis_for_cal, i)

    # flag state of the MS for the input hashes of the tables below (flags do not change between the solves)
    flag_fp = flag_fingerprint(vis_for_cal)

    # COMPUTE THE DELAY FOR THE BANDPASS CALIBRATOR
    gain_tables_BP_dict = {}
    table_stage_bpcal_d = '_bpcal_d_'
    # Each call of run_gaincal takes the previous tables (e.g. init_tables), computes the requested table
    # (e.g. delay) and returns the new list of tables, i.e. the generated table appended to the input list.
    gaintables_temp_K = run_gaincal(vis=vis_for_cal, calibration_dir=caldir,
                                    field=bandpass_calibrator,
                                    gaintables=init_tables,
                                    scan='', refant=ref_antenna,
                                    spw=spw_skip_edge,
                                    calmode='p', gaintype='K',
                                    solint=c.bp_solint_K, ctx=ctx, flag_fp=flag_fp,
                                    i=i, table_stage=table_stage_bpcal_d,
                                    minsnr=c.minsnr_K
                                    )
    gain_tables_BP_dict['bp_K'] = gaintables_temp_K[-1]

    tt = str(i) + table_stage_bpcal_d + c.bp_solint_K
    _plots.caltable(ctx, gain_tables_BP_dict['bp_K'], table_type=tt, xaxis='ant1', yaxis='delay')
    _plots.caltable(ctx, gain_tables_BP_dict['bp_K'], table_type=tt, xaxis='time', yaxis='delay')

    # USING THE DELAY TABLE; COMPUTE THE PHASE FOR THE BANDPASS CALIBRATOR WITH A SHORT SOLINT
    table_stage_bpcal_p = '_bpcal_p_'
    gaintables_temp_bpcal_p = run_gaincal(vis=vis_for_cal, calibration_dir=caldir,
                                          field=bandpass_calibrator,
                                          gaintables=gaintables_temp_K,
                                          scan='', refant=ref_antenna,
                                          spw=spw_central, calmode='p', gaintype='G',
                                          solint=c.bp_solint_G_p, ctx=ctx, flag_fp=flag_fp,
                                          i=i, table_stage=table_stage_bpcal_p,
                                          minsnr=c.minsnr_bp_G_p
                                          )
    gain_tables_BP_dict['bp_p'] = gaintables_temp_bpcal_p[-1]

    tt = str(i) + table_stage_bpcal_p + c.bp_solint_G_p
    _plots.caltable(ctx, gain_tables_BP_dict['bp_p'], table_type=tt, xaxis='time', yaxis='phase')

    # USING THE PREVIOUS DELAY AND SHORTER PHASES, COMPUTE THE AMPLITUDE GAINS FOR THE BANDPASS CALIBRATOR
    # THIS RUN IS DONE WITH A SHORTER SOLINT
    table_stage_bpcal_ap = '_bpcal_ap_'
    gaintables_temp_bpcal_ap = run_gaincal(vis=vis_for_cal, calibration_dir=caldir,
                                           field=bandpass_calibrator,
                                           gaintables=gaintables_temp_bpcal_p,
                                           scan='', refant=ref_antenna,
                                           combine='scan',
                                           spw=spw_central, calmode='ap', gaintype='G',
                                           solint=c.bp_solint_G_ap, ctx=ctx, flag_fp=flag_fp,
                                           i=i, table_stage=table_stage_bpcal_ap,
                                           minsnr=c.minsnr_bp_G_p
                                           )
    gain_tables_BP_dict['bp_ap'] = gaintables_temp_bpcal_ap[-1]

    tt = str(i) + table_stage_bpcal_ap + c.bp_solint_G_ap
    _plots.caltable(ctx, gain_tables_BP_dict['bp_ap'], table_type=tt, xaxis='time', yaxis='phase')
    _plots.caltable(ctx, gain_tables_BP_dict['bp_ap'], table_type=tt, xaxis='time', yaxis='amp')

    # USING THE PREVIOUS DELAY AND SHORTER PHASES, COMPUTE THE AMPLITUDE GAINS FOR THE BANDPASS CALIBRATOR
    # NOW, WITH AN INF SOLINT FOR THE AMPLITUDE GAINS.
    table_stage_bpcal_ap_inf = '_bpcal_ap_inf_'
    bp_solint_G_ap_inf = 'inf'
    gaintables_temp_bpcal_ap_inf = run_gaincal(vis=vis_for_cal, calibration_dir=caldir,
                                               field=bandpass_calibrator,
                                               gaintables=gaintables_temp_bpcal_p,
                                               scan='', refant=ref_antenna,
                                               combine='scan',
                                               spw=spw_central, calmode='ap', gaintype='G',
                                               solint=bp_solint_G_ap_inf, ctx=ctx, flag_fp=flag_fp,
                                               i=i, table_stage=table_stage_bpcal_ap_inf,
                                               minsnr=c.minsnr_bp_G_p
                                               )
    gain_tables_BP_dict['bp_ap_inf'] = gaintables_temp_bpcal_ap_inf[-1]

    tt = str(i) + table_stage_bpcal_ap_inf + bp_solint_G_ap_inf
    _plots.caltable(ctx, gain_tables_BP_dict['bp_ap_inf'], table_type=tt, xaxis='time', yaxis='phase')
    _plots.caltable(ctx, gain_tables_BP_dict['bp_ap_inf'], table_type=tt, xaxis='time', yaxis='amp')

    # NOW WE PROCEED TO THE BANDPASS. WE CAN APPROACH IN TWO DIFFERENT WAYS:
    # 1. COMPUTE BANDPASS USING DELAYS AND SHORT PHASES [K > P]
    # 2. COMPUTE BANDPASS USING DELAYS, SHORT PHASES AND AMPLITUDES [K > P > AP]:
    #   2.1 USING SHORT AMPLITUDES [K > P > AP_SHORT]
    #   2.2 USING INF AMPLITUDES [K > P > AP_INF]   <- the one applied/transferred
    def _bp(stage, priors):
        return run_bandpass(vis=vis_for_cal, calibration_dir=caldir,
                            field=bandpass_calibrator,
                            gaintables=priors,
                            combine='scan', bandtype='B',
                            scan='', refant=ref_antenna,
                            spw='*', ctx=ctx, flag_fp=flag_fp,
                            solint=c.bp_solint_BP,
                            fillgaps=c.bp_fillgaps,
                            solnorm=True,
                            i=i, table_stage=stage,
                            minsnr=c.minsnr_bp_G_p
                            )

    def _bp_plots(key, stage):
        tt_ = str(i) + stage + c.bp_solint_BP
        _plots.caltable(ctx, gain_tables_BP_dict[key], table_type=tt_, xaxis='chan', yaxis='phase')
        _plots.caltable(ctx, gain_tables_BP_dict[key], table_type=tt_, xaxis='freq', yaxis='phase')
        _plots.caltable(ctx, gain_tables_BP_dict[key], table_type=tt_, xaxis='chan', yaxis='amp')
        _plots.caltable(ctx, gain_tables_BP_dict[key], table_type=tt_, xaxis='freq', yaxis='amp')

    table_stage_bpcal_BP_ap_inf = '_bpcal_BP_ap_inf'
    gain_tables_BP_dict['bp_BP_ap_inf'] = _bp(table_stage_bpcal_BP_ap_inf, gaintables_temp_bpcal_ap_inf)[-1]
    _bp_plots('bp_BP_ap_inf', table_stage_bpcal_BP_ap_inf)

    # diagnostic only (not applied)
    table_stage_bpcal_BP_ap_short = '_bpcal_BP_ap_short'
    gain_tables_BP_dict['bp_BP_ap_short'] = _bp(table_stage_bpcal_BP_ap_short, gaintables_temp_bpcal_ap)[-1]
    _bp_plots('bp_BP_ap_short', table_stage_bpcal_BP_ap_short)

    # diagnostic only (not applied)
    table_stage_bpcal_BP = '_bpcal_BP_'
    gain_tables_BP_dict['bp_BP'] = _bp(table_stage_bpcal_BP, gaintables_temp_bpcal_p)[-1]
    _bp_plots('bp_BP', table_stage_bpcal_BP)

    log.info("Consolidating tables for bandpass cal apply.")
    # IF ENOUGH SNR, THIS IS BETTER THAN THE OTHER OPTIONS (K+p+BP, or K+p+ap_inf+BP_ap_inf).
    pre_cal_tables_temp = [gain_tables_BP_dict['bp_K'],
                           gain_tables_BP_dict['bp_p'],
                           gain_tables_BP_dict['bp_ap'],
                           gain_tables_BP_dict['bp_BP_ap_inf']
                           ]

    log.info("Consolidating gainfields for bandpass cal apply.")
    gainfield_init = [''] * len(init_tables)
    gainfield_bandpass = [bandpass_calibrator] * len(pre_cal_tables_temp)
    gainfield_bandpass_apply_self = gainfield_init.copy()
    gainfield_bandpass_apply_self.extend(gainfield_bandpass)

    gaintables_apply_BP_self = init_tables.copy()
    gaintables_apply_BP_self.extend(pre_cal_tables_temp)

    # Tables transferred to the other fields (complex calibrators and science sources).
    # The time-dependent gains of the bandpass calibrator (bp_p, bp_ap) are only used to
    # remove its own time variability while solving the bandpass. They must NOT be
    # transferred: they are time-interpolated across hours, and a single flagged solution
    # bracketing a field flags its data (with refantmode='strict', all antennas). This
    # happened, e.g., in 12B-184 (Q band), where the bandpass calibrator was observed at
    # the start and end of the run. Only the delay and the bandpass are transferred; the
    # phases and amplitudes of the other fields are solved later in cal_phases_amplitudes.
    transfer_tables_temp = [gain_tables_BP_dict['bp_K'],
                            gain_tables_BP_dict['bp_BP_ap_inf']]
    gainfield_bandpass_apply = gainfield_init.copy()
    gainfield_bandpass_apply.extend([bandpass_calibrator] * len(transfer_tables_temp))

    gaintables_apply_BP = init_tables.copy()
    gaintables_apply_BP.extend(transfer_tables_temp)

    gaintables_apply_BP_dict = {f"BP_tables_run_{i}": gaintables_apply_BP_self,
                                f"BP_transfer_tables_run_{i}": gaintables_apply_BP}
    gainfields_apply_BP_dict = {f"BP_gainfields_run_{i}": gainfield_bandpass_apply_self,
                                f"BP_transfer_gainfields_run_{i}": gainfield_bandpass_apply}
    log.info(f"     => Tables applied to the bandpass calibrator: {gaintables_apply_BP_self}")
    log.info(f"     => Tables transferred to other fields: {gaintables_apply_BP}")

    # record before applying, so that a failure below still leaves the solved tables in the state
    ctx.bp_tables[str(i)] = dict(gain_tables_BP_dict)
    lists = ctx.apply_lists.setdefault(str(i), {})
    lists['bp_self'] = {'gaintable': list(gaintables_apply_BP_self),
                        'gainfield': list(gainfield_bandpass_apply_self)}
    lists['transfer'] = {'gaintable': list(gaintables_apply_BP),
                         'gainfield': list(gainfield_bandpass_apply)}

    log.info("Creating flag-backup before applying initial bandpass.")
    # (restored at the start of this function if it exists; no flag changes since then, so replacing it here
    # saves the same flags v0.5 saved)
    save_flag_version(vis_for_cal, 'before_bandpass_init_' + str(i),
                      'Flags before apply bandpass init, iteration' + str(i) + '.')

    log.info('     ++==>> Reporting flags before applycal to bandpass.')
    summary_before_applycal_to_bandpass = flagdata(vis=vis_for_cal,
                                                   mode='summary',
                                                   field=bandpass_calibrator)
    report_flag(summary_before_applycal_to_bandpass, 'field')

    log.info(f"Applying bandpass solutions to bandpass calibrator {bandpass_calibrator}.")
    applycal(vis=vis_for_cal, field=bandpass_calibrator,
             gaintable=gaintables_apply_BP_self,
             gainfield=gainfield_bandpass_apply_self,
             applymode=c.bp_applymode,
             calwt=calwt, flagbackup=False)

    log.info('     ++==>> Reporting flags after applycal to bandpass.')
    summary_after_applycal_to_bandpass = flagdata(vis=vis_for_cal, mode='summary')
    record_flags(ctx, f'bandpass_{i}', summary_after_applycal_to_bandpass)
    report_flag(summary_after_applycal_to_bandpass, 'field')

    return (gaintables_apply_BP, gainfield_bandpass_apply,
            gain_tables_BP_dict, gaintables_apply_BP_dict, gainfields_apply_BP_dict)
