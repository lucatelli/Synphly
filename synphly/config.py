"""
Synphly configuration schema.

One dataclass per config section. Key names are identical to the v0.5 ``config.ini`` keys, so that
old INI files map 1:1 onto this schema. Defaults equal the values of the v0.5 active configuration;
changing a default changes the calibration, so do it deliberately and note it in CHANGELOG.md.

Loaders (TOML, legacy INI) and validation live further down in this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field, fields, asdict
from typing import Optional


@dataclass
class GlobalsConfig:
    experiment_name: str = ''          # REQUIRED. MS basename without the .ms extension
    working_directory: str = ''        # REQUIRED. All data products are written here
    asdm_file: str = ''                # if empty, the MS <working_directory>/<experiment_name>.ms must exist
    load_data: bool = True
    run_only_ms_info: bool = False     # kept for legacy INI files; prefer `synphly info CFG`
    do_hanning: bool = False
    use_singularity: bool = False
    singularity_path: str = ''
    ms_info: bool = True
    report_verbosity: int = 3


@dataclass
class SourcesConfig:
    # Comma-separated field names and/or IDs. Empty -> resolved from scan intents.
    flux_calibrator: str = ''
    bandpass_calibrator: str = ''
    phase_calibrator: str = ''
    target: str = ''
    # fluxscale transfer / reference field IDs (comma-separated). Empty -> derived from roles.
    transfer: str = ''
    reference: str = ''
    # Optional explicit mapping target -> phase calibrator (names or IDs).
    # Empty -> assigned automatically by time adjacency of scans.
    phasecal_for_target: dict = field(default_factory=dict)


@dataclass
class FlaggingConfig:
    do_flagging: bool = True
    do_pre_flagging: bool = True
    use_aoflagger: bool = False
    do_tfcrop_raw: bool = True
    aoflagger_sif: str = '/singularity_containers/lofar_aoflagger_3.1.0.sif'  # v0.5 config.ini value
    aoflagger_strategy: str = './aoflagger_strategies/jvla-default.lua'
    manual_file: str = ''
    edge_channel_frac: float = 0.2                # fraction skipped at each spw edge for the delay solve
    edge_channel_flag_frac_cals: float = 0.06
    edge_channel_flag_frac_science: float = 0.03
    do_flag_edge_channels_cals: bool = True
    do_flag_edge_channels_science: bool = True
    do_flag_pointing_scans: bool = True
    do_intent_flagging: bool = True               # re-apply the intent flags on the MS that is calibrated
    # Quack (seconds). v0.5 behaviour: 1 s at the beginning and 1 s at the end of each scan, all fields.
    quack_interval_beg: float = 1.0
    quack_interval_endb: float = 1.0
    # Extra quack per role, applied on top of the above (0 = off, which is the v0.5 behaviour).
    quack_extra_flux_beg: float = 0.0
    quack_extra_phase_beg: float = 0.0
    quack_extra_phase_endb: float = 0.0
    cals_flag_mode_strategy: str = 'rflag'        # rflag | tfcrop | none
    cals_datacolumn_to_flag: str = 'residual'
    science_flag_mode_strategy: str = 'rflag'     # rflag | tfcrop | none
    science_datacolumn_to_flag: str = 'residual'
    ntime: str = 'scan'
    combinescans: bool = False
    tfcrop_timecutoff_cals: float = 4.0
    tfcrop_freqcutoff_cals: float = 4.0
    tfcrop_freqcutoff_science: float = 4.0
    tfcrop_timecutoff_science: float = 4.0
    rflag_timedevscale_cals: float = 4.0
    rflag_freqdevscale_cals: float = 4.0
    rflag_timedevscale_science: float = 4.0
    rflag_freqdevscale_science: float = 4.0
    maxnpieces: int = 5
    winsize: int = 5
    do_clip_data: bool = True
    clipmin: float = 0.0
    clipmax: float = 50.0


@dataclass
class AverageConfig:
    do_average: bool = True
    time_avg: bool = True
    timebin_avg: str = '3s'
    channel_avg: bool = False
    chan_out_avg: int = 32


@dataclass
class CalibrateConfig:
    do_initial_cal: bool = True
    do_setjy: bool = True
    do_refant: bool = True
    refant: str = 'None'               # 'None' -> automatic selection; otherwise e.g. 'ea12,ea13'
    band: str = ''                     # VLA band letter used for the flux model (L,S,C,X,U,K,A,Q)
    bp_solint_K: str = 'inf'
    minsnr_K: float = 3.0
    bp_solint_G_p: str = '18s'
    minsnr_bp_G_p: float = 3.0
    bp_solint_G_ap: str = '36s'
    bp_solint_BP: str = 'inf'
    minsnr: float = 3.0
    all_solint_short_p: str = '18s'
    all_solint_short_ap: str = '36s'
    all_solint_long_p: str = 'inf'
    all_solint_inf_ap: str = 'inf'
    bp_applymode: str = 'calflag'
    ph_ap_applymode: str = 'calflag'
    science_applymode: str = 'calflagstrict'
    bp_fillgaps: int = 8
    do_bandpass_1st_run: bool = True
    do_gain_calibration_1st_run: bool = True
    do_apply_science_1st_run: bool = True
    calwt_1st: bool = True
    do_bandpass_2nd_run: bool = True
    do_gain_calibration_2nd_run: bool = True
    calwt_2nd: bool = False
    do_apply_science: bool = True
    do_flag_science: bool = True
    do_run_statwt: bool = False
    statwt_timebin: str = '12s'
    statwt_statalg: str = 'chauvenet'
    do_split: bool = True
    timebin_longer: str = '6s'
    timebin: str = '6s'
    width: int = 1
    solint: str = '60s'


@dataclass
class FluxscaleConfig:
    # 'auto' -> 1 if fractional bandwidth >= fitorder_bw_threshold else 0 (v0.5 behaviour)
    fitorder: str = 'auto'
    fitorder_bw_threshold: float = 0.05
    incremental: bool = False


@dataclass
class ImagingConfig:
    do_imaging: bool = False
    imager: str = 'tclean'
    parallel: bool = False


@dataclass
class PlottingConfig:
    plot_backend: str = 'python'       # python | plotms | none
    plot_caltables: bool = True
    plot_visibilities: bool = True
    plot_flag_stats: bool = True


@dataclass
class PipelineConfig:
    # auto   -> reuse a table only if its recorded input hash matches
    # always -> reuse any existing table with the expected name (v0.5 behaviour)
    # never  -> always recompute
    reuse_tables: str = 'auto'


@dataclass
class Config:
    globals: GlobalsConfig = field(default_factory=GlobalsConfig)
    sources: SourcesConfig = field(default_factory=SourcesConfig)
    flagging: FlaggingConfig = field(default_factory=FlaggingConfig)
    average: AverageConfig = field(default_factory=AverageConfig)
    calibrate: CalibrateConfig = field(default_factory=CalibrateConfig)
    fluxscale: FluxscaleConfig = field(default_factory=FluxscaleConfig)
    imaging: ImagingConfig = field(default_factory=ImagingConfig)
    plotting: PlottingConfig = field(default_factory=PlottingConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)

    # path of the file this config was loaded from (not a config key)
    source_path: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop('source_path', None)
        return d


SECTIONS = {f.name: f.type for f in fields(Config) if f.name != 'source_path'}
REQUIRED = {('globals', 'experiment_name'), ('globals', 'working_directory')}


# ======================================================================================================
# Loading, validation and writing
# ======================================================================================================
import configparser
import difflib
import logging
import math
import os
import re
import tomllib
import typing
from datetime import datetime

logger = logging.getLogger(__name__)

__all__ = [
    'Config', 'GlobalsConfig', 'SourcesConfig', 'FlaggingConfig', 'AverageConfig', 'CalibrateConfig',
    'FluxscaleConfig', 'ImagingConfig', 'PlottingConfig', 'PipelineConfig', 'SECTIONS', 'REQUIRED',
    'ConfigError', 'load_config', 'load_toml', 'load_ini', 'config_from_dict', 'validate', 'to_toml_text',
    'dump_toml', 'convert_config', 'resolved_config_text', 'diff_from_defaults', 'VALID_BANDS',
]


class ConfigError(ValueError):
    """Raised for any invalid configuration (unknown keys, wrong types, missing or bad values)."""

    def __init__(self, problems, source=None):
        if isinstance(problems, str):
            problems = [problems]
        self.problems = list(problems)
        self.source = source
        where = f" in {source}" if source else ""
        msg = f"Invalid configuration{where}:\n" + "\n".join(f"  - {p}" for p in self.problems)
        super().__init__(msg)


# Section name -> dataclass. (`SECTIONS` above holds the annotation strings because of
# `from __future__ import annotations`; resolve them to the classes here.)
_SECTION_CLASSES = typing.get_type_hints(Config)
_SECTION_CLASSES.pop('source_path', None)
SECTION_CLASSES = {name: _SECTION_CLASSES[name] for name in SECTIONS}
# section -> {key: python type}
FIELD_TYPES = {sec: typing.get_type_hints(cls) for sec, cls in SECTION_CLASSES.items()}

# Fields that are comma-separated lists of names/IDs: a TOML array is accepted and joined with ','.
LIST_FIELDS = {('sources', k) for k in ('flux_calibrator', 'bandpass_calibrator', 'phase_calibrator',
                                         'target', 'transfer', 'reference')}

VALID_BANDS = ('L', 'S', 'C', 'X', 'U', 'Ku', 'K', 'A', 'Ka', 'Q')
_PLOT_BACKENDS = ('python', 'plotms', 'none')
_REUSE = ('auto', 'always', 'never')
_FITORDER = ('auto', '0', '1')
_FLAG_STRATEGIES = ('rflag', 'tfcrop', 'none')
_APPLYMODES = ('calflag', 'calflagstrict', 'trial', 'flagonly', 'flagonlystrict', 'calonly')
_DATACOLUMNS = ('data', 'corrected', 'residual', 'residual_data', 'model', 'float_data')
_SOLINT_FIELDS = ('bp_solint_K', 'bp_solint_G_p', 'bp_solint_G_ap', 'bp_solint_BP', 'all_solint_short_p',
                  'all_solint_short_ap', 'all_solint_long_p', 'all_solint_inf_ap', 'solint')
_TIMEBIN_FIELDS = (('average', 'timebin_avg'), ('calibrate', 'statwt_timebin'),
                   ('calibrate', 'timebin_longer'), ('calibrate', 'timebin'))
_NUM = r'\d+(\.\d*)?|\.\d+'
_TIME_RE = re.compile(rf'^({_NUM})\s*(s|sec|min|m|h|ms|us)?$', re.IGNORECASE)
_FREQ_RE = re.compile(rf'^({_NUM})\s*(ch|hz|khz|mhz|ghz)?$', re.IGNORECASE)


def _is_casa_solint(value: str) -> bool:
    """'inf', 'int', '<n>', '<n>s', '<n>min', '<n>h', optionally followed by ',<n>ch' / ',<n>MHz'."""
    parts = [p.strip() for p in str(value).split(',')]
    if not 1 <= len(parts) <= 2:
        return False
    t = parts[0]
    if not (t.lower() in ('inf', 'int') or _TIME_RE.match(t)):
        return False
    if len(parts) == 2 and not (parts[1].lower() == 'inf' or _FREQ_RE.match(parts[1])):
        return False
    return True


def _is_timebin(value: str) -> bool:
    return bool(_TIME_RE.match(str(value).strip()))


def _close(word, candidates):
    m = difflib.get_close_matches(word, list(candidates), n=3, cutoff=0.6)
    return f" (did you mean: {', '.join(m)}?)" if m else ""


# ------------------------------------------------------------------------------------------------------
# value coercion
# ------------------------------------------------------------------------------------------------------
def _coerce_toml(section, key, value, ftype):
    """Check/coerce a TOML value against the schema type. Returns (value, error_or_None)."""
    where = f"[{section}] {key}"
    if ftype is bool:
        if isinstance(value, bool):
            return value, None
        return None, f"{where}: expected true/false, got {type(value).__name__} {value!r}"
    if ftype is int:
        if isinstance(value, int) and not isinstance(value, bool):
            return value, None
        if isinstance(value, float) and value.is_integer():
            return int(value), None
        return None, f"{where}: expected an integer, got {type(value).__name__} {value!r}"
    if ftype is float:
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value), None
        return None, f"{where}: expected a number, got {type(value).__name__} {value!r}"
    if ftype is str:
        if isinstance(value, str):
            return value, None
        if isinstance(value, list) and (section, key) in LIST_FIELDS:
            bad = [v for v in value if isinstance(v, (bool, list, dict)) or not isinstance(v, (str, int))]
            if bad:
                return None, f"{where}: array items must be strings or integers, got {bad!r}"
            return ','.join(str(v).strip() for v in value), None
        if isinstance(value, int) and not isinstance(value, bool):
            # e.g. `reference = 0`, `fitorder = 1`
            return str(value), None
        return None, f"{where}: expected a string, got {type(value).__name__} {value!r}"
    if ftype is dict:
        if not isinstance(value, dict):
            return None, f"{where}: expected a table, got {type(value).__name__} {value!r}"
        out = {}
        for k, v in value.items():
            if isinstance(v, (str, int)) and not isinstance(v, bool):
                out[str(k)] = str(v)
            else:
                return None, f"{where}.{k}: expected a string or integer, got {type(v).__name__} {v!r}"
        return out, None
    return None, f"{where}: unsupported schema type {ftype!r}"  # pragma: no cover


def _parse_mapping_string(text):
    """'T1:P1, T2:P2' -> {'T1': 'P1', 'T2': 'P2'} (INI form of [sources] phasecal_for_target)."""
    out = {}
    for item in filter(None, (s.strip() for s in text.split(','))):
        if ':' not in item:
            raise ValueError(f"expected 'target:phasecal' items, got {item!r}")
        k, v = item.split(':', 1)
        out[k.strip()] = v.strip()
    return out


# ------------------------------------------------------------------------------------------------------
# construction
# ------------------------------------------------------------------------------------------------------
def _build(values, source_path=None) -> Config:
    """values: {section: {key: coerced value}} -> Config (missing keys take schema defaults)."""
    kwargs = {sec: SECTION_CLASSES[sec](**values.get(sec, {})) for sec in SECTIONS}
    return Config(**kwargs, source_path=source_path)


def config_from_dict(data: dict, source: Optional[str] = None) -> Config:
    """Build a Config from a TOML-like nested dict, with full type checking (as for TOML files)."""
    problems = []
    values = {}
    if not isinstance(data, dict):
        raise ConfigError(f"top level must be a table, got {type(data).__name__}", source)
    for sec, content in data.items():
        if sec not in SECTIONS:
            problems.append(f"unknown section [{sec}]{_close(sec, SECTIONS)}")
            continue
        if not isinstance(content, dict):
            problems.append(f"[{sec}] must be a table, got {type(content).__name__} {content!r}")
            continue
        types = FIELD_TYPES[sec]
        values[sec] = {}
        for key, val in content.items():
            if key not in types:
                # look in other sections too, a common mistake is a key in the wrong section
                elsewhere = [s for s in SECTIONS if key in FIELD_TYPES[s]]
                hint = f" (it belongs to [{elsewhere[0]}])" if elsewhere else _close(key, types)
                problems.append(f"unknown key '{key}' in [{sec}]{hint}")
                continue
            coerced, err = _coerce_toml(sec, key, val, types[key])
            if err:
                problems.append(err)
            else:
                values[sec][key] = coerced
    for sec, key in sorted(REQUIRED):
        sec_data = data.get(sec, {})
        if not isinstance(sec_data, dict) or key not in sec_data:
            problems.append(f"missing required key '{key}' in [{sec}]")
    if problems:
        raise ConfigError(problems, source)
    return _build(values, source)


def load_toml(path) -> Config:
    path = os.path.abspath(os.fspath(path))
    try:
        with open(path, 'rb') as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"TOML syntax error: {e}", path) from e
    return config_from_dict(data, source=path)


def load_ini(path) -> Config:
    """
    Read a legacy v0.5 ``config.ini``.

    Parsing is identical to v0.5 ``main.py``: a default ``configparser.ConfigParser`` (keys are
    case-insensitive, full-line ``#``/``;`` comments, no inline comments), and ``getboolean`` /
    ``getint`` / ``getfloat`` / ``get`` according to the schema type. Keys missing from the file take
    the schema defaults; unknown sections/keys only produce a warning (old files carry junk).
    """
    path = os.path.abspath(os.fspath(path))
    if not os.path.isfile(path):
        raise ConfigError(f"file not found: {path}", path)
    cp = configparser.ConfigParser()
    try:
        cp.read(path)
    except configparser.Error as e:
        raise ConfigError(f"INI syntax error: {e}", path) from e

    problems = []
    values = {}
    defaulted = []
    for sec in cp.sections():
        if sec not in SECTIONS:
            logger.warning("%s: ignoring unknown INI section [%s]%s", path, sec, _close(sec, SECTIONS))
            continue
        types = FIELD_TYPES[sec]
        lower = {k.lower(): k for k in types}  # configparser lower-cases option names
        values[sec] = {}
        for opt in cp.options(sec):
            if opt not in lower:
                logger.warning("%s: ignoring unknown INI key '%s' in [%s]%s", path, opt, sec,
                               _close(opt, lower))
                continue
            key = lower[opt]
            ftype = types[key]
            try:
                if ftype is bool:
                    val = cp.getboolean(sec, opt)
                elif ftype is int:
                    val = cp.getint(sec, opt)
                elif ftype is float:
                    val = cp.getfloat(sec, opt)
                elif ftype is dict:
                    val = _parse_mapping_string(cp.get(sec, opt))
                else:
                    val = cp.get(sec, opt)
            except (ValueError, configparser.Error) as e:
                problems.append(f"[{sec}] {key}: {e}")
                continue
            values[sec][key] = val
    for sec in SECTIONS:
        for key in FIELD_TYPES[sec]:
            if key not in values.get(sec, {}):
                defaulted.append(f"{sec}.{key}")
    for sec, key in sorted(REQUIRED):
        if key not in values.get(sec, {}):
            problems.append(f"missing required key '{key}' in [{sec}]")
    if problems:
        raise ConfigError(problems, path)
    if defaulted:
        logger.info("%s: %d keys not in the INI file take schema defaults: %s", path, len(defaulted),
                    ', '.join(defaulted))
    return _build(values, path)


def load_config(path, check: bool = True) -> Config:
    """
    Load a configuration file. ``.toml`` -> TOML schema loader; ``.ini``/``.cfg`` -> legacy v0.5 INI reader.
    With ``check=True`` (default) :func:`validate` is run as well.
    """
    ext = os.path.splitext(os.fspath(path))[1].lower()
    if ext == '.toml':
        cfg = load_toml(path)
    elif ext in ('.ini', '.cfg'):
        cfg = load_ini(path)
    else:
        raise ConfigError(f"unknown config file extension '{ext}' (expected .toml, .ini or .cfg)",
                          os.fspath(path))
    if check:
        validate(cfg)
    return cfg


# ------------------------------------------------------------------------------------------------------
# semantic validation
# ------------------------------------------------------------------------------------------------------
def validate(cfg: Config) -> list:
    """
    Semantic checks. Raises :class:`ConfigError` listing every problem; returns the list of warnings
    (which are also logged).
    """
    errors, warnings = [], []
    g, s, fl, av, ca, fx, pl, pi = (cfg.globals, cfg.sources, cfg.flagging, cfg.average, cfg.calibrate,
                                    cfg.fluxscale, cfg.plotting, cfg.pipeline)

    if not g.experiment_name.strip():
        errors.append("[globals] experiment_name is empty")
    elif g.experiment_name.endswith('.ms'):
        errors.append("[globals] experiment_name must not include the .ms extension")
    if not g.working_directory.strip():
        errors.append("[globals] working_directory is empty")
    if g.report_verbosity < 0:
        errors.append(f"[globals] report_verbosity must be >= 0, got {g.report_verbosity}")
    if g.use_singularity and not g.singularity_path:
        warnings.append("[globals] use_singularity = true but singularity_path is empty")

    if pl.plot_backend not in _PLOT_BACKENDS:
        errors.append(f"[plotting] plot_backend must be one of {_PLOT_BACKENDS}, got {pl.plot_backend!r}")
    if pi.reuse_tables not in _REUSE:
        errors.append(f"[pipeline] reuse_tables must be one of {_REUSE}, got {pi.reuse_tables!r}")
    if str(fx.fitorder) not in _FITORDER:
        errors.append(f"[fluxscale] fitorder must be one of {_FITORDER}, got {fx.fitorder!r}")
    if not 0.0 <= fx.fitorder_bw_threshold <= 2.0:
        errors.append(f"[fluxscale] fitorder_bw_threshold out of range: {fx.fitorder_bw_threshold}")

    for key in ('cals_flag_mode_strategy', 'science_flag_mode_strategy'):
        v = getattr(fl, key)
        if v not in _FLAG_STRATEGIES:
            errors.append(f"[flagging] {key} must be one of {_FLAG_STRATEGIES}, got {v!r}")
    for key in ('cals_datacolumn_to_flag', 'science_datacolumn_to_flag'):
        v = getattr(fl, key)
        if v.lower() not in _DATACOLUMNS:
            errors.append(f"[flagging] {key} must be one of {_DATACOLUMNS}, got {v!r}")
    for key in ('edge_channel_frac', 'edge_channel_flag_frac_cals', 'edge_channel_flag_frac_science'):
        v = getattr(fl, key)
        if not 0.0 <= v < 0.5:
            errors.append(f"[flagging] {key} must be in [0, 0.5), got {v}")
    for key in ('quack_interval_beg', 'quack_interval_endb', 'quack_extra_flux_beg',
                'quack_extra_phase_beg', 'quack_extra_phase_endb'):
        if getattr(fl, key) < 0:
            errors.append(f"[flagging] {key} must be >= 0, got {getattr(fl, key)}")
    if fl.clipmax <= fl.clipmin:
        errors.append(f"[flagging] clipmax ({fl.clipmax}) must be larger than clipmin ({fl.clipmin})")
    if fl.use_aoflagger and not fl.aoflagger_strategy:
        errors.append("[flagging] use_aoflagger = true but aoflagger_strategy is empty")
    if fl.ntime.strip().lower() != 'scan' and not _is_timebin(fl.ntime):
        errors.append(f"[flagging] ntime must be 'scan' or a time interval like '60s', got {fl.ntime!r}")

    if av.chan_out_avg < 1:
        errors.append(f"[average] chan_out_avg must be >= 1, got {av.chan_out_avg}")

    if ca.band == '':
        warnings.append("[calibrate] band is empty: the band will be guessed from the observing frequency")
    elif ca.band not in VALID_BANDS:
        errors.append(f"[calibrate] band must be one of {VALID_BANDS} (or empty), got {ca.band!r}"
                      f"{_close(ca.band, VALID_BANDS)}")
    for key in _SOLINT_FIELDS:
        v = getattr(ca, key)
        if not _is_casa_solint(v):
            errors.append(f"[calibrate] {key} = {v!r} is not a CASA solint "
                          f"('inf', 'int', '<n>s', '<n>min', '<n>s,<n>ch', ...)")
    for sec, key in _TIMEBIN_FIELDS:
        v = getattr(getattr(cfg, sec), key)
        if not _is_timebin(v):
            errors.append(f"[{sec}] {key} = {v!r} is not a time interval like '6s'")
    for key in ('bp_applymode', 'ph_ap_applymode', 'science_applymode'):
        v = getattr(ca, key)
        if v not in _APPLYMODES:
            errors.append(f"[calibrate] {key} must be one of {_APPLYMODES}, got {v!r}")
    for key in ('minsnr', 'minsnr_K', 'minsnr_bp_G_p'):
        if getattr(ca, key) < 0:
            errors.append(f"[calibrate] {key} must be >= 0, got {getattr(ca, key)}")
    if ca.bp_fillgaps < 0:
        errors.append(f"[calibrate] bp_fillgaps must be >= 0, got {ca.bp_fillgaps}")
    if ca.refant.strip() == '':
        errors.append("[calibrate] refant is empty: use 'None' for automatic selection")

    for key in ('transfer', 'reference'):
        v = getattr(s, key).strip()
        if v and not all(p.strip().isdigit() for p in v.split(',')):
            warnings.append(f"[sources] {key} = {v!r} is expected to be a list of field IDs")

    src = cfg.source_path or '<config>'
    for w in warnings:
        logger.warning("%s: %s", src, w)
    if errors:
        raise ConfigError(errors, cfg.source_path)
    return warnings


# ------------------------------------------------------------------------------------------------------
# writing TOML
# ------------------------------------------------------------------------------------------------------
_BARE_KEY = re.compile(r'^[A-Za-z0-9_-]+$')


def _toml_str(s: str) -> str:
    out = ['"']
    for ch in s:
        if ch == '"':
            out.append('\\"')
        elif ch == '\\':
            out.append('\\\\')
        elif ch == '\n':
            out.append('\\n')
        elif ch == '\t':
            out.append('\\t')
        elif ch == '\r':
            out.append('\\r')
        elif ord(ch) < 0x20 or ord(ch) == 0x7f:
            out.append(f'\\u{ord(ch):04x}')
        else:
            out.append(ch)
    out.append('"')
    return ''.join(out)


def _toml_key(k: str) -> str:
    return k if _BARE_KEY.match(k) else _toml_str(k)


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if math.isnan(v):
            return 'nan'
        if math.isinf(v):
            return 'inf' if v > 0 else '-inf'
        return repr(v)
    if isinstance(v, str):
        return _toml_str(v)
    if isinstance(v, dict):
        if not v:
            return '{}'
        return '{ ' + ', '.join(f"{_toml_key(str(k))} = {_toml_value(x)}" for k, x in v.items()) + ' }'
    if isinstance(v, (list, tuple)):
        return '[' + ', '.join(_toml_value(x) for x in v) + ']'
    raise TypeError(f"cannot write {type(v).__name__} to TOML")


def diff_from_defaults(cfg: Config, keep_required: bool = True) -> dict:
    """{section: {key: value}} of the values that differ from ``Config()`` (plus the required keys)."""
    ref = Config().to_dict()
    cur = cfg.to_dict()
    out = {}
    for sec in SECTIONS:
        for key, val in cur[sec].items():
            if val != ref[sec][key] or (keep_required and (sec, key) in REQUIRED):
                out.setdefault(sec, {})[key] = val
    return out


def to_toml_text(cfg: Config, minimal: bool = False, header: Optional[str] = None) -> str:
    """Serialise to TOML. ``minimal=True`` writes only keys differing from the defaults (+ required)."""
    data = diff_from_defaults(cfg) if minimal else cfg.to_dict()
    lines = []
    if header:
        lines += [('# ' + ln).rstrip() for ln in header.splitlines()]
        lines.append('')
    for sec in SECTIONS:
        if sec not in data or (minimal and not data[sec]):
            continue
        lines.append(f'[{sec}]')
        for key, val in data[sec].items():
            lines.append(f'{key} = {_toml_value(val)}')
        lines.append('')
    return '\n'.join(lines).rstrip('\n') + '\n'


def dump_toml(cfg: Config, path, minimal: bool = False, header: Optional[str] = None) -> str:
    """Write ``cfg`` as TOML to ``path``; returns the text written."""
    text = to_toml_text(cfg, minimal=minimal, header=header)
    path = os.fspath(path)
    d = os.path.dirname(os.path.abspath(path))
    os.makedirs(d, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)
    return text


def convert_config(in_path, out_path, minimal: bool = False) -> Config:
    """Convert a legacy INI (or any loadable) config to TOML (``python -m synphly convert-config``)."""
    cfg = load_config(in_path, check=False)
    header = (f"Converted from {os.path.abspath(os.fspath(in_path))}\n"
              f"by synphly convert-config on {datetime.now().isoformat(timespec='seconds')}.\n"
              + ("Only keys that differ from the defaults (configs/template.toml) are written."
                 if minimal else "All keys written (resolved values)."))
    dump_toml(cfg, out_path, minimal=minimal, header=header)
    logger.info("Wrote %s (from %s)", out_path, in_path)
    return cfg


def resolved_config_text(cfg: Config) -> str:
    """Full TOML of the resolved config (defaults filled in), to be saved in the run's log directory."""
    header = (f"Resolved synphly configuration\n"
              f"source: {cfg.source_path or '<none>'}\n"
              f"written: {datetime.now().isoformat(timespec='seconds')}")
    return to_toml_text(cfg, minimal=False, header=header)
