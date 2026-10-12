"""
Thin wrappers around the CASA solvers (ported from v0.5 ``calibrate.py``).

Table naming (unchanged from v0.5)::

    {calibration_dir}/{i}{table_stage}{solint}_{basename(vis).replace('.ms', '.tb')}

Reuse of an existing table follows ``cfg.pipeline.reuse_tables`` through the table registry
(``synphly.calib.tables``): with the default 'auto' a table is reused only if its recorded input hash matches
('always' is the v0.5 behaviour: reuse whenever the file exists). After each solve the per-field solution
counts are logged; a missing or entirely flagged table raises ``CalTableError``.
"""
from __future__ import annotations

import logging
import os

import numpy as np

from ..casa import bandpass, gaincal, open_msmd
from . import tables as reg

log = logging.getLogger(__name__)


def caltable_name(calibration_dir: str, vis: str, i, table_stage: str, solint: str) -> str:
    return f"{calibration_dir}/{i}{table_stage}{solint}_{os.path.basename(vis.replace('.ms', '.tb'))}"


def task_name(task) -> str:
    """Stable name of a CASA task for the table input hash. casatasks tasks are instances of classes such as
    ``_gaincal`` without ``__name__``; their default repr contains a memory address that changes in every process
    (that made every table look changed on a re-run)."""
    name = getattr(task, '__name__', None) or type(task).__name__
    return name.lstrip('_')


def _solve(ctx, task, kind, call_kwargs, caltable, gaintables, i, table_stage, solint, field, gainfields,
           flag_fp):
    """Registry + reuse policy + solve + solution check for one table. Returns the CalTable record."""
    params = {'task': task_name(task)}
    params.update({k: v for k, v in call_kwargs.items() if k not in ('caltable',)})
    rec = reg.new_record(ctx, caltable, kind, params, gaintables=gaintables, stage=table_stage,
                         iteration=i, solint=solint, fields=field, gainfields=gainfields,
                         vis=call_kwargs['vis'], flag_fp=flag_fp)
    if not reg.prepare(ctx, rec):
        task(**call_kwargs)
    reg.check_solutions(ctx, rec, expected_fields=field)
    reg.write_record(ctx, rec)
    return rec


def run_bandpass(vis, calibration_dir, field, scan,
                 refant, spw, solint, minsnr,
                 gaintables, i, table_stage, combine, bandtype,
                 fillgaps,
                 solnorm=False,
                 refantmode='strict', ctx=None, flag_fp=None):
    """
    Solve a bandpass table and return ``gaintables + [caltable]``.

    Forwarded to ``bandpass``: solnorm and fillgaps. NOT forwarded (v0.5 behaviour, kept on purpose):
    ``refantmode`` (bandpass runs with the CASA default). v0.5 also accepted a ``normtype`` it never forwarded;
    it is gone (the CASA 6.7 bandpass task has no normtype parameter).
    Raises if the task fails, does not produce the table or the table is entirely flagged (03 bug 6).
    """
    caltable = None
    try:
        log.info(f"Running bandpass for field {field}.")
        log.info(f" >> Stage {table_stage},  with solint of {solint}.")
        caltable = caltable_name(calibration_dir, vis, i, table_stage, solint)
        log.info(f"     ++=> Caltable will be:, {caltable}")
        kw = dict(vis=vis, caltable=caltable, scan=scan,
                  field=field, refant=refant, spw=spw,
                  combine=combine, bandtype=bandtype,
                  fillgaps=fillgaps,
                  solint=solint, minsnr=minsnr,
                  solnorm=solnorm,
                  gaintable=gaintables)
        _solve(ctx, bandpass, 'B', kw, caltable, gaintables, i, table_stage, solint, field, [], flag_fp)
        _gaintables_temp = gaintables.copy()
        _gaintables_temp.append(caltable)
        return _gaintables_temp
    except Exception as e:
        log.critical(f"Exception {e} while generating {caltable}")
        raise


def run_gaincal(vis, calibration_dir, field, scan,
                refant, spw, calmode, solint, minsnr,
                gaintype, gaintables, i, table_stage, combine='', gainfield=None,
                refantmode='strict', ctx=None, flag_fp=None):
    """
    Solve a gaincal table and return ``gaintables + [caltable]``.

    gaincal always runs with ``solnorm=False`` (passed explicitly; it is also CASA's default and what v0.5
    effectively did: v0.5 accepted ``solnorm``/``normtype`` here but never forwarded them, 03 bug 8). Do not
    normalise these tables: fluxscale derives the flux densities from the amplitude gains of the
    ``allcal_ap_*`` tables, and solnorm=True would make it return ~1 for every field.
    """
    if gainfield is None:
        gainfield = []
    caltable = None
    try:
        log.info(f"Running gaincal [{calmode}] for field(s) {field}.")
        log.info(f" >> Stage {table_stage}  with solint of {solint}.")
        caltable = caltable_name(calibration_dir, vis, i, table_stage, solint)
        log.info(f"     ++=> Caltable will be:, {caltable}")
        kw = dict(vis=vis, caltable=caltable, scan=scan,
                  field=field, refant=refant, spw=spw, combine=combine,
                  calmode=calmode, solint=solint, minsnr=minsnr, gaintype=gaintype,
                  refantmode=refantmode,
                  solnorm=False,   # never normalise: solnorm=True on the ap tables breaks fluxscale (03 bug 8)
                  gaintable=gaintables, gainfield=gainfield)
        _solve(ctx, gaincal, gaintype if gaintype == 'K' else 'G', kw, caltable, gaintables, i, table_stage,
               solint, field, gainfield, flag_fp)
        _gaintables_temp = gaintables.copy()
        _gaintables_temp.append(caltable)
        return _gaintables_temp
    except Exception as e:
        log.critical(f"Exception {e} while generating {caltable}")
        raise


def get_chan_spws_map(vis, edge_channel_frac, edge_channel_flag_frac=0.05,
                      compute_edge_for_flagging=False):
    """
    Return ``(spw_skip_edge, spw_central)`` channel selections (and ``chan_spw_edge_flag`` if
    ``compute_edge_for_flagging``).

    - spw_skip_edge: ``spw:int(f*n)~int((1-f)*n)`` with f = edge_channel_frac (cfg.flagging.edge_channel_frac)
    - spw_central: ``spw:int(0.25*n)~int(0.75*n)``
    - chan_spw_edge_flag: ``spw:0~int(g*n),spw:int((1-g)*n)~n-1`` with g = edge_channel_flag_frac
    """
    with open_msmd(vis) as msmd:
        bandwidth = msmd.bandwidths()
        nspw = len(bandwidth)

        chan_spw_skip_edge_map = np.empty(nspw, dtype=object)
        for spw_id in range(nspw):
            chan_spw_skip_edge_map[spw_id] = (f"{spw_id}:{int(edge_channel_frac * msmd.nchan(spw_id))}~"
                                              f"{int(((1 - edge_channel_frac) * msmd.nchan(spw_id)))}")
        spw_skip_edge = ','.join(chan_spw_skip_edge_map)

        chan_spw_central_map = np.empty(nspw, dtype=object)
        for spw_id in range(nspw):
            chan_spw_central_map[spw_id] = (f"{spw_id}:"
                                            f"{int(0.25 * msmd.nchan(spw_id))}~"
                                            f"{int(0.75 * msmd.nchan(spw_id))}")
        spw_central = ','.join(chan_spw_central_map)

        chan_spw_edge_flag = None
        if compute_edge_for_flagging:
            chan_spw_edge_flag = np.empty(nspw, dtype=object)
            for spw_id in range(nspw):
                chan_spw_edge_flag[spw_id] = \
                    (f"{spw_id}:0~{int(edge_channel_flag_frac * msmd.nchan(spw_id))},"
                     f"{spw_id}:{int((1 - edge_channel_flag_frac) * msmd.nchan(spw_id))}~"
                     f"{msmd.nchan(spw_id) - 1}")
            chan_spw_edge_flag = ','.join(chan_spw_edge_flag)
    if compute_edge_for_flagging:
        return spw_skip_edge, spw_central, chan_spw_edge_flag
    return spw_skip_edge, spw_central
