"""
synphly.plotting.fluxes
=======================
Flux-density plots from setjy / fluxscale results.

plot_setjy_model(freqs_ghz, fluxes_jy, source_name, outfile)
    Port of the inline block in v0.5 calibrate.flux_scale_setjy.
plot_bootstrap_fluxes(fluxdict, field_names_by_id, outfile, spw_freqs_hz=None)
    Port of the block in v0.5 calibrate.cal_phases_amplitudes, fixing bug 3
    (03_known_issues): iterates over the real field-ID keys of the dict.
spw_fluxes_from_dict(fluxdict) -> {field_id: {...}}
"""

import logging

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

log = logging.getLogger(__name__)


def plot_setjy_model(freqs_ghz, fluxes_jy, source_name, outfile):
    """Model flux density per SPW vs frequency (setjy).  Returns outfile."""
    fig = plt.figure(figsize=(8, 5))
    try:
        plt.plot(np.asarray(freqs_ghz), np.asarray(fluxes_jy), 'o', color='black')
        plt.xlabel('Frequency [GHz]')
        plt.ylabel(f"Flux Density {source_name} [Jy]")
        plt.grid()
        plt.title('Flux density from setjy model')
        plt.savefig(outfile, dpi=600)
    finally:
        plt.close(fig)
    log.info("  Saved: %s", outfile)
    return outfile


def _field_name(fid, field_names_by_id, entry):
    if isinstance(field_names_by_id, dict):
        name = field_names_by_id.get(fid, field_names_by_id.get(str(fid)))
    elif field_names_by_id is not None and 0 <= int(fid) < len(field_names_by_id):
        name = field_names_by_id[int(fid)]
    else:
        name = None
    if name is None and isinstance(entry, dict):
        name = entry.get('fieldName')
    return str(name) if name is not None else f'field {fid}'


def spw_fluxes_from_dict(fluxdict):
    """
    Per-field, per-SPW Stokes I fluxes from a fluxscale or setjy result.

    Only digit keys are fields (skips 'freq', 'spwID', 'spwName', 'format');
    inside a field only digit keys are SPWs.  Non-positive fluxes (fluxscale
    uses -1 for failed SPWs) are dropped.

    Returns {field_id(str): {'spw': int array, 'flux': array, 'err': array
    (NaN when absent), 'fit': (fitFluxd, fitFluxdErr, fitRefFreq_Hz, spidx)
    or None, 'entry': raw dict}}.
    """
    out = {}
    for fkey in sorted((k for k in fluxdict if str(k).isdigit()), key=int):
        entry = fluxdict[fkey]
        if not isinstance(entry, dict):
            continue
        spws, flux, err = [], [], []
        for skey in sorted((k for k in entry if str(k).isdigit()), key=int):
            sd = entry[skey]
            if not isinstance(sd, dict) or 'fluxd' not in sd:
                continue
            f = float(np.atleast_1d(sd['fluxd'])[0])
            if not np.isfinite(f) or f <= 0:
                continue
            e = sd.get('fluxdErr')
            spws.append(int(skey))
            flux.append(f)
            err.append(float(np.atleast_1d(e)[0]) if e is not None else np.nan)
        fit = None
        if 'fitFluxd' in entry:
            fit = (float(entry['fitFluxd']), float(entry.get('fitFluxdErr', np.nan)),
                   float(entry.get('fitRefFreq', np.nan)),
                   np.atleast_1d(entry.get('spidx', [])).astype(float))
        out[str(fkey)] = {'spw': np.array(spws, dtype=int), 'flux': np.array(flux),
                          'err': np.array(err), 'fit': fit, 'entry': entry}
    return out


def plot_bootstrap_fluxes(fluxdict, field_names_by_id, outfile, spw_freqs_hz=None,
                          title='Flux Density Bootstrap For Phase Calibrators from Fluxscale',
                          logy=True):
    """
    Bootstrapped per-SPW flux densities (with errors) vs frequency for every
    field in a fluxscale (or setjy standard='fluxscale') result, plus the
    fitted spectrum when present.  Legend label: "name (ID)".

    spw_freqs_hz: per-SPW frequencies; defaults to fluxdict['freq'] (present
    in fluxscale results).  Returns outfile, or None if nothing to plot.
    """
    per_field = spw_fluxes_from_dict(fluxdict)
    freqs = spw_freqs_hz if spw_freqs_hz is not None else fluxdict.get('freq')
    if freqs is None:
        raise ValueError("No SPW frequencies: pass spw_freqs_hz or a fluxscale dict "
                         "with a 'freq' entry.")
    freqs = np.asarray(freqs, dtype=float)
    if not any(v['flux'].size for v in per_field.values()):
        log.warning("No valid bootstrap fluxes to plot for %s", outfile)
        return None

    cmap = plt.colormaps['tab10']
    fig, ax = plt.subplots(figsize=(8, 5))
    try:
        for i, (fid, v) in enumerate(per_field.items()):
            if v['flux'].size == 0:
                continue
            color = cmap(i % 10) if len(per_field) <= 10 else \
                plt.colormaps['viridis'](i / max(len(per_field) - 1, 1))
            label = f"{_field_name(fid, field_names_by_id, v['entry'])} ({fid})"
            x = freqs[v['spw']] / 1e9
            yerr = np.where(np.isfinite(v['err']), v['err'], 0.0)
            ax.errorbar(x, v['flux'], yerr=yerr, fmt='o', ms=4, color=color,
                        capsize=2, lw=0.8, label=label)
            if v['fit'] is not None and np.isfinite(v['fit'][0]):
                fitf, fite, fref, spidx = v['fit']
                xx = np.linspace(x.min(), x.max(), 50) if x.size > 1 else x
                if spidx.size > 1 and np.isfinite(fref) and fref > 0:
                    lr = np.log10(xx * 1e9 / fref)
                    yy = fitf * 10 ** sum(c * lr ** (k + 1)
                                          for k, c in enumerate(spidx[1:]))
                else:
                    yy = np.full_like(xx, fitf)
                ax.plot(xx, yy, '-', color=color, lw=1.2, alpha=0.8)
                if np.isfinite(fite) and spidx.size <= 1:
                    ax.axhspan(fitf - fite, fitf + fite, color=color, alpha=0.08, lw=0)
        ax.set_xlabel('Frequency [GHz]')
        ax.set_ylabel('Flux Density [Jy]')
        ax.grid(True, alpha=0.4)
        ax.legend(fontsize=8)
        ax.set_title(title + '\n(points: per-SPW fluxscale; line: fitted spectrum)',
                     fontsize=10)
        if logy:
            ax.set_yscale('log')
        fig.savefig(outfile, dpi=300, bbox_inches='tight')
    finally:
        plt.close(fig)
    log.info("  Saved: %s", outfile)
    return outfile
