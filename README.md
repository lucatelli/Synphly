           '                                                
           '                                 .;okOk;        
                                         .;xKWMMMMMMc.      
                .                     .:ONMMMMMMMMMM0:.     
                                    'xNMMMMMMMMMMMMWOO;     
                                 .cKMMMMMMWNNXWMMMMK0Xo.    
                               .dNMMNXXOdx,;..'lXMKWNOk,    
                           ..'l0K0x::.. ,.. . .. 00NWWk;    
                    ,cl,;;';0WXx;.. . .;.  . . .kNX0N0Ol    
                   lKMXxod0Koc::;c;',.;.  . . lN0NWKWKx,    
                  'o :x;k0lo,. . ...clc:.. ..oNNONXKdc,.    
                  k  :xKk.  .,::,..,. ..::ccXWKMWKNKo;;.    
                 d. ,ol.'d    .;00kl,. . lkXNKKkXKNok::     
                :c':.o, .,c  ,oxxc':ldodWNNNXWKMK0;.k''     
               .0c...k . .l,.;x:';:ccO0NNKKNXxKNKllOl'      
               O' . 'd. . :c'. ':::kWMMXNXNXNMK0c.;l'.      
             .k..  .:c ,', . . ..kNOKNNNXx0NNKk .o:'.       
           .dO,. . .k;;.. . . ;OMMMKMXXNN0XNd.X0xc'.        
          ,KXl..,,,,x. . . 'dNKNNNWKNNNXNKXc  0XWX,.        
         lWMMMNNxo;;x . .c0NNMKMMNXOXNWN0;l0c00NK::         
       .xMMMMMMMMMMMWKdo0XWWWXO0XNNMN0o;X..XONWN;;          
      .kMMMMMMMMMMX0KKNMN0NNNNN0NXOddl,.kxk00dxKOx.         
      '0MMMMWNKKK0XX0KKNN0NNNXXx;.;dd,;coKMMMxOMMM0.        
       .,cccx0x0WNKOKXX00xo;co,;c:'..  ;XMMMMxOMMMMX,       
           ...,;'',loc;;.c,'...       lWMMMMMxOMMMMMNc      
                  .                 .xMMMMMMMxOMMMMMMMd.    
                                 .',lddddddddoxddxxxxxxl;,, 
                                           ..',;clodxkO0.   
                             ..',:codkO0XNWMMMMMMMMMMMMM'   
                    .';ldOKWMMMMMMMMMMMMMMMMMMMMMMMMMMMW0do,

# Synphly
`Synphly` is a simple CASA pipeline for standard calibration, plotting and basic imaging of radio
interferometric (VLA/EVLA) data. It was written to calibrate early EVLA observations, where the
official VLA pipeline fails. In principle, `Synphly` can be used for any VLA observation.

WARNING: this code and its documentation are under development. Calibration may or may not work
for your data. It has been tested on VLA/EVLA visibilities ONLY. We use it to calibrate
observations in all VLA bands, and it performs well (bootstrapped fluxes within ~5% of the VLA
pipeline on the test datasets).

This README describes **v0.6** (see [`CHANGELOG.md`](CHANGELOG.md)). v0.6 restructures the code into a
Python package. The calibration strategy is the same as v0.5.1.

Contents: [Installation](#installation) · [Quick start](#quick-start) · [Command line](#command-line) ·
[Configuration](#configuration) · [Early EVLA observations](#early-evla-observations) ·
[Fields](#fields-the-id-based-field-model) · [Calibration strategy](#calibration-strategy) ·
[Outputs](#outputs) · [Resuming and table reuse](#resuming-and-table-reuse) · [Plotting](#plotting) ·
[Imaging](#imaging-experimental) · [Development](#development)

---

## Installation

Synphly runs on **modular CASA** (`casatools` + `casatasks` from pip) in a normal Python environment. The
monolithic `casa` application and `casa -c` are not needed. It is tested with CASA **6.7.3.21** and Python **3.12**.

```bash
git clone https://github.com/JBCA-Interferometry/Synphly.git && cd Synphly
conda env create -f environment.yml      # creates the env "synphly" and runs `pip install -e .`
conda activate synphly
synphly --version
```

If you prefer to install into an existing environment (Python 3.10 or later; 3.12 is recommended):

```bash
pip install casatools==6.7.3.21 casatasks==6.7.3.21 casadata
pip install -e .              # installs the `synphly` command
pip install -e ".[plotms]"    # optional: casaplotms, only for plot_backend = "plotms"
pip install -e ".[test]"      # optional: pytest
```

Notes:
- CASA needs its runtime data (`casadata`, or a `~/.casa/config.py` that points at a data directory). On the first
  import, `casaconfig` may try to download or update it. Check this before a long run.
- The default plots use matplotlib only. `casaplotms` is optional.
- AOFlagger is optional (`[flagging] use_aoflagger`). It runs natively or through a singularity container.

## Quick start: a new dataset

You need one config file per observation. Nothing else has to be edited.

**Which config file is which**

| File | What it is | Do you edit it? |
|---|---|---|
| `configs/datasets/<exp>.toml` | **Your dataset's config**, one per observation. Made by `synphly init`. It holds only what is specific to the dataset (paths, sources, any non-default option). | Yes |
| `configs/template.toml` | Reference: every key, its default and an explanation (also in [`docs/config_reference.md`](docs/config_reference.md)). Copy a key from here into your dataset file to change it. | No |
| `config.ini` | The old v0.5 config of the last dataset. It still works (`synphly run config.ini`), but you don't need it. | No |
| `configs/legacy/` | Older v0.5 INI files, kept for reference. | No |

**The workflow.** This is the v0.5 "import first, read the listobs, then write the config" workflow, as commands.

1. **Make a starter config.** It needs the experiment name (the MS name without `.ms`), the working directory
   and the SDM path:
   ```bash
   synphly init 21A-024.sb39746934.eb40140855.59469.05998622686_K \
       --wd /data/21A-024/ --asdm /data/21A-024/21A-024.sb39746934.eb40140855.59469.05998622686_K
   # -> configs/datasets/21A-024.sb39746934.eb40140855.59469.05998622686_K.toml
   ```
   If you already have the MS, put it in the working directory as `<wd>/<exp>.ms` and leave out `--asdm`. Add
   `--hanning` for Hanning smoothing, and `--band K` to fix the band (it is guessed from the frequency otherwise).
2. **Import and inspect.** This runs importasdm (if the MS does not exist yet) and the optional Hanning
   smoothing, and writes the listobs. It then prints the field table (IDs, names, intents, scans, rows),
   duplicated names, IDs that will be left out (pointing and setup scans), the band and fitorder, and a
   **ready-to-paste `[sources]` block** with the roles the run will use. Nothing is flagged or calibrated.
   ```bash
   synphly prepare configs/datasets/<exp>.toml
   ```
   The same text is saved in `<wd>/fields_report.txt`, and the listobs is `<wd>/<exp>_listobs.txt`.
   For an MS that already exists, `synphly info configs/datasets/<exp>.toml` prints the same thing and writes
   nothing at all.
3. **Edit `[sources]`** in your config only if needed. For recent VLA data with correct intents, the empty
   defaults are fine (the roles come from the intents). For early EVLA data, set the roles by name or field ID
   (see [Early EVLA observations](#early-evla-observations)). Run `synphly prepare` / `synphly info` again to see
   the effect.
4. **Check, then run.**
   ```bash
   synphly run configs/datasets/<exp>.toml --dry-run    # steps that will run + field roles; read-only
   synphly run configs/datasets/<exp>.toml              # expect several hours for a full dataset
   ```
5. **Look at `<wd>/run_report.md`**: fluxes, flag fractions, warnings and timings, with links to logs and plots.

Without `pip install -e .`, use `python -m synphly ...` from the repository directory. A complete worked
example, from environment to report, is in [`docs/guide_full_run_21A-024.md`](docs/guide_full_run_21A-024.md).

**Old (v0.5) configs.** INI files are still accepted everywhere a config is expected:
```bash
python main.py config.ini                              # legacy entry point, same as `synphly run config.ini`
synphly convert-config config.ini configs/datasets/<exp>.toml            # write all keys
synphly convert-config config.ini configs/datasets/<exp>.toml --minimal  # only keys that differ from defaults
```
Missing keys in an old INI file take the v0.5 defaults. `configs/datasets/` already has the converted configs of
the datasets that used to be commented out in `config.ini`.

**Multiple receivers.** Observations with several receivers (for example L, S and C band in one MS) are not
supported. Split the data per band first, using the spectral window range of each band.

## Command line

```
synphly init NAME --wd DIR [--asdm PATH] [--band B] [--hanning] [-o OUT] [--force]
synphly prepare CFG
synphly info CFG
synphly run CFG [--from STEP] [--only STEP[,STEP...]] [--force STEP[,STEP...]|all] [--dry-run]
synphly convert-config IN OUT [--minimal]
synphly steps
synphly --version
```
`python -m synphly ...` is equivalent to `synphly ...`. `CFG` is a TOML file or a legacy INI file.

| Command / option | Meaning |
|---|---|
| `init NAME --wd DIR` | Write a starter config for a new dataset (default `configs/datasets/NAME.toml`): the paths, an empty `[sources]` section with explanations, and `band`. |
| `prepare CFG` | Import the SDM if the MS does not exist (plus Hanning if enabled), write the listobs, and print the field table, duplicates, dropped IDs, band and a ready-to-paste `[sources]` block (also saved as `<wd>/fields_report.txt`). No flagging or calibration. Replaces `load_data` + `run_only_ms_info = true`. |
| `info CFG` | The same report as `prepare`, for an MS that already exists. Read-only: imports and writes nothing. |
| `run CFG` | Run every enabled step. Calibration tables whose recorded inputs did not change are reused (see [Resuming](#resuming-and-table-reuse)). |
| `--from STEP` | Start at `STEP`. The state of the earlier steps (field model, refant, apply lists) is loaded from `synphly_state.json`, so they must have completed in an earlier run. |
| `--only STEP[,STEP]` | Run only these steps, with the earlier state loaded from `synphly_state.json`. |
| `--force STEP[,STEP]` or `--force all` | Recompute these steps even if their recorded inputs match (their tables are rebuilt). |
| `--dry-run` | Resolve the config, the fields and the step plan, print what would run and what would be reused, and stop. Nothing is written to the MS. |
| `convert-config IN OUT` | Convert a legacy INI config to TOML. `--minimal` writes only the keys that differ from the defaults. |
| `steps` | List the step names in execution order. |

The `do_*` switches in the config still turn optional steps on and off. The CLI options choose *where* to
start and *what* to recompute.

### Steps

In execution order. Names are used by `--from`, `--only`, `--force` and in `synphly_state.json`.

| Step | Switch | What it does |
|---|---|---|
| `set_working_dir` | always | Create `calibration/`, `plots/`, `flags/`, `fields/`, `logs/` in the working directory. |
| `load_data` | `globals.load_data` | `importasdm` if the MS does not exist; optional Hanning smoothing (`do_hanning`); write the listobs file. |
| `ms_info` | `globals.ms_info` | Build the field model and resolve the field roles (see [Fields](#fields-the-id-based-field-model)). |
| `pre_flagging` | `flagging.do_flagging` + `do_pre_flagging` | Autocorrelations, shadowing, zero clipping, quack, edge channels, pointing / UNSPECIFIED / SYSTEM_CONFIGURATION intents. |
| `tfcrop_raw` | `do_tfcrop_raw` | `flagdata(mode='tfcrop')` on the DATA column of the calibrators. |
| `manual_flagging` | `manual_file != ""` | Apply the manual flag command file. |
| `run_aoflagger` | `use_aoflagger` | AOFlagger (native or singularity). Optional: a failure is logged and the run continues. |
| `average` | `average.do_average` | `mstransform` to `<exp>.avg.ms` (time and/or channel averaging). Skipped if the `.avg.ms` exists. From here on, calibration runs on the `.avg.ms`. |
| `intent_flagging` | `flagging.do_intent_flagging` | Re-apply the pointing / UNSPECIFIED / SYSTEM_CONFIGURATION intent flags of pre-flagging to the MS being calibrated (idempotent; protects an `.avg.ms` made from an MS without pre-flagging). |
| `initial_corrections` | `calibrate.do_initial_cal` | Antenna positions, gain curve and opacity tables. |
| `flux_scale_setjy` | `do_setjy` | Flux calibrator model (Perley-Butler 2017). |
| `select_refant` | `do_refant` | Reference antenna (automatic, or from the config). |
| `bandpass_1` | `do_bandpass_1st_run` | Pass 1: delay, bandpass-calibrator gains and bandpass. |
| `gains_1` | `do_gain_calibration_1st_run` | Pass 1: gains on all calibrators, fluxscale, applycal to the calibrators, autoflag + clip of the calibrators. |
| `apply_science_1` | `do_apply_science_1st_run` | Pass 1: applycal to the targets, split the pass-1 targets (`*_1`). |
| `bandpass_2` | `do_bandpass_2nd_run` | Pass 2 (on the data flagged in pass 1). |
| `gains_2` | `do_gain_calibration_2nd_run` | Pass 2 gains (autoflag of the calibrators, no clip). |
| `apply_science_2` | `do_apply_science` | Final applycal to the targets. |
| `statwt` | `do_run_statwt` | `statwt` on the calibrated data. |
| `flag_science` | `do_flag_science` | rflag / tfcrop on the calibrated targets. |
| `split` | `do_split` | Split every field into `fields/<field>/`. |
| `imaging` | `imaging.do_imaging` | Basic `tclean` imaging (experimental). |

## Configuration

Configs are TOML files with the sections `[globals]`, `[sources]`, `[flagging]`, `[average]`, `[calibrate]`,
`[fluxscale]`, `[imaging]`, `[plotting]` and `[pipeline]`. The config is validated at start-up: types, allowed values,
and unknown keys (with a "did you mean" hint) are checked before anything runs. The resolved config, with defaults
filled in, is written to `<wd>/logs/`.

**Full reference: [`docs/config_reference.md`](docs/config_reference.md)** (every key, its default and its meaning).
It is generated from the comments in [`configs/template.toml`](configs/template.toml) with
`python docs/gen_config_reference.py`.

The keys you are most likely to change:

| Key | Default | Notes |
|---|---|---|
| `globals.experiment_name`, `working_directory`, `asdm_file` | required | See [Quick start](#quick-start). |
| `globals.do_hanning` | `false` | Hanning smoothing after import. |
| `sources.flux_calibrator`, `bandpass_calibrator`, `phase_calibrator`, `target` | `""` (from intents) | Names and/or field IDs. See [Early EVLA observations](#early-evla-observations). |
| `sources.transfer`, `reference` | `""` (from roles) | fluxscale transfer / reference field IDs. |
| `sources.phasecal_for_target` | `{}` (automatic) | Explicit target to phase calibrator mapping. |
| `flagging.manual_file` | `""` | Manual flag commands, for example `mode='manual' scan='1' reason='Config Scan'`, one per line (CASA `flagdata` list syntax). |
| `flagging.edge_channel_frac` | `0.2` | Fraction of channels ignored at each spw edge in the solves (`0.3` keeps the central 40%). |
| `flagging.edge_channel_flag_frac_cals` / `_science` | `0.06` / `0.03` | Fraction of edge channels flagged (when `do_flag_edge_channels_cals` / `_science`). |
| `flagging.do_flag_pointing_scans` | `true` | Flag `*POINTING*` scans in pre-flagging (and in `intent_flagging`). |
| `flagging.do_intent_flagging` | `true` | Re-apply the intent flags to the MS being calibrated, right before `initial_corrections`. |
| `flagging.cals_flag_mode_strategy`, `science_flag_mode_strategy` | `"rflag"` | `rflag`, `tfcrop` or `none`, on `cals_datacolumn_to_flag` / `science_datacolumn_to_flag` (`residual` by default; `corrected` also works). |
| `flagging.do_clip_data`, `clipmin`, `clipmax` | `true`, 0, 50 Jy | Clip the corrected calibrator data after pass 1. Make sure no calibrator is brighter than `clipmax`, or it will be flagged. |
| `average.do_average`, `timebin_avg`, `channel_avg`, `chan_out_avg` | `true`, `"3s"`, `false`, 32 | `chan_out_avg` is the number of *output* channels per spw (128 channels with `chan_out_avg = 64` averages by 2). |
| `calibrate.refant` | `"None"` | `"None"` selects the refant automatically; otherwise a list such as `"ea12,ea13,ea02"`. |
| `calibrate.band` | `""` (from frequency) | Band letter of the flux model: L, S, C, X, U (Ku), K, A (Ka), Q. |
| `calibrate.bp_solint_*`, `all_solint_*`, `minsnr*` | see reference | Solution intervals and SNR limits of the solves. |
| `calibrate.*_applymode` | `calflag` / `calflagstrict` | applycal applymodes (bandpass cal, gain cals, targets). |
| `calibrate.calwt_1st`, `calwt_2nd` | `true`, `false` | calwt in pass 1 / pass 2. |
| `fluxscale.fitorder`, `fitorder_bw_threshold` | `"auto"`, 0.05 | See [fluxscale](#gain-chain-gains_i). |
| `plotting.plot_backend` | `"python"` | `python`, `plotms` or `none`. |
| `pipeline.reuse_tables` | `"auto"` | `auto`, `always` or `never`. See [table reuse](#resuming-and-table-reuse). |

Field lists can be written as a comma-separated string (`"0,2"`) or a TOML array (`[0, 2]`).

## Early EVLA observations

For early EVLA observations, things are not straightforward. You need some prior information about the
observation, which you can get from `synphly info CFG` and the listobs file (`<exp>_listobs.txt` in the working
directory).

1. **Wrong scan intents.** In early observations the scan intents are often wrong. For example, the flux
   calibrator can have `OBSERVE_TARGET` instead of `CALIBRATE_FLUX`.
2. **Duplicated field IDs.** One field name can have several field IDs. For example, `3C48` can have IDs `0` and `1`.
   Usually one is for pointing calibration (or some setup) and the other holds the actual calibrator scans. This
   also happens to phase calibrators. Selected by name, both IDs enter the solves, and `fluxscale` fails.

Example: the flux and bandpass calibrator is `3C48`, the phase calibrator is `J0410+7656`, and the target is
`VIIZw031`. `3C48` has the field IDs `0` (valid flux calibrator scans) and `1` (setup scans). `J0410+7656` has the
IDs `2` (valid phase calibrator scans) and `3` (setup scans).

For the wrong intents, set the roles by hand:
```toml
[sources]
flux_calibrator     = "3C48"
bandpass_calibrator = "3C48"
phase_calibrator    = "J0410+7656"
target              = "VIIZw031"
```
For the duplicated IDs, give the valid IDs. The most explicit way is to give the roles as IDs. Explicit IDs are used
exactly as given:
```toml
[sources]
flux_calibrator     = "0"
bandpass_calibrator = "0"
phase_calibrator    = "2"
target              = "VIIZw031"
transfer  = "0,2"   # fields that receive the flux scale: the flux calibrator itself and the phase calibrator
reference = "0"     # field ID of the flux calibrator, the flux-scale reference
```
`reference` is the field ID the flux scale is taken from. `transfer` lists the field IDs the flux scale is
transferred to. Here that is the flux calibrator (itself) and the phase calibrator. In v0.6, names are also
expanded to IDs with the rules in the next section, so setup-only duplicates are usually dropped automatically.
Check the result with `synphly info`.

## Fields: the ID-based field model

v0.5 selected fields by **name**. When several field IDs share a name (pointing scans, polarisation-leakage scans,
early-EVLA duplicates), a name selection silently pulls the extra IDs into gaincal, applycal and fluxscale. v0.6
builds a field model from the MS (`synphly/fields.py`). It holds one record per `FIELD_ID`, with the name, intents,
scans, scan times, row count and position. Every role is resolved to explicit IDs.

**Role resolution.**
- If a role (`flux_calibrator`, `bandpass_calibrator`, `phase_calibrator`, `target`) is set in `[sources]`, its
  tokens are used. Each token is a name or a field ID.
- If a role is empty, the names come from the scan intents (`CALIBRATE_FLUX`, `CALIBRATE_BANDPASS`,
  `CALIBRATE_PHASE`, `*TARGET*`), as in v0.5.
- Each **name** is expanded to all field IDs with that name. Then the following IDs are **dropped**, and the
  reason is recorded:
  - (a) IDs with no rows in the main table;
  - (b) IDs whose only intent is `CALIBRATE_POINTING` (plus `SYSTEM_CONFIGURATION` / `UNSPECIFIED`). These get the
    role `pointing`;
  - (c) IDs whose only intents are `SYSTEM_CONFIGURATION` / `UNSPECIFIED` (or none), while another ID with the same
    name has a real calibration or target intent.
- **Explicit integer IDs** in the config are kept as given. If one of the rules would have dropped it, a note is
  logged.

`synphly info CFG` prints the field table, the duplicates, the dropped IDs with their reasons, and every role where
the v0.6 ID selection differs from what the v0.5 name selection would have used.

**Overriding roles.** To force a selection, give IDs instead of names (for example `phase_calibrator = "4"`). To
exclude a field, leave it out of every role, giving the remaining fields as IDs if needed.

**fluxscale reference/transfer.** If they are empty, `reference` is the flux calibrator and `transfer` is all
calibrators. Otherwise the configured IDs are used.

**Phase calibrator per target.** Each target ID is mapped to one phase-calibrator ID. By default this is the phase
calibrator **closest in time** (the median over the target scans of the gap to the nearest phase-calibrator scan).
To override it, use names or IDs on both sides. If a phase-calibrator name has several phase IDs, the closest of them
is used:
```toml
[sources]
phasecal_for_target = { NGC4278 = "J1221+2813", NGC3031 = "J0958+6533" }
```
The final applycal of each target uses its own phase calibrator as `gainfield` for the gain tables. v0.5 used
`'nearest'` instead, which could pick a field without solutions.

## Calibration strategy

Synphly runs a standard VLA continuum calibration **twice**. Pass 1 calibrates and then autoflags the calibrated data.
Pass 2 repeats the whole bandpass and gain calibration on the cleaner data. The two-pass approach improves the
calibration significantly. The strategy is unchanged from v0.5.1.

General conventions:
- Solves use `refant` from `select_refant` with `refantmode='strict'`. They use CASA's default `interp` and
  `parang`, and are made on the central channels `spw_central` (25-75% of each spw), except where noted.
  `spw_skip_edge` skips `edge_channel_frac` at each spw edge.
- Every `applycal` uses `flagbackup=False`. Synphly saves its own flag versions before each applycal (see
  [Outputs](#outputs)).
- `gaincal` always runs with `solnorm=False`. `bandpass` uses `solnorm=True` and `fillgaps=bp_fillgaps`.

### Before the passes
1. **Initial corrections** (`initial_corrections`):
   - antenna positions (`gencal caltype='antpos'`), added only if a correction is produced;
   - gain curve (`gc`);
   - opacity (`opac`, all spws), with the zenith opacities from `plotweather(seasonal_weight=0.5)`.

   These are the **init tables**. They are a prior of every solve and part of every apply.
2. **Flux calibrator model** (`flux_scale_setjy`):
   - `delmod(otf=True, scr=False)` and `clearcal`;
   - save/restore the flag version `before_setjy`;
   - `setjy` with the Perley-Butler 2017 model image `<3C286|3C48|3C147|3C138>_<band>.im`
     (`scalebychan=True`, `usescratch=True`). An unknown source gets a manual 1 Jy model at the mean frequency.
3. **Reference antenna** (`select_refant`):
   - a phase-only `gaincal` on all calibrators (`solint='inf'`, `refantmode='flex'`, `minblperant=3`, no priors);
   - antennas are ranked by their fraction of good solutions;
   - or the `refant` list from the config is used.

### Bandpass chain (`bandpass_i`)
If the flag version `before_bandpass_init_i` exists, it is restored first, followed by `clearcal` and `delmod`.
So a re-run of pass *i* starts from the same flags. All solves are on `bandpass_calibrator`:

| Table stage | Task | spw | Type | solint | combine | Priors |
|---|---|---|---|---|---|---|
| `_bpcal_d_` | gaincal | `spw_skip_edge` | K (delay) | `bp_solint_K` | | init |
| `_bpcal_p_` | gaincal | `spw_central` | G, phase | `bp_solint_G_p` | | init + K |
| `_bpcal_ap_` | gaincal | `spw_central` | G, amp+phase | `bp_solint_G_ap` | scan | init + K + p |
| `_bpcal_ap_inf_` | gaincal | `spw_central` | G, amp+phase | `inf` | scan | init + K + p |
| `_bpcal_BP_ap_inf` | bandpass | all | B | `bp_solint_BP` | scan | init + K + p + ap_inf |
| `_bpcal_BP_ap_short`, `_bpcal_BP_` | bandpass | all | B | `bp_solint_BP` | scan | diagnostics only, never applied |

The bandpass calibrator is then corrected with its own **self** list (init + K + p + ap + B). Only the
**transfer** list, **init + K + B**, goes to the other fields. The time-dependent bandpass-calibrator gains (p,
ap) are never transferred. Interpolated across hours, a single flagged refant solution would flag every
secondary (the v0.5.1 fix).

### Gain chain (`gains_i`)
1. **Model reset.** Every calibrator except the flux calibrator gets a 1 Jy point model
   (`setjy standard='manual'`). Without it, pass 2 would solve against the bootstrapped pass-1 models.
2. **Solves on all calibrators** (`spw_central`, G, `minsnr`):
   - `_allcal_p_short_` (`all_solint_short_p`) and `_allcal_p_inf_` (`all_solint_long_p`): phase only, priors =
     transfer;
   - `_allcal_ap_short_` (`all_solint_short_ap`): amp+phase, priors = transfer + p_short;
   - `_allcal_ap_inf_` (`all_solint_inf_ap`, `combine='scan'`): amp+phase, priors = transfer + p_inf.
3. **fluxscale** on `ap_short` and on `ap_inf`. The outputs are always recomputed.
   - `reference` = config `reference` or the flux calibrator; `transfer` = config `transfer` or all calibrators;
     `incremental=False`.
   - `fitorder`: with `fitorder = "auto"`, it is 1 if the fractional bandwidth `(fmax - fmin) / mean(f)` is at
     least `fitorder_bw_threshold` (0.05), and 0 otherwise. Narrow-band setups give meaningless spectral indices,
     which `setjy` rejects. For `fitorder=0`, a flat spectral index is added to the fluxdict, because CASA's
     `setjy` needs one.
4. **setjy(standard='fluxscale')** with the `ap_inf` fluxscale result writes the bootstrapped models of all
   calibrators.
5. The flag version `before_applycal_i` is saved. Then each calibrator *C* is corrected with transfer + p_short +
   ap_inf_flux_scale, with `gainfield` = *C* for the last two tables.
6. The calibrators are autoflagged (`cals_flag_mode_strategy` on `cals_datacolumn_to_flag`). In **pass 1 only**,
   their corrected data are also clipped to `[clipmin, clipmax]`.

### Science (`apply_science_i`)
The flag version `before_applycal_science_i` is saved. Then each target is corrected with transfer + p_inf +
ap_inf_flux_scale, with `gainfield` = the target's phase calibrator for the last two tables. The pass-1 result is
split into `fields/<field>/*_1` so you can check the pass-1 quality. After pass 2 come the optional `statwt`,
`flag_science` (rflag/tfcrop on the targets) and `split`.

### What gets applied where (pass *i*)

| Applied to | Step | Tables, in order | gainfield | applymode | calwt |
|---|---|---|---|---|---|
| Bandpass calibrator | `bandpass_i` | init + K + bp_p + bp_ap + BP_ap_inf | `''` (init), BP cal (others) | `bp_applymode` | `calwt_i` |
| Priors of `allcal_p_*` | `gains_i` | init + K + BP_ap_inf (transfer) | `''`, BP cal | - | - |
| Priors of `allcal_ap_short` / `_ap_inf` | `gains_i` | transfer + `allcal_p_short` / `allcal_p_inf` | `''`, BP cal, `''` | - | - |
| Each calibrator *C* | `gains_i` | transfer + `allcal_p_short` + `allcal_ap_inf_flux_scale` | `''`, BP cal, *C*, *C* | `ph_ap_applymode` | `calwt_i` |
| Each target *T* | `apply_science_i` | transfer + `allcal_p_inf` + `allcal_ap_inf_flux_scale` | `''`, BP cal, phasecal(*T*) ×2 | `science_applymode` | `calwt_i` |

`calwt_1` = `calwt_1st` (default `true`) and `calwt_2` = `calwt_2nd` (default `false`). The weights are calibrated
once, in pass 1, and pass 2 does not rescale them again. The defaults are `bp_applymode = ph_ap_applymode =
"calflag"` and `science_applymode = "calflagstrict"`.

## Outputs

Everything is written to `working_directory`. Nothing is written to the repository directory.

```
<working_directory>/
  <exp>.ms  [<exp>_hs.ms]  <exp>.avg.ms   (+ .flagversions/)   measurement sets
  <exp>_listobs.txt, <exp>.avg_listobs.txt                    listobs
  calibration/        calibration tables (.tb), *_fluxinfo.txt, find_refant.phase, <table>.synphly.json
  plots/
    before/           visibilities, DATA column
    after/            calibrated visibilities (CORRECTED), per pass and stage
    calibration/      calibration-table plots (K, G, B, fluxscale, SNR)
    ...               flag statistics, weather/opacity, antenna layout
  fields/<field>/     split calibrated fields (<field>.calibrated_1.ms, <field>.calibrated.ms, time-averaged copies)
  flags/              flag reports
  logs/               synphly_<time>.log, casa_<time>.log, resolved config
  synphly_state.json  step status, outputs, apply lists, refant, field model, flag versions
  run_report.json     end-of-run summary (machine readable)
  run_report.md       the same, readable: fluxes per field and spw, flag fractions per step,
                      tables and their priors, warnings, timings, plot links
```

**Table naming.**
`calibration/{i}{stage}{solint}_{ms}.tb`, where `{ms}` is the calibrated MS name with `.ms` replaced by `.tb`.
For example, `1_bpcal_d_inf_<exp>.avg.tb` and `2_allcal_ap_inf_inf_<exp>.avg.tb`. The fluxscale outputs append
`_flux_scale.tb` and `_flux_scale_fluxinfo.txt`. The bootstrapped fluxes are in
`calibration/<i>_allcal_ap_inf_inf_<exp>.avg_flux_scale_fluxinfo.txt` and in `run_report.md`.

**Flag versions.** Flag versions are saved before the steps that change flags or apply calibration: `before_setjy`,
`before_bandpass_init_<i>`, `before_applycal_<i>`, `before_applycal_science_<i>` and others. Use
`flagmanager(vis=..., mode='list')` to see them, and `mode='restore'` to go back.

## Resuming and table reuse

**Resume.** After each step, its status (`done` / `failed`), timings, outputs and the shared state are written to
`synphly_state.json`. The shared state is the field model, init tables, refant, apply lists and fluxes. A run that
crashed can be continued with `synphly run CFG --from <step>`, and a single step re-run with `--only <step>`.
Re-running a bandpass pass restores its `before_bandpass_init_<i>` flag version first. This means manual flags added
to the MS after that version was saved are undone, unless you save the version again.

**Table reuse.** Each calibration table has a sidecar `<table>.synphly.json` that records how it was made:
- the stage, iteration, solint, solved fields, priors and gainfields;
- an **input hash** of the MS identity, the flag-version name, the solve parameters and the Synphly version.

`[pipeline] reuse_tables` decides what happens when a table already exists:

| `reuse_tables` | Behaviour |
|---|---|
| `auto` (default) | Reuse only if the sidecar exists and its input hash matches. Otherwise recompute. |
| `always` | Reuse any existing table with the expected name (v0.5 behaviour; use with care). |
| `never` | Always recompute. |

`--force STEP` (or `--force all`) recomputes the given steps whatever `reuse_tables` says. fluxscale outputs are
always recomputed, because they are cheap and derived from the `ap` tables. The averaged MS is reused if it exists.
To redo the averaging, delete `<exp>.avg.ms`.

## Plotting

`[plotting]` controls all plots. A failed plot logs a warning and never stops the run.

| Key | Default | Meaning |
|---|---|---|
| `plot_backend` | `"python"` | `python`: fast matplotlib + casatools plots, the default; no casaplotms needed. `plotms`: CASA plotms (needs `casaplotms`). `none`: no plots. |
| `plot_caltables` | `true` | Calibration-table plots: K delays per antenna, G phase/amplitude vs time, B amplitude/phase vs channel/frequency, fluxscale bootstrap fluxes, SNR histograms. |
| `plot_visibilities` | `true` | Amplitude/phase vs time and frequency, amplitude vs uv-distance (corrected, model, ratio, residual), uv coverage, per field. |
| `plot_flag_stats` | `true` | Flag fraction per step, field, antenna and spw. |

## Imaging (EXPERIMENTAL)

With `[imaging] do_imaging = true`, the targets are imaged with `tclean` using auto-multithresh masking (see
`synphly/steps/imaging.py`). For parallel imaging run under `mpicasa` and set `parallel = true`. Otherwise keep
`parallel = false`. Parallel imaging may not work with every CASA version.

## Development

**Package layout.**
```
synphly/
  cli.py, __main__.py   command line (synphly run/info/convert-config/steps)
  config.py             config schema (one dataclass per section), TOML + legacy INI loaders, validation
  context.py            Context (run state, replaces the v0.5 globals) and Paths; synphly_state.json
  fields.py             FieldModel: per-ID field roles, duplicates, target -> phase calibrator
  pipeline.py           step order and switches
  casa.py               the single place where casatools/casatasks are imported
  logs.py               synphly + CASA logs in <wd>/logs/
  steps/                one module per step (import_data, preflag, average, initial_corrections, setjy_fluxcal,
                        refant, bandpass, gains, applycal, autoflag, statwt, split, imaging, ms_info)
  calib/                gaincal/bandpass wrappers (raise on failure), table registry and reuse policy
  plotting/             visibilities, caltables, flags, fluxes, plotants
  reporting/            run_report.json / .md
  external/             optional: run the NRAO VLA / ALMA pipelines (vla_pipeline.py), not used by Synphly
configs/                template.toml (documented defaults), datasets/<exp>.toml, legacy/ (old INI configs)
tests/                  unit tests (no CASA data needed), the mock-CASA call-sequence regression (mockcasa/,
                        data/golden_calls/) and integration tests (-m integration)
tools/                  regression_metrics.py, compare_runs.py
docs/                   config_reference.md (generated), gen_config_reference.py, notes/
main.py                 legacy shim: python main.py [config] -> synphly run
```
The v0.5 code (`data_calibration/`, exec-ed by the old `main.py`) was removed in v0.6; it is in the git history
and in the `v0.5.1` tag.
Code rules: no `exec` or shared globals (steps get `ctx`), fields are selected by ID, no bare `except`, logging
through `logging.getLogger(__name__)`.

**Tests.**
```bash
pytest                    # unit tests: config, field model (mocked 12B-184 and 21A-024 metadata), plotting,
                          # and the call-sequence regression against v0.5.1 (tests/test_call_sequence.py)
pytest -m integration     # needs CASA and the regression MS / caltables on disk
```
`tests/test_call_sequence.py` runs the pipeline on recording fakes of CASA (`tests/mockcasa/`) and compares
every CASA call with the golden v0.5.1 calls in `tests/data/golden_calls/` (recorded once with
`tests/mockcasa/record_golden.py` from the `v0.5.1` tag). A deliberate change of a CASA call must be added to
`INTENDED_CHANGES` in `tests/mockcasa/compare.py`.

**Regression tools.** These check that a code change does not change the calibration:
```bash
python tools/regression_metrics.py WORKING_DIR CAL_MS OUT_DIR   # read-only: caltable stats, fluxes, flags, |CORRECTED|
python tools/compare_runs.py REF_DIR NEW_DIR [--strict] [--md report.md]
```
`compare_runs.py` exits with 1 if any difference is over tolerance. The default tolerances are caltable
parameters 1e-5, fluxes 0.1%, flag fractions 0.1 percentage points, and corrected medians 0.1%.

**Config reference.** After changing `configs/template.toml`, regenerate the reference with
`python docs/gen_config_reference.py`.

**Notes, known issues and plans.** These are in [`todos_and_improvements/`](todos_and_improvements/README.md):
the v0.5.1 session log, the current status, known issues, the v0.6 plan and dataset notes.

**Open items.**
- [ ] Quack policy (v0.5 uses 1 s at the beginning and end of each scan; per-role extra quack is configurable).
- [ ] A second regression dataset with duplicated field IDs (12B-184).
- [ ] Calibrating several bands of one observation in one run.
- [ ] Imaging arguments in the config.
- [ ] Self-calibration and imaging from [`morphen`](https://github.com/lucatelli/morphen/tree/dev/selfcal) /
      [`ph4ser`](https://github.com/lucatelli/ph4ser).
