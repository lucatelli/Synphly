"""
Field model: one record per FIELD_ID, roles assigned per ID.

v0.5 selected fields by NAME. When several FIELD_IDs share a name (pointing scans, leakage scans, early-EVLA
duplicated fields) a name selection silently pulls the extra IDs into gaincal/applycal/fluxscale. This module
resolves every role to explicit FIELD_IDs and records which IDs were dropped and why.

API:

    fm = FieldModel.from_ms(vis)                 # uses casatools.msmetadata + table (read only)
    fm = FieldModel.from_dict(d)                 # from a JSON dump / mocked metadata (tests)
    fm.resolve_roles(sources_cfg)                # SourcesConfig -> per-ID roles, intents as fallback
    fm.ids(role) -> list[int]                    # 'flux', 'bandpass', 'phase', 'target', 'pointing', 'ignore'
    fm.selection(role) -> str                    # comma-separated ID string for CASA `field=`
    fm.names(role) -> list[str]
    fm.calibrator_ids() -> list[int]             # flux + bandpass + phase (unique, sorted)
    fm.calibrator_selection() -> str
    fm.phasecal_for_target(override=None) -> dict[int, int]   # target ID -> phase calibrator ID
    fm.duplicates() -> dict[str, list[int]]      # name -> IDs sharing it
    fm.fluxscale_reference() -> list[int]
    fm.fluxscale_transfer() -> list[int]
    fm.legacy_name_selection(role) -> str        # what v0.5 (name based) would have used
    fm.legacy_ids(role) -> list[int]             # IDs CASA would select from that name string
    fm.compare_legacy() -> dict                  # role -> (legacy IDs, new IDs) where they differ
    fm.dropped -> list[dict]                     # {'id', 'name', 'role', 'reason'}
    fm.report() -> str                           # human-readable table for the log
    fm.to_dict() -> dict                         # JSON safe

Rules used when a name (from the config or from the intents) is expanded to IDs. An ID with that name is dropped
(and recorded in ``fm.dropped`` with the reason) when:
  (a) it has no rows in the main table;
  (b) its only intent is CALIBRATE_POINTING (plus SYSTEM_CONFIGURATION / UNSPECIFIED) -> role 'pointing';
  (c) its only intents are SYSTEM_CONFIGURATION / UNSPECIFIED (or none) while another ID with the same name
      has a real calibration or target intent.
Explicit integer IDs in the config are kept as given (only a note is added if one of the rules would apply).
If a role is empty in the config, names are taken from the intents (CALIBRATE_FLUX, CALIBRATE_BANDPASS,
CALIBRATE_PHASE, *TARGET*), exactly like v0.5 `getms_info` (listobs(intent=...)), and then expanded with the rules
above; this reproduces the v0.5 name selection minus the dropped IDs.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict

import numpy as np

logger = logging.getLogger(__name__)

ROLES = ('flux', 'bandpass', 'phase', 'target', 'pointing', 'ignore')
CONFIG_ROLES = ('flux', 'bandpass', 'phase', 'target')
_CFG_ATTR = {'flux': 'flux_calibrator', 'bandpass': 'bandpass_calibrator',
             'phase': 'phase_calibrator', 'target': 'target'}
# substring matched against the raw intents, as the v0.5 listobs(intent='*...*') calls did
_ROLE_INTENT = {'flux': 'CALIBRATE_FLUX', 'bandpass': 'CALIBRATE_BANDPASS',
                'phase': 'CALIBRATE_PHASE', 'target': 'TARGET'}
_NULL_INTENTS = {'SYSTEM_CONFIGURATION', 'UNSPECIFIED', ''}
_POINTING = 'CALIBRATE_POINTING'


class FieldModelError(ValueError):
    """Invalid field selection (unknown name/ID, bad override, empty role after filtering)."""


def _strip_intent(intent: str) -> str:
    """'CALIBRATE_PHASE#UNSPECIFIED' -> 'CALIBRATE_PHASE'."""
    return intent.split('#')[0].strip()


def _split_tokens(value) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        tokens = [str(v) for v in value]
    else:
        tokens = str(value).split(',')
    return [t.strip() for t in tokens if t.strip() != '']


@dataclass
class FieldRecord:
    id: int
    name: str
    intents: list = field(default_factory=list)       # stripped, unique, sorted
    intents_raw: list = field(default_factory=list)   # as stored in the MS
    scans: list = field(default_factory=list)
    nrows: int = 0
    # scan number -> [t_start, t_end] (MJD seconds)
    scan_times: dict = field(default_factory=dict)
    # scan number -> stripped intents of that scan
    scan_intents: dict = field(default_factory=dict)
    ra_rad: float = 0.0
    dec_rad: float = 0.0
    roles: list = field(default_factory=list)
    notes: list = field(default_factory=list)

    # --- intent classification -------------------------------------------------------------
    @property
    def real_intents(self) -> set:
        return {i for i in self.intents if i not in _NULL_INTENTS}

    def is_pointing_only(self) -> bool:
        return self.real_intents == {_POINTING}

    def is_null_only(self) -> bool:
        return len(self.real_intents) == 0

    def has_real_intent(self) -> bool:
        """A calibration (other than pointing) or target intent."""
        return any(i != _POINTING for i in self.real_intents)

    def has_raw_intent(self, substring: str) -> bool:
        return any(substring in i for i in self.intents_raw)

    def to_dict(self) -> dict:
        d = asdict(self)
        d['scan_times'] = {str(k): [float(v[0]), float(v[1])] for k, v in self.scan_times.items()}
        d['scan_intents'] = {str(k): list(v) for k, v in self.scan_intents.items()}
        return d

    @classmethod
    def from_dict(cls, d: dict) -> 'FieldRecord':
        raw = list(d.get('intents_raw', d.get('intents', [])))
        intents = d.get('intents')
        if intents is None:
            intents = sorted({_strip_intent(i) for i in raw})
        return cls(id=int(d['id']), name=str(d['name']),
                   intents=sorted({_strip_intent(i) for i in intents}),
                   intents_raw=raw,
                   scans=[int(s) for s in d.get('scans', [])],
                   nrows=int(d.get('nrows', 0)),
                   scan_times={int(k): [float(v[0]), float(v[1])]
                               for k, v in d.get('scan_times', {}).items()},
                   scan_intents={int(k): [_strip_intent(i) for i in v]
                                 for k, v in d.get('scan_intents', {}).items()},
                   ra_rad=float(d.get('ra_rad', 0.0)), dec_rad=float(d.get('dec_rad', 0.0)),
                   roles=list(d.get('roles', [])), notes=list(d.get('notes', [])))


class FieldModel:
    def __init__(self, records: list, vis: str = '', nspw: int = 0, freq_min_hz: float = 0.0,
                 freq_max_hz: float = 0.0, freq_mean_hz: float = 0.0):
        self.records = {r.id: r for r in sorted(records, key=lambda r: r.id)}
        self.vis = vis
        self.nspw = int(nspw)
        self.freq_min_hz = float(freq_min_hz)
        self.freq_max_hz = float(freq_max_hz)
        self.freq_mean_hz = float(freq_mean_hz)
        self.dropped = []                  # list of {'id', 'name', 'role', 'reason'}
        self._roles = {r: [] for r in ROLES}
        self._legacy = {}                  # role -> v0.5 name string
        self._phasecal_override = {}
        self._transfer_cfg = ''
        self._reference_cfg = ''
        self._resolved = False

    # ------------------------------------------------------------------------------------------
    # construction
    # ------------------------------------------------------------------------------------------
    @classmethod
    def from_ms(cls, vis: str) -> 'FieldModel':
        """Read the field metadata of ``vis`` (read only: msmetadata + FIELD_ID column, via synphly.casa)."""
        from .casa import open_msmd, open_table   # local import: the module works without CASA

        with open_msmd(vis) as msmd:
            names = list(msmd.fieldnames())
            nspw = int(msmd.nspw())
            freqs = np.concatenate([np.asarray(msmd.chanfreqs(s), dtype=float) for s in range(nspw)])
            scan_info = {}
            for scan in msmd.scannumbers():
                scan = int(scan)
                try:
                    times = np.asarray(msmd.timesforscan(scan))
                    s_int = [_strip_intent(i) for i in msmd.intentsforscan(scan)]
                except RuntimeError as exc:
                    logger.warning(f"Could not read times/intents of scan {scan} in {vis}: {exc}")
                    continue
                scan_info[scan] = ([float(times.min()), float(times.max())] if times.size else None, s_int)

            records = []
            for fid, name in enumerate(names):
                try:
                    raw = list(msmd.intentsforfield(fid))
                except RuntimeError:
                    raw = []
                try:
                    scans = sorted(int(s) for s in msmd.scansforfield(fid))
                except RuntimeError:
                    scans = []
                pc = msmd.phasecenter(fid)
                rec = FieldRecord(id=fid, name=name, intents=sorted({_strip_intent(i) for i in raw}),
                                  intents_raw=raw, scans=scans,
                                  ra_rad=float(pc['m0']['value']), dec_rad=float(pc['m1']['value']))
                for s in scans:
                    if s in scan_info:
                        if scan_info[s][0] is not None:
                            rec.scan_times[s] = scan_info[s][0]
                        rec.scan_intents[s] = scan_info[s][1]
                records.append(rec)

        with open_table(vis) as tb:
            fid_col = np.asarray(tb.getcol('FIELD_ID'))
        counts = np.bincount(fid_col, minlength=len(records)) if fid_col.size else np.zeros(len(records), int)
        for rec in records:
            rec.nrows = int(counts[rec.id])

        return cls(records, vis=vis, nspw=nspw, freq_min_hz=float(freqs.min()),
                   freq_max_hz=float(freqs.max()), freq_mean_hz=float(freqs.mean()))

    @classmethod
    def from_dict(cls, d: dict) -> 'FieldModel':
        fm = cls([FieldRecord.from_dict(r) for r in d['fields']], vis=d.get('vis', ''),
                 nspw=d.get('nspw', 0), freq_min_hz=d.get('freq_min_hz', 0.0),
                 freq_max_hz=d.get('freq_max_hz', 0.0), freq_mean_hz=d.get('freq_mean_hz', 0.0))
        if d.get('resolved'):
            fm._roles = {r: [int(i) for i in d.get('roles', {}).get(r, [])] for r in ROLES}
            fm.dropped = list(d.get('dropped', []))
            fm._legacy = dict(d.get('legacy', {}))
            fm._phasecal_override = dict(d.get('phasecal_override', {}))
            fm._transfer_cfg = d.get('transfer_cfg', '')
            fm._reference_cfg = d.get('reference_cfg', '')
            fm._resolved = True
        return fm

    def to_dict(self) -> dict:
        d = {'vis': self.vis, 'nspw': self.nspw, 'freq_min_hz': self.freq_min_hz,
             'freq_max_hz': self.freq_max_hz, 'freq_mean_hz': self.freq_mean_hz,
             'fields': [r.to_dict() for r in self.records.values()],
             'resolved': self._resolved}
        if self._resolved:
            d.update({'roles': {r: list(v) for r, v in self._roles.items()},
                      'dropped': list(self.dropped), 'legacy': dict(self._legacy),
                      'phasecal_override': {str(k): str(v) for k, v in self._phasecal_override.items()},
                      'transfer_cfg': self._transfer_cfg, 'reference_cfg': self._reference_cfg})
        return d

    # ------------------------------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------------------------------
    def fractional_bandwidth(self) -> float:
        """(max - min) / mean of all channel frequencies (same as v0.5 fitorder decision)."""
        if self.freq_mean_hz <= 0:
            return 0.0
        return (self.freq_max_hz - self.freq_min_hz) / self.freq_mean_hz

    def _available(self) -> str:
        return ', '.join(f"{r.id}:'{r.name}'" for r in self.records.values())

    def _ids_for_name(self, name: str) -> list:
        return [r.id for r in self.records.values() if r.name == name]

    def duplicates(self) -> dict:
        out = {}
        for r in self.records.values():
            out.setdefault(r.name, []).append(r.id)
        return {k: v for k, v in out.items() if len(v) > 1}

    def _drop_reason(self, rec: FieldRecord) -> str:
        """Reason to drop ``rec`` from a name expansion, '' to keep it."""
        if rec.nrows == 0:
            return 'no rows in the main table (metadata only)'
        if rec.is_pointing_only():
            return 'pointing scans only (CALIBRATE_POINTING)'
        if rec.is_null_only():
            siblings = [self.records[i] for i in self._ids_for_name(rec.name) if i != rec.id]
            real = [s.id for s in siblings if s.has_real_intent() and s.nrows > 0]
            if real:
                return (f"only SYSTEM_CONFIGURATION/UNSPECIFIED intents; field(s) "
                        f"{','.join(map(str, real))} with the same name carry the real intent")
        return ''

    def _record_drop(self, rec: FieldRecord, role: str, reason: str):
        entry = {'id': rec.id, 'name': rec.name, 'role': role, 'reason': reason}
        if entry not in self.dropped:
            self.dropped.append(entry)
            logger.info(f"Field {rec.id} '{rec.name}' not used as {role}: {reason}")
        if reason not in rec.notes:
            rec.notes.append(reason)

    def _expand(self, tokens: list, role: str, from_config: bool) -> list:
        """Turn names/IDs into kept IDs, recording dropped ones."""
        kept = []
        for tok in tokens:
            if tok.isdigit():
                fid = int(tok)
                if fid not in self.records:
                    raise FieldModelError(f"{role}: field ID {fid} not in the MS. Available: {self._available()}")
                reason = self._drop_reason(self.records[fid])
                if reason:
                    note = f"explicit ID given for {role} although: {reason}"
                    if note not in self.records[fid].notes:
                        self.records[fid].notes.append(note)
                    logger.warning(f"Field {fid}: {note}")
                if fid not in kept:
                    kept.append(fid)
                continue
            ids = self._ids_for_name(tok)
            if not ids:
                raise FieldModelError(f"{role}: field name '{tok}' not in the MS. Available: {self._available()}")
            name_kept = []
            for fid in ids:
                reason = self._drop_reason(self.records[fid])
                if reason:
                    self._record_drop(self.records[fid], role, reason)
                else:
                    name_kept.append(fid)
            if not name_kept:
                src = 'config' if from_config else 'intents'
                raise FieldModelError(
                    f"{role}: name '{tok}' (from {src}) matches IDs {ids} but none is usable: "
                    + '; '.join(f"{i}: {self._drop_reason(self.records[i])}" for i in ids))
            kept.extend(i for i in name_kept if i not in kept)
        return sorted(kept)

    def _intent_names(self, role: str) -> list:
        """Names of the fields with rows carrying the role's intent, in ID order (v0.5 listobs order)."""
        sub = _ROLE_INTENT[role]
        return [r.name for r in self.records.values() if r.nrows > 0 and r.has_raw_intent(sub)]

    # ------------------------------------------------------------------------------------------
    # role resolution
    # ------------------------------------------------------------------------------------------
    def resolve_roles(self, sources_cfg) -> 'FieldModel':
        self.dropped = []
        self._roles = {r: [] for r in ROLES}
        for rec in self.records.values():
            rec.roles = []
            rec.notes = []

        for role in CONFIG_ROLES:
            value = getattr(sources_cfg, _CFG_ATTR[role], '') or ''
            tokens = _split_tokens(value)
            from_config = bool(tokens)
            if from_config:
                self._legacy[role] = ','.join(tokens)
            else:
                names = self._intent_names(role)
                self._legacy[role] = ','.join(names)
                tokens = list(dict.fromkeys(names))
                logger.info(f"{role}: not given in the config; from intents -> {tokens}")
                if not tokens:
                    logger.warning(f"{role}: no field carries the {_ROLE_INTENT[role]} intent.")
            self._roles[role] = self._expand(tokens, role, from_config)

        assigned = set().union(*(self._roles[r] for r in CONFIG_ROLES))
        self._roles['pointing'] = sorted(r.id for r in self.records.values()
                                         if r.nrows > 0 and r.is_pointing_only() and r.id not in assigned)
        self._roles['ignore'] = sorted(i for i in self.records
                                       if i not in assigned and i not in self._roles['pointing'])
        for role in ROLES:
            for fid in self._roles[role]:
                self.records[fid].roles.append(role)

        self._phasecal_override = dict(getattr(sources_cfg, 'phasecal_for_target', {}) or {})
        self._transfer_cfg = getattr(sources_cfg, 'transfer', '') or ''
        self._reference_cfg = getattr(sources_cfg, 'reference', '') or ''
        self._resolved = True
        if self._phasecal_override:
            self.phasecal_for_target()      # validate early
        return self

    def _check(self):
        if not self._resolved:
            raise FieldModelError("resolve_roles() has not been called.")

    # ------------------------------------------------------------------------------------------
    # accessors
    # ------------------------------------------------------------------------------------------
    def ids(self, role: str) -> list:
        self._check()
        if role in ('calibrators', 'calibrators_all'):
            return self.calibrator_ids()
        if role not in self._roles:
            raise FieldModelError(f"Unknown role '{role}'. Valid: {ROLES + ('calibrators',)}")
        return list(self._roles[role])

    def selection(self, role: str) -> str:
        return ','.join(str(i) for i in self.ids(role))

    def names(self, role: str) -> list:
        return list(dict.fromkeys(self.records[i].name for i in self.ids(role)))

    def calibrator_ids(self) -> list:
        self._check()
        return sorted(set(self._roles['flux']) | set(self._roles['bandpass']) | set(self._roles['phase']))

    def calibrator_selection(self) -> str:
        return ','.join(str(i) for i in self.calibrator_ids())

    def _resolve_cfg_ids(self, value: str, label: str) -> list:
        tokens = _split_tokens(value)
        out = []
        for tok in tokens:
            if tok.isdigit():
                if int(tok) not in self.records:
                    raise FieldModelError(f"{label}: field ID {tok} not in the MS. Available: {self._available()}")
                out.append(int(tok))
            else:
                ids = [i for i in self._ids_for_name(tok) if not self._drop_reason(self.records[i])]
                if not self._ids_for_name(tok):
                    raise FieldModelError(f"{label}: field name '{tok}' not in the MS. "
                                          f"Available: {self._available()}")
                out.extend(ids)
        return sorted(set(out))

    def fluxscale_reference(self) -> list:
        """config `reference` if given, else the flux calibrator IDs."""
        self._check()
        if _split_tokens(self._reference_cfg):
            return self._resolve_cfg_ids(self._reference_cfg, 'reference')
        return self.ids('flux')

    def fluxscale_transfer(self) -> list:
        """config `transfer` if given, else (v0.5 default) all calibrators incl. the flux calibrator."""
        self._check()
        if _split_tokens(self._transfer_cfg):
            return self._resolve_cfg_ids(self._transfer_cfg, 'transfer')
        return self.calibrator_ids()

    # ------------------------------------------------------------------------------------------
    # target -> phase calibrator
    # ------------------------------------------------------------------------------------------
    def _intervals(self, rec: FieldRecord) -> list:
        if rec.scan_times:
            return [tuple(rec.scan_times[s]) for s in sorted(rec.scan_times)]
        # no times: fall back to scan numbers as a proxy for time order
        return [(float(s), float(s)) for s in rec.scans]

    def _time_gap(self, target_id: int, cal_id: int) -> float:
        """Median over the target scans of the minimal gap to any scan of the calibrator."""
        t_int = self._intervals(self.records[target_id])
        c_int = self._intervals(self.records[cal_id])
        if not t_int or not c_int:
            return float('inf')
        gaps = []
        for a, b in t_int:
            gaps.append(min(max(0.0, c - b, a - d) for c, d in c_int))
        return float(np.median(gaps))

    def _closest(self, target_id: int, candidates: list) -> int:
        return min(candidates, key=lambda c: (self._time_gap(target_id, c), c))

    def _ids_in_role(self, token, role: str, label: str) -> list:
        tok = str(token).strip()
        role_ids = self.ids(role)
        ids = [int(tok)] if tok.isdigit() else [i for i in self._ids_for_name(tok) if i in role_ids]
        if tok.isdigit() and int(tok) not in role_ids or not ids:
            raise FieldModelError(f"phasecal_for_target {label} '{tok}' is not a {role} field. "
                                  f"{role} fields: " + ', '.join(f"{i}:'{self.records[i].name}'"
                                                                 for i in role_ids))
        return ids

    def phasecal_for_target(self, override=None) -> dict:
        """target ID -> phase calibrator ID. Default: closest in time (robust median of the minimal gap per
        target scan). ``override`` (or the config mapping) maps target names/IDs to phase names/IDs; a phase
        name shared by several phase IDs selects the closest of them."""
        self._check()
        override = self._phasecal_override if override is None else override
        phase = self.ids('phase')
        out = {}
        forced = {}
        for key, value in (override or {}).items():
            tids = self._ids_in_role(key, 'target', 'target')
            cids = self._ids_in_role(value, 'phase', 'phase calibrator')
            for t in tids:
                forced[t] = cids
        for t in self.ids('target'):
            cands = forced.get(t, phase)
            if not cands:
                continue
            out[t] = self._closest(t, cands)
        return out

    # ------------------------------------------------------------------------------------------
    # v0.5 compatibility
    # ------------------------------------------------------------------------------------------
    def legacy_name_selection(self, role: str) -> str:
        """The name string v0.5 would have passed to CASA for ``role`` (getms_info + format_fields)."""
        self._check()
        if role in ('calibrators', 'calibrators_all'):
            f, b, p = self._legacy['flux'], self._legacy['bandpass'], self._legacy['phase']
            return f + ',' + b + ',' + p if f != b else f + ',' + p
        if role not in self._legacy:
            raise FieldModelError(f"No legacy selection for role '{role}'.")
        return self._legacy[role]

    def legacy_ids(self, role: str) -> list:
        """IDs CASA selects with the v0.5 name string (all IDs with each name, no filtering)."""
        out = set()
        for tok in _split_tokens(self.legacy_name_selection(role)):
            if tok.isdigit():
                out.add(int(tok))
            else:
                out.update(self._ids_for_name(tok))
        return sorted(out)

    def compare_legacy(self) -> dict:
        """role -> {'legacy': [...], 'new': [...]} for the roles whose ID sets differ."""
        diff = {}
        for role in CONFIG_ROLES + ('calibrators',):
            old, new = self.legacy_ids(role), self.ids(role)
            if old != new:
                diff[role] = {'legacy': old, 'new': new}
        return diff

    # ------------------------------------------------------------------------------------------
    # report
    # ------------------------------------------------------------------------------------------
    def report(self) -> str:
        rows = [('ID', 'Name', 'Intents', 'Nscans', 'Nrows', 'Roles', 'Notes')]
        for r in self.records.values():
            rows.append((str(r.id), r.name, ','.join(sorted(r.real_intents)) or ','.join(r.intents) or '-',
                         str(len(r.scans)), str(r.nrows), ','.join(r.roles) or '-', '; '.join(r.notes)))
        widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]) - 1)]
        lines = []
        for k, row in enumerate(rows):
            lines.append('  '.join(c.ljust(w) for c, w in zip(row[:-1], widths)) + '  ' + row[-1])
            if k == 0:
                lines.append('-' * len(lines[0]))
        if self._resolved:
            lines.append('')
            for role in CONFIG_ROLES + ('pointing',):
                lines.append(f"{role:>9}: {self.selection(role) or '-'}")
            lines.append(f"calibrators: {self.calibrator_selection()}")
            pmap = self.phasecal_for_target()
            if pmap:
                lines.append('phasecal_for_target: ' + ', '.join(f"{t}->{c}" for t, c in pmap.items()))
            for role, d in self.compare_legacy().items():
                lines.append(f"differs from v0.5 name selection [{role}]: legacy {d['legacy']} -> new {d['new']}")
        if self.nspw:
            lines.append(f"nspw={self.nspw}, {self.freq_min_hz/1e9:.4f}-{self.freq_max_hz/1e9:.4f} GHz, "
                         f"fractional bandwidth {self.fractional_bandwidth():.4f}")
        return '\n'.join(lines)
