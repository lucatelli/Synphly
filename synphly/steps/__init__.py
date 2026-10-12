"""
Pipeline steps. Every step takes the run context ``ctx`` (``ctx.cfg`` is the Config) as first argument.

Modules: import_data, ms_info, preflag, average, initial_corrections, setjy_fluxcal, refant, bandpass,
gains, applycal, autoflag, statwt, split, imaging. ``_plots`` holds the optional plotting calls.
"""
