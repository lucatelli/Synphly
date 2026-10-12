# Changelog

All notable changes to Synphly are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

Changes to calibration behaviour are always listed explicitly. The default values of the config keys equal the
v0.5.1 active configuration, so a v0.5 config gives the same calibration under v0.6 unless an entry below says
otherwise.

## [0.6.0] - unreleased

A restructure of the code into a Python package. The calibration strategy is unchanged: every phase was checked
against a v0.5.1 baseline run on a spw subset of 21A-024 (K band) with `tools/compare_runs.py`.

### Added
- The `synphly` package with a command line:
  - `synphly run CFG [--from STEP] [--only STEP,...] [--force STEP,...|all] [--dry-run]`
  - `synphly info CFG`, which replaces `run_only_ms_info`
  - `synphly convert-config IN OUT [--minimal]`
  - `synphly steps`

  `python -m synphly` and the legacy `python main.py [config.ini]` also work.
- TOML configs with a validated schema (`synphly/config.py`): types, allowed values, unknown-key errors with
  suggestions, and clear messages for missing required keys. `configs/template.toml` documents every key with its
  default. One config per dataset is in `configs/datasets/` (the archive that used to be commented out in
  `config.ini`). Legacy INI files are still accepted.
- New explicit config keys:
  - `[fluxscale] fitorder` (`auto|0|1`), `fitorder_bw_threshold` (0.05) and `incremental` (false)
  - per-role extra quack `quack_extra_{flux_beg,phase_beg,phase_endb}`, plus `quack_interval_beg/endb`
  - `[sources] phasecal_for_target`; `transfer`/`reference` as field IDs (string or TOML array)
  - `[plotting] plot_backend` (`python|plotms|none`) and the per-kind plot switches
  - `[pipeline] reuse_tables` (`auto|always|never`)
- An ID-based field model (`synphly/fields.py`). There is one record per FIELD_ID, and each role is resolved to
  explicit IDs:
  - duplicate names are detected;
  - pointing-only, row-less and setup-only duplicate IDs are dropped, with the reasons logged;
  - targets are mapped to their phase calibrator by time adjacency, or by the config override.
- A run state in `<wd>/synphly_state.json`, saved after every step (status, timings, outputs, apply lists, refant,
  field model, flag versions). This allows resuming with `--from` / `--only`.
- A calibration-table registry. Each table gets a `<table>.synphly.json` sidecar with its priors, gainfields and
  an input hash (solve parameters, the priors' hashes, the MS path and a flag fingerprint sampled over every
  1000th row; the Synphly version is recorded but not hashed). Tables are reused only when the hash matches
  (`reuse_tables = "auto"`); use `--force STEP` after small flag edits the sampled fingerprint can miss. The apply
  lists have names: `bp_self`, `transfer`, `cal`, `science`.
- An end-of-run report, `run_report.json` and `run_report.md`: fluxes per field and spw, flag fractions per step,
  tables and their priors, warnings, timings and plot links.
- Logs in `<wd>/logs/`: the Synphly log, the CASA log (`casalog.setlogfile`) and the resolved config.
- Pure-python calibration-table plots (K delays, G, B vs channel/frequency, fluxscale, SNR histograms) and a single
  visibility-plotting implementation. plotms is optional.
- An always-on intent-flagging step, `intent_flagging` (`[flagging] do_intent_flagging`, default true), right before
  `initial_corrections`. It re-applies the pre-flagging intent selections (pointing if `do_flag_pointing_scans`,
  UNSPECIFIED, SYSTEM_CONFIGURATION) to the MS being calibrated and records the flag summaries before and after.
  It is idempotent with pre-flagging (checked read-only on the 21A-024 regression `.avg.ms`: no POINTING or
  UNSPECIFIED rows, SYSTEM_CONFIGURATION rows already 100% flagged), and protects an `.avg.ms` made from an MS
  that never had pre-flagging (03 issue 12). A selection without rows is logged at INFO.
- `pyproject.toml` (entry point `synphly`), `environment.yml` (CASA 6.7.3.21, Python 3.12), this changelog, and a
  generated config reference (`docs/config_reference.md`, from `docs/gen_config_reference.py`).
- Tests: unit tests for the config, the field model (mocked 12B-184 and 21A-024 metadata) and plotting, which need
  no CASA data, plus integration tests (`pytest -m integration`).
- Regression tools: `tools/regression_metrics.py` (read-only caltable, flux, flag and |CORRECTED| metrics) and
  `tools/compare_runs.py` (tolerance-based comparison of two runs).

### Changed
- `main.py` no longer `exec`s the three `data_calibration/` modules into one namespace. Every step is a function of
  an explicit `Context` (`synphly/context.py`), so the ~150 implicit globals are gone.
- **Fields are selected by ID** in every CASA call, instead of by name.
- **The science applycal uses the explicit phase-calibrator ID per target** as `gainfield` for the gain tables,
  instead of `'nearest'`. The results are identical when each target has one unambiguous phase calibrator, as in
  21A-024. They differ, and are now correct, when `'nearest'` picked a duplicate field without solutions.
- Calibration tables are no longer reused just because a file with the expected name exists (the v0.5 behaviour is
  available as `reuse_tables = "always"`).
- Flag versions keep their v0.5 names (the restore-on-rerun logic and existing working directories depend on
  them), but an existing version is deleted before it is saved again, so `*.old.<timestamp>` copies no longer pile
  up.
- The gaincal wrapper's dead `solnorm`/`normtype` arguments are removed. gaincal still runs with `solnorm=False`
  (the effective v0.5 behaviour), now passed explicitly; bandpass still uses `solnorm=True`. Because the parameter
  is part of the table input hash, gain tables of earlier v0.6 development runs are recomputed once under
  `reuse_tables = "auto"`.
- The early steps (`load_data`, `ms_info`, `select_refant`) fail loudly instead of logging `critical` and
  continuing.
- Nothing is written to the repository directory any more: logs, CASA logs and `TempLattice*` go to the working
  directory.
- The quack default stays at the v0.5 value (1 s at the beginning and end of every scan). The quack is now
  configurable, and it is reported in the run report.

### Fixed
- **Re-runs calibrated the flux scale against a 1 Jy flux calibrator** (inherited from v0.5). On a re-run in an
  existing working directory, `bandpass_cal` restores `before_bandpass_init_<i>` and runs `clearcal`, which resets
  MODEL_DATA to 1 Jy for every field, including the flux calibrator. Every bootstrapped flux of a re-run was
  wrong by the flux calibrator's flux density (2.45x too low on the 21A-024 K-band regression). Fresh runs were
  not affected. After that `clearcal`, the models of a fresh run are now re-established (the flux-calibrator
  setjy, and before pass 2 the pass-1 `setjy(standard='fluxscale')` models), so a re-run reproduces a fresh run.
- The calibration-table input hash contained the memory address of the CASA task object, so no solved table was
  ever reused across runs with `reuse_tables = "auto"`.
- A finished run could exit with status 1: with `DISPLAY` set, matplotlib picked the Qt backend when casatasks
  imported pyplot, and the X session manager's error handler called `exit(1)` at shutdown. The CLI now forces the
  `Agg` backend (an explicit `MPLBACKEND` is respected).
- `refant` given in the config raised a `NameError` and left `ref_antenna` unset.
- The science rflag used `rflag_timedevscale_science` as `freqdevscale`. This is a no-op with the defaults, where both
  are 4.0.
- `run_bandpass` swallowed exceptions. The wrappers now raise on a missing or all-flagged table and log the
  per-field solution counts.
- The bootstrap-flux plot assumed phase-calibrator IDs 1..n. It now iterates over the real field IDs.
- `incremental` is read from the config instead of being hard-coded.
- The undefined `check_bandpass_plots` call; the missing `exportfits` import in imaging.
- `check_longest_baseline` read the wrong MS (the global `vis_for_cal`).
- `import_data` raised `UnboundLocalError` when Hanning smoothing failed.
- AOFlagger via singularity: `singularity_bind` was never set.
- `before_applycal_science` was overwritten between the two passes. It is now `before_applycal_science_<i>`.
- An unknown flux-calibrator model raised `UnboundLocalError`. It now raises a clear `RuntimeError` naming the
  field and the known calibrators, before the MS is touched. The aliases `J0137+3309` (3C48), `J0521+1638`
  (3C138) and the B1950 names (`1328+307`, `0134+329`, `0538+498`, `0518+165`) are now recognised. A known
  source without a model for the band still gets the manual 1 Jy model, as in v0.5.
- The manual setjy fallback used the global `vis_for_cal`.
- About 39 bare `except:` clauses were replaced by specific exceptions with context. Only plotting is allowed to
  fail without stopping the run.
- Failures that v0.5 logged and then ignored now stop the step: the gain-curve and opacity tables (plotweather,
  gencal), `delmod`/`clearcal` before setjy, the rflag on calibrators/targets, the pre-flagging commands
  (autocorr, shadow, zero clip, quack, intents, saving the `pre_flagging` version) and `split`. A selection without
  rows (`MSSelectionNullSelection`) is still normal and only logged. AOFlagger failures (including a non-zero exit
  code) mark the optional `run_aoflagger` step as failed instead of done. Still tolerated, as in v0.5: a failed
  antenna-position gencal (now a warning in the run report), a bad manual flag file, and the listobs text file.

### Removed
- `data_calibration/` (replaced by `synphly/`; it remains in the git history and the `v0.5.1` tag), the empty
  `setup.py`, and stray `casa-*.log` / `TempLattice*` in the repository directory. The VLA/ALMA pipeline scripts
  `casapipe.py` / `almapipe.py` became the optional functions `synphly.external.vla_pipeline.run_vla_pipeline` /
  `run_alma_pipeline`. `config-stable.ini` moved to `configs/legacy/`, `adaptation_py_plot_vis.md` to
  `docs/notes/`, and the `Sy_plot_vis_test/` output directory was deleted.
- Dead code: the duplicate `get_fields`, `__split`, `get_list`, `flux_3C286`, `ctn`, and the legacy plotms
  `make_plots_stages`. plotms plotting is still available through `plot_backend = "plotms"`.
- The archive of commented-out dataset configs in `config.ini`, which moved to `configs/datasets/`.

## [0.5.1] - 2026-10-12

v0.5 working state plus the fixes of the 2026-10-11 debugging session on 12B-184 (Q band). See
`todos_and_improvements/01_changelog_session_2026-10-11.md` for the evidence behind each fix.

### Fixed
- **Only the delay and the bandpass are transferred to other fields.** `bandpass_cal` used to return init + K +
  bp_p (18 s) + bp_ap (36 s) + B, and that list was used as the prior of every gain solve and in every applycal.
  The time-dependent bandpass-calibrator gains, linearly interpolated across hours with `refantmode='strict'`,
  flagged every secondary when one refant solution was flagged, and fluxscale then failed. The full list
  (`bp_self`) is now applied only to the bandpass calibrator. The transfer list is init + K + B.
- **Calibrator models are reset to 1 Jy before each gain pass** (`reset_transfer_models`). Pass 2 used to solve
  against the bootstrapped pass-1 models, because `delmod(scr=False)` does not clear MODEL_DATA, and reported ~1 Jy for
  every secondary. The science calibration itself was not affected.
- **fluxscale `fitorder` follows the fractional bandwidth.** It is 1 if `(fmax - fmin) / mean(f) >= 0.05`, and 0
  otherwise. Narrow-band setups (for example 60 MHz at 41 GHz) gave spectral indices that setjy rejects.
- A flat spectral index (0.0) is added to the fluxdict when `fitorder=0`. CASA's `setjy(standard='fluxscale')`
  always reads `spidx[1]`.
- The fluxscale outputs are removed and recomputed on every run. CASA refuses to overwrite them, which blocked
  every re-run.
- fluxscale failures raise a `RuntimeError` that names the reference/transfer fields and the CASA error, instead of
  ending in `UnboundLocalError: flux_bp`.
- `run_gaincal` passes `gainfield` through, raises if gaincal writes no table, and re-raises instead of returning
  `None`.

### Added
- `[flagging] do_flag_pointing_scans` (default true) restores the flagging of `*POINTING*` scans in pre-flagging.
  Pointing scans can share a calibrator's name and otherwise enter the gain calibration.

### Changed (v0.5 working-tree changes included in this release)
- The `rq` gencal is disabled. The `J1331+3030` alias was added for the 3C286 model. `run_bandpass` uses
  `fillgaps=bp_fillgaps`. `bandpass_cal` takes `calwt` and restores flags on the MS being calibrated. `minsnr_K` is
  used for the delay solve. The central channel range is now 25-75% (was 30-70%).
- The shadow tolerance is 10 m. The quack is reduced to 1 s (scan start and end, all fields), and the extra quack for the
  flux and phase calibrators is removed.
- New plotting modules: `Sy_plot_vis.py`, `plot_vis_python.py` and `task_plotants.py`.

## Older versions

See the git history (`git log`) for v0.5 and earlier.

[0.6.0]: https://github.com/JBCA-Interferometry/Synphly/compare/v0.5.1...v0.6-restructure
[0.5.1]: https://github.com/JBCA-Interferometry/Synphly/tree/v0.5.1
