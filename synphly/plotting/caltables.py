"""
synphly.plotting.caltables
==========================
Pure-Python (matplotlib) plots of CASA calibration tables, replacing the
plotms calls of v0.5 ``helper_functions.calibration_table_plot``.

Modelled on ph4ser ``gain_plots.py`` (scan-gap-compressed time axis,
antenna-averaged variant) and ``plot_K_diagnostics.py`` (K delay tables).

Public API
----------
calibration_table_plot(table, plots_dir, stage='calibration', table_type='',
                       xaxis='time', yaxis='phase', fields='', minsnr=3.0,
                       backend='python', coloraxis='spw', extras=True,
                       snr_outfile=None)
make_plot_snr(caltable, cut_off=3.0, plot_snr=True, bins=50, density=True,
              save_fig=True, snr=None, outfile=None)
read_caltable(table) -> dict
detect_table_type(keywords, colnames=(), n_chan=1) -> 'K'|'G'|'T'|'B'|...

(xaxis, yaxis) combinations
---------------------------
  ('ant1', 'delay')  K: delay [ns] vs antenna, colour by SPW, marker by pol
                     extra: '<..>_heatmap'  antenna x SPW delay map
  ('time', 'delay')  K: delay [ns] vs time
  ('time', 'phase'|'amp')  G/T/fluxscale: vs time, scan gaps compressed
                     extras: '<..>_avgant' (mean over antennas+pols per SPW,
                     circular mean for phase) and '<..>_perant' (one panel
                     per antenna)
  ('chan'|'freq', 'phase'|'amp')  B: vs channel / frequency, all antennas
                     overlaid, colour by SPW; extra '<..>_perant'

File names (under {plots_dir}/{stage}/)
---------------------------------------
  main (v0.5 name): {table_type}_{xaxis}_{yaxis}_field_{F}_ant__spw_.jpg
  extras:           {table_type}_{xaxis}_{yaxis}_{variant}_field_{F}.jpg
  F = 'all' when fields == '', else the field selection string.
SNR histogram: caltable.replace('.tb', '.jpg') (v0.5 behaviour) unless
snr_outfile is given.
"""

import os
import logging
import datetime as dt

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from matplotlib.lines import Line2D
from matplotlib.collections import LineCollection

log = logging.getLogger(__name__)

_MJD_EPOCH = dt.datetime(1858, 11, 17, tzinfo=dt.timezone.utc)
_POL_MARKERS = ['o', 'x', 's', '^']
_PLOT_ERRORS = (RuntimeError, ValueError, KeyError, IndexError, TypeError,
                OSError, MemoryError)

# VisCal first token (upper case) -> canonical table type
_VISCAL_MAP = {
    'K': 'K', 'KCROSS': 'K', 'KMBD': 'K', 'KDISP': 'K', 'KF': 'K',
    'KANTPOS': 'KAntPos',
    'G': 'G', 'GSPLINE': 'G', 'GF': 'G',
    'T': 'T', 'TF': 'T', 'TOPAC': 'TOpac', 'TFOPAC': 'TOpac',
    'B': 'B', 'BPOLY': 'B',
    'D': 'D', 'DF': 'D', 'X': 'X', 'XF': 'X',
    'GAINCURVE': 'GainCurve', 'EGAINCURVE': 'GainCurve',
}


# ===========================================================================
# Table type detection and I/O
# ===========================================================================

def detect_table_type(keywords, colnames=(), n_chan=1):
    """
    Canonical table type from the table keywords ('VisCal', e.g. 'G Jones',
    'K Jones', 'B Jones') with a column-based fallback: FPARAM -> 'K',
    CPARAM with n_chan > 1 -> 'B', otherwise 'G'.
    """
    viscal = str((keywords or {}).get('VisCal', '') or '').strip()
    if viscal:
        token = viscal.split()[0].upper()
        if token in _VISCAL_MAP:
            return _VISCAL_MAP[token]
        for prefix, ttype in (('KANTPOS', 'KAntPos'), ('K', 'K'), ('B', 'B'),
                              ('G', 'G'), ('T', 'T')):
            if token.startswith(prefix):
                return ttype
    cols = set(colnames or ())
    if 'FPARAM' in cols and 'CPARAM' not in cols:
        return 'K'
    if 'CPARAM' in cols and n_chan > 1:
        return 'B'
    return 'G'


def read_caltable(table):
    """
    Read everything needed for plotting from a calibration table in a
    single open (plus the small ANTENNA / SPECTRAL_WINDOW / FIELD subtables).

    Returns dict: param (n_pol, n_chan, N; complex or float), flag, snr,
    time, field, scan, antenna, spw, obs, is_float, table_type, viscal,
    ant_names, chan_freqs {spw: Hz array}, field_names.
    """
    import casatools
    tb = casatools.table()
    tb.open(table)
    try:
        kw = tb.getkeywords()
        cols = tb.colnames()
        is_float = 'FPARAM' in cols and 'CPARAM' not in cols
        d = dict(
            param=tb.getcol('FPARAM' if is_float else 'CPARAM'),
            flag=tb.getcol('FLAG').astype(bool),
            snr=tb.getcol('SNR') if 'SNR' in cols else None,
            time=tb.getcol('TIME'),
            field=tb.getcol('FIELD_ID'),
            scan=tb.getcol('SCAN_NUMBER'),
            antenna=tb.getcol('ANTENNA1'),
            spw=tb.getcol('SPECTRAL_WINDOW_ID'),
            obs=tb.getcol('OBSERVATION_ID') if 'OBSERVATION_ID' in cols else None,
        )
    finally:
        tb.close()

    def _sub(name, func):
        sub = casatools.table()
        try:
            sub.open(os.path.join(table, name))
        except RuntimeError as exc:
            log.debug("No %s subtable in %s: %s", name, table, exc)
            return None
        try:
            return func(sub)
        finally:
            sub.close()

    d['ant_names'] = _sub('ANTENNA', lambda t: list(t.getcol('NAME'))) or []
    d['field_names'] = _sub('FIELD', lambda t: list(t.getcol('NAME'))) or []
    d['chan_freqs'] = _sub('SPECTRAL_WINDOW', lambda t: {
        r: np.atleast_1d(t.getcell('CHAN_FREQ', r)) for r in range(t.nrows())}) or {}
    d['is_float'] = is_float
    d['viscal'] = str(kw.get('VisCal', ''))
    d['table_type'] = detect_table_type(kw, cols, d['param'].shape[1])
    return d


def _subset(d, mask):
    """Row-subset of a caltable dict (row axis last for param/flag/snr)."""
    out = dict(d)
    for k in ('time', 'field', 'scan', 'antenna', 'spw', 'obs'):
        if out.get(k) is not None:
            out[k] = d[k][mask]
    for k in ('param', 'flag', 'snr'):
        if out.get(k) is not None:
            out[k] = d[k][..., mask]
    return out


def _resolve_fields(sel, field_names):
    """Field selection (IDs or names) -> sorted list of field IDs."""
    ids = []
    for f in sel:
        f = str(f).strip()
        if not f:
            continue
        if f.isdigit():
            ids.append(int(f))
        elif f in field_names:
            ids.extend(i for i, n in enumerate(field_names) if n == f)
        else:
            log.warning("Field '%s' not found in caltable FIELD subtable.", f)
    return sorted(set(ids))


def _values(d, yaxis):
    """(n_pol, n_chan, N) float array for yaxis, flagged -> NaN."""
    p = d['param']
    if yaxis == 'delay' or d['is_float']:
        if not d['is_float']:
            raise ValueError("yaxis='delay' requires an FPARAM (K) table")
        v = p.astype(float)
    elif yaxis == 'phase':
        v = np.angle(p, deg=True)
    elif yaxis in ('amp', 'amplitude'):
        v = np.abs(p)
    elif yaxis == 'real':
        v = p.real
    elif yaxis == 'imag':
        v = p.imag
    else:
        raise ValueError(f"unsupported yaxis {yaxis!r}")
    return np.where(d['flag'], np.nan, v)


def _chan_avg_values(d, yaxis):
    """Channel-averaged values (n_pol, N); complex average for phase/amp."""
    if d['param'].shape[1] == 1:
        return _values(d, yaxis)[:, 0, :]
    if d['is_float']:
        v = _values(d, yaxis)
        with np.errstate(invalid='ignore'):
            return np.nanmean(v, axis=1)
    c = np.where(d['flag'], 0, d['param'])
    n = (~d['flag']).sum(axis=1)
    with np.errstate(invalid='ignore', divide='ignore'):
        mean = np.where(n > 0, c.sum(axis=1) / np.maximum(n, 1), np.nan)
    return np.angle(mean, deg=True) if yaxis == 'phase' else np.abs(mean)


# ===========================================================================
# Colour, time-axis and figure helpers
# ===========================================================================

def _group_colors(ids):
    """Fixed-order colours for SPW / antenna ids (tab20; viridis beyond 20)."""
    ids = sorted(set(int(i) for i in ids))
    n = len(ids)
    if n <= 10:
        cmap = plt.colormaps['tab10']
        return {g: cmap(i) for i, g in enumerate(ids)}
    if n <= 20:
        cmap = plt.colormaps['tab20']
        return {g: cmap(i) for i, g in enumerate(ids)}
    cmap = plt.colormaps['viridis']
    return {g: cmap(i / max(n - 1, 1)) for i, g in enumerate(ids)}


def _legend(ax, colors, labels, title, max_entries=32, fontsize=7):
    if not colors or len(colors) > max_entries:
        return
    handles = [Line2D([0], [0], marker='o', color='w', markerfacecolor=colors[g],
                      markersize=6, label=labels.get(g, str(g)))
               for g in sorted(colors)]
    ax.legend(handles=handles, title=title, fontsize=fontsize,
              title_fontsize=fontsize, loc='center left',
              bbox_to_anchor=(1.005, 0.5), framealpha=0.8,
              ncol=1 if len(handles) <= 16 else 2)


def _pol_labels(n_pol):
    return ['RR', 'LL'] if n_pol == 2 else [f'P{p}' for p in range(n_pol)]


def compress_time(times, gap_pad_fraction=0.04, min_gap=60.0):
    """
    Compress inter-scan gaps on a time axis.

    Solutions are grouped into blocks separated by gaps larger than
    max(min_gap, 3 x median spacing); each gap is replaced by a fixed pad
    (gap_pad_fraction of the total on-source span, at least 30 s).

    Returns t_comp (same shape as times), block_bounds [(x0, x1)],
    block_t0 (real start time of each block), block_c0 (compressed start).
    """
    times = np.asarray(times, dtype=float)
    ut = np.unique(times)
    if ut.size == 0:
        return times.copy(), [], np.array([]), np.array([])
    dts = np.diff(ut)
    thr = max(min_gap, 3.0 * float(np.median(dts))) if dts.size else min_gap
    breaks = np.where(dts > thr)[0]
    starts = np.concatenate([[0], breaks + 1])
    ends = np.concatenate([breaks, [ut.size - 1]])
    durations = ut[ends] - ut[starts]
    pad = max(gap_pad_fraction * float(durations.sum()), 30.0)
    block_c0 = np.concatenate([[0.0], np.cumsum(durations + pad)[:-1]])
    block_t0 = ut[starts]
    blk = np.searchsorted(block_t0, times, side='right') - 1
    t_comp = block_c0[blk] + (times - block_t0[blk])
    bounds = [(c, c + du) for c, du in zip(block_c0, durations)]
    return t_comp, bounds, block_t0, block_c0


def _time_formatter(block_t0, block_c0):
    def fmt(x, pos):
        if len(block_c0) == 0:
            return ''
        i = int(np.clip(np.searchsorted(block_c0, x, side='right') - 1,
                        0, len(block_c0) - 1))
        t = block_t0[i] + (x - block_c0[i])
        return (_MJD_EPOCH + dt.timedelta(seconds=float(t))).strftime('%H:%M')
    return ticker.FuncFormatter(fmt)


def _decorate_time_ax(ax, d, t_comp, bounds, block_t0, block_c0, ylabel, phase,
                      annotate_fields=True):
    ax.xaxis.set_major_formatter(_time_formatter(block_t0, block_c0))
    ax.xaxis.set_major_locator(ticker.MaxNLocator(nbins=8))
    if len(d['time']):
        date = (_MJD_EPOCH + dt.timedelta(seconds=float(np.min(d['time'])))
                ).strftime('%Y-%m-%d')
        ax.set_xlabel(f'Time UTC [{date}]  (inter-scan gaps compressed)')
    for x0, x1 in bounds:
        ax.axvspan(x0, x1 if x1 > x0 else x0 + 1e-3, color='steelblue',
                   alpha=0.05, lw=0)
    if bounds:
        span = bounds[-1][1] - bounds[0][0]
        padx = max(span * 0.01, 10.0)
        ax.set_xlim(bounds[0][0] - padx, bounds[-1][1] + padx)
    if phase:
        ax.set_ylim(-180, 180)
        ax.axhline(0, color='k', lw=0.4, ls='--', alpha=0.4)
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.25, lw=0.4)
    if annotate_fields and len(block_c0) and len(d['field']):
        # Label the field at each block where the field changes.
        fnames = d['field_names']
        prev = None
        trans = ax.get_xaxis_transform()
        blk = np.searchsorted(block_t0, d['time'], side='right') - 1
        order = np.argsort(blk, kind='stable')
        ub, starts = np.unique(blk[order], return_index=True)
        ends = list(starts[1:]) + [order.size]
        block_field = {int(b): int(np.bincount(d['field'][order[s:e]]).argmax())
                       for b, s, e in zip(ub, starts, ends)}
        for b, c0 in enumerate(block_c0):
            fid = block_field.get(b)
            if fid is None:
                continue
            if fid != prev:
                name = fnames[fid] if fid < len(fnames) else str(fid)
                ax.text(c0, 1.005, f'{name} ({fid})', transform=trans,
                        rotation=60, fontsize=6, ha='left', va='bottom',
                        color='0.3')
                prev = fid


def _save(fig, path, dpi=150):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    try:
        fig.savefig(path, dpi=dpi, bbox_inches='tight')
    finally:
        plt.close(fig)
    log.info("  Saved: %s", path)
    return path


def _ylabel(yaxis, table_type):
    return {'phase': 'Phase [deg]', 'amp': 'Amplitude', 'amplitude': 'Amplitude',
            'delay': 'Delay [ns]'}.get(yaxis, f'{yaxis} ({table_type})')


def _grid(n, max_cols=6, panel=(3.0, 2.2)):
    ncols = min(max_cols, max(1, n))
    nrows = int(np.ceil(n / ncols))
    fig, axes = plt.subplots(nrows, ncols, figsize=(panel[0] * ncols, panel[1] * nrows),
                             sharex=True, sharey=True, squeeze=False)
    flat = axes.ravel().tolist()
    for ax in flat[n:]:
        ax.set_visible(False)
    return fig, flat


# ===========================================================================
# Renderers
# ===========================================================================

def _plot_time(d, yaxis, title, out_main, out_extra, coloraxis='spw', extras=True):
    """vs time (G/T/fluxscale gains, or K delay with yaxis='delay')."""
    written = []
    vals = _chan_avg_values(d, yaxis)                       # (n_pol, N)
    t_comp, bounds, bt0, bc0 = compress_time(d['time'])
    phase = (yaxis == 'phase')
    ylabel = _ylabel(yaxis, d['table_type'])
    n_pol = vals.shape[0]
    group = d['spw'] if coloraxis == 'spw' else d['antenna']
    colors = _group_colors(group)
    if coloraxis == 'spw':
        labels = {g: f'SPW {g}' for g in colors}
    else:
        labels = {g: (d['ant_names'][g] if g < len(d['ant_names']) else str(g))
                  for g in colors}
    marker_by_pol = (yaxis == 'delay')

    # ---- main --------------------------------------------------------------
    fig, ax = plt.subplots(figsize=(14, 5))
    n_good = int(np.isfinite(vals).sum())
    s = 6 if n_good < 5000 else 3
    for g, c in colors.items():
        m = group == g
        for p in range(n_pol):
            good = m & np.isfinite(vals[p])
            if good.any():
                ax.scatter(t_comp[good], vals[p, good], s=s * (3 if marker_by_pol else 1),
                           color=c, alpha=0.6, linewidths=0.6 if marker_by_pol else 0,
                           marker=_POL_MARKERS[p % 4] if marker_by_pol else 'o',
                           rasterized=True)
    _decorate_time_ax(ax, d, t_comp, bounds, bt0, bc0, ylabel, phase)
    ax.set_title(title, fontsize=10, pad=55)
    _legend(ax, colors, labels, coloraxis.capitalize())
    written.append(_save(fig, out_main))
    if not extras or yaxis == 'delay':
        return written

    # ---- antenna-averaged (per SPW, per time) -------------------------------
    fig, ax = plt.subplots(figsize=(14, 5))
    spw_colors = _group_colors(d['spw'])
    for g, c in spw_colors.items():
        m = d['spw'] == g
        if not m.any():
            continue
        ut, inv = np.unique(t_comp[m], return_inverse=True)
        v = vals[:, m]                                       # (n_pol, n_m)
        fin = np.isfinite(v)
        cnt = np.zeros(ut.size)
        for p in range(n_pol):
            cnt += np.bincount(inv, weights=fin[p].astype(float), minlength=ut.size)
        if phase:
            z = np.zeros(ut.size, dtype=complex)
            for p in range(n_pol):
                e = np.where(fin[p], np.exp(1j * np.deg2rad(np.nan_to_num(v[p]))), 0)
                z += np.bincount(inv, weights=e.real, minlength=ut.size) \
                    + 1j * np.bincount(inv, weights=e.imag, minlength=ut.size)
            mean = np.rad2deg(np.angle(z))
        else:
            ssum = np.zeros(ut.size)
            for p in range(n_pol):
                ssum += np.bincount(inv, weights=np.nan_to_num(v[p]), minlength=ut.size)
            mean = ssum / np.maximum(cnt, 1)
        ok = cnt > 0
        ax.plot(ut[ok], mean[ok], '-', color=c, lw=0.6, alpha=0.4)
        ax.scatter(ut[ok], mean[ok], s=10, color=c, alpha=0.85, linewidths=0,
                   rasterized=True)
    _decorate_time_ax(ax, d, t_comp, bounds, bt0, bc0, ylabel, phase)
    ax.set_title(title + '  |  antenna-averaged', fontsize=10, pad=55)
    _legend(ax, spw_colors, {g: f'SPW {g}' for g in spw_colors}, 'Spw')
    written.append(_save(fig, out_extra('avgant')))

    # ---- one panel per antenna ---------------------------------------------
    ants = np.unique(d['antenna'])
    fig, axes = _grid(len(ants))
    rgba = np.array([spw_colors[int(s)] for s in d['spw']])
    for ax, a in zip(axes, ants):
        m = d['antenna'] == a
        xs = np.concatenate([t_comp[m]] * n_pol)
        ys = np.concatenate([vals[p, m] for p in range(n_pol)])
        cs = np.concatenate([rgba[m]] * n_pol)
        ok = np.isfinite(ys)
        if ok.any():
            ax.scatter(xs[ok], ys[ok], s=2, c=cs[ok], alpha=0.6, linewidths=0,
                       rasterized=True)
        name = d['ant_names'][a] if a < len(d['ant_names']) else str(a)
        ax.set_title(f'{name} ({a})', fontsize=8, pad=2)
        ax.xaxis.set_major_formatter(_time_formatter(bt0, bc0))
        ax.xaxis.set_major_locator(ticker.MaxNLocator(nbins=3))
        ax.tick_params(labelsize=6)
        ax.grid(True, alpha=0.25, lw=0.4)
        if phase:
            ax.set_ylim(-180, 180)
    fig.suptitle(title + f'  |  per antenna  |  {ylabel}  (colour: SPW)', fontsize=10)
    fig.subplots_adjust(top=0.93, hspace=0.35, wspace=0.08)
    written.append(_save(fig, out_extra('perant'), dpi=110))
    return written


def _plot_vs_antenna(d, yaxis, title, out_main, out_extra, extras=True):
    """Delay (or other value) vs antenna, colour by SPW, marker by pol."""
    written = []
    vals = _chan_avg_values(d, yaxis)                       # (n_pol, N)
    n_pol = vals.shape[0]
    spws = np.unique(d['spw'])
    colors = _group_colors(spws)
    rank = {int(s): i for i, s in enumerate(spws)}
    width = 0.7
    offs = np.array([(rank[int(s)] + 0.5) / len(spws) - 0.5 for s in d['spw']]) * width
    ants_all = np.arange(max(len(d['ant_names']), int(d['antenna'].max()) + 1))
    used = np.unique(d['antenna'])
    plabels = _pol_labels(n_pol)
    ylabel = _ylabel(yaxis, d['table_type'])

    fig, ax = plt.subplots(figsize=(max(10, 0.45 * len(used) + 4), 5))
    for g, c in colors.items():
        m = d['spw'] == g
        for p in range(n_pol):
            good = m & np.isfinite(vals[p])
            if good.any():
                ax.scatter(d['antenna'][good] + offs[good], vals[p, good], s=16,
                           color=c, marker=_POL_MARKERS[p % 4], alpha=0.8,
                           linewidths=0.8, rasterized=True)
    ax.axhline(0, color='k', lw=0.5, ls='--', alpha=0.5)
    names = [d['ant_names'][a] if a < len(d['ant_names']) else str(a) for a in ants_all]
    ax.set_xticks(ants_all)
    ax.set_xticklabels([f'{n} ({a})' for a, n in zip(ants_all, names)],
                       rotation=60, ha='right', fontsize=7)
    ax.set_xlim(-0.6, ants_all[-1] + 0.6)
    ax.set_xlabel('Antenna')
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.25, lw=0.4)
    ax.set_title(title, fontsize=10)
    handles = [Line2D([0], [0], marker='o', color='w', markerfacecolor=colors[g],
                      markersize=6, label=f'SPW {g}') for g in sorted(colors)]
    handles += [Line2D([0], [0], marker=_POL_MARKERS[p % 4], color='0.3', ls='none',
                       label=plabels[p]) for p in range(n_pol)]
    ax.legend(handles=handles, fontsize=7, loc='center left',
              bbox_to_anchor=(1.005, 0.5), ncol=1 if len(handles) <= 18 else 2)
    written.append(_save(fig, out_main))
    if not extras:
        return written

    # ---- heatmap antenna x SPW (mean over time) ----------------------------
    n_ant = len(ants_all)
    fig, axes = plt.subplots(1, n_pol, figsize=(max(8, 0.35 * n_ant + 3) * n_pol / 1.4,
                                                max(4, 0.32 * len(spws) + 2)),
                             squeeze=False)
    s_idx = np.array([rank[int(s)] for s in d['spw']])
    finite_all = vals[np.isfinite(vals)]
    vmax = float(np.max(np.abs(finite_all))) if finite_all.size else 1.0
    for p, ax in enumerate(axes[0]):
        ssum = np.zeros((len(spws), n_ant))
        cnt = np.zeros((len(spws), n_ant))
        fin = np.isfinite(vals[p])
        np.add.at(ssum, (s_idx[fin], d['antenna'][fin]), vals[p, fin])
        np.add.at(cnt, (s_idx[fin], d['antenna'][fin]), 1)
        img = np.where(cnt > 0, ssum / np.maximum(cnt, 1), np.nan)
        im = ax.imshow(img, aspect='auto', cmap='RdBu_r', vmin=-vmax, vmax=vmax,
                       origin='upper', interpolation='nearest')
        ax.set_xticks(range(n_ant))
        ax.set_xticklabels(names, rotation=90, fontsize=6)
        ax.set_yticks(range(len(spws)))
        ax.set_yticklabels([f'SPW {s}' for s in spws], fontsize=6)
        ax.set_title(f'Pol {plabels[p]}  (blank = flagged/absent)', fontsize=9)
        fig.colorbar(im, ax=ax, fraction=0.04, pad=0.02).set_label(ylabel, fontsize=8)
    fig.suptitle(title + '  |  antenna x SPW (time-averaged)', fontsize=10)
    fig.tight_layout()
    written.append(_save(fig, out_extra('heatmap')))
    return written


def _plot_vs_chan(d, xaxis, yaxis, title, out_main, out_extra, extras=True):
    """Bandpass: value vs channel index or frequency, colour by SPW."""
    written = []
    vals = _values(d, yaxis)                                # (n_pol, n_chan, N)
    n_pol, n_chan, _ = vals.shape
    colors = _group_colors(d['spw'])
    ylabel = _ylabel(yaxis, d['table_type'])
    phase = (yaxis == 'phase')

    def _x(spw):
        if xaxis == 'freq':
            f = d['chan_freqs'].get(int(spw))
            if f is not None and f.size == n_chan:
                return f / 1e9
            log.warning("No CHAN_FREQ for SPW %s; using channel index.", spw)
        return np.arange(n_chan)

    xlabel = 'Frequency [GHz]' if xaxis == 'freq' else 'Channel'
    xs = {int(s): _x(s) for s in colors}

    fig, ax = plt.subplots(figsize=(14, 5))
    n_pts = int(np.isfinite(vals).sum())
    ms = 2.0 if n_pts < 50_000 else 1.0
    for g, c in colors.items():
        rows = np.where(d['spw'] == g)[0]
        if rows.size == 0:
            continue
        x = np.repeat(xs[g][:, None], rows.size, axis=1)  # (n_chan, n_rows)
        for p in range(n_pol):
            y = vals[p][:, rows]
            ok = np.isfinite(y)
            ax.plot(x[ok], y[ok], '.', ms=ms, color=c, alpha=0.5, rasterized=True)
    if phase:
        ax.set_ylim(-180, 180)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.grid(True, alpha=0.25, lw=0.4)
    ax.set_title(title, fontsize=10)
    _legend(ax, colors, {g: f'SPW {g}' for g in colors}, 'Spw')
    written.append(_save(fig, out_main))
    if not extras:
        return written

    ants = np.unique(d['antenna'])
    fig, axes = _grid(len(ants))
    for ax, a in zip(axes, ants):
        segs, cols = [], []
        for r in np.where(d['antenna'] == a)[0]:
            g = int(d['spw'][r])
            for p in range(n_pol):
                y = vals[p, :, r]
                if np.isfinite(y).any():
                    segs.append(np.column_stack([xs[g], y]))
                    cols.append(colors[g])
        if segs:
            ax.add_collection(LineCollection(segs, colors=cols, linewidths=0.6,
                                             alpha=0.7))
            ax.autoscale_view()
        name = d['ant_names'][a] if a < len(d['ant_names']) else str(a)
        ax.set_title(f'{name} ({a})', fontsize=8, pad=2)
        ax.tick_params(labelsize=6)
        ax.grid(True, alpha=0.25, lw=0.4)
        if phase:
            ax.set_ylim(-180, 180)
    fig.suptitle(title + f'  |  per antenna  |  {ylabel} vs {xlabel}  (colour: SPW)',
                 fontsize=10)
    fig.subplots_adjust(top=0.93, hspace=0.35, wspace=0.08)
    written.append(_save(fig, out_extra('perant'), dpi=110))
    return written


# ===========================================================================
# SNR histogram (port of v0.5 helper_functions.make_plot_snr)
# ===========================================================================

def make_plot_snr(caltable, cut_off=3.0, plot_snr=True, bins=50, density=True,
                  save_fig=True, snr=None, outfile=None):
    """
    SNR histogram of a calibration table; logs the fraction of solutions
    with SNR < cut_off.  Saved to caltable.replace('.tb', '.jpg') (v0.5), or
    caltable + '.jpg' if the name has no '.tb', or outfile if given.
    `snr` may be passed to avoid re-reading the table.  Never raises.
    """
    try:
        from scipy import stats
        if snr is None:
            import casatools
            tb = casatools.table()
            tb.open(caltable)
            try:
                snr = tb.getcol('SNR')
            finally:
                tb.close()
        snr = np.asarray(snr, dtype=float).ravel()
        snr = snr[np.isfinite(snr)]
        if plot_snr:
            fig = plt.figure(figsize=(3, 3))
            try:
                plt.hist(snr, bins=bins, density=density, histtype='step')
                plt.xlabel('SNR')
                plt.axvline(x=3, color='k', linestyle='--')
                plt.axvline(x=cut_off, color='r', linestyle='--')
                plt.grid()
                if save_fig:
                    if outfile is None:
                        outfile = (caltable.replace('.tb', '.jpg') if '.tb' in caltable
                                   else caltable.rstrip('/') + '.jpg')
                    plt.savefig(outfile, dpi=300, bbox_inches='tight')
            finally:
                plt.close(fig)
        fraction_flagged_solutions = stats.percentileofscore(snr, cut_off)
        logging.info(f" ++==>> Fraction of flagged solutions with SNR < {cut_off} is"
                     f" {fraction_flagged_solutions:.2f}%")
    except (_PLOT_ERRORS + (ImportError,)) as exc:
        log.warning(" --==>> Error plotting SNR for table %s (%s). Going to skip...",
                    caltable, exc)


# ===========================================================================
# plotms backend (port of the v0.5 branch)
# ===========================================================================

def _plotms_plot(table, out_dir, table_type, xaxis, yaxis, fields, antenna='', spw=''):
    from casaplotms import plotms
    plotrange = [-1, -1, -180, 180] if yaxis == 'phase' else [-1, -1, -1, -1]
    if fields == '':
        plotfile = f"{out_dir}/{table_type}_{xaxis}_{yaxis}_field_all_ant_{antenna}_spw_{spw}.jpg"
        plotms(vis=table, xaxis=xaxis, yaxis=yaxis, field='',
               gridcols=1, gridrows=1, coloraxis='spw', antenna=antenna, spw=spw,
               plotrange=plotrange, width=2000, height=800, showgui=False,
               overwrite=True, dpi=1200, highres=True, plotfile=plotfile)
        return [plotfile]
    out = []
    for FIELD in fields:
        plotfile = f"{out_dir}/{table_type}_{xaxis}_{yaxis}_field_{FIELD}_ant_{antenna}_spw_{spw}.jpg"
        plotms(vis=table, xaxis=xaxis, yaxis=yaxis, field=FIELD,
               gridcols=1, gridrows=1, coloraxis='spw', antenna=antenna, spw=spw,
               plotrange=plotrange, width=2000, height=800, showgui=False,
               overwrite=True, dpi=1200, highres=True, plotfile=plotfile)
        out.append(plotfile)
    return out


# ===========================================================================
# Public entry point
# ===========================================================================

def calibration_table_plot(table, plots_dir, stage='calibration', table_type='',
                           xaxis='time', yaxis='phase', fields='', minsnr=3.0,
                           backend='python', coloraxis='spw', extras=True,
                           snr_outfile=None, kind=''):
    """
    Plot a calibration table into {plots_dir}/{stage}/ (see module doc).

    fields : '' -> all fields in one figure ('field_all');
             'a,b' string -> those fields together in one figure;
             list -> one figure per field.
    backend: 'python' (default), 'plotms' (v0.5 plotms calls) or 'none'.
    kind   : accepted and ignored (v0.5 compatibility).
    Returns the list of written plot files.  Never raises: every failure is
    logged as a warning.
    """
    if backend == 'none':
        return []
    written = []
    try:
        out_dir = os.path.join(str(plots_dir).rstrip('/'), stage)
        os.makedirs(out_dir, exist_ok=True)
        if not table_type:
            table_type = os.path.basename(str(table).rstrip('/')).replace('.tb', '')

        if backend == 'plotms':
            make_plot_snr(caltable=table, cut_off=minsnr, plot_snr=True, bins=50,
                          density=True, save_fig=True, outfile=snr_outfile)
            return _plotms_plot(table, out_dir, table_type, xaxis, yaxis, fields)
        if backend != 'python':
            log.warning("Unknown plot backend %r; skipping %s", backend, table)
            return []

        d = read_caltable(table)
        make_plot_snr(caltable=table, cut_off=minsnr, snr=d['snr'],
                      outfile=snr_outfile)
        if d['time'].size == 0:
            log.warning("Calibration table %s has no rows; nothing to plot.", table)
            return []

        if isinstance(fields, str):
            groups = [('all', None)] if fields.strip() == '' else \
                [(fields.strip(), [f for f in fields.split(',') if f.strip()])]
        else:
            groups = [(str(f), [f]) for f in fields]

        for label, sel in groups:
            dd = d
            if sel is not None:
                ids = _resolve_fields(sel, d['field_names'])
                mask = np.isin(d['field'], ids)
                if not mask.any():
                    log.warning("No solutions for field(s) %s in %s", sel, table)
                    continue
                dd = _subset(d, mask)
            main = os.path.join(out_dir,
                                f"{table_type}_{xaxis}_{yaxis}_field_{label}_ant__spw_.jpg")

            def extra(variant, _label=label):
                return os.path.join(out_dir,
                                    f"{table_type}_{xaxis}_{yaxis}_{variant}_field_{_label}.jpg")

            title = (f"{table_type}  [{d['table_type']}]  |  {yaxis} vs {xaxis}  |  "
                     f"field {label}")
            try:
                if xaxis == 'time':
                    written += _plot_time(dd, yaxis, title, main, extra,
                                          coloraxis=coloraxis, extras=extras)
                elif xaxis in ('ant1', 'antenna', 'ant'):
                    written += _plot_vs_antenna(dd, yaxis, title, main, extra,
                                                extras=extras)
                elif xaxis in ('chan', 'channel', 'freq', 'frequency'):
                    xa = 'freq' if xaxis.startswith('freq') else 'chan'
                    written += _plot_vs_chan(dd, xa, yaxis, title, main, extra,
                                             extras=extras)
                else:
                    log.warning("Unsupported xaxis %r for %s", xaxis, table)
            except _PLOT_ERRORS as exc:
                log.warning("Calibration table plot %s (%s vs %s, field %s) failed: %s",
                            table, yaxis, xaxis, label, exc)
                plt.close('all')
    except (_PLOT_ERRORS + (ImportError,)) as exc:
        log.warning("Calibration table plot for %s failed: %s", table, exc)
        plt.close('all')
    return written
