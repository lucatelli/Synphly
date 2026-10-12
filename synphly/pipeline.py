"""
The Synphly pipeline: an ordered registry of steps (the v0.5 ``main.py`` order) with explicit state.

    STEPS = set_working_dir, load_data, ms_info, pre_flagging, tfcrop_raw, manual_flagging, run_aoflagger,
            average, intent_flagging, initial_corrections, flux_scale_setjy, select_refant, bandpass_1, gains_1,
            apply_science_1, bandpass_2, gains_2, apply_science_2, statwt, flag_science, split, imaging

Each step is enabled by its v0.5 ``do_*`` config switch (``Step.enabled``). Every step is run through
``_step()``, which records ``ctx.steps[name] = {status, start, end, duration_s, error}`` and saves
``<wd>/synphly_state.json`` after the step. ``run_pipeline(cfg, from_step=..., only=..., force=...)`` resumes
from the saved state: the steps before ``from_step`` (or not in ``only``) are skipped and their outputs are
taken from the state; a missing output stops the run before anything is executed, naming the step that
produces it.

Differences from v0.5 main.py (deliberate):
- load_data, ms_info and refant failures stop the run (v0.5 logged them and continued; 03 bug 11).
- A configured refant no longer raises NameError (03 bug 1).
- intent_flagging (new, 03 issue 12) re-applies the pre-flagging intent flags to vis_for_cal before
  initial_corrections.
- The science rflag uses freqdevscale=rflag_freqdevscale_science (v0.5 passed rflag_timedevscale_science;
  03 bug 2).
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from .context import Context
from .logs import absolutize_config_paths, run_directory, setup_logging, write_resolved_config

log = logging.getLogger(__name__)


class PipelineError(RuntimeError):
    """Invalid step selection or missing outputs of earlier steps."""


def _now() -> str:
    return datetime.now().isoformat(timespec='seconds')


def _step(ctx, name, func, *args, optional=False, **kwargs):
    """Run one step, record its status in ctx.steps and save the state.

    ``optional=True``: a failure is logged as critical and the run continues (only used for AOFlagger,
    as in v0.5)."""
    t0 = datetime.now()
    rec = {'status': 'running', 'start': t0.isoformat(timespec='seconds'), 'end': None, 'duration_s': None,
           'error': None}
    ctx.steps[name] = rec
    ctx.current_step = name
    log.info(f"==== Step {name} ====")
    try:
        result = func(*args, **kwargs)
    except Exception as e:
        rec.update(status='failed', end=_now(), duration_s=round((datetime.now() - t0).total_seconds(), 1),
                   error=f"{type(e).__name__}: {e}")
        log.critical(f"Exception {e} in step {name}")
        _save(ctx)
        if optional:
            return None
        raise
    finally:
        ctx.current_step = ''
    rec.update(status='done', end=_now(), duration_s=round((datetime.now() - t0).total_seconds(), 1))
    _save(ctx)
    return result


def _save(ctx):
    try:
        ctx.save()
    except OSError as e:
        log.warning(f"Could not save the pipeline state to {ctx.state_file}: {e}")


def _apply_list(ctx, i, name):
    try:
        return ctx.apply_lists[str(i)][name]
    except KeyError:
        raise RuntimeError(f"No '{name}' apply list for iteration {i}: run the bandpass step of "
                           f"iteration {i} first.") from None


def _gain_tables(ctx, i):
    try:
        return ctx.gain_tables[str(i)]
    except KeyError:
        raise RuntimeError(f"No gain tables for iteration {i}: run the gain calibration step of "
                           f"iteration {i} first.") from None


# ======================================================================================================
# step bodies (each takes ctx; results are stored in ctx)
# ======================================================================================================
def _set_working_dir(ctx):
    from .steps.import_data import set_working_dir
    set_working_dir(ctx)


def _load_data(ctx):
    from .steps.import_data import import_data
    log.info("Running CASA task importasdm")
    ctx.vis_for_cal = import_data(ctx)


def _ms_info(ctx):
    from .steps.ms_info import resolve_fields
    log.info("Getting ms information")
    resolve_fields(ctx, ctx.vis_for_cal)


def _pre_flagging(ctx):
    from .steps.preflag import pre_flagging
    log.info(" > Flagging data")
    pre_flagging(ctx, vis=ctx.vis_for_cal)


def _tfcrop_raw(ctx):
    from .steps.preflag import tfcrop_raw
    tfcrop_raw(ctx, vis=ctx.vis_for_cal, field=ctx.calibrators_all)


def _manual_flagging(ctx):
    from .steps.preflag import manual_flagging
    log.info(" ++==>> Running manual flagging.")
    manual_flagging(ctx, vis=ctx.vis_for_cal)


def _run_aoflagger(ctx):
    from .steps.preflag import run_aoflagger_nat, run_aoflagger_sif
    log.info(" ++==>> Flagging with AOflagger")
    if ctx.cfg.globals.use_singularity:
        run_aoflagger_sif(ctx, vis=ctx.vis_for_cal)
    else:
        run_aoflagger_nat(ctx, vis=ctx.vis_for_cal)


def _average(ctx):
    from .steps.average import average
    average(ctx)


def _intent_flagging(ctx):
    from .steps.preflag import intent_flagging
    intent_flagging(ctx, vis=ctx.vis_for_cal)


def _initial_corrections(ctx):
    from .steps.initial_corrections import initial_corrections
    log.info("Correcting antenna pos, gaincurves, sys power and atmospheric corrections")
    ctx.init_tables, ctx.init_tables_dict = initial_corrections(ctx, vis=ctx.vis_for_cal)


def _flux_scale_setjy(ctx):
    from .steps.setjy_fluxcal import flux_scale_setjy
    flux_density_data, _, _ = flux_scale_setjy(ctx, vis=ctx.vis_for_cal, band=ctx.cfg.calibrate.band,
                                               flux_density='', model_image='')
    ctx.fluxes['setjy_fluxcal'] = flux_density_data


def _select_refant(ctx):
    from .steps.refant import select_refant
    select_refant(ctx)


def _bandpass(i):
    def run(ctx):
        from .steps import _plots
        from .steps.bandpass import bandpass_cal
        log.info("Running bandpass calibration")
        if not ctx.init_tables:
            log.warning("No a-priori (initial_corrections) tables in the state: the bandpass is solved without "
                        "antpos/gaincurve/opacity corrections.")
        calwt = ctx.cfg.calibrate.calwt_1st if i == 1 else ctx.cfg.calibrate.calwt_2nd
        bandpass_cal(ctx, i=i, calwt=calwt)
        _plots.flag_stats(ctx)
    return run


def _gains(i):
    def run(ctx):
        from .steps import _plots
        from .steps.autoflag import clip_data, flag_calibrators
        from .steps.gains import cal_phases_amplitudes
        cfg = ctx.cfg
        fl = cfg.flagging
        calwt = cfg.calibrate.calwt_1st if i == 1 else cfg.calibrate.calwt_2nd
        log.info("Running gain calibration")
        transfer = _apply_list(ctx, i, 'transfer')
        cal_phases_amplitudes(ctx, transfer['gaintable'], transfer['gainfield'],
                              transfer=cfg.sources.transfer, reference=cfg.sources.reference,
                              calwt=calwt, i=i)
        flag_calibrators(ctx, i=i)
        # v0.5: clip only after the 1st gain calibration (not after the 2nd)
        if i == 1 and fl.do_clip_data:
            clip_data(ctx, vis=ctx.vis_for_cal, field=ctx.calibrators_all,
                      clipminmax=[fl.clipmin, fl.clipmax],
                      datacolumn='corrected')
        _plots.visibilities(ctx, ctx.vis_for_cal, stage='after',
                            kind=f'after_apply_calibration_and_flag_iter_{i}',
                            FIELDS=_plots.plot_fields(ctx, ctx.calibrators_all_arr))
        _plots.flag_stats(ctx)
    return run


def _apply_science(i):
    def run(ctx):
        from .steps import _plots
        from .steps.applycal import apply_cal_to_science
        from .steps.split import split_fields
        calwt = ctx.cfg.calibrate.calwt_1st if i == 1 else ctx.cfg.calibrate.calwt_2nd
        transfer = _apply_list(ctx, i, 'transfer')
        gt = _gain_tables(ctx, i)
        apply_cal_to_science(ctx, vis=ctx.vis_for_cal,
                             gain_tables_to_apply_science_final=gt['to_apply_science'],
                             gainfield_bandpass_apply_final=transfer['gainfield'],
                             gain_tables_ampphase_for_science_final=gt['ampphase_for_science'],
                             i=i, calwt=calwt)
        _plots.visibilities(ctx, ctx.vis_for_cal, stage='after', kind=f'after_apply_cal_{i}',
                            extra_plot=False, FIELDS=_plots.plot_fields(ctx, ctx.target_fields_arr))
        if i == 1:
            split_fields(ctx, ctx.vis_for_cal, iter='_1')
        _plots.flag_stats(ctx)
    return run


def _statwt(ctx):
    from .steps.statwt import run_statwt
    run_statwt(ctx, vis=ctx.vis_for_cal)


def _flag_science(ctx):
    from .steps import _plots
    from .steps.autoflag import flag_science, report_science_flags
    flag_science(ctx)
    _plots.visibilities(ctx, ctx.vis_for_cal, stage='after', kind='final_science_after_flag',
                        extra_plot=False, FIELDS=_plots.plot_fields(ctx, ctx.target_fields_arr))
    report_science_flags(ctx)
    _plots.flag_stats(ctx)


def _split(ctx):
    from .steps.split import split_fields
    split_fields(ctx, ctx.vis_for_cal)


def _imaging(ctx):
    from .steps.imaging import run_imaging_tclean
    from .steps.ms_info import field_names
    # the split directories and the split MSs are named after the field NAME (as v0.5)
    run_imaging_tclean(ctx, field_names(ctx, ctx.target_fields_arr))


# ======================================================================================================
# registry
# ======================================================================================================
@dataclass(frozen=True)
class Step:
    name: str
    run: Callable
    enabled: Callable            # cfg -> bool
    switch: str                  # config switch(es), for messages
    requires: tuple = ()         # outputs of earlier steps (keys of OUTPUTS)
    produces: tuple = ()
    optional: bool = False       # a failure is logged and the run continues (AOFlagger, as v0.5)
    group: str = ''
    doc: str = ''


def _fl(cfg):
    return cfg.flagging.do_flagging


STEPS = (
    Step('set_working_dir', _set_working_dir, lambda c: True, '(always)',
         doc='create <wd> and its flags/, calibration/, plots/ directories'),
    Step('load_data', _load_data, lambda c: c.globals.load_data, 'globals.load_data',
         produces=('vis_for_cal',), doc='importasdm (if the MS does not exist), Hanning smoothing, listobs'),
    Step('ms_info', _ms_info, lambda c: c.globals.ms_info, 'globals.ms_info',
         produces=('fields',), doc='field model and roles by field ID'),
    Step('pre_flagging', _pre_flagging, lambda c: _fl(c) and c.flagging.do_pre_flagging,
         'flagging.do_flagging + do_pre_flagging', requires=('fields',), group='flagging',
         doc='autocorr, shadow, zeros, quack, edge channels, pointing/UNSPECIFIED/SYSTEM_CONFIGURATION'),
    Step('tfcrop_raw', _tfcrop_raw, lambda c: _fl(c) and c.flagging.do_tfcrop_raw,
         'flagging.do_flagging + do_tfcrop_raw', requires=('fields',), group='flagging',
         doc='tfcrop on the raw data of the calibrators'),
    Step('manual_flagging', _manual_flagging, lambda c: _fl(c) and c.flagging.manual_file != '',
         'flagging.do_flagging + manual_file', requires=('fields',), group='flagging',
         doc='flagdata(mode=list) with the manual flag file'),
    Step('run_aoflagger', _run_aoflagger, lambda c: _fl(c) and c.flagging.use_aoflagger,
         'flagging.do_flagging + use_aoflagger', requires=('fields',), optional=True, group='flagging',
         doc='AOFlagger (singularity or native); a failure does not stop the run'),
    Step('average', _average, lambda c: c.average.do_average, 'average.do_average', requires=('fields',),
         produces=('vis_for_cal',), doc='time/channel averaging into <vis>.avg.ms (reused if it exists)'),
    Step('intent_flagging', _intent_flagging, lambda c: c.flagging.do_intent_flagging,
         'flagging.do_intent_flagging', requires=('fields',),
         doc='re-apply the pointing/UNSPECIFIED/SYSTEM_CONFIGURATION intent flags to the MS being calibrated'),
    Step('initial_corrections', _initial_corrections, lambda c: c.calibrate.do_initial_cal,
         'calibrate.do_initial_cal', requires=('fields',), produces=('init_tables',),
         doc='antenna positions, gain curve, opacity tables'),
    Step('flux_scale_setjy', _flux_scale_setjy, lambda c: c.calibrate.do_setjy, 'calibrate.do_setjy',
         requires=('fields',), doc='Perley-Butler 2017 model of the flux calibrator'),
    Step('select_refant', _select_refant, lambda c: c.calibrate.do_refant, 'calibrate.do_refant',
         requires=('fields',), produces=('ref_antenna',), doc='reference antenna (configured or automatic)'),
    Step('bandpass_1', _bandpass(1), lambda c: c.calibrate.do_bandpass_1st_run, 'calibrate.do_bandpass_1st_run',
         requires=('fields', 'ref_antenna'), produces=('transfer_1',), doc='bandpass chain, pass 1'),
    Step('gains_1', _gains(1), lambda c: c.calibrate.do_gain_calibration_1st_run,
         'calibrate.do_gain_calibration_1st_run', requires=('fields', 'ref_antenna', 'transfer_1'),
         produces=('gains_1',), doc='gain chain + fluxscale + calibrator applycal/flagging, pass 1'),
    Step('apply_science_1', _apply_science(1), lambda c: c.calibrate.do_apply_science_1st_run,
         'calibrate.do_apply_science_1st_run', requires=('fields', 'transfer_1', 'gains_1'),
         doc='applycal to the targets + split (_1), pass 1'),
    Step('bandpass_2', _bandpass(2), lambda c: c.calibrate.do_bandpass_2nd_run, 'calibrate.do_bandpass_2nd_run',
         requires=('fields', 'ref_antenna'), produces=('transfer_2',), doc='bandpass chain, pass 2'),
    Step('gains_2', _gains(2), lambda c: c.calibrate.do_gain_calibration_2nd_run,
         'calibrate.do_gain_calibration_2nd_run', requires=('fields', 'ref_antenna', 'transfer_2'),
         produces=('gains_2',), doc='gain chain + fluxscale + calibrator applycal/flagging, pass 2'),
    Step('apply_science_2', _apply_science(2), lambda c: c.calibrate.do_apply_science,
         'calibrate.do_apply_science', requires=('fields', 'transfer_2', 'gains_2'),
         doc='applycal to the targets, pass 2'),
    Step('statwt', _statwt, lambda c: c.calibrate.do_run_statwt, 'calibrate.do_run_statwt',
         requires=('fields',), doc='statwt on the corrected data'),
    Step('flag_science', _flag_science, lambda c: c.calibrate.do_flag_science, 'calibrate.do_flag_science',
         requires=('fields',), doc='rflag/tfcrop on the targets'),
    Step('split', _split, lambda c: c.calibrate.do_split, 'calibrate.do_split', requires=('fields',),
         doc='split every field into <wd>/fields/<name>/'),
    Step('imaging', _imaging, lambda c: c.imaging.do_imaging, 'imaging.do_imaging', requires=('fields',),
         doc='quick-look tclean of the split targets'),
)
STEP_NAMES = tuple(s.name for s in STEPS)
_BY_NAME = {s.name: s for s in STEPS}

# output key -> (predicate on ctx, producing step)
OUTPUTS = {
    'vis_for_cal': (lambda ctx: bool(ctx.vis_for_cal), 'load_data'),
    'fields': (lambda ctx: bool(ctx.field_model) and bool(ctx.calibrators_all) and bool(ctx.target), 'ms_info'),
    'init_tables': (lambda ctx: bool(ctx.init_tables), 'initial_corrections'),
    'ref_antenna': (lambda ctx: bool(ctx.ref_antenna), 'select_refant'),
    'transfer_1': (lambda ctx: 'transfer' in ctx.apply_lists.get('1', {}), 'bandpass_1'),
    'gains_1': (lambda ctx: '1' in ctx.gain_tables, 'gains_1'),
    'transfer_2': (lambda ctx: 'transfer' in ctx.apply_lists.get('2', {}), 'bandpass_2'),
    'gains_2': (lambda ctx: '2' in ctx.gain_tables, 'gains_2'),
}


def parse_steps(value) -> list:
    """'a,b' or ['a', 'b'] -> validated step names ('all' allowed only where noted by the caller)."""
    if value is None:
        return []
    names = [t.strip() for t in (value.split(',') if isinstance(value, str) else value) if str(t).strip()]
    bad = [n for n in names if n not in _BY_NAME and n != 'all']
    if bad:
        raise PipelineError(f"Unknown step(s) {bad}. Valid steps: {', '.join(STEP_NAMES)}")
    return names


def plan(cfg, from_step=None, only=None) -> list:
    """[(Step, action)] for every registered step; action is 'run' or 'skip: <reason>'."""
    only = parse_steps(only)
    if 'all' in only:
        raise PipelineError("--only does not accept 'all'")
    if from_step is not None:
        parse_steps([from_step])
        if from_step == 'all':
            raise PipelineError("--from does not accept 'all'")
    out = []
    started = from_step is None
    stop = False
    for s in STEPS:
        if s.name == from_step:
            started = True
        if stop:
            action = 'skip: globals.run_only_ms_info'
        elif s.name == 'set_working_dir':
            action = 'run'
        elif only:
            if s.name not in only:
                action = 'skip: not in --only'
            elif not s.enabled(cfg):
                raise PipelineError(f"Step '{s.name}' was requested with --only but is disabled by "
                                    f"{s.switch} in the config; enable it there.")
            else:
                action = 'run'
        elif not started:
            action = f'skip: before --from {from_step}'
        elif not s.enabled(cfg):
            action = f'skip: disabled ({s.switch})'
        else:
            action = 'run'
        if s.name == 'ms_info' and cfg.globals.run_only_ms_info and not only:
            stop = True
        out.append((s, action))
    return out


def check_requirements(ctx, steps_to_run) -> None:
    """Raise PipelineError if a step to run needs an output that neither the state nor an earlier step to run
    provides."""
    available = {k for k, (pred, _) in OUTPUTS.items() if pred(ctx)}
    problems = []
    for s in steps_to_run:
        missing = [r for r in s.requires if r not in available]
        for r in missing:
            producer = OUTPUTS[r][1]
            problems.append(f"step '{s.name}' needs '{r}' (produced by step '{producer}'), which is not in "
                            f"{ctx.state_file} and is not produced by an earlier step of this run")
        available.update(s.produces)
    if problems:
        raise PipelineError("Cannot run the requested steps:\n  - " + "\n  - ".join(problems)
                            + "\nRun the producing step(s) first (or include them, e.g. with --from).")


def run_pipeline(cfg, ctx: Context | None = None, from_step=None, only=None, force=None) -> Context:
    """
    Run the pipeline for ``cfg`` (a synphly.config.Config). Returns the run context.

    from_step: start at this step; the context is loaded from <wd>/synphly_state.json.
    only:      run only these steps (list or comma string); the context is loaded from the state.
    force:     recompute the tables of these steps ('all' = every step), i.e. reuse_tables='never' for them.
    """
    absolutize_config_paths(cfg)
    resume = from_step is not None or bool(parse_steps(only))
    if ctx is None:
        if resume:
            ctx = Context.load(cfg)
            if not os.path.exists(ctx.state_file):
                raise PipelineError(f"--from/--only need the state of a previous run, but {ctx.state_file} "
                                    f"does not exist. Run the full pipeline first.")
        else:
            ctx = Context.new(cfg)
    ctx.force_steps = parse_steps(force)
    steps = plan(cfg, from_step=from_step, only=only)
    to_run = [s for s, action in steps if action == 'run']
    check_requirements(ctx, to_run)

    # CASA writes casa-*.log, <task>.last and TempLattice* into the cwd: run inside <wd>/logs
    with run_directory(ctx.paths.logs):
        setup_logging(ctx)
        try:
            write_resolved_config(ctx)
        except OSError as e:
            log.warning(f"Could not write the resolved configuration: {e}")
        log.info("Steps: " + ', '.join(f"{s.name}" + ('' if a == 'run' else f" [{a}]") for s, a in steps))
        if ctx.force_steps:
            log.info(f"Tables recomputed for step(s): {', '.join(ctx.force_steps)}")
        try:
            _run_steps(ctx, cfg, to_run)
        except Exception as e:
            _report(ctx, 'failed', f"{type(e).__name__}: {e}")
            raise
        _report(ctx, 'finished')

    if cfg.globals.run_only_ms_info and not only:
        return ctx
    log.info("Synphly pipeline finished.")
    return ctx


def _run_steps(ctx, cfg, to_run):
    from .steps import _plots
    ran_flagging = False
    for idx, s in enumerate(to_run):
        _step(ctx, s.name, s.run, ctx, optional=s.optional)
        if s.group == 'flagging':
            ran_flagging = True
        nxt = to_run[idx + 1] if idx + 1 < len(to_run) else None
        if ran_flagging and (nxt is None or nxt.group != 'flagging'):
            if not cfg.flagging.use_aoflagger:
                log.info(" --==>> Flagging using aoflagger not requested")
            _plots.flag_stats(ctx)        # v0.5: plot_flag_stats at the end of the flagging block
            ran_flagging = False


def _report(ctx, status, error=None):
    """Write run_report.json/.md (best effort: a report failure never hides the run result)."""
    try:
        from .reporting.summary import write_report
        write_report(ctx, status=status, error=error)
    except Exception as e:   # noqa: BLE001 - the report is optional
        log.warning(f"Could not write the run report: {type(e).__name__}: {e}")


def dry_run(cfg, from_step=None, only=None, force=None) -> str:
    """Text of the steps that would run and of the resolved field roles. Runs no CASA task that modifies
    data (the field model is read from the state, or from the MS with read-only msmetadata)."""
    import tempfile
    from .fields import FieldModel
    absolutize_config_paths(cfg)
    steps = plan(cfg, from_step=from_step, only=only)
    resume = from_step is not None or bool(parse_steps(only))
    ctx = Context.load(cfg) if resume or os.path.exists(Context.new(cfg).state_file) else Context.new(cfg)
    lines = [f"Synphly dry run: {cfg.source_path or '<config>'}", f"working directory: "
             f"{ctx.paths.working_directory}", '', 'Steps:']
    for s, action in steps:
        lines.append(f"  {'RUN ' if action == 'run' else 'skip'} {s.name:<20} "
                     f"{'' if action == 'run' else action[6:]}")
    force_list = parse_steps(force)
    if force_list:
        lines.append(f"Tables recomputed (--force): {', '.join(force_list)}")
    if resume:
        try:
            check_requirements(ctx, [s for s, a in steps if a == 'run'])
            lines.append('Requirements from the saved state: OK')
        except PipelineError as e:
            lines.append(f"ERROR: {e}")
    lines.append('')
    fm = None
    if ctx.field_model:
        fm = FieldModel.from_dict(ctx.field_model)
        lines.append(f"Field roles (from {ctx.state_file}):")
    else:
        vis = ctx.vis_for_cal or ctx.vis
        if cfg.globals.do_hanning and os.path.exists(vis.replace('.ms', '_hs.ms')):
            vis = vis.replace('.ms', '_hs.ms')
        if os.path.exists(vis):
            # (first CASA import writes a casa-*.log into the cwd: keep it out of the launch directory)
            rundir = ctx.paths.logs if os.path.isdir(ctx.paths.working_directory) else tempfile.gettempdir()
            with run_directory(rundir):
                fm = FieldModel.from_ms(vis).resolve_roles(cfg.sources)
            lines.append(f"Field roles (from {vis}, read only):")
        else:
            lines.append(f"Field roles: {vis} does not exist yet (it is made by load_data).")
    if fm is not None:
        lines.append(fm.report())
    return '\n'.join(lines)


def steps_table() -> str:
    """Text listing of the registered steps (``synphly steps``)."""
    w = max(len(n) for n in STEP_NAMES)
    return '\n'.join(f"{s.name:<{w}}  {s.switch:<45}  {s.doc}" for s in STEPS)
