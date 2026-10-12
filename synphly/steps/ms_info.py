"""
MS information and field role resolution by FIELD_ID (``synphly.fields.FieldModel``).

v0.5 (``getms_info`` + ``format_fields``) resolved the roles to field NAMES and passed the names to CASA, so
every field ID sharing a name was selected. Since v0.6 every CASA ``field=`` selection is a comma-separated
string of field IDs taken from the FieldModel; names are kept only where a name is needed (flux model lookup,
plot titles/file names, split directory names, the log). The v0.5 name selection is still computed
(``FieldModel.compare_legacy``) and any difference is logged as a warning.

Context fields set here (all ID strings):
    flux_calibrator, bandpass_calibrator, phase_calibrator, target   fm.selection(role)
    calibrators_all                                                  fm.calibrator_selection()
    calibrators_all_arr, target_fields_arr, all_fields_arr           lists of ID strings
    all_fields_str                                                   calibrators_all + ',' + target
    phasecal_for_target                                              {target ID: phase calibrator ID}
    field_model                                                      fm.to_dict()
"""
from __future__ import annotations

import logging

import numpy as np

from ..casa import open_msmd
from ..fields import FieldModel

log = logging.getLogger(__name__)


def get_fields(ms_list, type_str):
    """From a listobs dictionary, return (field IDs as strings, field names) of the ``field_*`` keys."""
    list_obs = [x for x in ms_list if x.startswith(type_str)]
    log.debug(f"The list {type_str} is {list_obs}")
    field_names = []
    for LO in list_obs:
        field_names.append(ms_list[LO]['name'])
    fids = np.asarray(list_obs)
    for i in range(len(fids)):
        fids[i] = fids[i].replace('field_', '')
    return fids, field_names


# ----------------------------------------------------------------------------------------------------
# access to the field model stored in the context
# ----------------------------------------------------------------------------------------------------
def field_model(ctx) -> FieldModel:
    """The resolved FieldModel of the run (rebuilt from ``ctx.field_model``; cached on the context)."""
    if not ctx.field_model:
        raise RuntimeError("The field model is not available (ctx.field_model is empty): run the ms_info "
                           "step first (globals.ms_info = true).")
    cached = getattr(ctx, '_fm_cache', None)
    if cached is not None and cached[0] is ctx.field_model:
        return cached[1]
    fm = FieldModel.from_dict(ctx.field_model)
    object.__setattr__(ctx, '_fm_cache', (ctx.field_model, fm))
    return fm


def field_name(ctx, field_id) -> str:
    """Name of a field ID (int or ID string)."""
    return field_model(ctx).records[int(field_id)].name


def field_names(ctx, selection) -> list:
    """Unique names (in ID order) of a comma-separated ID selection or a list of IDs."""
    if isinstance(selection, str):
        selection = [t for t in selection.split(',') if t.strip()]
    return list(dict.fromkeys(field_name(ctx, i) for i in selection))


def role_names(ctx, role) -> list:
    return field_model(ctx).names(role)


def _log_spw_info(vis):
    with open_msmd(vis) as msmd:
        nchan = msmd.nchan(0)
        bandwidth = msmd.bandwidths() * 1e-6
    nspw = len(bandwidth)
    log.info(f"Total channels {nchan}")
    log.info(f"Data observed over a bandwidth of {bandwidth[0] * nspw} MHz over"
             f" {nspw} spw each {bandwidth[0]} MHz in size and divided "
             f"into {nchan} channels")


def apply_field_model(ctx, fm: FieldModel):
    """Store the roles of a resolved FieldModel in ``ctx`` (ID selection strings)."""
    ctx.field_model = fm.to_dict()
    object.__setattr__(ctx, '_fm_cache', (ctx.field_model, fm))
    ctx.flux_calibrator = fm.selection('flux')
    ctx.bandpass_calibrator = fm.selection('bandpass')
    ctx.phase_calibrator = fm.selection('phase')
    ctx.target = fm.selection('target')
    ctx.calibrators_all = fm.calibrator_selection()
    ctx.calibrators_all_arr = [str(i) for i in fm.calibrator_ids()]
    ctx.target_fields_arr = [str(i) for i in fm.ids('target')]
    ctx.all_fields_str = ctx.calibrators_all + ',' + ctx.target
    ctx.all_fields_arr = [str(i) for i in sorted(set(fm.calibrator_ids()) | set(fm.ids('target')))]
    ctx.phasecal_for_target = {str(t): str(p) for t, p in fm.phasecal_for_target().items()}
    return ctx


def resolve_fields(ctx, vis):
    """Build the FieldModel of ``vis``, resolve the roles from ``cfg.sources`` and store them in ``ctx``."""
    fm = FieldModel.from_ms(vis)
    fm.resolve_roles(ctx.cfg.sources)
    log.info("Field model of %s:\n%s", vis, fm.report())
    for role, d in fm.compare_legacy().items():
        msg = (f"Field selection for '{role}' differs from the v0.5 name-based selection: "
               f"v0.5 would select IDs {d['legacy']}, v0.6 uses IDs {d['new']}.")
        log.warning(msg)
        ctx.warnings.append(msg)
    for d in fm.dropped:
        log.warning(f"Field {d['id']} '{d['name']}' dropped from role {d['role']}: {d['reason']}")
    apply_field_model(ctx, fm)
    for t in fm.ids('target'):
        if str(t) not in ctx.phasecal_for_target:
            msg = f"No phase calibrator assigned to target {t} '{fm.records[t].name}'."
            log.warning(msg)
            ctx.warnings.append(msg)
    try:
        _log_spw_info(vis)
    except RuntimeError as e:
        log.warning(f"Could not read the spw information of {vis}: {e}")
    log.info(f"Flux calibrator: {ctx.flux_calibrator} {fm.names('flux')} | "
             f"bandpass: {ctx.bandpass_calibrator} {fm.names('bandpass')} | "
             f"phase: {ctx.phase_calibrator} {fm.names('phase')} | "
             f"target: {ctx.target} {fm.names('target')}")
    log.info(f"All calibrators: {ctx.calibrators_all}")
    log.info(f"Phase calibrator per target: {ctx.phasecal_for_target}")
    return ctx
