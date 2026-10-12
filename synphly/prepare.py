"""
Starting a new dataset: ``synphly init`` and ``synphly prepare``.

The v0.5 workflow for a new observation was: run only the import (``load_data``, ``run_only_ms_info``), read
the listobs, then fill in the config. v0.6 keeps that workflow with two commands:

    synphly init NAME --wd DIR [--asdm PATH] [--band B]   write a starter config (only the keys you must set)
    synphly prepare CFG                                    import the SDM (if needed), Hanning (if enabled), write
                                                           the listobs, and print the field table, the roles that
                                                           would be used and a ready-to-paste [sources] block

``prepare`` modifies nothing except creating the MS (importasdm) and the listobs file; it never flags or
calibrates. It still prints the field table when the roles cannot be resolved (e.g. early EVLA data with wrong
intents): that is exactly when you need to look.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

# VLA bands by mean observing frequency (GHz); letters as used by the flux-model names (U = Ku, A = Ka)
_BANDS = ((1, 2, 'L'), (2, 4, 'S'), (4, 8, 'C'), (8, 12, 'X'), (12, 18, 'U'), (18, 26.5, 'K'),
          (26.5, 40, 'A'), (40, 50, 'Q'))

REPORT_FILENAME = 'fields_report.txt'


def guess_band(freq_hz: float) -> str:
    ghz = freq_hz / 1e9
    for lo, hi, b in _BANDS:
        if lo <= ghz <= hi:
            return b
    return ''


# ------------------------------------------------------------------------------------------------------------
# synphly init
# ------------------------------------------------------------------------------------------------------------
_INIT_TEMPLATE = '''\
# Synphly config for {name}
# Made by `synphly init`. Only the keys you normally need are here; every other key takes the default of
# configs/template.toml (all keys, with explanations: docs/config_reference.md). To change one, copy it from the
# template into this file, under the same [section].
#
# Next steps:
#   1. synphly prepare {cfg}        import the data, write the listobs, show the fields and suggested roles
#   2. edit [sources] below if needed (prepare prints a ready-to-paste block)
#   3. synphly run {cfg} --dry-run  check the steps and the field roles (read-only)
#   4. synphly run {cfg}

[globals]
experiment_name = "{name}"           # the MS is <working_directory>/<experiment_name>.ms
working_directory = "{wd}"
asdm_file = "{asdm}"                 # used only if the MS does not exist yet
do_hanning = {hanning}

[sources]
# Comma-separated field NAMES or IDs. Leave empty to take them from the scan intents.
# `synphly prepare` shows what the intents give and which IDs are dropped (pointing scans, setup scans, ...).
flux_calibrator = ""
bandpass_calibrator = ""
phase_calibrator = ""
target = ""
# fluxscale field IDs; empty = flux calibrator (reference) and all calibrators (transfer)
transfer = ""
reference = ""
# Optional, if a target must use a specific phase calibrator (default: the closest in time):
# phasecal_for_target = {{ "TARGET_NAME" = "PHASECAL_NAME" }}

[calibrate]
band = "{band}"                      # L S C X U(=Ku) K A(=Ka) Q; empty = guessed from the frequency
'''


def init_config(name: str, working_directory: str, asdm_file: str = '', band: str = '', hanning: bool = False,
                output: str = '', force: bool = False) -> str:
    """Write a starter config for a new dataset. Returns the path written."""
    name = os.path.basename(name.rstrip('/'))
    if name.endswith('.ms'):
        name = name[:-3]
    if not name:
        raise ValueError('The experiment name is empty.')
    wd = os.path.abspath(working_directory).rstrip('/') + '/'
    asdm = os.path.abspath(asdm_file) if asdm_file else wd + name
    if not output:
        output = os.path.join('configs', 'datasets', name + '.toml') if os.path.isdir(
            os.path.join('configs', 'datasets')) else name + '.toml'
    if os.path.exists(output) and not force:
        raise FileExistsError(f"{output} exists; use --force to overwrite it.")
    os.makedirs(os.path.dirname(os.path.abspath(output)), exist_ok=True)
    text = _INIT_TEMPLATE.format(name=name, wd=wd, asdm=asdm, band=band, cfg=output,
                                 hanning='true' if hanning else 'false')
    with open(output, 'w') as f:
        f.write(text)
    # the file must load and validate (catches a bad band letter, ...)
    from .config import load_config
    load_config(output)
    return output


# ------------------------------------------------------------------------------------------------------------
# synphly prepare
# ------------------------------------------------------------------------------------------------------------
def _toml_value(fm, role) -> str:
    """Field selection for a [sources] key: names when they are unambiguous, IDs otherwise."""
    dup = fm.duplicates()
    out = []
    for fid in fm.ids(role):
        name = fm.records[fid].name
        out.append(str(fid) if name in dup else name)
    return ','.join(out)


def prepare_text(fm, vis: str, listobs: str, cfg_path: str = '', error: str = '') -> str:
    """The text printed (and written to <wd>/fields_report.txt) by ``synphly prepare``."""
    cfg_path = cfg_path or 'CFG'
    lines = ['=' * 100, 'Synphly prepare', '=' * 100,
             f'MS:      {vis}', f'listobs: {listobs}   <- scans, intents, spws: read this first', '',
             'Fields (one row per FIELD_ID):', fm.report(), '']
    dup = fm.duplicates()
    if dup:
        lines.append('Duplicated field names (a NAME in the config selects all of these IDs; use IDs to pick one):')
        for name, ids in dup.items():
            lines.append(f'  {name}: IDs {", ".join(str(i) for i in ids)}')
        lines.append('')
    if fm.dropped:
        lines.append('IDs left out of the roles:')
        for d in fm.dropped:
            lines.append(f"  {d['id']} {d['name']} ({d['role']}): {d['reason']}")
        lines.append('')
    band = guess_band(fm.freq_mean_hz) if fm.freq_mean_hz else ''
    if fm.nspw:
        fbw = fm.fractional_bandwidth()
        lines.append(f'Band: {band or "?"} (mean {fm.freq_mean_hz / 1e9:.3f} GHz); fractional bandwidth {fbw:.3f} '
                     f'-> fluxscale fitorder={"1" if fbw >= 0.05 else "0"} (auto)')
        lines.append('')

    if error:
        lines += ['ROLES COULD NOT BE RESOLVED:', f'  {error}', '',
                  'Set them explicitly in [sources] (names or field IDs from the table above), then run',
                  f'  synphly prepare {cfg_path}   again.']
        return '\n'.join(lines)

    missing = [r for r in ('flux', 'bandpass', 'phase', 'target') if not fm.ids(r)]
    if missing:
        lines += [f'WARNING: no field for role(s) {", ".join(missing)} (no matching intent). Set them in [sources].',
                  '']
    lines += ['Suggested [sources] block (what the run will use; paste it into the config to make it explicit):',
              '', '[sources]']
    for key, role in (('flux_calibrator', 'flux'), ('bandpass_calibrator', 'bandpass'),
                      ('phase_calibrator', 'phase'), ('target', 'target')):
        lines.append(f'{key} = "{_toml_value(fm, role)}"')
    lines.append(f'transfer = "{",".join(str(i) for i in fm.fluxscale_transfer())}"')
    lines.append(f'reference = "{",".join(str(i) for i in fm.fluxscale_reference())}"')
    pmap = fm.phasecal_for_target()
    if len(set(pmap.values())) > 1 or dup:
        items = ', '.join(f'"{fm.records[t].name}" = "{_phasecal_label(fm, c, dup)}"' for t, c in pmap.items())
        lines.append(f'phasecal_for_target = {{ {items} }}')
    else:
        lines.append('# phasecal_for_target: not needed (' +
                     ', '.join(f'{fm.records[t].name} -> {fm.records[c].name}' for t, c in pmap.items()) + ')')
    if band:
        lines += ['', '[calibrate]', f'band = "{band}"']
    lines += ['', 'Next:', f'  1. check the listobs and the table above; edit [sources] in {cfg_path} if needed',
              f'  2. synphly run {cfg_path} --dry-run', f'  3. synphly run {cfg_path}']
    return '\n'.join(lines)


def _phasecal_label(fm, cid, dup) -> str:
    name = fm.records[cid].name
    return str(cid) if name in dup else name


def prepare(cfg):
    """Import (if needed) and inspect a dataset; returns (ctx, text). Writes <wd>/fields_report.txt."""
    from .context import Context
    from .fields import FieldModel, FieldModelError
    from .logs import absolutize_config_paths, run_directory, setup_logging
    from .pipeline import _load_data, _set_working_dir, _step

    absolutize_config_paths(cfg)
    ctx = Context.new(cfg)
    with run_directory(ctx.paths.logs):
        setup_logging(ctx)
        _step(ctx, 'set_working_dir', _set_working_dir, ctx)
        if cfg.globals.load_data:
            _step(ctx, 'load_data', _load_data, ctx)
        vis = ctx.vis_for_cal or ctx.vis
        if not os.path.exists(vis):
            raise FileNotFoundError(f"Measurement set {vis} not found (load_data is off and the MS does not exist).")
        fm = FieldModel.from_ms(vis)
        error = ''
        try:
            fm.resolve_roles(cfg.sources)
        except FieldModelError as e:
            error = str(e)
        text = prepare_text(fm, vis, vis.replace('.ms', '_listobs.txt'), cfg.source_path or '', error)
        out = os.path.join(ctx.paths.working_directory, REPORT_FILENAME)
        with open(out, 'w') as f:
            f.write(text + '\n')
    return ctx, text + f'\n\n(written to {out})'


def inspect(cfg):
    """Read-only twin of ``prepare`` (``synphly info``): the same text for an MS that already exists; imports
    nothing and writes nothing (CASA's own casa-*.log goes to a temporary directory)."""
    import tempfile
    from .context import Context
    from .fields import FieldModel, FieldModelError
    from .logs import absolutize_config_paths, run_directory

    absolutize_config_paths(cfg)
    ctx = Context.new(cfg)
    vis = ctx.vis
    if cfg.globals.do_hanning and os.path.exists(vis.replace('.ms', '_hs.ms')):
        vis = vis.replace('.ms', '_hs.ms')
    if not os.path.exists(vis):
        raise FileNotFoundError(f"Measurement set {vis} not found. To import it from the SDM, run "
                                f"`synphly prepare {cfg.source_path or 'CFG'}`.")
    with run_directory(tempfile.mkdtemp(prefix='synphly_info_')):
        fm = FieldModel.from_ms(vis)
    error = ''
    try:
        fm.resolve_roles(cfg.sources)
    except FieldModelError as e:
        error = str(e)
    return prepare_text(fm, vis, vis.replace('.ms', '_listobs.txt'), cfg.source_path or '', error)
