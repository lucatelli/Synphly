"""
Split every field of the calibrated MS into ``<wd>/fields/<field>/<field>.calibrated<iter>.ms``
(ported from v0.5 ``helper_functions.split_fields``).
"""
from __future__ import annotations

import logging
import os

from ..casa import listobs, split
from .ms_info import get_fields
from .preflag import is_null_selection

log = logging.getLogger(__name__)


def split_fields(ctx, vis_to_split, iter=''):
    """Split the CORRECTED column of each field (by field ID). Existing outputs are not recreated.
    A field without rows is skipped; any other split failure raises after all fields were tried."""
    ms_all = listobs(vis=vis_to_split)
    all_ms_fields_ids, all_ms_fields_names = get_fields(ms_all, 'field')

    fields_split_dir = ctx.paths.fields
    if not os.path.exists(fields_split_dir):
        log.info("Creating directory fields/.")
        os.makedirs(fields_split_dir)
    failed = []
    for field_id, field_to_split in zip(all_ms_fields_ids, all_ms_fields_names):
        formated_field = field_to_split.replace(' ', '').replace('/', '')
        os.makedirs(f"{fields_split_dir}/{formated_field}", exist_ok=True)
        outputvis = f'{fields_split_dir}/{formated_field}/{formated_field}.calibrated{iter}.ms'
        try:
            if os.path.exists(outputvis):
                log.info(f"{formated_field}.calibrated{iter}.ms exists. Will not create a new one.")
            else:
                log.info(f"Splitting field {field_to_split} into -->> {outputvis}")
                split(vis=vis_to_split,
                      outputvis=outputvis,
                      datacolumn='corrected', field=str(field_id))
        except Exception as e:
            if is_null_selection(e):     # a field ID without rows (e.g. a dropped duplicate): nothing to split
                log.info(f"Field {field_to_split} (ID {field_id}) has no rows to split ({e}).")
                continue
            log.error(f"Split of field {field_to_split} (ID {field_id}) failed: {e}")
            failed.append(f"{field_to_split} (ID {field_id}): {e}")
    # (v0.5 logged a failed split and finished the run as if it had worked)
    if failed:
        raise RuntimeError(f"split failed for {len(failed)} field(s): " + '; '.join(failed))
