"""
Gain calibration of all calibrators + flux bootstrap (ported from v0.5 ``calibrate``:
reset_transfer_models, cal_phases_amplitudes).
"""
from __future__ import annotations

import logging
import os
import shutil

import numpy as np

from ..calib import tables as reg
from ..calib.tables import flag_fingerprint
from ..calib.wrappers import get_chan_spws_map, run_gaincal
from ..casa import applycal, flagdata, fluxscale, open_msmd, setjy
from . import _plots
from .autoflag import record_flags, report_flag
from .flagversions import save_flag_version
from .bandpass import require_refant
from .ms_info import field_model
from .setjy_fluxcal import spw_mean_freqs

log = logging.getLogger(__name__)


def reset_transfer_models(ctx, vis):
    """
    Reset the models of all calibrators, except the flux calibrator, to a 1 Jy point source.

    fluxscale assumes that the transfer fields were solved against a 1 Jy model. The
    setjy(standard='fluxscale') call in cal_phases_amplitudes writes the bootstrapped flux
    densities to MODEL_DATA, and delmod(scr=False) does not clear them. Without this reset,
    the next gain calibration (2nd iteration, or a re-run) solves against those models,
    fluxscale reports ~1.0 (S_true/S_model), and setjy then writes ~1 Jy models.

    Uses the field-ID sets of the FieldModel (calibrator IDs minus flux-calibrator IDs).
    """
    from .ms_info import field_model
    fm = field_model(ctx)
    flux_ids = set(fm.ids('flux'))
    if len(flux_ids) == 0:
        log.warning(f"No flux calibrator field ({ctx.flux_calibrator!r}); "
                    f"not resetting the models of the other calibrators.")
        return
    transfer_ids = sorted(set(fm.calibrator_ids()) - flux_ids)
    if len(transfer_ids) == 0:
        return
    transfer_ids_str = ','.join(str(x) for x in transfer_ids)
    log.info(f"Resetting the models of field(s) {transfer_ids_str} to 1 Jy before gain "
             f"calibration.")
    setjy(vis=vis, field=transfer_ids_str, standard='manual',
          fluxdensity=[1, 0, 0, 0], scalebychan=True, usescratch=True)


def _remove(path):
    if os.path.isdir(path):
        shutil.rmtree(path)
    elif os.path.exists(path):
        os.remove(path)


def fluxscale_fitorder(ctx, vis):
    """
    fitorder for fluxscale. cfg.fluxscale.fitorder: 'auto' -> 1 if the fractional bandwidth is
    >= cfg.fluxscale.fitorder_bw_threshold (default 0.05, the v0.5 rule) else 0; '0'/'1' -> forced.

    The spectral index fitted by fluxscale is only meaningful when the spws span a
    reasonable fractional bandwidth. For narrow setups (e.g. 12B-184, Q band, 16 spws
    within 60 MHz) a fitorder=1 fit is unconstrained (e.g. spidx = -12 +/- 8) and setjy
    refuses it. In that case, fit only the flux density (fitorder=0).
    """
    with open_msmd(vis) as msmd:
        _spw_freqs = np.concatenate([msmd.chanfreqs(_spw) for _spw in range(msmd.nspw())])
    frac_bandwidth = (_spw_freqs.max() - _spw_freqs.min()) / np.mean(_spw_freqs)
    setting = str(ctx.cfg.fluxscale.fitorder).strip().lower()
    if setting == 'auto':
        threshold = ctx.cfg.fluxscale.fitorder_bw_threshold
        flux_fitorder = 1 if frac_bandwidth >= threshold else 0
        log.info(f"Fractional bandwidth is {frac_bandwidth:.4f}; "
                 f"using fitorder={flux_fitorder} in fluxscale.")
    elif setting in ('0', '1'):
        flux_fitorder = int(setting)
        log.info(f"Fractional bandwidth is {frac_bandwidth:.4f}; "
                 f"using fitorder={flux_fitorder} in fluxscale (set in the config).")
    else:
        raise ValueError(f"fluxscale.fitorder must be 'auto', '0' or '1', not {ctx.cfg.fluxscale.fitorder!r}")
    return flux_fitorder


def cal_phases_amplitudes(ctx, gaintables_apply_BP, gainfield_bandpass_apply, i=1,
                          transfer='', reference='',
                          calwt=False):
    """
    Solve phases/amplitudes of all calibrators against the transferred bandpass tables, bootstrap the
    flux scale (fluxscale + setjy(fluxscale)) and apply the solutions to each calibrator.

    Returns (gain_tables_phases_dict, gain_tables_ampphase_for_science, gain_tables_to_apply_science,
    flag_FLUX_SCALE) as v0.5. Also stores ``ctx.gain_tables[str(i)]``, ``ctx.fluxes[str(i)]`` and
    ``ctx.apply_lists[str(i)]['cal']``.
    """
    c = ctx.cfg.calibrate
    vis_for_cal = ctx.vis_for_cal
    calibrators_all = ctx.calibrators_all
    ref_antenna = require_refant(ctx)
    caldir = ctx.paths.calibration
    minsnr = c.minsnr

    spw_skip_edge, spw_central = get_chan_spws_map(vis=vis_for_cal,
                                                   edge_channel_frac=ctx.cfg.flagging.edge_channel_frac)

    gain_tables_phases_dict = {}

    reset_transfer_models(ctx, vis=vis_for_cal)
    # flag state for the input hashes of the tables below (no flags change between these solves)
    flag_fp = flag_fingerprint(vis_for_cal)

    # First, the short phases for all complex calibrators.
    table_stage_all_p_short = '_allcal_p_short_'
    gaintables_temp_calibrators_p_short = run_gaincal(vis=vis_for_cal, calibration_dir=caldir,
                                                      field=calibrators_all,
                                                      gaintables=gaintables_apply_BP,
                                                      gainfield=gainfield_bandpass_apply,
                                                      scan='', refant=ref_antenna,
                                                      spw=spw_central,
                                                      calmode='p', gaintype='G',
                                                      solint=c.all_solint_short_p,
                                                      ctx=ctx, flag_fp=flag_fp,
                                                      i=i, table_stage=table_stage_all_p_short,
                                                      minsnr=minsnr
                                                      )
    gain_tables_phases_dict['allcals_p_short'] = gaintables_temp_calibrators_p_short[-1]

    _plots.caltable(ctx, gain_tables_phases_dict['allcals_p_short'],
                    table_type=str(i) + table_stage_all_p_short + c.all_solint_short_p,
                    xaxis='time', yaxis='phase')

    # Longer phase solutions for all calibrators: usually the ones transferred to the science sources.
    table_stage_all_p_inf = '_allcal_p_inf_'
    gaintables_temp_calibrators_p_inf = run_gaincal(vis=vis_for_cal, calibration_dir=caldir,
                                                    field=calibrators_all, combine='',
                                                    gaintables=gaintables_apply_BP,
                                                    gainfield=gainfield_bandpass_apply,
                                                    scan='', refant=ref_antenna,
                                                    spw=spw_central,
                                                    calmode='p', gaintype='G',
                                                    solint=c.all_solint_long_p, ctx=ctx, flag_fp=flag_fp,
                                                    i=i, table_stage=table_stage_all_p_inf,
                                                    minsnr=minsnr
                                                    )
    gain_tables_phases_dict['allcals_p_inf'] = gaintables_temp_calibrators_p_inf[-1]

    _plots.caltable(ctx, gain_tables_phases_dict['allcals_p_inf'],
                    table_type=str(i) + table_stage_all_p_inf + c.all_solint_long_p,
                    xaxis='time', yaxis='phase')

    # Amplitude solutions for the complex calibrators with a short solution interval (should not be
    # smaller than 32s), using the short phase solutions. (v0.5 never overwrote these; reuse now follows cfg.pipeline.reuse_tables)
    table_stage_all_ap_short = '_allcal_ap_short_'
    gaintables_temp_calibrators_amp_short = run_gaincal(vis=vis_for_cal, calibration_dir=caldir,
                                                        field=calibrators_all, combine='',
                                                        gaintables=gaintables_temp_calibrators_p_short,
                                                        gainfield=gainfield_bandpass_apply + [''],
                                                        scan='', refant=ref_antenna,
                                                        spw=spw_central, calmode='ap', gaintype='G',
                                                        solint=c.all_solint_short_ap,
                                                        ctx=ctx, flag_fp=flag_fp,
                                                        i=i, table_stage=table_stage_all_ap_short,
                                                        minsnr=minsnr
                                                        )
    gain_tables_phases_dict['allcals_ap_short'] = gaintables_temp_calibrators_amp_short[-1]

    tt = str(i) + table_stage_all_ap_short + c.all_solint_short_ap
    _plots.caltable(ctx, gain_tables_phases_dict['allcals_ap_short'], table_type=tt, xaxis='time', yaxis='phase')
    _plots.caltable(ctx, gain_tables_phases_dict['allcals_ap_short'], table_type=tt, xaxis='time', yaxis='amp')

    # Amplitude solutions for the complex calibrators with an infinite solution interval (combine=scan),
    # using the inf phase solutions. (v0.5 never overwrote these; reuse now follows cfg.pipeline.reuse_tables)
    table_stage_allcal_ap_inf = '_allcal_ap_inf_'
    gaintables_temp_calibrators_amp_inf = run_gaincal(vis=vis_for_cal, calibration_dir=caldir,
                                                      field=calibrators_all,
                                                      gaintables=gaintables_temp_calibrators_p_inf,
                                                      gainfield=gainfield_bandpass_apply + [''],
                                                      combine='scan',
                                                      scan='', refant=ref_antenna,
                                                      spw=spw_central, calmode='ap', gaintype='G',
                                                      solint=c.all_solint_inf_ap,
                                                      ctx=ctx, flag_fp=flag_fp,
                                                      i=i, table_stage=table_stage_allcal_ap_inf,
                                                      minsnr=minsnr
                                                      )
    gain_tables_phases_dict['allcals_ap_inf'] = gaintables_temp_calibrators_amp_inf[-1]

    tt = str(i) + table_stage_allcal_ap_inf + c.all_solint_inf_ap
    _plots.caltable(ctx, gain_tables_phases_dict['allcals_ap_inf'], table_type=tt, xaxis='time', yaxis='phase')
    _plots.caltable(ctx, gain_tables_phases_dict['allcals_ap_inf'], table_type=tt, xaxis='time', yaxis='amp')

    # ---- Flux scale: bootstrap the flux densities of the transfer fields ----
    incremental = bool(ctx.cfg.fluxscale.incremental)
    flux_fitorder = fluxscale_fitorder(ctx, vis_for_cal)
    try:
        fluxtable_short = gain_tables_phases_dict['allcals_ap_short'].replace('.tb', '_flux_scale.tb')
        listfluxfile_short = fluxtable_short.replace('.tb', '_fluxinfo.txt')

        fluxtable = gain_tables_phases_dict['allcals_ap_inf'].replace('.tb', '_flux_scale.tb')
        listfluxfile = fluxtable.replace('.tb', '_fluxinfo.txt')

        # config values win; otherwise the FieldModel defaults (ID strings): reference = flux calibrator,
        # transfer = all calibrators (incl. the flux calibrator, as v0.5).
        fm = field_model(ctx)
        if transfer == '':
            transfer = ','.join(str(x) for x in fm.fluxscale_transfer())
        if reference == '':
            reference = ','.join(str(x) for x in fm.fluxscale_reference())

        # fluxscale refuses to write to an existing fluxtable. These are derived from the
        # (reused) amplitude tables, so recompute them on every run.
        for _fluxfile in [fluxtable_short, listfluxfile_short, fluxtable, listfluxfile]:
            _remove(_fluxfile)

        fluxscale(vis=vis_for_cal,
                  caltable=gain_tables_phases_dict['allcals_ap_short'],
                  fluxtable=fluxtable_short, reference=reference,
                  transfer=transfer, incremental=incremental,
                  listfile=listfluxfile_short, fitorder=flux_fitorder)

        flux_bp = fluxscale(vis=vis_for_cal,
                            caltable=gain_tables_phases_dict['allcals_ap_inf'],
                            fluxtable=fluxtable, reference=reference,
                            transfer=transfer, incremental=incremental,
                            listfile=listfluxfile, fitorder=flux_fitorder)
        # Workaround for observations with duplicated fields where one copy is fully flagged
        # (early EVLA, ~2010-2012): set `transfer` and `reference` to valid field IDs in the config.
    except Exception as e:
        log.critical(f"Fluxscale failed (reference={reference}, transfer={transfer}): {e}")
        raise RuntimeError(
            f"fluxscale failed for reference='{reference}', transfer='{transfer}' ({e}). "
            f"Check that every transfer field has solutions in "
            f"{gain_tables_phases_dict['allcals_ap_inf']}. With duplicated field names "
            f"(e.g. pointing or leakage scans with the same name as a calibrator), set "
            f"'transfer' and 'reference' to valid field IDs in the config.") from e

    if not isinstance(flux_bp, dict) or len(flux_bp) == 0 or not os.path.exists(fluxtable):
        raise RuntimeError(f"fluxscale returned no flux densities or did not create "
                           f"{fluxtable} (reference='{reference}', transfer='{transfer}').")

    # registry records of the fluxscale tables (always recomputed, never reused)
    for _src, _out in ((gain_tables_phases_dict['allcals_ap_short'], fluxtable_short),
                       (gain_tables_phases_dict['allcals_ap_inf'], fluxtable)):
        _rec = reg.new_record(ctx, _out, 'F', {'task': 'fluxscale', 'vis': vis_for_cal, 'caltable': _src,
                                               'reference': reference, 'transfer': transfer,
                                               'incremental': incremental, 'fitorder': flux_fitorder},
                              gaintables=[_src], stage='fluxscale', iteration=i, fields=transfer,
                              vis=vis_for_cal, flag_fp=flag_fp)
        if os.path.exists(_out):
            reg.check_solutions(ctx, _rec)
        reg.write_record(ctx, _rec)

    if flux_fitorder == 0:
        # setjy(standard='fluxscale') always reads spidx[1] (the spectral index), which
        # fluxscale does not return for fitorder=0. Set a flat spectrum explicitly.
        for _key, _fld in flux_bp.items():
            if isinstance(_fld, dict) and 'spidx' in _fld and len(_fld['spidx']) < 2:
                _fld['spidx'] = np.append(_fld['spidx'], 0.0)
                _fld['spidxerr'] = np.append(_fld['spidxerr'], 0.0)

    gain_tables_phases_dict['allcals_ap_fluxscale'] = fluxtable
    gain_tables_phases_dict['allcals_ap_fluxscale_short'] = fluxtable_short

    flux_phase_cals_scaled = setjy(vis=vis_for_cal, field=calibrators_all,
                                   scalebychan=True, standard='fluxscale',
                                   usescratch=True,
                                   fluxdict=flux_bp)

    tt = str(i) + table_stage_all_ap_short + c.all_solint_short_ap + '_flux_scale'
    _plots.caltable(ctx, fluxtable_short, table_type=tt, xaxis='time', yaxis='phase')
    _plots.caltable(ctx, fluxtable_short, table_type=tt, xaxis='time', yaxis='amp')
    tt = str(i) + table_stage_allcal_ap_inf + c.all_solint_inf_ap + '_flux_scale'
    _plots.caltable(ctx, fluxtable, table_type=tt, xaxis='time', yaxis='phase')
    _plots.caltable(ctx, fluxtable, table_type=tt, xaxis='time', yaxis='amp')

    # Bootstrap-flux plot of the phase calibrators. The setjy result is keyed by the real field IDs
    # (v0.5 assumed IDs 1..n, 03 bug 3).
    try:
        fm = field_model(ctx)
        names_by_id = {str(fid): fm.records[fid].name for fid in fm.ids('phase')}
        fluxdict = {k: v for k, v in (flux_phase_cals_scaled or {}).items() if k in names_by_id}
        _plots.bootstrap_fluxes(ctx, fluxdict, names_by_id,
                                os.path.join(ctx.paths.plots, 'phasecals_flux_density_bootstrap.pdf'),
                                spw_freqs_hz=spw_mean_freqs(vis_for_cal))
    except Exception as e:
        log.warning(f"Flux plot not generated due to: {e}")

    if incremental:
        gain_tables_ampphase_for_all_cals = [gain_tables_phases_dict['allcals_p_short'],
                                             gain_tables_phases_dict['allcals_ap_short'],
                                             gain_tables_phases_dict['allcals_ap_fluxscale']
                                             ]
        gain_tables_ampphase_for_science = [gain_tables_phases_dict['allcals_p_inf'],
                                            gain_tables_phases_dict['allcals_ap_inf'],
                                            gain_tables_phases_dict['allcals_ap_fluxscale']
                                            ]
    else:
        gain_tables_ampphase_for_all_cals = [gain_tables_phases_dict['allcals_p_short'],
                                             gain_tables_phases_dict['allcals_ap_fluxscale']
                                             ]
        gain_tables_ampphase_for_science = [gain_tables_phases_dict['allcals_p_inf'],
                                            gain_tables_phases_dict['allcals_ap_fluxscale']
                                            ]

    flag_FLUX_SCALE = False

    log.info(f"Creating flag-backup before applycal to calibrators iteration {i}")
    save_flag_version(vis_for_cal, 'before_applycal_' + str(i), 'Flags before applycal, iteration' + str(i) + '.')

    log.info(f"Reporting flags before applycal to calibrators iteration {i}")
    summary_before_applycal_to_calibrators = flagdata(vis=vis_for_cal, mode='summary')
    report_flag(summary_before_applycal_to_calibrators, 'field')

    # Tables for the applycal to the calibrators (shorter phase and amplitude solutions).
    gain_tables_to_apply_all_cals = gaintables_apply_BP.copy()
    gain_tables_to_apply_all_cals.extend(gain_tables_ampphase_for_all_cals)
    # Tables for the applycal to the science sources (longer or inf phase and amplitude solutions).
    gain_tables_to_apply_science = gaintables_apply_BP.copy()
    gain_tables_to_apply_science.extend(gain_tables_ampphase_for_science)

    # record the products before applying
    ctx.gain_tables[str(i)] = dict(gain_tables_phases_dict,
                                   ampphase_for_science=list(gain_tables_ampphase_for_science),
                                   to_apply_science=list(gain_tables_to_apply_science))
    ctx.fluxes[str(i)] = {'fluxscale': flux_bp, 'setjy': flux_phase_cals_scaled,
                          'fitorder': flux_fitorder, 'reference': reference, 'transfer': transfer}
    gainfield_by_field = {}
    lists = ctx.apply_lists.setdefault(str(i), {})
    lists['cal'] = {'gaintable': list(gain_tables_to_apply_all_cals),
                    'gainfield_by_field': gainfield_by_field}

    # One applycal per calibrator field ID; the gain tables are interpolated from that field's own solutions.
    for calibrator_field in ctx.calibrators_all_arr:
        ext_cal_fields = [calibrator_field] * len(gain_tables_ampphase_for_all_cals)
        gainfield_to_apply_all_cals = gainfield_bandpass_apply.copy()
        gainfield_to_apply_all_cals.extend(ext_cal_fields)
        gainfield_by_field[calibrator_field] = list(gainfield_to_apply_all_cals)

        log.info(f"Applying calibration to: {calibrator_field}")
        log.info(f"     => Gainfields are: {gainfield_to_apply_all_cals}")
        log.info(f"     => Gaintables are: {gain_tables_to_apply_all_cals}")
        applycal(vis=vis_for_cal,
                 field=calibrator_field,
                 applymode=c.ph_ap_applymode,
                 gaintable=gain_tables_to_apply_all_cals, flagbackup=False,
                 gainfield=gainfield_to_apply_all_cals, calwt=calwt)

    log.info(f"Reporting flags after applycal to calibrators iteration {i}")
    summary_after_applycal_to_calibrators = flagdata(vis=vis_for_cal, mode='summary')
    record_flags(ctx, f'applycal_cals_{i}', summary_after_applycal_to_calibrators)
    report_flag(summary_after_applycal_to_calibrators, 'field')

    return (gain_tables_phases_dict,
            gain_tables_ampphase_for_science, gain_tables_to_apply_science,
            flag_FLUX_SCALE)
