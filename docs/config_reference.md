# Synphly configuration reference

Generated from [`configs/template.toml`](../configs/template.toml) by `docs/gen_config_reference.py`. Do not edit by hand: edit the
template comments and re-run the script.

A dataset config only needs the keys that differ from these defaults. Lists of fields can be written as a
comma-separated string (`"0,2"`) or as a TOML array (`[0, 2]`). Unknown keys are an error.

Sections: [`[globals]`](#globals), [`[sources]`](#sources), [`[flagging]`](#flagging), [`[average]`](#average), [`[calibrate]`](#calibrate), [`[fluxscale]`](#fluxscale), [`[imaging]`](#imaging), [`[plotting]`](#plotting), [`[pipeline]`](#pipeline).

## [globals]

| Key | Default | Description |
|---|---|---|
| `experiment_name` | `""` | REQUIRED. Name of the measurement set to create/use, WITHOUT the .ms extension. |
| `working_directory` | `""` | REQUIRED. Directory where all data products are written. |
| `asdm_file` | `""` | Path of the ASDM to import. If you have no ASDM, set it equal to the MS name without .ms. |
| `load_data` | `true` | Import the ASDM (importasdm) if the MS does not exist yet. |
| `run_only_ms_info` | `false` | Only import the data and write listobs, then stop (legacy v0.5 switch; prefer `synphly prepare`). |
| `do_hanning` | `false` | Hanning smoothing of the imported data. |
| `use_singularity` | `false` | Run AOFlagger through a singularity container, and the container path. |
| `singularity_path` | `""` | (as above) |
| `ms_info` | `true` | Read MS metadata (fields, intents, spws). Leave true. |
| `report_verbosity` | `3` | Detail level of the flag reports (integer, 3 = v0.5 default). |

## [sources]

| Key | Default | Description |
|---|---|---|
| `flux_calibrator` | `""` | Field names and/or field IDs, comma-separated (string or TOML array). Empty -> taken from the scan intents of the MS. |
| `bandpass_calibrator` | `""` | (as above) |
| `phase_calibrator` | `""` | (as above) |
| `target` | `""` | (as above) |
| `transfer` | `""` | VALID field IDs used by fluxscale. transfer: fields receiving the flux scale (flux calibrator itself, phase calibrators, bandpass calibrator). reference: field ID of the flux calibrator. Empty -> derived from the field roles (transfer = all calibrators, reference = flux calibrator). |
| `reference` | `""` | (as above) |
| `phasecal_for_target` | `{}` | Optional explicit target -> phase calibrator mapping (names or IDs), e.g. `phasecal_for_target = { NGC4278 = "J1221+2813", NGC3031 = "J0958+6533" }` Empty -> assigned automatically by time adjacency of the scans. |

## [flagging]

| Key | Default | Description |
|---|---|---|
| `do_flagging` | `true` | Master switch for the flagging block run before averaging. |
| `do_pre_flagging` | `true` | Pre-flagging: autocorrelations, shadowing, quack, pointing scans and edge channels. |
| `use_aoflagger` | `false` | Run AOFlagger (natively, or via singularity if globals.use_singularity = true). |
| `do_tfcrop_raw` | `true` | Run flagdata mode='tfcrop' on the native (DATA column) visibilities. |
| `aoflagger_sif` | `"/singularity_containers/lofar_aoflagger_3.1.0.sif"` | AOFlagger singularity image and Lua strategy file. |
| `aoflagger_strategy` | `"./aoflagger_strategies/jvla-default.lua"` | (as above) |
| `manual_file` | `""` | Manual flag command file (one flagdata command per line, e.g. mode='manual' scan='1'). Empty = none. |
| `edge_channel_frac` | `0.2` | Fraction of channels ignored at EACH spw edge for the calibration solves (e.g. 0.3 -> the central 40% of the channels are used). |
| `edge_channel_flag_frac_cals` | `0.06` | Fraction of channels FLAGGED at each spw edge for calibrators / science targets, applied when do_flag_edge_channels_cals / do_flag_edge_channels_science are true. |
| `edge_channel_flag_frac_science` | `0.03` | (as above) |
| `do_flag_edge_channels_cals` | `true` | (as above) |
| `do_flag_edge_channels_science` | `true` | (as above) |
| `do_flag_pointing_scans` | `true` | Flag scans with a *POINTING* intent during pre-flagging. Pointing scans may share a calibrator name and, if left unflagged, enter the gain calibration. Only effective with do_pre_flagging = true. |
| `do_intent_flagging` | `true` | Re-apply the intent flags of pre-flagging (pointing, if do_flag_pointing_scans, UNSPECIFIED and SYSTEM_CONFIGURATION) to the MS that is calibrated, right before initial_corrections (step intent_flagging). Independent of do_flagging / do_pre_flagging. Idempotent with pre-flagging; it protects an .avg.ms that was made from an MS without pre-flagging. |
| `quack_interval_beg` | `1.0` | Quack (seconds) at the beginning / end of every scan, all fields (v0.5: 1 s and 1 s). |
| `quack_interval_endb` | `1.0` | (as above) |
| `quack_extra_flux_beg` | `0.0` | Extra quack (seconds) per field role, on top of the above. 0 = off (v0.5 behaviour). |
| `quack_extra_phase_beg` | `0.0` | (as above) |
| `quack_extra_phase_endb` | `0.0` | (as above) |
| `cals_flag_mode_strategy` | `"rflag"` | Autoflagging of calibrated calibrator / science data: rflag \| tfcrop \| none, on datacolumn corrected \| residual \| data (corrected or residual are good choices). |
| `cals_datacolumn_to_flag` | `"residual"` | (as above) |
| `science_flag_mode_strategy` | `"rflag"` | (as above) |
| `science_datacolumn_to_flag` | `"residual"` | (as above) |
| `ntime` | `"scan"` | tfcrop/rflag parameters (see the CASA flagdata documentation). |
| `combinescans` | `false` | (as above) |
| `tfcrop_timecutoff_cals` | `4.0` | (as above) |
| `tfcrop_freqcutoff_cals` | `4.0` | (as above) |
| `tfcrop_freqcutoff_science` | `4.0` | (as above) |
| `tfcrop_timecutoff_science` | `4.0` | (as above) |
| `rflag_timedevscale_cals` | `4.0` | (as above) |
| `rflag_freqdevscale_cals` | `4.0` | (as above) |
| `rflag_timedevscale_science` | `4.0` | (as above) |
| `rflag_freqdevscale_science` | `4.0` | (as above) |
| `maxnpieces` | `5` | (as above) |
| `winsize` | `5` | (as above) |
| `do_clip_data` | `true` | Clip the corrected data of the calibrators outside [clipmin, clipmax] (Jy) after pass-1 calibration. Be careful if any source is brighter than clipmax (50 for safety, instead of 30). |
| `clipmin` | `0.0` | (as above) |
| `clipmax` | `50.0` | (as above) |

## [average]

| Key | Default | Description |
|---|---|---|
| `do_average` | `true` | Average the data after flagging (flagging is always done on the native data). Skipped if the .avg.ms already exists. |
| `time_avg` | `true` | Time averaging and its bin, e.g. "6s". |
| `timebin_avg` | `"3s"` | (as above) |
| `channel_avg` | `false` | Channel averaging. chan_out_avg is the number of OUTPUT channels per spw (not the averaging factor): 128 channels with chan_out_avg = 64 -> factor 2. Must not exceed the channels of any spw. |
| `chan_out_avg` | `32` | (as above) |

## [calibrate]

| Key | Default | Description |
|---|---|---|
| `do_initial_cal` | `true` | Initial corrections (antenna positions, gain curve, opacity). |
| `do_setjy` | `true` | Set the flux calibrator model (Perley-Butler 2017). |
| `do_refant` | `true` | Reference antenna: "None" -> chosen automatically by the fraction of good solutions; otherwise a list such as "ea12,ea13,ea02". |
| `refant` | `"None"` | (as above) |
| `band` | `""` | VLA band letter of the flux model: L, S, C, X, U (= Ku), K, A (= Ka), Q. Note: for Ka band use "A", for Ku band use "U". Empty -> guessed from the observing frequency. |
| `bp_solint_K` | `"inf"` | Bandpass-calibrator solves: delay (K), phase (G p), amplitude+phase (G ap), bandpass (BP). Solution intervals are CASA solints: "inf", "int", "<n>s", "<n>min", "<n>s,<n>ch". |
| `minsnr_K` | `3.0` | (as above) |
| `bp_solint_G_p` | `"18s"` | (as above) |
| `minsnr_bp_G_p` | `3.0` | (as above) |
| `bp_solint_G_ap` | `"36s"` | (as above) |
| `bp_solint_BP` | `"inf"` | (as above) |
| `minsnr` | `3.0` | minsnr of the gain solves on all calibrators. |
| `all_solint_short_p` | `"18s"` | Gain solves on all calibrators: short/long phase, short/scan-combined amplitude+phase. |
| `all_solint_short_ap` | `"36s"` | (as above) |
| `all_solint_long_p` | `"inf"` | (as above) |
| `all_solint_inf_ap` | `"inf"` | (as above) |
| `bp_applymode` | `"calflag"` | applycal applymode for the bandpass calibrator, the gain calibrators and the science targets: calflag \| calflagstrict \| trial \| flagonly \| flagonlystrict \| calonly. |
| `ph_ap_applymode` | `"calflag"` | (as above) |
| `science_applymode` | `"calflagstrict"` | (as above) |
| `bp_fillgaps` | `8` | bandpass fillgaps (channels). |
| `do_bandpass_1st_run` | `true` | Pass 1: bandpass, gains, apply to the science targets (and split them, to check pass-1 quality), with calibrated weights (calwt). |
| `do_gain_calibration_1st_run` | `true` | (as above) |
| `do_apply_science_1st_run` | `true` | (as above) |
| `calwt_1st` | `true` | (as above) |
| `do_bandpass_2nd_run` | `true` | Pass 2 (after autoflagging the pass-1 corrected data). calwt_2nd = false: weights are calibrated only once. |
| `do_gain_calibration_2nd_run` | `true` | (as above) |
| `calwt_2nd` | `false` | (as above) |
| `do_apply_science` | `true` | Apply the final calibration to the science targets, then autoflag them. |
| `do_flag_science` | `true` | (as above) |
| `do_run_statwt` | `false` | statwt on the final calibrated data (may be unnecessary if calwt was applied). |
| `statwt_timebin` | `"12s"` | (as above) |
| `statwt_statalg` | `"chauvenet"` | (as above) |
| `do_split` | `true` | Split the calibrated data per field; timebin_longer = timebin of the extra time-averaged copies. |
| `timebin_longer` | `"6s"` | (as above) |
| `timebin` | `"6s"` | Not used for now. |
| `width` | `1` | (as above) |
| `solint` | `"60s"` | (as above) |

## [fluxscale]

| Key | Default | Description |
|---|---|---|
| `fitorder` | `"auto"` | fluxscale fitorder: "auto" -> 1 if the fractional bandwidth >= fitorder_bw_threshold, else 0 (v0.5 behaviour); or "0" / "1". |
| `fitorder_bw_threshold` | `0.05` | (as above) |
| `incremental` | `false` | fluxscale incremental mode. false (v0.5): the fluxscale table replaces the ap gains when applied. |

## [imaging]

| Key | Default | Description |
|---|---|---|
| `do_imaging` | `false` | Basic tclean imaging with auto-multithresh masking (EXPERIMENTAL). parallel = true only under mpicasa. |
| `imager` | `"tclean"` | (as above) |
| `parallel` | `false` | (as above) |

## [plotting]

| Key | Default | Description |
|---|---|---|
| `plot_backend` | `"python"` | Plot backend: python \| plotms \| none. And what to plot. |
| `plot_caltables` | `true` | (as above) |
| `plot_visibilities` | `true` | (as above) |
| `plot_flag_stats` | `true` | (as above) |

## [pipeline]

| Key | Default | Description |
|---|---|---|
| `reuse_tables` | `"auto"` | Calibration table reuse: auto (reuse only if the recorded inputs match) \| always (any existing table with the expected name, v0.5 behaviour) \| never (always recompute). |
