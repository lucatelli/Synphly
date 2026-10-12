"""
Calibration table registry: one ``CalTable`` record per produced table, the input hash, and the reuse policy.

Every table Synphly writes gets a JSON sidecar ``<table>.synphly.json`` next to it (outside the CASA table
directory) and an entry in ``ctx.tables[<basename>]``. The record holds what the table was solved from:

    path, type (K/G/B/F/init/refant), stage, iteration, solint, fields solved, priors (paths + their hashes),
    gainfields, the key solve parameters, the input hash, per-field solution counts, created time,
    synphly version, whether it was reused.

Input hash = sha256 of the canonical JSON of {solve parameters, the priors' hashes, the vis path, a cheap flag
fingerprint of the MS}. A prior's hash is the input hash in its sidecar (so a recomputed prior with identical
inputs keeps its hash); without a sidecar a file-level fingerprint (size + mtime of the files) is used.
The synphly version is recorded but is not part of the hash (a version bump alone does not force a recompute).

Reuse policy (``cfg.pipeline.reuse_tables``, ``--force STEP`` -> 'never' for the tables of that step):

    auto   (default) reuse a table only if it exists, its sidecar exists and the input hash matches;
           otherwise the table (and sidecar) is removed and recomputed
    always the v0.5 behaviour: an existing table with the expected name is reused
    never  always recompute (the existing table is removed first)

fluxscale outputs are always recomputed (fluxscale refuses to overwrite).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime

import numpy as np

log = logging.getLogger(__name__)

SIDECAR_SUFFIX = '.synphly.json'
REUSE_MODES = ('auto', 'always', 'never')
FLAG_SAMPLE_ROWINCR = 1000


class CalTableError(RuntimeError):
    """A calibration table is missing or has no unflagged solutions."""


@dataclass
class CalTable:
    path: str
    type: str                  # K, G, B, F (fluxscale), init (gencal), refant
    stage: str = ''            # e.g. '_bpcal_d_', '_allcal_ap_inf_', 'antpos'
    iteration: str = ''
    solint: str = ''
    fields: str = ''           # field selection the table was solved on
    priors: list = field(default_factory=list)       # [{'path': ..., 'hash': ...}]
    gainfields: list = field(default_factory=list)
    params: dict = field(default_factory=dict)       # key solve parameters (as passed to CASA)
    flag_fingerprint: str = ''
    input_hash: str = ''
    step: str = ''
    created: str = ''
    synphly_version: str = ''
    reused: bool = False
    hash_verified: bool = True    # False when reused under reuse_tables='always' without a matching sidecar
    solutions: dict = field(default_factory=dict)    # field ID -> {'unflagged': n, 'total': n}

    @property
    def name(self) -> str:
        return os.path.basename(self.path.rstrip('/'))

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> 'CalTable':
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        return cls(**known)


# ----------------------------------------------------------------------------------------------------
# hashing
# ----------------------------------------------------------------------------------------------------
def _canonical(obj) -> str:
    def conv(o):
        if isinstance(o, dict):
            return {str(k): conv(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [conv(v) for v in o]
        if hasattr(o, 'tolist'):
            return o.tolist()
        if o is None or isinstance(o, (str, int, float, bool)):
            return o
        # Anything else (objects, functions) has no stable representation across processes: refuse it rather
        # than hashing a repr with a memory address in it.
        raise TypeError(f"cannot hash a {type(o).__name__} in the table inputs: {o!r}")
    return json.dumps(conv(obj), sort_keys=True, separators=(',', ':'))


def sidecar_path(path: str) -> str:
    return path.rstrip('/') + SIDECAR_SUFFIX


def read_sidecar(path: str):
    sc = sidecar_path(path)
    if not os.path.exists(sc):
        return None
    try:
        with open(sc) as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        log.warning(f"Could not read the sidecar {sc}: {e}")
        return None


def _file_fingerprint(path: str) -> str:
    """Fallback hash of a table without a sidecar: relative path, size and mtime of every file."""
    h = hashlib.sha256()
    if os.path.isdir(path):
        for root, _, files in sorted(os.walk(path)):
            for fn in sorted(files):
                p = os.path.join(root, fn)
                st = os.stat(p)
                h.update(f"{os.path.relpath(p, path)}:{st.st_size}:{st.st_mtime_ns};".encode())
    elif os.path.exists(path):
        st = os.stat(path)
        h.update(f"{st.st_size}:{st.st_mtime_ns}".encode())
    else:
        h.update(b'missing')
    return 'files:' + h.hexdigest()


def table_hash(path: str) -> str:
    """Hash identifying a table's content for its dependents: the input hash in its sidecar, if any."""
    sc = read_sidecar(path)
    if sc and sc.get('input_hash'):
        return sc['input_hash']
    return _file_fingerprint(path)


def prior_records(gaintables) -> list:
    return [{'path': p, 'hash': table_hash(p)} for p in (gaintables or [])]


def flag_fingerprint(vis: str, rowincr: int = FLAG_SAMPLE_ROWINCR) -> str:
    """
    Cheap fingerprint of the flags of ``vis`` (read only): number of rows, and the number of flagged / total
    FLAG elements over every ``rowincr``-th row of the main table. ~0.1 s on 4.6 M rows.
    """
    from ..casa import open_table
    with open_table(vis) as tb:
        nrows = int(tb.nrows())
        if nrows == 0:
            return '0:0:0/0'
        sample = tb.getvarcol('FLAG', 0, -1, rowincr)
    nflag = sum(int(np.count_nonzero(v)) for v in sample.values())
    ntot = sum(int(np.size(v)) for v in sample.values())
    return f"{nrows}:{len(sample)}:{nflag}/{ntot}"


def input_hash(params: dict, priors: list, vis: str, flag_fp: str = '') -> str:
    payload = {'params': params, 'priors': [p['hash'] for p in priors], 'vis': os.path.abspath(vis),
               'flags': flag_fp}
    return hashlib.sha256(_canonical(payload).encode()).hexdigest()


# ----------------------------------------------------------------------------------------------------
# reuse policy
# ----------------------------------------------------------------------------------------------------
def _remove(path: str) -> None:
    if os.path.isdir(path):
        shutil.rmtree(path)
    elif os.path.exists(path):
        os.remove(path)


def reuse_mode(ctx, step: str = '') -> str:
    """cfg.pipeline.reuse_tables, or 'never' if ``step`` (or 'all') is in ``ctx.force_steps``."""
    force = getattr(ctx, 'force_steps', None) or []
    step = step or getattr(ctx, 'current_step', '') or ''
    if 'all' in force or (step and step in force):
        return 'never'
    mode = getattr(ctx.cfg.pipeline, 'reuse_tables', 'auto')
    if mode not in REUSE_MODES:
        raise ValueError(f"pipeline.reuse_tables must be one of {REUSE_MODES}, got {mode!r}")
    return mode


def new_record(ctx, path, type, params, gaintables=(), stage='', iteration='', solint='', fields='',
               gainfields=(), vis='', flag_fp=None) -> CalTable:
    """Build the record (and its input hash) of a table that is about to be solved."""
    from .. import __version__
    priors = prior_records(gaintables)
    if flag_fp is None:
        flag_fp = flag_fingerprint(vis) if vis else ''
    rec = CalTable(path=path, type=type, stage=stage, iteration=str(iteration), solint=str(solint),
                   fields=str(fields), priors=priors, gainfields=list(gainfields or []),
                   params=dict(params), flag_fingerprint=flag_fp,
                   step=getattr(ctx, 'current_step', '') or '',
                   synphly_version=__version__)
    rec.input_hash = input_hash(rec.params, priors, vis, flag_fp)
    return rec


def prepare(ctx, rec: CalTable) -> bool:
    """
    Apply the reuse policy to ``rec.path``. Returns True if the existing table is reused; otherwise the
    table and its sidecar are removed (CASA gaincal/bandpass would overwrite, but we do not rely on it).
    """
    mode = reuse_mode(ctx, rec.step)
    exists = os.path.exists(rec.path)
    old = read_sidecar(rec.path)
    if mode == 'always':
        reuse = exists
        rec.hash_verified = bool(old and old.get('input_hash') == rec.input_hash)
        if reuse:
            log.info(f"     --=> {rec.name} exists; reused (reuse_tables='always'"
                     f"{'' if rec.hash_verified else ', inputs NOT verified'}).")
    elif mode == 'never':
        reuse = False
        if exists:
            log.info(f"     --=> {rec.name} exists; recomputing (reuse_tables='never' or --force).")
    else:
        if not exists:
            reuse = False
        elif old is None:
            reuse = False
            log.info(f"     --=> {rec.name} exists without a synphly sidecar; recomputing.")
        elif old.get('input_hash') != rec.input_hash:
            reuse = False
            changed = [k for k in ('params', 'priors', 'flag_fingerprint')
                       if _canonical(old.get(k)) != _canonical(getattr(rec, k))]
            log.info(f"     --=> {rec.name} exists but its inputs changed ({', '.join(changed) or 'vis'}); "
                     f"recomputing.")
        else:
            reuse = True
            log.info(f"     --=> {rec.name} exists with identical inputs; reused.")
    if not reuse:
        _remove(rec.path)
        _remove(sidecar_path(rec.path))
    rec.reused = reuse
    if reuse and old is not None and old.get('created'):
        rec.created = old['created']
    return reuse


def write_record(ctx, rec: CalTable) -> None:
    """Store ``rec`` in ctx.tables and (unless it is an unverified reuse) in its sidecar."""
    if not rec.created:
        rec.created = datetime.now().isoformat(timespec='seconds')
    ctx.tables[rec.name] = rec.to_dict()
    if rec.reused and not rec.hash_verified:
        return       # do not claim that the existing table matches the current inputs
    try:
        tmp = sidecar_path(rec.path) + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(rec.to_dict(), f, indent=1, default=str)
        os.replace(tmp, sidecar_path(rec.path))
    except OSError as e:
        log.warning(f"Could not write the sidecar of {rec.path}: {e}")


# ----------------------------------------------------------------------------------------------------
# solution checks
# ----------------------------------------------------------------------------------------------------
def _read_flags(tb):
    try:
        return [np.asarray(tb.getcol('FLAG'))], True
    except RuntimeError:      # variable-shaped FLAG column (e.g. B tables with different nchan per spw)
        return list(tb.getvarcol('FLAG').values()), False


def solution_counts(path: str) -> dict:
    """field ID -> {'unflagged': n, 'total': n} over the FLAG elements of a caltable."""
    from ..casa import open_table
    with open_table(path) as tb:
        fids = np.asarray(tb.getcol('FIELD_ID'))
        flags, fixed = _read_flags(tb)
    out = {}
    if fixed:
        f = flags[0]
        for fid in np.unique(fids):
            sel = f[..., fids == fid]
            out[str(int(fid))] = {'unflagged': int(sel.size - np.count_nonzero(sel)), 'total': int(sel.size)}
    else:
        for fid, f in zip(fids, flags):
            d = out.setdefault(str(int(fid)), {'unflagged': 0, 'total': 0})
            d['total'] += int(np.size(f))
            d['unflagged'] += int(np.size(f) - np.count_nonzero(f))
    return out


def check_solutions(ctx, rec: CalTable, expected_fields: str = '') -> dict:
    """
    Log the per-field solution counts of ``rec.path``. Raises CalTableError if the table is missing or has
    no unflagged solution at all. A field of ``expected_fields`` (ID selection) without any unflagged
    solution is logged as an error and added to ctx.warnings (not raised).
    """
    if not os.path.exists(rec.path):
        raise CalTableError(f"Calibration table {rec.path} was not produced "
                            f"(no unflagged data/solutions for field(s) {rec.fields}?)")
    counts = solution_counts(rec.path)
    rec.solutions = counts
    tot = sum(c['total'] for c in counts.values())
    good = sum(c['unflagged'] for c in counts.values())
    for fid, c in sorted(counts.items(), key=lambda kv: int(kv[0])):
        frac = 100.0 * c['unflagged'] / c['total'] if c['total'] else 0.0
        log.info(f"     {rec.name}: field {fid}: {c['unflagged']}/{c['total']} unflagged solutions "
                 f"({frac:.1f}%)")
    if good == 0:
        raise CalTableError(f"Calibration table {rec.path} has no unflagged solutions "
                            f"({tot} solutions, all flagged; fields {rec.fields}).")
    expected = [t.strip() for t in str(expected_fields).split(',') if t.strip().isdigit()]
    for fid in expected:
        if counts.get(fid, {}).get('unflagged', 0) == 0:
            msg = (f"Calibration table {rec.name}: calibrator field {fid} has no unflagged solutions; "
                   f"its data will be flagged by applycal.")
            log.error(msg)
            if msg not in ctx.warnings:
                ctx.warnings.append(msg)
    return counts
