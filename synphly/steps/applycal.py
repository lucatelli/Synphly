"""
Apply the calibration to the science targets (ported from v0.5 ``calibrate.apply_cal_to_science``).
"""
from __future__ import annotations

import logging

from ..casa import applycal, flagdata
from .autoflag import record_flags, report_flag
from .flagversions import save_flag_version

log = logging.getLogger(__name__)


def apply_cal_to_science(ctx, vis, gain_tables_to_apply_science_final,
                         gainfield_bandpass_apply_final,
                         gain_tables_ampphase_for_science_final,
                         i, calwt=False):
    """
    applycal on every target with gaintable=transfer+[p_inf, ap_inf_fluxscale] and
    gainfield=transfer gainfields + [<phase calibrator ID of that target>]*2,
    applymode=cfg.calibrate.science_applymode.

    v0.6 change (03 bugs 4/5): v0.5 used gainfield 'nearest' (nearest field on the sky among the fields
    with solutions, i.e. possibly the bandpass or flux calibrator). The phase calibrator of each target is
    now explicit: ``ctx.phasecal_for_target`` (FieldModel.phasecal_for_target: closest in time, or the
    ``[sources] phasecal_for_target`` mapping). A target without a phase calibrator falls back to 'nearest'
    with a warning.

    The flags are saved as 'before_applycal_science_{i}' (v0.5 saved 'before_applycal_science' in both passes, so
    pass 2 overwrote the pass-1 version; nothing restores it).
    """
    log.info("Applying calibration to science source(s).")

    log.info(" ++==>> Creating flag-backup before applycal to science sources.")
    save_flag_version(vis, f'before_applycal_science_{i}', f'Flags before applycal to science sources, pass {i}.')

    log.info("     => Reporting data flagged before applycal.")
    summary_cal_before = flagdata(vis=vis,
                                  mode='summary', field='', datacolumn='data')
    report_flag(summary_cal_before, 'field')

    gainfield_by_target = {}
    for n in range(len(ctx.target_fields_arr)):
        target_id = ctx.target_fields_arr[n]
        phasecal = ctx.phasecal_for_target.get(str(target_id))
        if phasecal is None:
            msg = (f"No phase calibrator known for target field {target_id}; using gainfield 'nearest' "
                   f"(v0.5 behaviour) for its phase/amplitude tables.")
            log.warning(msg)
            ctx.warnings.append(msg)
            phasecal = 'nearest'
        gainfields_final = (gainfield_bandpass_apply_final +
                            [phasecal] * len(gain_tables_ampphase_for_science_final))
        gainfield_by_target[str(target_id)] = list(gainfields_final)
        log.info(f"Applying calibration to: {target_id} (phase calibrator {phasecal})")
        log.info(f"Gaintables: {gain_tables_to_apply_science_final}")
        log.info(f"Gainfields: {gainfields_final}")
        applycal(vis=vis,
                 field=ctx.target_fields_arr[n],
                 gaintable=gain_tables_to_apply_science_final,
                 flagbackup=False,
                 applymode=ctx.cfg.calibrate.science_applymode,
                 gainfield=gainfields_final, calwt=calwt)

    lists = ctx.apply_lists.setdefault(str(i), {})
    lists['science'] = {'gaintable': list(gain_tables_to_apply_science_final),
                        'gainfield_by_target': gainfield_by_target}

    log.info('     => Reporting data flagged after applycal.')
    summary_cal_after = flagdata(vis=vis,
                                 mode='summary', field='', datacolumn='data')
    record_flags(ctx, f'applycal_science_{i}', summary_cal_after)
    report_flag(summary_cal_after, 'field')
