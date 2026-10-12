"""
Absolute flux density scale: setjy on the flux calibrator (ported from v0.5
``calibrate.flux_scale_setjy``).
"""
from __future__ import annotations

import logging
import os

import numpy as np

from ..casa import clearcal, delmod, flagmanager, open_msmd, setjy
from . import _plots

log = logging.getLogger(__name__)

# Perley-Butler 2017 model images shipped with CASA (as listed in v0.5).
available_models = ['3C123_P.im', '3C138_K.im', '3C138_Q.im', '3C138_X.im', '3C147_K.im',
                    '3C147_Q.im', '3C147_X.im', '3C286_C.im', '3C286_P.im', '3C286_U.im',
                    '3C380_P.im', '3C48_K.im', '3C48_Q.im', '3C48_X.im', '3C138_A.im',
                    '3C138_L.im', '3C138_S.im', '3C147_A.im', '3C147_L.im', '3C147_S.im',
                    '3C196_P.im', '3C286_K.im', '3C286_Q.im', '3C286_X.im', '3C48_A.im',
                    '3C48_L.im', '3C48_S.im', '3C138_C.im', '3C138_P.im', '3C138_U.im',
                    '3C147_C.im', '3C147_P.im', '3C147_U.im', '3C286_A.im',
                    '3C286_L.im', '3C286_S.im', '3C295_P.im', '3C48_C.im',
                    '3C48_P.im', '3C48_U.im']


# Flux calibrators with a Perley-Butler 2017 model, and the name fragments that identify them (substring match on
# the field name, as v0.5): 3C name, J2000 short name, J2000 IAU name and B1950 name.
FLUX_CALIBRATOR_ALIASES = {
    '3C286': ('3C286', '1331+305', 'J1331+3030', '1328+307'),
    '3C48': ('3C48', '0137+331', 'J0137+3309', '0134+329'),
    '3C147': ('3C147', '0542+498', '0542+4951', '0538+498'),
    '3C138': ('3C138', '0521+166', 'J0521+1638', '0518+165'),
}


# Logged after every delmod(otf=True, scr=False) (03 issue 14).
DELMOD_NOTE = ("delmod(otf=True, scr=False) removed the on-the-fly model only; MODEL_DATA is not cleared here "
               "(setjy rewrites the flux-calibrator model; reset_transfer_models resets the secondary calibrators "
               "to 1 Jy before each gain pass).")


def flux_model_for(name: str):
    """The model source ('3C286', '3C48', '3C147' or '3C138') of a flux-calibrator field name, or None.

    As in v0.5 the checks run in this order and the last match wins."""
    model = None
    for source, aliases in FLUX_CALIBRATOR_ALIASES.items():
        if any(a in name for a in aliases):
            model = source
    return model


def spw_mean_freqs(vis):
    """Mean frequency (Hz) of every spw."""
    with open_msmd(vis) as msmd:
        bandwidth = msmd.bandwidths()
        nspw = len(bandwidth)
        chan_freqs_all = np.empty(nspw, dtype=object)
        spws_freq = np.zeros(nspw)
        for nch in range(nspw):
            chan_freqs_all[nch] = msmd.chanfreqs(nch)
            spws_freq[nch] = np.nanmean(chan_freqs_all[nch])
    return spws_freq


def flux_scale_setjy(ctx, vis, flux_density=None, model_image=None, spix=None,
                     band=''):
    """
    Set the model of the flux calibrator.

    The CASA selection is ``ctx.flux_calibrator`` (field IDs); the Perley-Butler model is looked up on the
    field NAME(S) (3C286 / 1331+305 / ..., as v0.5), and the plot file name uses the name as in v0.5.

    Returns (flux_density_data, spws, fluxes) as v0.5 (spws/fluxes are only used for the plot).
    """
    from .ms_info import field_names
    flux_calibrator = ctx.flux_calibrator               # ID selection, for CASA
    flux_calibrator_name = ','.join(field_names(ctx, flux_calibrator))   # v0.5 name string
    plots_dir = ctx.paths.plots

    # The model is matched on the field NAME (v0.5 matched the name string it used as selection).
    # v0.5 raised UnboundLocalError further down for an unknown source; fail here, before touching the MS.
    # (A known source without a model for the band still takes the manual 1 Jy path below, as in v0.5.)
    model = flux_model_for(flux_calibrator_name)
    if model is None:
        known = '; '.join(f"{k} ({', '.join(v[1:])})" for k, v in FLUX_CALIBRATOR_ALIASES.items())
        raise RuntimeError(
            f"No Perley-Butler 2017 model for the flux calibrator {flux_calibrator_name!r} (field "
            f"{flux_calibrator}). Known flux calibrators: {known}. Set [sources] flux_calibrator to one of them.")

    # delmod(otf=True, scr=False) removes only the on-the-fly (virtual) model kept in the MS keywords. It does NOT
    # clear the MODEL_DATA column (scr=False) - deliberately, as in v0.5: setjy below (usescratch=True) rewrites
    # the model of the flux calibrator, and reset_transfer_models (gains step) resets the models of the other
    # calibrators to 1 Jy before every gain pass (03 issue 14).
    try:
        log.info("Clearing the on-the-fly model (delmod otf=True, scr=False)")
        delmod(vis, otf=True, scr=False)
        log.info(DELMOD_NOTE)
    except Exception as e:
        log.critical(f"Exception {e} while deleting model column")
        raise

    try:
        log.info("Re-initialize the calibration")
        clearcal(vis)
        log.info("Successfully cleared the calibration")
    except Exception as e:
        log.critical(f"Exception {e} while clearing calibrations")
        raise

    log.info(f'Setting the flux scaling using {flux_calibrator_name} (field {flux_calibrator})')
    if os.path.exists(vis + '.flagversions/flags.before_setjy/'):
        flagmanager(vis=vis, mode='restore', versionname='before_setjy')
    else:
        flagmanager(vis=vis, mode='save', versionname='before_setjy')

    flux_density_data, spws_freq = set_flux_calibrator_model(ctx, vis, flux_density=flux_density,
                                                            model_image=model_image, spix=spix, band=band)
    nspw = len(spws_freq)
    spws = None
    fluxes = None
    try:
        # setjy returns {field_id: {spw_id: {'fluxd': [I,Q,U,V]}, 'fieldName': ...}, 'format': ...}.
        # v0.5 always read field '0'; use it if present, else the first (real) field ID.
        field_keys = [k for k in flux_density_data if str(k).isdigit()]
        fkey = '0' if '0' in flux_density_data else field_keys[0]
        spws = []
        fluxes = []
        for spw_id in range(nspw):
            spws.append(spw_id)
            fluxes.append(flux_density_data[fkey][str(spw_id)]['fluxd'][0])
        spws = np.asarray(spws)
        fluxes = np.asarray(fluxes)
    except Exception as e:
        log.warning(f"Flux plot not generated due to: {e}")
    else:
        flux_plot = os.path.join(plots_dir, flux_calibrator_name + '_flux_density_model.pdf')
        _plots.setjy_model(ctx, spws_freq * 1e-9, fluxes, flux_calibrator_name, flux_plot)

    return flux_density_data, spws, fluxes


def set_flux_calibrator_model(ctx, vis, flux_density='', model_image='', spix=None, band=''):
    """
    Write the model of the flux calibrator into MODEL_DATA (setjy, usescratch=True). This is the setjy part of
    ``flux_scale_setjy`` (same calls, same order); it is also used to re-establish the model after a
    ``clearcal`` (see ``restore_models_after_clearcal``). Returns (setjy result, mean frequency per spw [Hz]).
    """
    from .ms_info import field_names
    flux_calibrator = ctx.flux_calibrator
    flux_calibrator_name = ','.join(field_names(ctx, flux_calibrator))
    model = flux_model_for(flux_calibrator_name)
    if model is None:
        raise RuntimeError(f"No Perley-Butler 2017 model for the flux calibrator {flux_calibrator_name!r}.")

    # Some high frequency observations may have spw 0 in a lower frequency band (e.g. X band)
    # due to pointing calibration. So, using spw 0 may not be adequate.
    # Instead, we take an average between all channels and spectral windows.
    spws_freq = spw_mean_freqs(vis)
    mean_freq = np.nanmean(spws_freq) * 1e-9

    freq_ranges = {
        (1, 2): "L",
        (2, 4): "S",
        (4, 8): "C",
        (8, 12): "X",
        (12, 18): "U",  # U is the Ku band.
        (18, 26.5): "K",
        (26.5, 40): "A",  # A is the Ka band
        (40, 50): "Q",
    }

    if band == '':
        for range_, band in freq_ranges.items():
            if mean_freq >= range_[0] and mean_freq <= range_[1]:
                log.info(f"Observations done in band: {band}")
                log.info(f"Will use model {model}_{band}.im for absolute flux calibration")
                model = model + f'_{band}.im'
    else:
        log.info(f"Observations done in band: {band}")
        log.info(f"Will use model {model}_{band}.im for absolute flux calibration")
        model = model + f'_{band}.im'

    if model not in available_models:
        log.warning(f"Model {model} not available for band {band}.")
        log.warning("Will use set flux density to [1,0,0,0] for absolute flux "
                    "calibration, which may be wrong. Please, provide the flux density "
                    "using the arguments fluxdensity=[I,Q,U,V] and standard='manual' in setjy.")
        flux_density = [1.0, 0.0, 0.0, 0.0]
    flux_density_data = None

    if flux_density == '':
        log.info(f"Performing absolute flux calibration using {model}")
        flux_density_data = setjy(vis=vis, field=flux_calibrator,
                                  spw='', model=model, scalebychan=True,
                                  standard='Perley-Butler 2017', listmodels=False,
                                  usescratch=True)
    else:
        # Should be properly implemented. Used when the flux density must be set explicitly (no model
        # available), or when a model image is given for the flux calibrator.
        if model_image != '':
            log.warning(f"Using provided model image {model_image} for flux calibrator"
                        f" {flux_calibrator_name} at {band} band.")
            flux_density_data = setjy(vis=vis, field=flux_calibrator,
                                      spw='', model=model_image, scalebychan=True,
                                      standard='Perley-Butler 2017', listmodels=False,
                                      usescratch=True)
        else:
            # v0.5 used the global vis_for_cal here; main.py always passed vis=vis_for_cal.
            flux_density_data = setjy(vis=vis, field=flux_calibrator,
                                      spw='', scalebychan=True,
                                      standard='manual', fluxdensity=flux_density,
                                      reffreq=f'{mean_freq}GHz', spix=spix,
                                      listmodels=False, usescratch=True)
    return flux_density_data, spws_freq


def _as_arrays(obj):
    """A fluxscale dict read back from synphly_state.json (lists) -> the numpy form setjy expects."""
    if isinstance(obj, dict):
        return {k: _as_arrays(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return np.asarray(obj)
    return obj


def restore_models_after_clearcal(ctx, vis, i):
    """
    Re-establish the calibrator models that a fresh run has at the start of bandpass pass ``i``.

    On a re-run, bandpass_cal restores the flag version ``before_bandpass_init_<i>`` and runs ``clearcal``, which
    resets MODEL_DATA to 1 Jy for every field -- including the flux calibrator. v0.5 then calibrated the flux
    scale against a 1 Jy flux calibrator: on 21A-024 every bootstrapped flux of a re-run came out 2.45x too low
    (3C286 is ~2.45 Jy at K band). A fresh run never takes that branch. To make a re-run reproduce a fresh run:
      - pass 1: the flux calibrator gets its setjy model again (the other calibrators stay at 1 Jy);
      - pass i > 1: additionally, the calibrators get the bootstrapped setjy(standard='fluxscale') models of
        pass i-1, which is what a fresh run has when it reaches bandpass pass i.
    """
    c = ctx.cfg.calibrate
    log.info("clearcal reset MODEL_DATA to 1 Jy for every field; re-establishing the calibrator models of a "
             f"fresh run at bandpass pass {i}.")
    set_flux_calibrator_model(ctx, vis, flux_density='', model_image='', band=c.band)
    if int(i) > 1:
        prev = (ctx.fluxes.get(str(int(i) - 1)) or {}).get('fluxscale')
        if not prev:
            raise RuntimeError(f"Cannot re-run bandpass pass {i}: the fluxscale result of pass {int(i) - 1} is not "
                               "in the run state. Re-run from the previous gain step (synphly run --from "
                               f"gains_{int(i) - 1}).")
        setjy(vis=vis, field=ctx.calibrators_all, scalebychan=True, standard='fluxscale', usescratch=True,
              fluxdict=_as_arrays(prev))
