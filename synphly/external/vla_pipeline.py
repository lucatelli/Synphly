"""
Run the NRAO VLA (``hifv``) or the ALMA (``hifa``) CASA pipeline on a measurement set.

Optional helpers, ported from the v0.5 scripts ``data_calibration/casapipe.py`` and ``almapipe.py`` (which were
``exec``-ed with a global ``vis``). They are not wired into the Synphly pipeline; use them to produce a reference
calibration to compare with, e.g.::

    from synphly.external.vla_pipeline import run_vla_pipeline
    run_vla_pipeline('/data/21A-024.ms')

They need a CASA installation that includes the pipeline (``casa --pipeline``, or the modular ``pipeline``
package). The pipeline modules are imported only when a function is called. The pipeline writes its products
and weblog into the current directory, so run them from a dedicated working directory.
"""
from __future__ import annotations

import builtins
import importlib
import logging

log = logging.getLogger(__name__)

# The pipeline tasks live in these CLI modules (modular CASA). Inside ``casa --pipeline`` they are also globals.
_CLI_MODULES = ('pipeline.h.cli', 'pipeline.hif.cli', 'pipeline.hifv.cli', 'pipeline.hifa.cli')

# v0.5 casapipe.py
VLA_FLAG_INTENTS = '*POINTING*,*FOCUS*,*ATMOSPHERE*,*SIDEBAND_RATIO*'
EARLY_EVLA_FLAG_INTENTS = ('*POINTING*,*FOCUS*,*ATMOSPHERE*,*SIDEBAND_RATIO*,*UNKNOWN*,*SYSTEM_CONFIGURATION*,'
                           '*UNSPECIFIED#UNSPECIFIED*')


class _Tasks:
    """Lazy lookup of the pipeline tasks (h_init, h_save, hifv_*, hif_*, hifa_*)."""

    def __init__(self):
        self._modules = []
        for name in _CLI_MODULES:
            try:
                self._modules.append(importlib.import_module(name))
            except ImportError as e:
                log.debug(f"pipeline module {name} not importable: {e}")

    def __getattr__(self, task):
        for mod in self._modules:
            if hasattr(mod, task):
                return getattr(mod, task)
        if hasattr(builtins, task):
            return getattr(builtins, task)
        raise ImportError(f"CASA pipeline task {task!r} not found. Run inside a CASA installation that includes the "
                          f"pipeline (e.g. `casa --pipeline`) or install the modular `pipeline` package.")


def _vla_context(t):
    context = t.h_init()
    context.set_state('ProjectSummary', 'proposal_code', 'VLA/null')
    context.set_state('ProjectSummary', 'proposal_title', 'unknown')
    context.set_state('ProjectSummary', 'piname', 'unknown')
    context.set_state('ProjectSummary', 'observatory', 'Karl G. Jansky Very Large Array')
    context.set_state('ProjectSummary', 'telescope', 'EVLA')
    context.set_state('ProjectStructure', 'ppr_file', 'PPR.xml')
    context.set_state('ProjectStructure', 'recipe_name', 'hifv_cal')
    return context


def run_vla_pipeline(vis: str, hanning: bool = True, online_flags: bool = True, flag_intents: str = VLA_FLAG_INTENTS,
                     syspower: bool = True, early_evla: bool = False, stop_after_flagging: bool = False):
    """
    Run the VLA calibration pipeline (recipe ``hifv_cal``) on ``vis``. Returns the pipeline context.

    Default (v0.5 ``casapipe.py``, first recipe): importdata; deterministic flags (shadow, clip, online flags from
    ``<vis>.flagonline.txt``); intent flags ``flag_intents``; Hanning; vlasetjy; priorcals; syspower;
    testBPdcals; checkflag(bpd-vla); semiFinalBPdcals; checkflag(allcals-vla); solint; fluxboot; finalcals;
    applycals; checkflag(target-vla); statwt; plotsummary. ``h_save()`` after every stage.

    ``early_evla=True`` (v0.5 recipe for early EVLA data with manually fixed scan intents): no deterministic/online
    flag stage, the extended intent list (UNKNOWN, SYSTEM_CONFIGURATION, UNSPECIFIED as well), no Hanning, no
    syspower, and a failing stage after the flagging is logged and the recipe continues (v0.5: bare ``except``).

    ``stop_after_flagging=True`` (v0.5 second recipe): import and flagging only, online flags not applied.
    """
    t = _Tasks()
    context = _vla_context(t)
    if early_evla:
        t.hifv_importdata(vis=[vis])
        t.h_save()
        t.hifv_flagdata(hm_tbuff='1.5int', fracspw=0.01, intents=EARLY_EVLA_FLAG_INTENTS)
        stages = [('hifv_vlasetjy', {}), ('hifv_priorcals', {}), ('hifv_testBPdcals', {}),
                  ('hifv_checkflag', {'checkflagmode': 'bpd-vla'}), ('hifv_semiFinalBPdcals', {}),
                  ('hifv_checkflag', {'checkflagmode': 'allcals-vla'}), ('hifv_solint', {}), ('hifv_fluxboot', {}),
                  ('hifv_finalcals', {}), ('hifv_applycals', {}), ('hifv_checkflag', {'checkflagmode': 'target-vla'}),
                  ('hifv_statwt', {}), ('hifv_plotsummary', {})]
        for name, kw in stages:
            try:
                getattr(t, name)(**kw)
                t.h_save()
            except Exception as e:     # noqa: BLE001 - the early-EVLA recipe continues past failing stages
                log.warning(f"VLA pipeline stage {name}({kw}) failed, continuing: {type(e).__name__}: {e}")
        return context

    t.hifv_importdata(vis=[vis], session=['default'])
    t.h_save()
    t.hifv_flagdata(autocorr=False, shadow=True, scan=False, quack=False, clip=True, baseband=False,
                    edgespw=False, online=online_flags and not stop_after_flagging, template=False,
                    hm_tbuff='manual', tbuff=0.0, fileonline=vis + '.flagonline.txt')
    t.h_save()
    t.hifv_flagdata(hm_tbuff='1.5int', fracspw=0.01, intents=flag_intents)
    t.h_save()
    if stop_after_flagging:
        return context
    if hanning:
        t.hifv_hanning()
        t.h_save()
    for name, kw in [('hifv_vlasetjy', {}), ('hifv_priorcals', {})] + \
            ([('hifv_syspower', {})] if syspower else []) + \
            [('hifv_testBPdcals', {}), ('hifv_checkflag', {'checkflagmode': 'bpd-vla'}),
             ('hifv_semiFinalBPdcals', {}), ('hifv_checkflag', {'checkflagmode': 'allcals-vla'}),
             ('hifv_solint', {}), ('hifv_fluxboot', {}), ('hifv_finalcals', {}), ('hifv_applycals', {}),
             ('hifv_checkflag', {'checkflagmode': 'target-vla'}), ('hifv_statwt', {}), ('hifv_plotsummary', {})]:
        getattr(t, name)(**kw)
        t.h_save()
    return context


def run_alma_pipeline(vis: str, imaging: bool = True):
    """
    Run the ALMA pipeline (recipe ``hifa_calimage``) on ``vis``. Returns the pipeline context.

    ``imaging=True`` (v0.5 ``almapipe.py``, first recipe): the full calibration + imaging + selfcal recipe, with
    ``h_save()`` after every stage. ``imaging=False`` (second recipe): calibration only, from importdata to
    applycal, with one ``h_save()`` at the end (also when a stage fails).
    """
    t = _Tasks()
    context = t.h_init()
    context.set_state('ProjectStructure', 'recipe_name', 'hifa_calimage')
    calib = [('hifa_importdata', {'vis': [vis], 'session': ['session_1'], 'dbservice': True}),
             ('hifa_flagdata', {}), ('hifa_fluxcalflag', {}), ('hif_rawflagchans', {}), ('hif_refant', {}),
             ('h_tsyscal', {}), ('hifa_tsysflag', {}), ('hifa_tsysflagcontamination', {}), ('hifa_antpos', {}),
             ('hifa_wvrgcalflag', {}), ('hif_lowgainflag', {}), ('hif_setmodels', {}), ('hifa_bandpassflag', {}),
             ('hifa_bandpass', {}), ('hifa_spwphaseup', {}), ('hifa_gfluxscaleflag', {}), ('hifa_gfluxscale', {}),
             ('hifa_timegaincal', {}), ('hifa_renorm', {'createcaltable': True, 'atm_auto_exclude': True}),
             ('hifa_targetflag', {}), ('hif_applycal', {})]
    if not imaging:
        try:
            for name, kw in calib:
                getattr(t, name)(**kw)
        finally:
            t.h_save()
        return context
    imaging_stages = [
        ('hif_makeimlist', {'intent': 'PHASE,BANDPASS,AMPLITUDE'}), ('hif_makeimages', {}),
        ('hif_makeimlist', {'intent': 'CHECK', 'per_eb': True}), ('hif_makeimages', {}),
        ('hifa_imageprecheck', {}),
        ('hif_checkproductsize', {'maxcubesize': 40.0, 'maxcubelimit': 60.0, 'maxproductsize': 500.0}),
        ('hifa_exportdata', {}), ('hif_mstransform', {}), ('hifa_flagtargets', {}),
        ('hif_makeimlist', {'specmode': 'mfs'}), ('hif_findcont', {}), ('hif_uvcontsub', {}), ('hif_makeimages', {}),
        ('hif_makeimlist', {'specmode': 'cont'}), ('hif_makeimages', {}),
        ('hif_makeimlist', {'specmode': 'repBW'}), ('hif_makeimages', {}),
        ('hif_selfcal', {}),
        ('hif_makeimlist', {'specmode': 'mfs', 'datatype': 'selfcal'}), ('hif_makeimages', {}),
        ('hif_makeimlist', {'specmode': 'cont', 'datatype': 'selfcal'}), ('hif_makeimages', {}),
        ('hif_makeimlist', {'specmode': 'cube', 'datatype': 'best'}), ('hif_makeimages', {}),
        ('hif_makeimlist', {'specmode': 'repBW', 'datatype': 'selfcal'}), ('hif_makeimages', {}),
    ]
    for name, kw in calib + imaging_stages:
        getattr(t, name)(**kw)
        t.h_save()
    t.h_save()
    return context
