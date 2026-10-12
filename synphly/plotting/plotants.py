"""
synphly.plotting.plotants
=========================
Antenna-position plot (cleaned port of the v0.5.1 data_calibration/task_plotants.py,
itself derived from the CASA plotants task): pyplot instead of pylab, Agg
only (no GUI), explicit figure per call, tools always closed, logging
instead of casalog.

plotants(vis, figfile, antindex=False, logpos=False, exclude=None,
         checkbaselines=False, title='')
"""

import os
import logging

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

log = logging.getLogger(__name__)


def plotants(vis, figfile, antindex=False, logpos=False, exclude=None,
             checkbaselines=False, title=''):
    """
    Plot antenna positions in the local frame (X east, Y north) and save to
    figfile.  logpos=True gives the logarithmic polar plot.  exclude: antenna
    selection string/list to drop.  Returns figfile.
    """
    import casatools
    vis = vis.rstrip('/')
    exclude_ids = []
    if exclude:
        myms = casatools.ms()
        try:
            exclude_ids = myms.msseltoindex(vis, baseline=exclude)['antenna1'].tolist()
        except RuntimeError as rterr:
            errmsg = str(rterr).replace('specificion', 'specification')
            raise RuntimeError("Exclude selection error: "
                               + errmsg.replace('Antenna Expression: ', '')) from rterr
        finally:
            myms.done()

    telescope, names, ids, xpos, ypos, stations = get_antenna_info(
        vis, logpos, exclude_ids, checkbaselines)
    if not names:
        raise ValueError("No antennas selected.  Exiting plotants.")

    if not title:
        msname = os.path.basename(vis)
        title = "Antenna Positions for " + ('\n' if len(msname) > 55 else '') + msname

    fig = plt.figure()
    try:
        if logpos:
            _plot_antennas_log(fig, telescope, names, ids, xpos, ypos, antindex, stations)
        else:
            _plot_antennas(fig, telescope, names, ids, xpos, ypos, antindex, stations)
        plt.title(title, {'fontsize': 12})
        if figfile:
            os.makedirs(os.path.dirname(os.path.abspath(figfile)), exist_ok=True)
            fig.savefig(figfile)
            log.info("  Saved: %s", figfile)
    finally:
        plt.close(fig)
    return figfile


def get_observatory_info(msname):
    import casatools
    md = casatools.msmetadata()
    md.open(msname)
    try:
        return md.observatorynames()[0], md.observatoryposition()
    finally:
        md.close()


def get_antenna_info(msname, logpos, exclude, checkbaselines):
    """(telescope, names, ids, x, y, stations) in local E/N metres (deg for VLBA)."""
    import casatools
    tb = casatools.table()
    me = casatools.measures()
    qa = casatools.quanta()
    try:
        telescope, array_pos = get_observatory_info(msname)
        array_wgs84 = me.measure(array_pos, 'WGS84')
        array_lon, array_lat = [array_wgs84[i]['value'] for i in ['m0', 'm1']]

        tb.open(msname + '/ANTENNA')
        try:
            ant_names = np.array(tb.getcol("NAME")).tolist()
            station_names = np.array(tb.getcol("STATION")).tolist()
            positions = tb.getcol('POSITION').transpose()
        finally:
            tb.close()
        if telescope == 'VLBA':
            ant_names = ['@'.join(a) for a in zip(ant_names, station_names)]
        ant_positions = [me.position('ITRF', qa.quantity(x, 'm'), qa.quantity(y, 'm'),
                                     qa.quantity(z, 'm')) for (x, y, z) in positions]

        if checkbaselines:
            tb.open(msname)
            try:
                used = sorted(set(np.append(tb.getcol('ANTENNA1'), tb.getcol('ANTENNA2'))))
            finally:
                tb.close()
            ant_ids_used = [int(a) for a in used]
        else:
            ant_ids_used = list(range(len(ant_names)))

        for ant_id in exclude:
            if ant_id in ant_ids_used:
                ant_ids_used.remove(ant_id)
                log.info("Exclude antenna %s (id %d)", ant_names[ant_id], ant_id)
            else:
                log.warning("Cannot exclude antenna id %s: not in main table", ant_id)

        ant_names = [ant_names[i] for i in ant_ids_used]
        ant_positions = [ant_positions[i] for i in ant_ids_used]
        station_names = [station_names[i] for i in ant_ids_used]
        log.info("Number of points being plotted: %d", len(ant_ids_used))
        if not ant_ids_used:
            return telescope, ant_names, [], [], [], []

        wgs = [me.measure(pos, 'WGS84') for pos in ant_positions]
        if telescope == 'VLBA' and not logpos:
            xs = [qa.convert(p['m0'], 'deg')['value'] for p in wgs]
            ys = [qa.convert(p['m1'], 'deg')['value'] for p in wgs]
        else:
            lons = np.array([p['m0']['value'] for p in wgs])
            lats = np.array([p['m1']['value'] for p in wgs])
            rad_e = 6370000.
            xs = (lons - array_lon) * rad_e * np.cos(array_lat)
            ys = (lats - array_lat) * rad_e
        return telescope, ant_names, ant_ids_used, np.asarray(xs), np.asarray(ys), station_names
    finally:
        me.done()
        qa.done()


def _label_props(telescope, station, logpos=False):
    """(valign, halign, rotation) for VLA station labels (CAS-7120)."""
    v_align, h_align, rot = 'center', 'left', 0
    if station and "VLA" in telescope:
        if 'VLA:' in station:
            station = station[4:]
        if station and station[0] == '_':
            station = station[1:]
        if station in ['W01', 'E01', 'W1', 'E1']:
            v_align, h_align = 'top', 'center'
        else:
            v_align = 'bottom'
            if 'W' in station or 'MAS' in station:
                h_align, rot = 'right', -35
            elif 'E' in station or ('N' in station and not logpos):
                rot = 35
    return v_align, h_align, rot


def _plot_antennas_log(fig, telescope, names, ids, xpos, ypos, antindex, stations):
    ax = fig.add_subplot(1, 1, 1, projection='polar')
    ax.set_theta_zero_location('N')
    ax.set_theta_direction(-1)
    ax.set_xticklabels([])
    ax.set_yticklabels([])
    ax.grid(False)

    if 'VLA' in telescope:
        xcenter, ycenter = -32, 0          # CAS-7479
        rmin_min, rmin_max = 12.5, 350
    else:
        xcenter, ycenter = np.median(xpos), np.median(ypos)
        rmin_min, rmin_max = 3, 350
    r = ((xpos - xcenter) ** 2 + (ypos - ycenter) ** 2) ** 0.5
    rmin = min(rmin_max, max(rmin_min, 0.8 * np.min(r[r > 0])))
    r[r <= rmin] = rmin
    rmin = np.log(rmin)
    rmax = np.log(1.5 * np.max(r))
    theta = np.arctan2(xpos - xcenter, ypos - ycenter)

    angles = np.arange(0, 2.01 * np.pi, 0.01 * np.pi)
    show_circle = True
    circles = [1e5, 3e5, 1e6, 3e6, 1e7] if telescope == "VLBA" else \
        [30, 100, 300, 1000, 3000, 10000]
    for cr in circles:
        if cr > np.min(r) and show_circle:
            ax.plot(angles, np.ones(len(angles)) * np.log(cr), 'k:')
            inc = 0.1 * (1e8 if telescope == "VLBA" else 10000) / cr
            if cr > 100:
                for angle in np.arange(inc / 2., 2 * np.pi + 0.05, inc):
                    ax.plot([angle, angle], [np.log(0.95 * cr), np.log(1.05 * cr)], 'k-')
            lab_ang = -20.0 * np.pi / 180.
            if cr >= 1000:
                if np.log(cr) < rmax:
                    for a in (lab_ang, lab_ang + np.pi):
                        ax.text(a, np.log(cr), '%d km' % (cr / 1000), size=8, va='top')
            else:
                for a in (lab_ang, lab_ang + np.pi):
                    ax.text(a, np.log(cr), '%dm' % cr, size=8, va='top')
        if np.log(cr) > rmax:
            show_circle = False

    for i, (name, station) in enumerate(zip(names, stations)):
        if station and 'OUT' not in station:
            ax.plot(theta[i], np.log(r[i]), 'ko', ms=5, mfc='r')
            if antindex:
                name += ' (' + str(ids[i]) + ')'
            valign, halign, angle = _label_props(telescope, station, logpos=True)
            yoffset = 0.1 if halign == 'center' else 0
            ax.text(theta[i], np.log(r[i]) + yoffset, ' ' + name, size=8, va=valign,
                    ha=halign, rotation=angle, weight='semibold')
    ax.set_rmax(rmax)
    ax.set_rmin(rmin)
    fig.subplots_adjust(top=0.88)


def _plot_antennas(fig, telescope, names, ids, xpos, ypos, antindex, stations):
    ax = fig.add_subplot(111)
    xpos, ypos = np.array(xpos, dtype=float), np.array(ypos, dtype=float)
    if telescope == 'VLBA':
        labelx, labely = 'Longitude (deg)', 'Latitude (deg)'
    else:
        units = ' (m)'
        if np.median(xpos) > 1e6 or np.median(ypos) > 1e6:
            xpos /= 1e3
            ypos /= 1e3
            units = ' (km)'
        labelx, labely = 'X' + units, 'Y' + units
    for i, (x, y, name, station) in enumerate(zip(xpos, ypos, names, stations)):
        if station and 'OUT' not in station:
            ax.plot(x, y, 'ro')
            if antindex:
                name += ' (' + str(ids[i]) + ')'
            valign, halign, angle = _label_props(telescope, station)
            if halign == 'center':
                y -= 10
            ax.text(x, y, ' ' + name, size=8, va=valign, ha=halign, rotation=angle,
                    weight='semibold')
    ax.set_xlabel(labelx)
    ax.set_ylabel(labely)
    ax.margins(0.1, 0.1)
