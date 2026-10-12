"""
synphly.plotting.visibilities
=============================
Pure-Python / matplotlib visibility plotting (replaces plotms on MSes).

Merged from the v0.5.1 modules ``data_calibration/Sy_plot_vis.py`` (Synphly v0.5 infrastructure,
field selection, output layout) and ``data_calibration/plot_vis_python.py``
(ph4ser: corrected/model ratio, corrected-model residual, SPW colouring, uv
coverage).  All functions are plain functions; casatools tools are created
locally and always closed.

Public API
----------
make_plots_stages_py(vis, stage='after', kind='', plots=None, FIELDS=None,
                     plot_all_uv=False, avgantenna=True, extra_plot=True,
                     working_directory=None, correlation='RR',
                     mem_fraction=0.20, dpi=150, figsize=(16, 6),
                     overwrite=True, plot_ratio=False, plot_residual=False,
                     color_by='baseline')
plot_uvwave(vis, plotfile_wave, plotfile_metric=None, field_ids=None, ...)
plot_uv_coverage(vis_list, concat_ms=None, output_dir='.', ...)

Default output of make_plots_stages_py (identical to v0.5 Sy_plot_vis)
------------------------------------------------------------------------
  {wd}/plots/{stage}/time_amp/time_amp_avg_{col}_field_{field}_{kind}.jpg
  {wd}/plots/{stage}/freq_amp/freq_amp_avg_{col}_field_{field}_{kind}.jpg
  {wd}/plots/{stage}/time_phase/time_phase_avg_{col}_field_{field}_{kind}.jpg
  {wd}/plots/{stage}/uvwave_amp_{col}_field_{field}_{kind}.jpg
  [extra_plot and MODEL_DATA present]
  {wd}/plots/{stage}/freq_amp/freq_amp_avg_model_field_{field}_{kind}.jpg

Opt-in extras (all default off)
-------------------------------
  plot_ratio=True     {wd}/plots/{stage}/uvwave_amp_{col}_div_model_field_{field}_{kind}.jpg
  plot_residual=True  {wd}/plots/{stage}/uvwave_amp_{col}-model_field_{field}_{kind}.jpg
  plot_all_uv=True    {wd}/plots/{stage}/uv_coverage/uvwave_field_{field}_{kind}.jpg
  color_by='spw'      colour freq/uvwave plots by SPW instead of baseline

Averaging (matches plotms)
--------------------------
  time_amp / time_phase : avgchannel='9999' (channel avg only, native time)
  freq_amp              : avgtime='9999'    (time avg only, native channels)
  uvwave_amp            : avgchannel='9999' + avgtime='9999' (per scan)
  For (col1 op col2) the two columns are accumulated separately and the
  ratio/difference is formed from their complex means.
"""

import os
import time
import logging

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.lines as mlines

log = logging.getLogger(__name__)

_LIGHT_SPEED = 299792458.0    # m s-1
_NAN_C64 = np.complex64(complex(float('nan'), 0.0))

_CORR_STR_INT = {
    'RR': 5, 'RL': 6, 'LR': 7, 'LL': 8,
    'XX': 9, 'XY': 10, 'YX': 11, 'YY': 12,
}
_CORR_FALLBACK = {'RR': 'XX', 'LL': 'YY', 'XX': 'RR', 'YY': 'LL'}

_DATA_KEYS = frozenset(['data', 'corrected_data', 'model_data'])


# ===========================================================================
# CASA tools
# ===========================================================================

def _casatools():
    """Import casatools lazily (so the module imports without CASA)."""
    import casatools
    return casatools


def _read_subtable_col(vis, sub, col):
    """Read one column of an MS subtable ('' = main table); tool closed."""
    tb = _casatools().table()
    tb.open(os.path.join(vis, sub) if sub else vis)
    try:
        return tb.getcol(col)
    finally:
        tb.close()


# ===========================================================================
# Memory helpers
# ===========================================================================

def _get_available_memory_gb():
    """Return available system RAM in GB; None on failure."""
    try:
        import psutil
        return psutil.virtual_memory().available / 1e9
    except ImportError:
        pass
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024 / 1e9
    except OSError:
        pass
    return None


def _chunk_rows(n_chan, mem_budget_gb, n_datacols=1, safety=3.0):
    """
    Safe number of MS rows per iteration chunk.

    Memory model per row: n_chan * (8 + 1) bytes * n_datacols * safety
    (complex64 + bool flag; safety for intermediates).  At least 500 rows.
    """
    bytes_per_row = n_chan * 9.0 * n_datacols * safety
    budget = max(0.5, float(mem_budget_gb)) * 1e9
    return max(500, int(budget / bytes_per_row))


# ===========================================================================
# MS metadata helpers
# ===========================================================================

def _existing_cols(vis):
    """Set of column names in the main MS table."""
    tb = _casatools().table()
    tb.open(vis)
    try:
        return set(tb.colnames())
    finally:
        tb.close()


def _corr_types(vis, corr_str):
    """CORR_TYPE ints of the polarisation setup (handles ragged rows)."""
    tb = _casatools().table()
    tb.open(vis + '/POLARIZATION')
    try:
        try:
            return tb.getcol('CORR_TYPE')[:, 0].astype(int)
        except RuntimeError:
            rows = [np.array(tb.getcell('CORR_TYPE', r), dtype=int)
                    for r in range(tb.nrows())]
    finally:
        tb.close()
    non_empty = [r for r in rows if len(r) > 0]
    ctypes = non_empty[0] if non_empty else np.array([], dtype=int)
    target_int = _CORR_STR_INT.get(corr_str.upper())
    if target_int is not None:
        for row_ct in non_empty:
            if target_int in row_ct:
                return row_ct
    return ctypes


def _corr_idx_from_types(ctypes, corr_str):
    """Axis-0 index of corr_str in ctypes, with RR<->XX/LL<->YY fallback."""
    ctypes = np.asarray(ctypes, dtype=int)
    target = _CORR_STR_INT.get(corr_str.upper())
    if target is not None and target in ctypes:
        return int(np.where(ctypes == target)[0][0])
    fb = _CORR_FALLBACK.get(corr_str.upper())
    if fb:
        fb_int = _CORR_STR_INT.get(fb)
        if fb_int is not None and fb_int in ctypes:
            idx = int(np.where(ctypes == fb_int)[0][0])
            log.warning("  Corr '%s' not found; using '%s' (idx=%d).",
                        corr_str, fb, idx)
            return idx
    log.warning("  Corr '%s' not found; defaulting to index 0.", corr_str)
    return 0


def _corr_idx(vis, corr_str):
    """Axis-0 index for corr_str in the DATA array of vis."""
    return _corr_idx_from_types(_corr_types(vis, corr_str), corr_str)


def _spw_meta(vis):
    """dd_info: {dd_id: {spw_id, n_chan, chan_freqs, mean_freq}}."""
    spw_per_dd = list(_read_subtable_col(vis, 'DATA_DESCRIPTION',
                                         'SPECTRAL_WINDOW_ID'))
    msmd = _casatools().msmetadata()
    msmd.open(vis)
    try:
        dd_info = {}
        for dd_id, spw_id in enumerate(spw_per_dd):
            freqs = msmd.chanfreqs(int(spw_id))
            dd_info[int(dd_id)] = {
                'spw_id': int(spw_id),
                'n_chan': int(len(freqs)),
                'chan_freqs': freqs,
                'mean_freq': float(freqs.mean()),
            }
    finally:
        msmd.done()
    return dd_info


def _ant_names(vis):
    return list(_read_subtable_col(vis, 'ANTENNA', 'NAME'))


def _resolve_field_ids_from_names(fields, ms_names):
    """
    Resolve field strings (integer IDs or names) to a sorted list of IDs.

    '' / None -> None (no filter).  Exact name match first, then substring.
    """
    if not fields:
        return None
    n_fields_ms = len(ms_names)
    result = []
    for f in fields:
        f = str(f).strip()
        if not f:
            continue
        try:
            fid = int(f)
        except ValueError:
            fid = None
        if fid is not None:
            if 0 <= fid < n_fields_ms:
                result.append(fid)
            else:
                log.warning("  Field ID %d out of range [0, %d).", fid, n_fields_ms)
            continue
        matches = [i for i, n in enumerate(ms_names) if n == f]
        if not matches:
            matches = [i for i, n in enumerate(ms_names) if f in n or n in f]
        if matches:
            result.extend(matches)
        else:
            log.warning("  Field '%s' not found (fields: %s).", f, ms_names)
    if not result:
        return None
    return sorted(set(result))


def _resolve_field_ids(vis, fields):
    return _resolve_field_ids_from_names(
        fields, list(_read_subtable_col(vis, 'FIELD', 'NAME')))


# ===========================================================================
# Colour / style helpers
# ===========================================================================

def _get_cmap(name):
    try:
        return plt.colormaps[name]
    except AttributeError:
        return plt.cm.get_cmap(name)


def _baseline_colormap(ant1_arr, ant2_arr, ant_names, cmap_name='twilight_shifted'):
    """Colour dict keyed by (ant1, ant2): one colour per unique baseline."""
    pairs = sorted(set(zip(np.asarray(ant1_arr).tolist(),
                           np.asarray(ant2_arr).tolist())))
    n = max(len(pairs), 1)
    cmap = _get_cmap(cmap_name)
    colors, handles = {}, []
    for i, (a1, a2) in enumerate(pairs):
        col = cmap(i / n)
        colors[(a1, a2)] = col
        n1 = ant_names[a1] if (ant_names and a1 < len(ant_names)) else str(a1)
        n2 = ant_names[a2] if (ant_names and a2 < len(ant_names)) else str(a2)
        handles.append(mpatches.Patch(color=col, label=f'{n1}-{n2}'))
    return colors, handles


def _spw_colormap(dd_ids, dd_info, cmap_name='tab20'):
    """Colour dict keyed by dd_id, plus legend handles labelled by SPW."""
    cmap = _get_cmap(cmap_name)
    colors = {dd: cmap(i % cmap.N) for i, dd in enumerate(sorted(dd_ids))}
    handles = [mpatches.Patch(color=colors[dd],
                              label='SPW {}'.format(dd_info[dd]['spw_id']))
               for dd in sorted(dd_ids)]
    return colors, handles


def _adaptive_style(n_points):
    """Markersize and alpha scaled to data density (v0.5 Sy_plot_vis values)."""
    if n_points < 500:
        return dict(markersize=6, alpha=0.95)
    if n_points < 5_000:
        return dict(markersize=4, alpha=0.90)
    if n_points < 50_000:
        return dict(markersize=2, alpha=0.80)
    return dict(markersize=1, alpha=0.60)


# ===========================================================================
# Field-aware SPW row iterator
# ===========================================================================

def _iter_spw_chunks(vis, dd_ids, chunk_rows, request_cols, field_ids=None):
    """
    Iterate over vis rows one DATA_DESC_ID at a time in row chunks,
    optionally filtering by FIELD_ID.  Yields ms.getdata() dicts + 'dd_id'.

    Each data column is fetched in its own getdata() call (CASA drops all
    but one when several are requested together).  selecttaql + selectinit
    handles non-homogeneous SPW channel counts (CASA 6.7+).
    """
    data_cols = [c for c in request_cols if c in _DATA_KEYS]
    other_cols = [c for c in request_cols if c not in _DATA_KEYS]
    if field_ids:
        field_taql = ' && FIELD_ID IN [{}]'.format(
            ', '.join(str(int(f)) for f in field_ids))
    else:
        field_taql = ''

    ms_tool = _casatools().ms()
    ms_tool.open(vis)
    try:
        for dd_id in dd_ids:
            ms_tool.selectinit(reset=True)
            ms_tool.selecttaql(f'DATA_DESC_ID=={dd_id}{field_taql}')
            ms_tool.selectinit(datadescid=int(dd_id))   # shape only, no reset
            ms_tool.iterinit(maxrows=int(chunk_rows))
            more = ms_tool.iterorigin()
            while more:
                chunk = ms_tool.getdata(other_cols) if other_cols else {}
                for dc in data_cols:
                    chunk.update(ms_tool.getdata([dc]))
                chunk['dd_id'] = int(dd_id)
                yield chunk
                more = ms_tool.iternext()
    finally:
        ms_tool.close()


def _split_datacol(datacol):
    """'col' -> ('col', None, None, ['col']); (c1, op, c2) -> (c1, op, c2, [c1, c2])."""
    if isinstance(datacol, tuple):
        col1, op, col2 = datacol
        return col1, op, col2, [col1, col2]
    return datacol, None, None, [datacol]


def _sel_flags(chunk, ci):
    """Per-channel flag of the selected correlation OR row flag -> (n_chan, n_rows)."""
    return chunk['flag'][ci, :, :] | chunk['flag_row'][np.newaxis, :]


def _chan_avg(chunk, col_key, ci, f_sel):
    """Channel-average one column over unflagged channels -> (n_rows,) complex64."""
    d = chunk[col_key][ci, :, :].astype(np.complex64)
    n_valid = (~f_sel).sum(axis=0, dtype=np.int32)
    d_sum = np.where(f_sel, np.complex64(0j), d).sum(axis=0)
    avg = (d_sum / np.maximum(n_valid, 1).astype(np.float32)).astype(np.complex64)
    avg[n_valid == 0] = _NAN_C64
    return avg


def _bl_sort_index(ant1, ant2, n_ant):
    """Sort order grouping rows by baseline + group starts/counts."""
    bl_idx = ant1.astype(np.int64) * int(n_ant) + ant2.astype(np.int64)
    sort_ord = np.argsort(bl_idx, kind='stable')
    _, starts, cnts = np.unique(bl_idx[sort_ord], return_index=True,
                                return_counts=True)
    return sort_ord, starts, cnts


def _combine(mean1, mean2, op):
    """Amplitude of mean1 (op) mean2 for scalars or arrays."""
    if op == '/':
        with np.errstate(divide='ignore', invalid='ignore'):
            ratio = np.where(np.abs(mean2) > 0, mean1 / np.where(
                np.abs(mean2) > 0, mean2, 1.0), np.nan + 0j)
        return np.abs(ratio)
    return np.abs(mean1 - mean2)


# ===========================================================================
# Accumulators
# ===========================================================================

def _collect_uvwave_amp(vis, datacol, ci, dd_info, chunk_rows, n_ant,
                        field_ids=None, avgscan=False):
    """
    Channel + time average -> amplitude vs |uv| [klambda], one point per
    (dd, baseline, scan) (plotms avgchannel/avgtime='9999', avgscan=False).

    Returns uvwave, amp, ant1, ant2, dd (arrays) or all None.
    """
    col1, op, col2, req = _split_datacol(datacol)
    is_tuple = op is not None
    request_cols = req + ['flag', 'flag_row', 'uvw', 'antenna1', 'antenna2',
                          'scan_number']
    accum = {}
    n64 = np.int64(n_ant)

    for chunk in _iter_spw_chunks(vis, sorted(dd_info), chunk_rows,
                                  request_cols, field_ids=field_ids):
        dd_id = chunk['dd_id']
        flag_row = chunk['flag_row']
        ant1 = chunk['antenna1'].astype(np.int32)
        ant2 = chunk['antenna2'].astype(np.int32)
        scan_num = chunk['scan_number'].astype(np.int32)
        f_sel = _sel_flags(chunk, ci)

        cavg1 = _chan_avg(chunk, col1, ci, f_sel)
        cavg2 = _chan_avg(chunk, col2, ci, f_sel) if is_tuple else None
        good = (ant1 != ant2) & (~flag_row) & np.isfinite(cavg1.real)
        if is_tuple:
            good &= np.isfinite(cavg2.real)
        if not good.any():
            continue

        g_ant1, g_ant2, g_scan = ant1[good], ant2[good], scan_num[good]
        if avgscan:
            key_arr = g_ant1.astype(np.int64) * n64 + g_ant2
        else:
            key_arr = (g_scan.astype(np.int64) * n64 * n64
                       + g_ant1.astype(np.int64) * n64 + g_ant2)
        sort_ord = np.argsort(key_arr, kind='stable')
        _, starts, cnts = np.unique(key_arr[sort_ord], return_index=True,
                                    return_counts=True)
        s_ant1, s_ant2, s_scan = g_ant1[sort_ord], g_ant2[sort_ord], g_scan[sort_ord]
        s_c1 = cavg1[good][sort_ord]
        s_c2 = cavg2[good][sort_ord] if is_tuple else None
        s_uvw = chunk['uvw'][:, good][:, sort_ord]

        for start, cnt in zip(starts, cnts):
            sl = slice(start, start + cnt)
            key = (dd_id, int(s_ant1[start]), int(s_ant2[start]),
                   0 if avgscan else int(s_scan[start]))
            acc = accum.get(key)
            if acc is None:
                acc = accum[key] = {'sum1': np.complex64(0j), 'sum2': np.complex64(0j),
                                    'count': 0, 'uvw_sum': np.zeros(3)}
            acc['sum1'] += s_c1[sl].sum()
            acc['count'] += cnt
            acc['uvw_sum'] += s_uvw[:, sl].sum(axis=1)
            if is_tuple:
                acc['sum2'] += s_c2[sl].sum()

    out = {'uvwave': [], 'amp': [], 'ant1': [], 'ant2': [], 'dd': []}
    for (dd_id, a1v, a2v, _scan), v in accum.items():
        cnt = v['count']
        if cnt == 0:
            continue
        mean1 = v['sum1'] / cnt
        if is_tuple:
            mean2 = v['sum2'] / cnt
            if op == '/' and abs(mean2) == 0.0:
                continue
            amp = float(_combine(mean1, mean2, op))
        else:
            amp = abs(mean1)
        if not np.isfinite(amp):
            continue
        mean_uvw = v['uvw_sum'] / cnt
        uv_m = np.sqrt(mean_uvw[0] ** 2 + mean_uvw[1] ** 2)
        out['uvwave'].append(uv_m * dd_info[dd_id]['mean_freq'] / _LIGHT_SPEED / 1e3)
        out['amp'].append(float(amp))
        out['ant1'].append(a1v)
        out['ant2'].append(a2v)
        out['dd'].append(dd_id)

    if not out['uvwave']:
        return None, None, None, None, None
    return (np.array(out['uvwave'], dtype=np.float64),
            np.array(out['amp'], dtype=np.float64),
            np.array(out['ant1'], dtype=np.int32),
            np.array(out['ant2'], dtype=np.int32),
            np.array(out['dd'], dtype=np.int32))


def _accumulate_freq_amp(vis, datacol, ci, dd_info, chunk_rows, n_ant,
                         field_ids=None):
    """
    Time-average complex visibilities per (dd_id, ant1, ant2, channel)
    (plotms avgtime='9999').

    Returns {(dd_id, a1, a2): {'freqs': Hz array, 'amp': array}}.
    """
    col1, op, col2, req = _split_datacol(datacol)
    is_tuple = op is not None
    request_cols = req + ['flag', 'flag_row', 'antenna1', 'antenna2']
    accum = {}

    for chunk in _iter_spw_chunks(vis, sorted(dd_info), chunk_rows,
                                  request_cols, field_ids=field_ids):
        dd_id = chunk['dd_id']
        n_chan = dd_info[dd_id]['n_chan']
        flag_row = chunk['flag_row']
        ant1 = chunk['antenna1'].astype(np.int32)
        ant2 = chunk['antenna2'].astype(np.int32)
        f_sel = _sel_flags(chunk, ci)

        cross = (ant1 != ant2) & (~flag_row)
        if not cross.any():
            continue
        f_c = f_sel[:, cross]
        valid_c = ~f_c
        d1_c = np.where(f_c, np.complex64(0j),
                        chunk[col1][ci][:, cross].astype(np.complex64))
        d2_c = (np.where(f_c, np.complex64(0j),
                         chunk[col2][ci][:, cross].astype(np.complex64))
                if is_tuple else None)
        g_ant1, g_ant2 = ant1[cross], ant2[cross]
        sort_ord, starts, cnts = _bl_sort_index(g_ant1, g_ant2, n_ant)

        for start, cnt in zip(starts, cnts):
            idx = sort_ord[start:start + cnt]
            key = (dd_id, int(g_ant1[idx[0]]), int(g_ant2[idx[0]]))
            acc = accum.get(key)
            if acc is None:
                acc = accum[key] = {'sum1': np.zeros(n_chan, np.complex64),
                                    'sum2': np.zeros(n_chan, np.complex64),
                                    'count': np.zeros(n_chan, np.int32)}
            acc['sum1'] += d1_c[:, idx].sum(axis=1)
            acc['count'] += valid_c[:, idx].sum(axis=1).astype(np.int32)
            if is_tuple:
                acc['sum2'] += d2_c[:, idx].sum(axis=1)

    result = {}
    for key, v in accum.items():
        has_data = v['count'] > 0
        denom = np.maximum(v['count'], 1).astype(np.float32)
        mean1 = np.where(has_data, v['sum1'] / denom, _NAN_C64)
        if is_tuple:
            mean2 = np.where(has_data, v['sum2'] / denom, _NAN_C64)
            amp = _combine(mean1, mean2, op)
        else:
            amp = np.abs(mean1)
        result[key] = {'freqs': dd_info[key[0]]['chan_freqs'],
                       'amp': np.where(has_data, amp, np.nan).astype(np.float32)}
    return result


def _collect_time_vis(vis, datacol, ci, dd_info, chunk_rows, field_ids=None):
    """
    Channel-averaged visibilities per row (plotms avgchannel='9999', no
    time averaging).  Returns times [MJD s], amps, phases [deg], ant1, ant2
    or five Nones.
    """
    col1, op, col2, req = _split_datacol(datacol)
    is_tuple = op is not None
    request_cols = req + ['flag', 'flag_row', 'antenna1', 'antenna2', 'time']
    parts = {'t': [], 'a': [], 'p': [], 'a1': [], 'a2': []}

    for chunk in _iter_spw_chunks(vis, sorted(dd_info), chunk_rows,
                                  request_cols, field_ids=field_ids):
        flag_row = chunk['flag_row']
        ant1 = chunk['antenna1'].astype(np.int32)
        ant2 = chunk['antenna2'].astype(np.int32)
        f_sel = _sel_flags(chunk, ci)
        cavg1 = _chan_avg(chunk, col1, ci, f_sel)
        cavg2 = _chan_avg(chunk, col2, ci, f_sel) if is_tuple else None
        good = (ant1 != ant2) & (~flag_row) & np.isfinite(cavg1.real)
        if is_tuple:
            good &= np.isfinite(cavg2.real)
        if not good.any():
            continue
        c_out = cavg1[good]
        if is_tuple:
            g2 = cavg2[good]
            if op == '/':
                safe = np.abs(g2) > 0
                c_out = np.where(safe, c_out / np.where(safe, g2, np.complex64(1)),
                                 _NAN_C64)
            else:
                c_out = (c_out - g2).astype(np.complex64)
        amps = np.abs(c_out).astype(np.float32)
        phases = np.degrees(np.angle(c_out)).astype(np.float32)
        finite = np.isfinite(amps)
        if not finite.any():
            continue
        parts['t'].append(chunk['time'][good][finite])
        parts['a'].append(amps[finite])
        parts['p'].append(phases[finite])
        parts['a1'].append(ant1[good][finite])
        parts['a2'].append(ant2[good][finite])

    if not parts['t']:
        return None, None, None, None, None
    return (np.concatenate(parts['t']),
            np.concatenate(parts['a']).astype(np.float32),
            np.concatenate(parts['p']).astype(np.float32),
            np.concatenate(parts['a1']).astype(np.int32),
            np.concatenate(parts['a2']).astype(np.int32))


# ===========================================================================
# Renderers
# ===========================================================================

def _apply_plotrange(ax, plotrange):
    if plotrange is None:
        return
    xmin, xmax, ymin, ymax = plotrange
    if xmin != 0 or xmax != 0:
        ax.set_xlim(xmin, xmax)
    if ymin != 0 or ymax != 0:
        ax.set_ylim(ymin, ymax)


def _ensure_dir(path):
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)


def _finish(fig, ax, plotfile, title, xlabel, ylabel, dpi, legend_handles=None):
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(True, lw=0.3, alpha=0.4)
    if legend_handles and len(legend_handles) <= 32:
        ax.legend(handles=legend_handles, fontsize=7, loc='upper right',
                  framealpha=0.7, ncol=max(1, int(np.ceil(len(legend_handles) / 8))))
    _ensure_dir(plotfile)
    try:
        fig.savefig(plotfile, dpi=dpi, bbox_inches='tight')
    finally:
        plt.close(fig)
    log.info("  Saved: %s", plotfile)


def _scatter_grouped(ax, x, y, groups, colors, style):
    """Plot x/y points split by a per-point group key array -> colors[key]."""
    if groups.ndim == 2:   # (n, 2) baseline pairs
        keys = groups[:, 0].astype(np.int64) * 100000 + groups[:, 1]
        lut = {k[0] * 100000 + k[1]: c for k, c in colors.items()}
    else:
        keys = groups.astype(np.int64)
        lut = dict(colors)
    order = np.argsort(keys, kind='stable')
    uk, starts = np.unique(keys[order], return_index=True)
    bounds = list(starts[1:]) + [len(keys)]
    for k, s, e in zip(uk, starts, bounds):
        idx = order[s:e]
        ax.plot(x[idx], y[idx], '.', markersize=style['markersize'],
                color=lut.get(int(k), 'grey'), alpha=style['alpha'],
                rasterized=True, linewidth=0)


def _render_points(x, y, ant1_arr, ant2_arr, colors, plotrange=None,
                   figsize=(16, 6), dd_arr=None):
    """Scatter on a new figure: baseline colours, or SPW colours if dd_arr given."""
    style = _adaptive_style(len(x))
    fig, ax = plt.subplots(figsize=figsize)
    if dd_arr is not None:
        _scatter_grouped(ax, x, y, dd_arr, colors, style)
    else:
        _scatter_grouped(ax, x, y, np.column_stack([ant1_arr, ant2_arr]),
                         colors, style)
    _apply_plotrange(ax, plotrange)
    return fig, ax


def _render_uvwave_amp(uvwave, amp, ant1_arr, ant2_arr, colors, plotfile, title,
                       plotrange=None, figsize=(16, 6), dpi=150,
                       dd_arr=None, legend_handles=None, ylabel="Amplitude [Jy]"):
    fig, ax = _render_points(uvwave, amp, ant1_arr, ant2_arr, colors,
                             plotrange, figsize, dd_arr)
    _finish(fig, ax, plotfile, title, r"$|uv|\;[\mathrm{k}\lambda]$",
            ylabel, dpi, legend_handles)


def _render_freq_amp(freq_amp, colors, plotfile, title, plotrange=None,
                     figsize=(16, 6), dpi=150, by_spw=False, legend_handles=None,
                     ylabel="Amplitude [Jy]"):
    n_total = sum(int(np.isfinite(v['amp']).sum()) for v in freq_amp.values())
    style = _adaptive_style(n_total)
    fig, ax = plt.subplots(figsize=figsize)
    for (dd_id, a1v, a2v), v in sorted(freq_amp.items()):
        amp = v['amp']
        valid = np.isfinite(amp)
        if not valid.any():
            continue
        color = colors.get(dd_id if by_spw else (a1v, a2v), 'grey')
        ax.plot(v['freqs'][valid] / 1e9, amp[valid], '.',
                markersize=style['markersize'], color=color,
                alpha=style['alpha'], rasterized=True, linewidth=0)
    _apply_plotrange(ax, plotrange)
    _finish(fig, ax, plotfile, title, "Frequency [GHz]", ylabel, dpi,
            legend_handles)


def _render_time(times, values, ant1_arr, ant2_arr, colors, plotfile, title,
                 ylabel, plotrange=None, figsize=(16, 6), dpi=150, phase=False):
    """Amp or phase vs time [hours from first sample]."""
    if len(times) == 0:
        log.warning("  No data for time plot: %s", plotfile)
        return
    t_hours = (times - times.min()) / 3600.0
    fig, ax = _render_points(t_hours, values, ant1_arr, ant2_arr, colors,
                             None, figsize)
    if phase and plotrange is None:
        ax.set_ylim(-180, 180)   # plotms plotrange=[-1,-1,-180,180]
    else:
        _apply_plotrange(ax, plotrange)
    _finish(fig, ax, plotfile, title, "Time from scan start [hours]", ylabel, dpi)


# ===========================================================================
# make_plots_stages_py  (main public API)
# ===========================================================================

def make_plots_stages_py(vis, stage='after', kind='',
                         plots=None, FIELDS=None,
                         plot_all_uv=False, avgantenna=True,
                         extra_plot=True,
                         working_directory=None,
                         correlation='RR',
                         mem_fraction=0.20,
                         dpi=150,
                         figsize=(16, 6),
                         overwrite=True,
                         plot_ratio=False,
                         plot_residual=False,
                         color_by='baseline'):
    """
    Pure-Python / matplotlib replacement for plotms make_plots_stages().

    Parameters
    ----------
    vis              : str   Measurement set (read-only access).
    stage            : str   'before' (DATA) or 'after' (CORRECTED_DATA).
    kind             : str   Label appended to output filenames.
    plots            : -     Unused (kept for v0.5 signature compatibility).
    FIELDS           : list or comma string of field names / ID strings.
    plot_all_uv      : bool  Also write a uv-coverage plot per field (opt-in).
    avgantenna       : bool  Unused (plots are per baseline, as in v0.5).
    extra_plot       : bool  MODEL_DATA amp vs freq (if MODEL_DATA exists).
    working_directory: str   Output root ({wd}/plots/{stage}/...); default
                             dirname(vis).
    correlation      : str   'RR' (falls back to XX), etc.
    mem_fraction     : float Fraction of available RAM for data chunks.
    dpi, figsize     :       Figure parameters.
    overwrite        : bool  If False, skip plots whose file already exists.
    plot_ratio       : bool  {col}/MODEL amp vs uvwave (opt-in).
    plot_residual    : bool  {col}-MODEL amp vs uvwave (opt-in).
    color_by         : 'baseline' (v0.5 default) or 'spw' for freq/uvwave plots.

    Failures of individual plots are logged as warnings; a missing column or
    field is logged and skipped.
    """
    t_start = time.time()
    if working_directory is None:
        working_directory = os.path.dirname(os.path.abspath(vis))
    stage_dir = os.path.join(working_directory.rstrip('/'), 'plots', stage)
    for subdir in ['time_amp', 'freq_amp', 'time_phase',
                   'amp_phase', 'chan_amp', 'chan_phase']:
        os.makedirs(os.path.join(stage_dir, subdir), exist_ok=True)

    if stage == 'before':
        col_label, datacol = 'data', 'data'
    else:
        col_label, datacol = 'corrected', 'corrected_data'

    existing = _existing_cols(vis)
    has_corrected = 'CORRECTED_DATA' in existing
    has_model = 'MODEL_DATA' in existing
    if stage != 'before' and not has_corrected:
        log.warning("  CORRECTED_DATA absent in %s; cannot plot stage='%s'.",
                    vis, stage)
        return

    ci = _corr_idx(vis, correlation)
    dd_info = _spw_meta(vis)
    ant_names = _ant_names(vis)
    n_ant = len(ant_names)
    field_names = list(_read_subtable_col(vis, 'FIELD', 'NAME'))

    n_chan_max = max(v['n_chan'] for v in dd_info.values())
    avail_gb = _get_available_memory_gb() or 2.0
    cr_single = _chunk_rows(n_chan_max, avail_gb * mem_fraction, n_datacols=1)
    cr_double = _chunk_rows(n_chan_max, avail_gb * mem_fraction, n_datacols=2)
    log.info("  plotting.visibilities: n_chan_max=%d chunk(1col)=%d "
             "avail_ram=%.1f GB mem_fraction=%.2f",
             n_chan_max, cr_single, avail_gb, mem_fraction)

    if isinstance(FIELDS, str):
        FIELDS = [f.strip() for f in FIELDS.split(',') if f.strip()]
    else:
        FIELDS = list(FIELDS) if FIELDS is not None else []
    if not FIELDS:
        log.warning("  No FIELDS specified; nothing to plot.")
        return

    by_spw = (color_by == 'spw')
    spw_colors, spw_handles = _spw_colormap(list(dd_info), dd_info)

    def _need(path):
        return overwrite or not os.path.isfile(path)

    def _uvwave_plot(dcol, pf, title, cr, field_ids, plotrange=None):
        uvwave, amp, a1, a2, dd = _collect_uvwave_amp(
            vis, dcol, ci, dd_info, cr, n_ant, field_ids=field_ids)
        if uvwave is None:
            log.warning("    No valid data for %s", pf)
            return
        ylabel = ("Amplitude ratio" if isinstance(dcol, tuple) and dcol[1] == '/'
                  else "Amplitude [Jy]")
        if by_spw:
            _render_uvwave_amp(uvwave, amp, a1, a2, spw_colors, pf, title,
                               plotrange=plotrange, figsize=figsize, dpi=dpi,
                               dd_arr=dd, legend_handles=spw_handles, ylabel=ylabel)
        else:
            colors, _ = _baseline_colormap(a1, a2, ant_names)
            _render_uvwave_amp(uvwave, amp, a1, a2, colors, pf, title,
                               plotrange=plotrange, figsize=figsize, dpi=dpi,
                               ylabel=ylabel)

    def _freq_plot(dcol, pf, title, field_ids):
        freq_amp = _accumulate_freq_amp(vis, dcol, ci, dd_info, cr_single,
                                        n_ant, field_ids=field_ids)
        if not freq_amp:
            log.warning("    No valid data for %s", pf)
            return
        if by_spw:
            _render_freq_amp(freq_amp, spw_colors, pf, title, figsize=figsize,
                             dpi=dpi, by_spw=True, legend_handles=spw_handles)
        else:
            a1s = np.array([k[1] for k in freq_amp], dtype=np.int32)
            a2s = np.array([k[2] for k in freq_amp], dtype=np.int32)
            colors, _ = _baseline_colormap(a1s, a2s, ant_names)
            _render_freq_amp(freq_amp, colors, pf, title, figsize=figsize, dpi=dpi)

    def _safe(label, func, *args, **kwargs):
        try:
            func(*args, **kwargs)
        except (RuntimeError, ValueError, KeyError, IndexError, OSError,
                MemoryError) as exc:
            log.warning("    %s plot failed (field=%s): %s", label, field_str, exc)

    for FIELD in FIELDS:
        field_str = str(FIELD).strip()
        field_ids = _resolve_field_ids_from_names([field_str], field_names)
        if field_ids is None:
            log.warning("  Field '%s' not found; skipping.", field_str)
            continue
        log.info("  Plotting field '%s' (FIELD_ID=%s) stage=%s kind=%s",
                 field_str, field_ids, stage, kind)

        def _pf(subdir, prefix, label=col_label):
            name = f"{prefix}_{label}_field_{field_str}_{kind}.jpg"
            return os.path.join(stage_dir, subdir, name) if subdir \
                else os.path.join(stage_dir, name)

        pf_time_amp = _pf('time_amp', 'time_amp_avg')
        pf_freq_amp = _pf('freq_amp', 'freq_amp_avg')
        pf_time_phase = _pf('time_phase', 'time_phase_avg')
        pf_uvwave_amp = _pf('', 'uvwave_amp')

        # ----- time vs amp / phase ------------------------------------------
        if _need(pf_time_amp) or _need(pf_time_phase):
            def _time_plots():
                times, amps, phases, a1, a2 = _collect_time_vis(
                    vis, datacol, ci, dd_info, cr_single, field_ids=field_ids)
                if times is None:
                    log.warning("    No valid data for time plots (field=%s).",
                                field_str)
                    return
                colors, _ = _baseline_colormap(a1, a2, ant_names)
                if _need(pf_time_amp):
                    _render_time(times, amps, a1, a2, colors, pf_time_amp,
                                 f"Time vs Amp  |  {col_label}  |  field {field_str}  |  {kind}",
                                 "Amplitude [Jy]", figsize=figsize, dpi=dpi)
                if _need(pf_time_phase):
                    _render_time(times, phases, a1, a2, colors, pf_time_phase,
                                 f"Time vs Phase  |  {col_label}  |  field {field_str}  |  {kind}",
                                 "Phase [degrees]", figsize=figsize, dpi=dpi,
                                 phase=True)
            _safe('time', _time_plots)

        # ----- freq vs amp ---------------------------------------------------
        if _need(pf_freq_amp):
            _safe('freq-amp', _freq_plot, datacol, pf_freq_amp,
                  f"Freq vs Amp  |  {col_label}  |  field {field_str}  |  {kind}",
                  field_ids)

        # ----- uvwave vs amp -------------------------------------------------
        if _need(pf_uvwave_amp):
            _safe('uvwave-amp', _uvwave_plot, datacol, pf_uvwave_amp,
                  f"UV-wave vs Amp  |  {col_label}  |  field {field_str}  |  {kind}",
                  cr_single, field_ids)

        # ----- extra: MODEL freq vs amp -------------------------------------
        if extra_plot and has_model:
            pf_model = _pf('freq_amp', 'freq_amp_avg', label='model')
            if _need(pf_model):
                _safe('model freq-amp', _freq_plot, 'model_data', pf_model,
                      f"Freq vs Amp  |  model  |  field {field_str}  |  {kind}",
                      field_ids)
        elif extra_plot:
            log.warning("    extra_plot=True but MODEL_DATA absent; skipping model plots.")

        # ----- opt-in: ratio / residual vs model -----------------------------
        if (plot_ratio or plot_residual) and not has_model:
            log.warning("    MODEL_DATA absent; skipping ratio/residual plots.")
        else:
            if plot_ratio:
                pf = _pf('', 'uvwave_amp', label=f'{col_label}_div_model')
                if _need(pf):
                    _safe('ratio', _uvwave_plot, (datacol, '/', 'model_data'), pf,
                          f"UV-wave vs Amp  |  {col_label}/model  |  field {field_str}  |  {kind}",
                          cr_double, field_ids, plotrange=[0, 0, 0, 10])
            if plot_residual:
                pf = _pf('', 'uvwave_amp', label=f'{col_label}-model')
                if _need(pf):
                    _safe('residual', _uvwave_plot, (datacol, '-', 'model_data'), pf,
                          f"UV-wave vs Amp  |  {col_label}-model  |  field {field_str}  |  {kind}",
                          cr_double, field_ids)

        # ----- opt-in: uv coverage ------------------------------------------
        if plot_all_uv:
            pf = os.path.join(stage_dir, 'uv_coverage',
                              f"uvwave_field_{field_str}_{kind}.jpg")
            if _need(pf):
                _safe('uv-coverage', plot_uvwave, vis, pf, field_ids=field_ids,
                      title=f"field {field_str}", mem_fraction=mem_fraction,
                      dd_info=dd_info, ant_names=ant_names)

    log.info("  plotting.visibilities: plotting '%s' for fields %s took %.2f minutes",
             kind, FIELDS, (time.time() - t_start) / 60.0)


# ===========================================================================
# uv coverage
# ===========================================================================

def plot_uvwave(vis, plotfile_wave, plotfile_metric=None, field_ids=None,
                title='', mem_fraction=0.10, cmap_name='twilight_shifted',
                dd_info=None, ant_names=None, chan_bin=16, dpi=150):
    """
    u vs v [klambda] (channels grouped in chan_bin chunks, conjugates
    included), coloured by baseline; optionally u vs v [m] too.
    """
    if dd_info is None:
        dd_info = _spw_meta(vis)
    if ant_names is None:
        ant_names = _ant_names(vis)
    n_ant = len(ant_names)
    avail_gb = _get_available_memory_gb() or 2.0
    chunk_rows = min(500_000, max(10_000, int(avail_gb * mem_fraction * 1e9 / 24)))

    bl_u, bl_v, bl_ukl, bl_vkl = {}, {}, {}, {}
    for chunk in _iter_spw_chunks(vis, sorted(dd_info), chunk_rows,
                                  ['uvw', 'antenna1', 'antenna2', 'flag_row'],
                                  field_ids=field_ids):
        ant1 = chunk['antenna1'].astype(np.int32)
        ant2 = chunk['antenna2'].astype(np.int32)
        good = (ant1 != ant2) & (~chunk['flag_row'])
        if not good.any():
            continue
        g_u, g_v = chunk['uvw'][0, good], chunk['uvw'][1, good]
        g_a1, g_a2 = ant1[good], ant2[good]
        freqs = dd_info[chunk['dd_id']]['chan_freqs']
        n_c = max(1, len(freqs) // chan_bin)
        cf = freqs[:n_c * chan_bin].reshape(n_c, -1).mean(axis=1) \
            if len(freqs) >= chan_bin else np.array([freqs.mean()])
        wl = (_LIGHT_SPEED / cf).reshape(-1, 1)
        sort_ord, starts, cnts = _bl_sort_index(g_a1, g_a2, n_ant)
        for start, cnt in zip(starts, cnts):
            idx = sort_ord[start:start + cnt]
            key = (int(g_a1[idx[0]]), int(g_a2[idx[0]]))
            u_bl, v_bl = g_u[idx], g_v[idx]
            bl_u.setdefault(key, []).append(u_bl)
            bl_v.setdefault(key, []).append(v_bl)
            bl_ukl.setdefault(key, []).append(
                (np.hstack([u_bl, -u_bl])[None, :] / wl / 1e3).ravel())
            bl_vkl.setdefault(key, []).append(
                (np.hstack([v_bl, -v_bl])[None, :] / wl / 1e3).ravel())

    if not bl_u:
        log.warning("  No unflagged cross-correlation rows found in %s", vis)
        return
    keys = list(bl_u)
    colors, _ = _baseline_colormap(np.array([k[0] for k in keys]),
                                   np.array([k[1] for k in keys]),
                                   ant_names, cmap_name=cmap_name)
    n_bl = len(keys)

    def _plot(pf, xs, ys, xlabel, ylabel, sub, conj):
        fig, ax = plt.subplots(figsize=(8, 8))
        for key, color in colors.items():
            x, y = np.concatenate(xs[key]), np.concatenate(ys[key])
            if conj:
                x, y = np.hstack([x, -x]), np.hstack([y, -y])
            ax.plot(x, y, '.', markersize=0.1, color=color, alpha=0.4,
                    rasterized=True, linewidth=0)
        ax.set_aspect('equal', adjustable='datalim')
        _finish(fig, ax, pf, f"{title} | uv coverage ({sub}) - {n_bl} baselines",
                xlabel, ylabel, dpi)

    _plot(plotfile_wave, bl_ukl, bl_vkl, r"$u\;[\mathrm{k}\lambda]$",
          r"$v\;[\mathrm{k}\lambda]$", 'wavelength-scaled', False)
    if plotfile_metric:
        _plot(plotfile_metric, bl_u, bl_v, "u [m]", "v [m]", 'metric', True)


def plot_uv_coverage(vis_list, concat_ms=None, output_dir='.',
                     chunk_size=None, downsample_factor=None,
                     mem_fraction=0.5):
    """
    UV coverage comparison for a list of MSes (optionally a concatenated MS
    in the background).  Saves {output_dir}/{base}_uv_coverage_total.png and
    returns its path.
    """
    ct = _casatools()
    os.makedirs(output_dir, exist_ok=True)
    target_gb = mem_fraction * (_get_available_memory_gb() or 4.0)

    def _freqs(vis):
        msmd = ct.msmetadata()
        msmd.open(vis)
        try:
            return np.concatenate([msmd.chanfreqs(s) for s in range(msmd.nspw())])
        finally:
            msmd.done()

    def _nrows(vis):
        tb = ct.table()
        tb.open(vis)
        try:
            return tb.nrows()
        finally:
            tb.close()

    def _auto_params(vis):
        try:
            n_rows, n_freq = _nrows(vis), len(_freqs(vis))
        except RuntimeError as exc:
            log.warning("  uv coverage: cannot inspect %s: %s", vis, exc)
            return 4, 150
        max_chunks = max(1, int(target_gb * 1e9 / 2.0 / (n_rows * 32)))
        cs = max(1, int(np.ceil(n_freq / max_chunks)))
        raw_points = max(1, n_freq // cs) * 2 * n_rows
        return cs, max(1, int(np.ceil(raw_points / 2_000_000)))

    has_concat = bool(concat_ms and os.path.exists(concat_ms))
    all_vis = ([concat_ms] if has_concat else []) + list(vis_list)
    auto_cs, auto_ds = chunk_size, downsample_factor
    if auto_cs is None or auto_ds is None:
        worst_cs, worst_ds = 4, 150
        for v in all_vis:
            cs_v, ds_v = _auto_params(v)
            worst_cs, worst_ds = max(worst_cs, cs_v), max(worst_ds, ds_v)
        auto_cs = worst_cs if auto_cs is None else auto_cs
        auto_ds = worst_ds if auto_ds is None else auto_ds

    cmap = _get_cmap('tab10')
    colors = [cmap(i % 10) for i in range(len(vis_list))]
    fig, ax = plt.subplots(figsize=(8, 8))

    def _plot_one(vis, color, alpha=0.65):
        try:
            all_freqs = _freqs(vis)
            tb = ct.table()
            tb.open(vis)
            try:
                uvw = tb.getcol('UVW')
                ant1 = tb.getcol('ANTENNA1')
                ant2 = tb.getcol('ANTENNA2')
            finally:
                tb.close()
        except RuntimeError as exc:
            log.warning("  uv coverage: cannot read %s: %s", vis, exc)
            return
        cs = max(1, auto_cs)
        n_chunks = max(1, len(all_freqs) // cs)
        chunk_frq = all_freqs[:n_chunks * cs].reshape(n_chunks, cs).mean(axis=1)
        wavelens = (_LIGHT_SPEED / chunk_frq).reshape(-1, 1)
        cross = ant1 != ant2
        u = uvw[0, cross][::auto_ds]
        v = uvw[1, cross][::auto_ds]
        u_kl = (np.hstack([u, -u])[None, :] / wavelens / 1e3).ravel()
        v_kl = (np.hstack([v, -v])[None, :] / wavelens / 1e3).ravel()
        ax.plot(u_kl, v_kl, '.', markersize=0.2, color=color, alpha=alpha,
                rasterized=True, linewidth=0)

    handles = []
    if has_concat:
        log.info("  Plotting concat MS (background): %s", os.path.basename(concat_ms))
        _plot_one(concat_ms, color='silver', alpha=0.35)
        handles.append(mlines.Line2D([], [], color='silver', marker='.',
                                     linestyle='None', markersize=6,
                                     label='concat: ' + os.path.basename(concat_ms)))
    for vis, col in zip(vis_list, colors):
        log.info("  Plotting: %s", os.path.basename(vis))
        _plot_one(vis, col)
        handles.append(mlines.Line2D([], [], color=col, marker='.', linestyle='None',
                                     markersize=6, label=os.path.basename(vis)))
    ax.legend(handles=handles, fontsize=7, loc='upper right', framealpha=0.7)
    ax.set_xlabel(r"$u\;[\mathrm{k}\lambda]$")
    ax.set_ylabel(r"$v\;[\mathrm{k}\lambda]$")
    ax.set_aspect('equal', adjustable='datalim')
    ax.grid(True, lw=0.3, alpha=0.5)
    ax.set_title(r"Total $uv$ coverage")
    base = os.path.basename(concat_ms).replace('.ms', '') if concat_ms else 'uv_coverage'
    fig_path = os.path.join(output_dir, base + '_uv_coverage_total.png')
    try:
        fig.savefig(fig_path, dpi=150, bbox_inches='tight')
    finally:
        plt.close(fig)
    log.info("  Saved: %s", fig_path)
    return fig_path
