"""
Run context: the explicit replacement of the v0.5 module-level globals.

Every pipeline step receives ``ctx`` (and reads ``ctx.cfg``). Anything a later step needs is stored here,
never in module globals. ``Context.save()``/``Context.load()`` persist the JSON-serialisable part to
``<working_directory>/synphly_state.json`` so that a run can be resumed from any step.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from typing import Optional

from .config import Config

STATE_FILENAME = 'synphly_state.json'
_RUNTIME_ONLY = ('flag_data_steps', 'current_step', 'force_steps')


def jsonable(obj):
    """Recursively convert numpy arrays/scalars (e.g. in setjy/fluxscale results) to plain Python."""
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    if hasattr(obj, 'tolist'):          # numpy array or numpy scalar
        return obj.tolist()
    return obj


@dataclass
class Paths:
    working_directory: str
    calibration: str
    plots: str
    flags: str
    logs: str
    fields: str

    @classmethod
    def from_working_directory(cls, wd: str) -> 'Paths':
        wd = wd.rstrip('/')
        return cls(working_directory=wd,
                   calibration=f'{wd}/calibration',
                   plots=f'{wd}/plots',
                   flags=f'{wd}/flags',
                   logs=f'{wd}/logs',
                   fields=f'{wd}/fields')


@dataclass
class Context:
    cfg: Config
    paths: Paths

    # measurement sets
    vis: str = ''                 # <wd>/<experiment>.ms (as imported)
    vis_for_cal: str = ''         # the MS being calibrated (raw / hanning / .avg.ms)

    # field roles (comma-separated selection strings, as passed to CASA `field=`)
    flux_calibrator: str = ''
    bandpass_calibrator: str = ''
    phase_calibrator: str = ''
    target: str = ''
    calibrators_all: str = ''
    calibrators_all_arr: list = field(default_factory=list)
    all_fields_str: str = ''      # calibrators_all + ',' + target (as in v0.5 format_fields)
    all_fields_arr: list = field(default_factory=list)
    target_fields_arr: list = field(default_factory=list)
    # target field selection -> phase calibrator field selection (filled from the FieldModel)
    phasecal_for_target: dict = field(default_factory=dict)
    field_model: Optional[dict] = None   # FieldModel.to_dict()

    # calibration products
    init_tables: list = field(default_factory=list)
    init_tables_dict: dict = field(default_factory=dict)
    ref_antenna: str = ''
    ref_antenna_list: list = field(default_factory=list)
    # apply lists per iteration, e.g. apply_lists['1'] = {'bp_self': {...}, 'transfer': {...}, ...}
    # each entry: {'gaintable': [...], 'gainfield': [...]}
    apply_lists: dict = field(default_factory=dict)
    tables: dict = field(default_factory=dict)          # name -> CalTable record dict
    # per iteration ('1', '2'): the v0.5 dicts of produced tables
    bp_tables: dict = field(default_factory=dict)       # gain_tables_BP_dict (bp_K, bp_p, ...)
    gain_tables: dict = field(default_factory=dict)     # gain_tables_phases_dict (+ apply helper lists)
    fluxes: dict = field(default_factory=dict)          # iteration -> fluxscale result (JSON-safe)

    # bookkeeping
    flag_data_steps: dict = field(default_factory=dict)   # step -> flagdata summary (not persisted)
    flag_fractions: dict = field(default_factory=dict)    # step -> {field: fraction} (persisted)
    steps: dict = field(default_factory=dict)             # step name -> {'status', 'start', 'end', ...}
    warnings: list = field(default_factory=list)
    # run-time only (not persisted): the step being run, and the steps whose tables must be recomputed
    # (``synphly run --force``; 'all' = every step) -> synphly.calib.tables.reuse_mode
    current_step: str = ''
    force_steps: list = field(default_factory=list)
    log_file: str = ''
    casa_log_file: str = ''

    @classmethod
    def new(cls, cfg: Config) -> 'Context':
        paths = Paths.from_working_directory(cfg.globals.working_directory)
        vis = f"{paths.working_directory}/{cfg.globals.experiment_name}.ms"
        return cls(cfg=cfg, paths=paths, vis=vis, vis_for_cal=vis)

    @property
    def state_file(self) -> str:
        return os.path.join(self.paths.working_directory, STATE_FILENAME)

    def to_state(self) -> dict:
        d = asdict(self)
        d.pop('cfg')
        for k in _RUNTIME_ONLY:
            d.pop(k, None)
        return d

    def save(self) -> None:
        tmp = self.state_file + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(jsonable(self.to_state()), f, indent=2, default=str)
        os.replace(tmp, self.state_file)

    @classmethod
    def load(cls, cfg: Config) -> 'Context':
        ctx = cls.new(cfg)
        if os.path.exists(ctx.state_file):
            with open(ctx.state_file) as f:
                state = json.load(f)
            state.pop('paths', None)
            for k in _RUNTIME_ONLY:
                state.pop(k, None)
            for k, v in state.items():
                if hasattr(ctx, k):
                    setattr(ctx, k, v)
        return ctx
