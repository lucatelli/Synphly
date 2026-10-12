"""
The single place where Synphly imports CASA (casatools / casatasks).

Every other module imports the tasks it needs from here, e.g. ``from ..casa import gaincal``. This keeps the
CASA dependency in one spot and makes it easy to replace the tasks with recorders in tests.

Tools are created by the factories ``msmetadata()``, ``table()`` and ``ms()``. Use the context managers
``open_msmd(vis)``, ``open_table(path)`` and ``open_ms(vis)``: they always close the tool, also on errors.
"""
from __future__ import annotations

from contextlib import contextmanager

_CASA_MSG = ("Synphly could not import the CASA modules (casatools/casatasks). "
             "Run Synphly inside a CASA-enabled environment (modular CASA 6, e.g. "
             "`pip install casatools casatasks`).")

try:
    import casatools as _casatools
    from casatasks import (
        applycal, bandpass, clearcal, delmod, exportfits, flagdata, flagmanager, fluxscale, gaincal,
        gencal, hanningsmooth, importasdm, listobs, mstransform, plotants, plotweather, setjy, split,
        statwt, tclean, casalog,
    )
except ImportError as _e:  # pragma: no cover - depends on the environment
    raise ImportError(f"{_CASA_MSG} Original error: {_e}") from _e

__all__ = [
    'applycal', 'bandpass', 'clearcal', 'delmod', 'exportfits', 'flagdata', 'flagmanager', 'fluxscale',
    'gaincal', 'gencal', 'hanningsmooth', 'importasdm', 'listobs', 'mstransform', 'plotants',
    'plotweather', 'setjy', 'split', 'statwt', 'tclean', 'casalog',
    'msmetadata', 'table', 'ms', 'open_msmd', 'open_table', 'open_ms',
]


def msmetadata():
    """Return a new casatools.msmetadata tool."""
    return _casatools.msmetadata()


def table():
    """Return a new casatools.table tool."""
    return _casatools.table()


def ms():
    """Return a new casatools.ms tool."""
    return _casatools.ms()


@contextmanager
def open_msmd(vis: str):
    """Open ``vis`` with msmetadata (read only) and always call ``done()``."""
    md = msmetadata()
    md.open(vis)
    try:
        yield md
    finally:
        md.done()


@contextmanager
def open_table(path: str, nomodify: bool = True):
    """Open a CASA table (read only by default) and always close it."""
    tb = table()
    tb.open(path, nomodify=nomodify)
    try:
        yield tb
    finally:
        tb.close()


@contextmanager
def open_ms(vis: str):
    """Open ``vis`` with the ms tool and always close it."""
    m = ms()
    m.open(vis)
    try:
        yield m
    finally:
        m.close()
