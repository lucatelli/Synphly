"""
Quick-look imaging of the split fields with tclean (ported from v0.5 ``helper_functions``:
run_imaging_tclean, check_longest_baseline, check_band, eimshow).
"""
from __future__ import annotations

import logging
import os

import numpy as np

from ..casa import exportfits, open_ms, open_msmd, tclean

log = logging.getLogger(__name__)


def check_band(vis):
    """Return (band_name, mean_freq, max_freq, min_freq) with frequencies in GHz."""
    band_name = None
    freq_ranges = {
        (1, 2): "L",
        (2, 4): "S",
        (4, 8): "C",
        (8, 12): "X",
        (12, 18): "Ku",
        (18, 26.5): "K",
        (26.5, 40): "Ka",
        (40, 50): "Q",
    }
    with open_msmd(vis) as msmd:
        bandwidth = msmd.bandwidths()
        nspw = len(bandwidth)
        chan_freqs_all = np.empty(nspw, dtype=object)
        spws_freq = np.zeros(nspw)
        for nch in range(nspw):
            chan_freqs_all[nch] = msmd.chanfreqs(nch)
            spws_freq[nch] = np.nanmean(chan_freqs_all[nch])

    mean_freq = np.nanmean(spws_freq) * 1e-9
    max_freq = np.nanmax(spws_freq) * 1e-9
    min_freq = np.nanmin(spws_freq) * 1e-9
    for range_, band in freq_ranges.items():
        if mean_freq >= range_[0] and mean_freq <= range_[1]:
            band_name = band
    return band_name, mean_freq, max_freq, min_freq


def check_longest_baseline(vis):
    """Longest baseline of ``vis`` in wavelengths at its highest spw frequency.

    (v0.5 read the uvw from the global vis_for_cal instead of ``vis``; both the uvw and the frequencies now come
    from ``vis``.)"""
    with open_ms(vis) as ms:
        ms.selectinit(datadescid=0)
        uvw = ms.getdata('uvw')['uvw']
    uvdist_meters = np.sqrt(uvw[0] ** 2 + uvw[1] ** 2)
    longest_baseline_meters = np.nanmax(uvdist_meters)
    band_name, mean_freq, max_freq, min_freq = check_band(vis)
    frequency_hz = max_freq * 1e9
    speed_of_light = 3e8  # m/s
    wavelength_meters = speed_of_light / frequency_hz
    longest_baseline_lambda = longest_baseline_meters / wavelength_meters
    return longest_baseline_lambda


def run_imaging_tclean(ctx, fields_to_image):
    timebin_longer = ctx.cfg.calibrate.timebin_longer
    parallel = ctx.cfg.imaging.parallel
    fields_dir = ctx.paths.fields

    calcpsf = True
    spw = ''
    outlierfile = ''
    specmode = 'mfs'
    deconvolver = 'mtmfs'
    ext = ''
    gridder = 'standard'
    wprojplanes = 1024
    scales = [0, 5, 20]
    interactive = False
    datacolumn = 'data'
    usemask = 'auto-multithresh'
    niter = 1500
    mask = ''
    cycleniter = 200
    smallscalebias = 0.75
    robust = 0.5
    weighting = 'briggs'
    gain = 0.1
    pblimit = -0.1
    nterms = 2
    sidelobethreshold = 3.0
    noisethreshold = 6.0
    lownoisethreshold = 4.0
    minbeamfrac = 0.2
    growiterations = 75
    negativethreshold = 0.0
    fastnoise = False
    phasecenter = ''
    psfphasecenter = ''
    usepointing = True
    uvtaper = ''
    uvrange = ''
    imsize = 3072
    if deconvolver == 'mtmfs':
        ext = ext + '.tt0'

    for field_to_image in fields_to_image:
        formated_field = field_to_image.replace(' ', '').replace('/', '')
        # v0.5 built this path as f"{working_directory}fields/..." (missing '/').
        g_name = f"{fields_dir}/{formated_field}/{formated_field}.calibrated.avg{timebin_longer}"
        g_vis = g_name + '.ms'
        log.info(f" ++==>> Checking splited visibility: {g_vis}")

        if os.path.exists(f'{g_vis}'):
            imagename = (f"{fields_dir}/{formated_field}/"
                         f"phasecal_image_{formated_field}.calibrated.avg{timebin_longer}")
            longest_baseline_lambda = check_longest_baseline(g_vis)
            cell_float = (180.0 * 3600 / (np.pi * 5)) * (1.0 / longest_baseline_lambda)
            cell = f'{cell_float:.2f}arcsec'
            log.info(f" ++==>> Imaging field {formated_field}")
            log.info(f"      > Image name prefix: {imagename}")
            log.info(f"      > Cell size: {cell}")

            if not os.path.exists(imagename + '.image' + ext):
                tclean(vis=g_vis,
                       imagename=imagename,
                       spw=spw, field=field_to_image, outlierfile=outlierfile, gain=gain,
                       specmode=specmode, deconvolver=deconvolver, gridder=gridder,
                       wprojplanes=wprojplanes,
                       scales=scales, smallscalebias=smallscalebias,
                       imsize=imsize, cell=cell,
                       weighting=weighting, robust=robust,
                       niter=niter, interactive=interactive,
                       pblimit=pblimit, nterms=nterms,
                       usemask=usemask,
                       mask=mask, pbcor=True,
                       sidelobethreshold=sidelobethreshold,
                       noisethreshold=noisethreshold,
                       lownoisethreshold=lownoisethreshold,
                       minbeamfrac=minbeamfrac, fastnoise=fastnoise,
                       usepointing=usepointing, psfphasecenter=psfphasecenter,
                       phasecenter=phasecenter,
                       datacolumn=datacolumn, cycleniter=cycleniter, calcpsf=calcpsf,
                       growiterations=growiterations,
                       negativethreshold=negativethreshold, parallel=parallel,
                       verbose=True, uvtaper=uvtaper, uvrange=uvrange,
                       savemodel='none')
                exportfits(imagename=imagename + '.image' + ext,
                           fitsimage=imagename + '.image' + ext + '.fits',
                           velocity=True)
            else:
                log.warning(f"Image {imagename + '.image' + ext} exists. Will not image again")
            if ctx.cfg.plotting.plot_backend != 'none':
                try:
                    eimshow(imagename + '.image' + ext + '.fits',
                            num_contours=6,
                            mad_factor=6)
                except Exception as e:
                    log.warning(f" --==>> Could not plot image {imagename + '.image' + ext + '.fits'}: {e}")
                    log.warning(" --==>> You may need to install astropy inside CASA.")


def eimshow(imagename, num_contours=5, mad_factor=6, contour_max_factor=0.95,
            cmap='magma_r', cutout_size=256):
    """
    enhanced-imshow: plot a FITS image with geometric contours, saved as ``<image>_map.jpg``.

    Parameters:
    - imagename: Path to the FITS file containing the image data.
    - num_contours: Number of contour levels.
    - mad_factor: Factor to multiply the MAD value for the minimum contour level.
    - contour_max_factor: Maximum fraction of the peak value for the highest contour.
    - cmap: Colormap for the image display.
    """
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
    from astropy.io import fits
    from astropy.stats import mad_std
    from astropy.visualization import simple_norm
    from mpl_toolkits.axes_grid1 import make_axes_locatable

    class CustomFormatter(mticker.ScalarFormatter):
        def __init__(self, factor=1, **kwargs):
            self.factor = factor
            mticker.ScalarFormatter.__init__(self, **kwargs)

        def __call__(self, x, pos=None):
            x = x * self.factor
            if x == 0:
                return "0.00"
            return "{:.2f}".format(x)

    with fits.open(imagename) as hdul:
        image_data = hdul[0].data
    if len(image_data.shape) == 4:
        image_data = image_data[0][0]
    peak_y, peak_x = np.unravel_index(np.argmax(image_data), image_data.shape)

    # robust standard deviation using MAD; minimum contour level proportional to it
    mad_std_value = mad_std(image_data)
    min_contour_level = mad_factor * mad_std_value
    max_value = np.max(image_data)

    # If a cutout size is specified, extract the region centered on the peak
    if cutout_size is not None:
        half_size = cutout_size // 2
        x_min = max(peak_x - half_size, 0)
        x_max = min(peak_x + half_size, image_data.shape[1])
        y_min = max(peak_y - half_size, 0)
        y_max = min(peak_y + half_size, image_data.shape[0])
        image_data = image_data[y_min:y_max, x_min:x_max]

    fig, ax = plt.subplots(figsize=(8, 8))

    norm0 = simple_norm(image_data, stretch='linear', max_percent=99.0)
    img = ax.imshow(image_data, origin='lower', cmap='gray', norm=norm0, alpha=0.5)
    try:
        norm = simple_norm(image_data, stretch='sqrt', asinh_a=0.02, vmin=min_contour_level,
                           vmax=max_value)
    except Exception:
        # older astropy versions use min_cut/max_cut
        try:
            norm = simple_norm(image_data, stretch='sqrt', asinh_a=0.02, min_cut=min_contour_level,
                               max_cut=max_value)
        except Exception:
            norm = simple_norm(image_data, stretch='sqrt', asinh_a=0.02)

    img = ax.imshow(image_data, origin='lower', cmap=cmap, norm=norm)

    try:
        levels_g = np.geomspace(2.0 * np.nanmax(image_data), 5 * mad_std_value, num_contours)
        levels_low = np.asarray([4 * mad_std_value, 3 * mad_std_value])
        levels_neg = np.asarray([-3]) * mad_std_value

        contour_palette_ = ['#000000', '#444444', '#666666', '#EEEEEE',
                            '#EEEEEE', '#FFFFFF']
        if '_r' in cmap:
            contour_palette = contour_palette_
        else:
            contour_palette = contour_palette_[::-1]

        ax.contour(image_data, levels=levels_g[::-1], colors=contour_palette, linewidths=1.2)
        ax.contour(image_data, levels=levels_low[::-1], colors='brown', linewidths=1.0)
        ax.contour(image_data, levels=levels_neg, colors='k',
                   linewidths=1.0, alpha=1.0)
    except Exception as e:
        log.warning(f" --==>> Could not plot contours for {imagename}: {e}")

    divider = make_axes_locatable(ax)
    cax = divider.append_axes("right", size="5%", pad=0.05)
    cbar = fig.colorbar(img, cax=cax)
    cbar.set_label('Intensity [Jy/beam]')
    cbar.formatter = CustomFormatter(factor=1000, useMathText=True)
    cbar.update_ticks()
    ax.set_xlabel(r'Pixel $x$')
    ax.set_ylabel(r'Pixel $y$')
    ax.grid(False)
    plt.savefig(imagename.replace('.fits', '') + '_map.jpg', dpi=600,
                bbox_inches='tight')
    plt.clf()
    plt.close()
