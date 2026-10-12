"""
Run report: ``<wd>/run_report.json`` and ``<wd>/run_report.md``.

Written at the end of every run and, best effort, when a step fails. Built only from the run context
(no CASA access), so it can also be regenerated from a saved state::

    from synphly.context import Context
    from synphly.reporting.summary import write_report
    write_report(Context.load(cfg))

Contents: run metadata and log files, the field model (IDs, names, intents, roles, dropped IDs, target ->
phase calibrator), the reference antenna, the bootstrapped flux densities per iteration, field and spw with
the fitted values (from the fluxscale dicts in ``ctx.fluxes``), the flag fraction per field after every
recorded flagging step (``ctx.flag_fractions``), the calibration tables with their priors and solution counts
(``ctx.tables``), the warnings, the per-step timings and relative links to the main plot directories.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime

from ..context import jsonable

log = logging.getLogger(__name__)

JSON_NAME = 'run_report.json'
MD_NAME = 'run_report.md'


def _rel(ctx, path):
    if not path:
        return ''
    try:
        return os.path.relpath(path, ctx.paths.working_directory)
    except ValueError:
        return path


def _field_section(ctx) -> dict:
    if not ctx.field_model:
        return {}
    from ..fields import FieldModel
    fm = FieldModel.from_dict(ctx.field_model)
    out = {'fields': [], 'roles': {}, 'dropped': list(fm.dropped), 'phasecal_for_target': dict(ctx.phasecal_for_target),
           'duplicates': {k: v for k, v in fm.duplicates().items()}, 'differs_from_v05': {}}
    for r in fm.records.values():
        out['fields'].append({'id': r.id, 'name': r.name, 'intents': sorted(r.real_intents) or list(r.intents),
                              'nscans': len(r.scans), 'nrows': r.nrows, 'roles': list(r.roles),
                              'notes': list(r.notes)})
    if fm._resolved:
        for role in ('flux', 'bandpass', 'phase', 'target', 'pointing', 'ignore'):
            out['roles'][role] = fm.ids(role)
        out['roles']['calibrators'] = fm.calibrator_ids()
        out['differs_from_v05'] = fm.compare_legacy()
    return out


def _flux_rows(fluxdict, names=None) -> list:
    """Rows {field, name, spw, flux_jy, err_jy, nsol} + per-field fit from a fluxscale result dict."""
    names = names or {}
    fields = []
    for key, val in (fluxdict or {}).items():
        if not (str(key).isdigit() and isinstance(val, dict)):
            continue
        spws = []
        for sk, sv in val.items():
            if str(sk).isdigit() and isinstance(sv, dict) and 'fluxd' in sv:
                fl = list(sv.get('fluxd', []))
                er = list(sv.get('fluxdErr', [])) if sv.get('fluxdErr') is not None else []
                ns = sv.get('numSol', [])
                ns = list(ns) if isinstance(ns, (list, tuple)) else [ns]
                if fl and fl[0] == -1:       # fluxscale marks spws without solutions with -1
                    continue
                spws.append({'spw': int(sk), 'flux_jy': fl[0] if fl else None,
                             'err_jy': er[0] if er else None, 'nsol': ns[0] if ns else None})
        fields.append({'field': str(key), 'name': val.get('fieldName', names.get(str(key), '')),
                       'spws': sorted(spws, key=lambda d: d['spw']),
                       'fit_flux_jy': val.get('fitFluxd'), 'fit_flux_err_jy': val.get('fitFluxdErr'),
                       'fit_ref_freq_hz': val.get('fitRefFreq'),
                       'spidx': list(val.get('spidx', [])) if val.get('spidx') is not None else [],
                       'spidxerr': list(val.get('spidxerr', [])) if val.get('spidxerr') is not None else []})
    return sorted(fields, key=lambda d: int(d['field']))


def _flux_section(ctx) -> dict:
    out = {}
    fluxes = jsonable(ctx.fluxes or {})
    for it, d in fluxes.items():
        if it == 'setjy_fluxcal':
            out['setjy_fluxcal'] = {'fields': _flux_rows(d)}
            continue
        if not isinstance(d, dict):
            continue
        out[str(it)] = {'fitorder': d.get('fitorder'), 'reference': d.get('reference'),
                        'transfer': d.get('transfer'), 'fields': _flux_rows(d.get('fluxscale'))}
    return out


def _tables_section(ctx) -> list:
    rows = []
    for name, rec in (ctx.tables or {}).items():
        sol = rec.get('solutions') or {}
        rows.append({'name': name, 'type': rec.get('type'), 'step': rec.get('step'),
                     'iteration': rec.get('iteration'), 'fields': rec.get('fields'),
                     'priors': [os.path.basename(p.get('path', '')) for p in rec.get('priors', [])],
                     'gainfields': rec.get('gainfields', []), 'reused': rec.get('reused', False),
                     'hash_verified': rec.get('hash_verified', True),
                     'input_hash': (rec.get('input_hash') or '')[:12], 'created': rec.get('created'),
                     'solutions': sol,
                     'unflagged_fraction': (sum(c['unflagged'] for c in sol.values()) /
                                            max(1, sum(c['total'] for c in sol.values()))) if sol else None})
    return rows


def _plot_links(ctx) -> list:
    out = []
    plots = ctx.paths.plots
    if os.path.isdir(plots):
        out.append(_rel(ctx, plots))
        for d in sorted(os.listdir(plots)):
            p = os.path.join(plots, d)
            if os.path.isdir(p):
                out.append(_rel(ctx, p))
    if os.path.isdir(ctx.paths.fields):
        out.append(_rel(ctx, ctx.paths.fields))
    return out


def build_report(ctx, status='finished', error=None) -> dict:
    from .. import __version__
    steps = {k: dict(v) for k, v in (ctx.steps or {}).items()}
    warnings = list(dict.fromkeys(ctx.warnings or []))
    return jsonable({
        'synphly_version': __version__,
        'generated': datetime.now().isoformat(timespec='seconds'),
        'status': status,
        'error': error,
        'experiment': ctx.cfg.globals.experiment_name,
        'config': ctx.cfg.source_path,
        'working_directory': ctx.paths.working_directory,
        'vis': _rel(ctx, ctx.vis), 'vis_for_cal': _rel(ctx, ctx.vis_for_cal),
        'logs': {'synphly': _rel(ctx, ctx.log_file), 'casa': _rel(ctx, ctx.casa_log_file)},
        'fields': _field_section(ctx),
        'ref_antenna': ctx.ref_antenna,
        'fluxes': _flux_section(ctx),
        'flag_fractions': dict(ctx.flag_fractions or {}),
        'tables': _tables_section(ctx),
        'apply_lists': dict(ctx.apply_lists or {}),
        'warnings': warnings,
        'steps': steps,
        'total_duration_s': sum(v.get('duration_s') or 0 for v in steps.values()),
        'plots': _plot_links(ctx),
    })


# ----------------------------------------------------------------------------------------------------
# Markdown
# ----------------------------------------------------------------------------------------------------
def _table(header, rows) -> list:
    if not rows:
        return ['(none)', '']
    lines = ['| ' + ' | '.join(header) + ' |', '|' + '|'.join('---' for _ in header) + '|']
    for r in rows:
        lines.append('| ' + ' | '.join('' if c is None else str(c).replace('|', '/') for c in r) + ' |')
    return lines + ['']


def _fmt(v, f='{:.4f}'):
    try:
        return f.format(v)
    except (TypeError, ValueError):
        return '' if v is None else str(v)


def to_markdown(rep: dict) -> str:
    L = [f"# Synphly run report: {rep['experiment']}", '',
         f"- status: **{rep['status']}**" + (f" ({rep['error']})" if rep.get('error') else ''),
         f"- synphly {rep['synphly_version']}, generated {rep['generated']}",
         f"- config: `{rep.get('config')}`", f"- working directory: `{rep['working_directory']}`",
         f"- calibrated MS: `{rep['vis_for_cal']}`",
         f"- logs: [{rep['logs']['synphly']}]({rep['logs']['synphly']}), "
         f"[{rep['logs']['casa']}]({rep['logs']['casa']})",
         f"- reference antenna: {rep['ref_antenna'] or '-'}", '']

    fs = rep.get('fields') or {}
    L += ['## Fields', '']
    L += _table(['ID', 'Name', 'Intents', 'Scans', 'Rows', 'Roles', 'Notes'],
                [(f['id'], f['name'], ','.join(f['intents']), f['nscans'], f['nrows'], ','.join(f['roles']) or '-',
                  '; '.join(f['notes'])) for f in fs.get('fields', [])])
    if fs.get('roles'):
        L += ['Roles (field IDs): ' + '; '.join(f"{k}: {','.join(map(str, v)) or '-'}"
                                                 for k, v in fs['roles'].items()), '']
    if fs.get('phasecal_for_target'):
        L += ['Phase calibrator per target: ' + ', '.join(f"{t} -> {c}"
                                                           for t, c in fs['phasecal_for_target'].items()), '']
    if fs.get('dropped'):
        L += ['Dropped field IDs:', '']
        L += _table(['ID', 'Name', 'Role', 'Reason'], [(d['id'], d['name'], d['role'], d['reason'])
                                                        for d in fs['dropped']])
    for role, d in (fs.get('differs_from_v05') or {}).items():
        L.append(f"- {role}: v0.5 name selection -> IDs {d['legacy']}, v0.6 -> {d['new']}")
    L.append('')

    L += ['## Flux densities', '']
    for it, d in (rep.get('fluxes') or {}).items():
        if it == 'setjy_fluxcal':
            continue
        L += [f"### Iteration {it} (fluxscale fitorder={d.get('fitorder')}, reference={d.get('reference')}, "
              f"transfer={d.get('transfer')})", '']
        L += _table(['Field', 'Name', 'Fit flux [Jy]', 'err', 'spidx', 'ref freq [GHz]'],
                    [(f['field'], f['name'], _fmt(f['fit_flux_jy']), _fmt(f['fit_flux_err_jy']),
                      ', '.join(_fmt(x, '{:.3f}') for x in f['spidx']),
                      _fmt((f['fit_ref_freq_hz'] or 0) / 1e9 if f['fit_ref_freq_hz'] else None, '{:.4f}'))
                     for f in d['fields']])
        rows = [(f['field'], f['name'], s['spw'], _fmt(s['flux_jy']), _fmt(s['err_jy']), s['nsol'])
                for f in d['fields'] for s in f['spws']]
        L += ['Per spw:', ''] + _table(['Field', 'Name', 'spw', 'Flux [Jy]', 'err', 'nsol'], rows)

    ff = rep.get('flag_fractions') or {}
    L += ['## Flag fraction per field after each step', '']
    fields = list(dict.fromkeys(k for v in ff.values() for k in v))
    L += _table(['Step'] + fields, [[step] + [_fmt(100 * v[f], '{:.1f}%') if f in v else '' for f in fields]
                                    for step, v in ff.items()])

    L += ['## Calibration tables', '']
    L += _table(['Table', 'Type', 'Step', 'Fields', 'Priors', 'Unflagged', 'Reused'],
                [(t['name'], t['type'], t['step'], t['fields'], ', '.join(t['priors']),
                  _fmt(100 * t['unflagged_fraction'], '{:.1f}%') if t['unflagged_fraction'] is not None else '',
                  ('yes' if t['reused'] else 'no') + ('' if t['hash_verified'] else ' (unverified)'))
                 for t in rep.get('tables', [])])

    L += ['## Warnings', '']
    L += [f"- {w}" for w in rep.get('warnings', [])] or ['(none)']
    L.append('')

    L += ['## Steps', '']
    L += _table(['Step', 'Status', 'Start', 'Duration [min]', 'Error'],
                [(k, v.get('status'), v.get('start'),
                  _fmt((v.get('duration_s') or 0) / 60.0, '{:.2f}'), v.get('error') or '')
                 for k, v in rep.get('steps', {}).items()])
    L += [f"Total: {_fmt(rep.get('total_duration_s', 0) / 60.0, '{:.1f}')} min", '']

    L += ['## Plots', '']
    L += [f"- [{p}]({p})" for p in rep.get('plots', [])] or ['(none)']
    L.append('')
    return '\n'.join(L)


def write_report(ctx, status='finished', error=None):
    """Write run_report.json and run_report.md in the working directory. Returns (json_path, md_path)."""
    rep = build_report(ctx, status=status, error=error)
    wd = ctx.paths.working_directory
    jpath, mpath = os.path.join(wd, JSON_NAME), os.path.join(wd, MD_NAME)
    with open(jpath, 'w') as f:
        json.dump(rep, f, indent=1, default=str)
    with open(mpath, 'w') as f:
        f.write(to_markdown(rep))
    log.info(f"Run report: {mpath}")
    return jpath, mpath
