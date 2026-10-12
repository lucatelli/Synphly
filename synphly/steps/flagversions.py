"""
Flag-version helpers.

The v0.5 version names are kept (the restore-on-rerun logic and existing working directories depend on them).
``save_flag_version`` deletes an existing version of the same name before saving it: CASA ``flagmanager``
otherwise renames the old one to ``<name>.old.<timestamp>``, and those copies piled up on every re-run
(03 issue 15). Restores are unchanged: every place where v0.5 restores a version before re-saving it still
restores it first; the delete happens only at the (later) save, after which the saved content is the same as
the version CASA would have written.
"""
from __future__ import annotations

import logging
import os

from ..casa import flagmanager

log = logging.getLogger(__name__)


def flag_version_exists(vis: str, versionname: str) -> bool:
    return os.path.exists(f"{vis}.flagversions/flags.{versionname}")


def save_flag_version(vis: str, versionname: str, comment: str = '') -> None:
    """flagmanager(mode='save'), replacing an existing version of the same name."""
    if flag_version_exists(vis, versionname):
        log.info(f"Replacing the existing flag version '{versionname}' of {vis}.")
        flagmanager(vis=vis, mode='delete', versionname=versionname)
    flagmanager(vis=vis, mode='save', versionname=versionname, comment=comment)
