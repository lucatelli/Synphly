"""
Logging setup.

``setup_logging(ctx)`` writes two log files to ``<working_directory>/logs/``:

- ``synphly_<timestamp>.log``: the Synphly log (DEBUG and above);
- ``casa_<timestamp>.log``: the CASA log (``casalog.setlogfile``).

It also adds a console handler (INFO) and quietens matplotlib. Calling it again (for example in an
interactive session) does not add duplicate handlers.

``write_resolved_config(ctx)`` saves the resolved configuration (all keys, defaults filled in) next to the
log as ``config_resolved_<timestamp>.toml``.

``run_directory(path)`` is the working directory of the process while the pipeline runs (``<wd>/logs``): CASA
writes its default ``casa-*.log`` on import, ``<task>.last`` parameter files and ``TempLattice*`` scratch
images into the current directory, and none of these should land in the repository or wherever Synphly was
started from. ``absolutize_config_paths(cfg)`` first resolves the relative paths of the config against the
launch directory (the v0.5 semantics).
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from datetime import datetime

_MARK = '_synphly_handler'
_FMT = '%(asctime)s %(levelname)-8s %(name)s: %(message)s'


def _has_handler(root: logging.Logger, kind: str):
    for h in root.handlers:
        if getattr(h, _MARK, None) == kind:
            return h
    return None


def setup_logging(ctx, console_level: int = logging.INFO) -> str:
    """Configure the synphly + CASA logs in ``ctx.paths.logs``. Returns the synphly log file path."""
    log_dir = ctx.paths.logs
    os.makedirs(log_dir, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    file_handler = _has_handler(root, 'file')
    if file_handler is not None and os.path.dirname(file_handler.baseFilename) != os.path.abspath(log_dir):
        # a different working directory in the same session: move the file log there
        root.removeHandler(file_handler)
        file_handler.close()
        file_handler = None
    if file_handler is None:
        logfile = os.path.join(log_dir, f'synphly_{stamp}.log')
        file_handler = logging.FileHandler(logfile)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(_FMT))
        setattr(file_handler, _MARK, 'file')
        root.addHandler(file_handler)
    logfile = file_handler.baseFilename

    if _has_handler(root, 'console') is None:
        console = logging.StreamHandler()
        console.setLevel(console_level)
        console.setFormatter(logging.Formatter('%(levelname)s %(message)s'))
        setattr(console, _MARK, 'console')
        root.addHandler(console)

    logging.getLogger('matplotlib').setLevel(logging.WARNING)
    logging.getLogger('PIL').setLevel(logging.WARNING)

    log = logging.getLogger(__name__)
    try:
        # first import of CASA: its default casa-<time>.log is created in the cwd -> create it in log_dir
        prev = os.getcwd()
        os.chdir(log_dir)
        try:
            from .casa import casalog
        finally:
            os.chdir(prev)
        casa_logfile = os.path.join(log_dir, f'casa_{stamp}.log')
        current = casalog.logfile() if hasattr(casalog, 'logfile') else ''
        if os.path.dirname(os.path.abspath(current or '')) != os.path.abspath(log_dir):
            casalog.setlogfile(casa_logfile)
            current = casa_logfile
        ctx.casa_log_file = current
    except ImportError as e:
        log.warning(f"CASA log not redirected ({e}).")

    ctx.log_file = logfile
    log.info(f"Synphly log: {logfile}")
    return logfile


def write_resolved_config(ctx) -> str:
    """Write the resolved config to ``<wd>/logs/config_resolved_<stamp>.toml`` (stamp of the synphly log)."""
    from .config import resolved_config_text
    base = os.path.basename(ctx.log_file or '')
    stamp = base[len('synphly_'):-len('.log')] if base.startswith('synphly_') else \
        datetime.now().strftime('%Y%m%d_%H%M%S')
    path = os.path.join(ctx.paths.logs, f'config_resolved_{stamp}.toml')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(resolved_config_text(ctx.cfg))
    logging.getLogger(__name__).info(f"Resolved configuration: {path}")
    return path


# config keys holding file paths (resolved against the launch directory before the cwd changes)
PATH_KEYS = (('globals', 'working_directory'), ('globals', 'asdm_file'), ('globals', 'singularity_path'),
             ('flagging', 'aoflagger_sif'), ('flagging', 'aoflagger_strategy'), ('flagging', 'manual_file'))


def absolutize_config_paths(cfg, base=None) -> None:
    """Make the relative file paths of ``cfg`` absolute (relative to ``base``, default the cwd)."""
    base = base or os.getcwd()
    for sec, key in PATH_KEYS:
        obj = getattr(cfg, sec)
        v = getattr(obj, key, '')
        if isinstance(v, str) and v and not os.path.isabs(v):
            setattr(obj, key, os.path.normpath(os.path.join(base, v)))


@contextmanager
def run_directory(path):
    """Temporarily make ``path`` (created if needed) the current directory."""
    os.makedirs(path, exist_ok=True)
    prev = os.getcwd()
    os.chdir(path)
    try:
        yield path
    finally:
        os.chdir(prev)
