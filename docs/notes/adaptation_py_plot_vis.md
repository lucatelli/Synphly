Hi, I need help adapting some visibility plotting code from the `ph4ser` code. The `ph4ser` version of this implementation is `data_calibration/plot_vis_python.py`. In `ph4ser` this submodule is invoked by simply 
```python
from plot_vis_python import plot_visibilities, plot_uvwave

...

class Pipeline():
    ...

    plot_visibilities = plot_visibilities
    plot_uvwave       = plot_uvwave

    ....


    if PLOT == True:
    self.plot_visibilities(g_vis=g_vis, name=base_name,
                            with_CORRECTED=with_CORRECTED,
                            with_MODEL=with_MODEL,
                            with_DATA=with_DATA)
    
    ...
    #etc
```

I want to use the same principle in `synphly` because the current implementation uses plotms and it takes way too long, hours to make a plot. 
The python version is working super nice, and is efficient, from seconds to minutes (for bit MSs). The way I am plotting in `synphly` is with the help of the function `make_plots_stages`, 
```python
def make_plots_stages(vis,stage='after', kind='',
                      plots=None, FIELDS='', plot_all_uv=False, avgantenna=True,
                      extra_plot=True):
    """
    Make standard plots given a stage (before or after) of calibration.
    This can be useful to compare how calibration performs on the data.

    PS. This function takes a long time to complete if all plots are asked.
    """
    # Amplitude vs channel; Amplitude vs time; Amplitude vs Frequency;
    # phase vs time;
    make_plots_starttime = time.time()

    calibration_dir = os.path.join(working_directory).rstrip('/')+'/'+'calibration'
    plots_dir = os.path.join(working_directory).rstrip('/')+'/'+ 'plots'

    if not os.path.exists(f"{plots_dir}/{stage}"):
        os.makedirs(f"{plots_dir}/{stage}")
    if not os.path.exists(f"{plots_dir}/{stage}/chan_amp"):
        os.makedirs(f"{plots_dir}/{stage}/chan_amp")
    if not os.path.exists(f"{plots_dir}/{stage}/time_amp"):
        os.makedirs(f"{plots_dir}/{stage}/time_amp")
    if not os.path.exists(f"{plots_dir}/{stage}/freq_amp"):
        os.makedirs(f"{plots_dir}/{stage}/freq_amp")
    if not os.path.exists(f"{plots_dir}/{stage}/time_phase"):
        os.makedirs(f"{plots_dir}/{stage}/time_phase")
    if not os.path.exists(f"{plots_dir}/{stage}/amp_phase"):
        os.makedirs(f"{plots_dir}/{stage}/amp_phase")
    if not os.path.exists(f"{plots_dir}/{stage}/chan_phase"):
        os.makedirs(f"{plots_dir}/{stage}/chan_phase")

    if stage == 'before':
        ydatacolumn = 'data'
    if stage == 'after':
        ydatacolumn = 'corrected'


    # if plotting_level >= 1:
    for FIELD in FIELDS:
        # print('Plotting Chan vs Amp: Field')
        plotfile = f"{plots_dir}/{stage}/time_amp/time_amp_avg_{ydatacolumn}_field_{FIELD}_{kind}.jpg"
        plotms(vis=vis, xaxis='time', yaxis='amp', ydatacolumn=ydatacolumn,
                          avgchannel='9999', coloraxis='baseline', field=FIELD,
                          xselfscale=True, yselfscale=True, correlation='RR,LL',
                          title='Time vs Amp, ' + str(FIELD), avgantenna=avgantenna,
                          gridrows=1, gridcols=1, width=2000, height=800, showgui=False,
                          overwrite=True, dpi=1200,
                          customsymbol=True,symbolsize=3,symbolshape='diamond',
                          highres=True,
                          plotfile=plotfile)
        plotfile = f"{plots_dir}/{stage}/freq_amp/freq_amp_avg_{ydatacolumn}_field_{FIELD}_{kind}.jpg"
        plotms(vis=vis, xaxis='freq', yaxis='amp', ydatacolumn=ydatacolumn,
                          avgtime='9999', coloraxis='baseline', field=FIELD,
                          xselfscale=True, yselfscale=True, correlation='RR,LL',
                          title='Freq vs Amp, ' + str(FIELD), avgantenna=avgantenna,
                          # width=800,height=540,dpi=600,overwrite=True,showgui=False,
                          gridrows=1, gridcols=1, width=2000, height=800, showgui=False,
                          overwrite=True, dpi=1200,
                          customsymbol=True,symbolsize=3,symbolshape='diamond',
                          highres=True,
                          plotfile=plotfile)
        plotfile = f"{plots_dir}/{stage}/time_phase/time_phase_avg_{ydatacolumn}_field_{FIELD}_{kind}.jpg"
        plotms(vis=vis, xaxis='time', yaxis='phase', ydatacolumn=ydatacolumn, correlation='RR,LL',
                          avgchannel='9999', coloraxis='baseline', field=FIELD,
                          title='Time vs Phase, ' + str(FIELD), avgantenna=avgantenna,
                          gridrows=1, gridcols=1, width=2000, height=800, showgui=False,
                          overwrite=True,
                          dpi=1200, highres=True,
                          customsymbol=True,symbolsize=3,symbolshape='diamond',
                          plotrange=[-1, -1, -180, 180],
                          plotfile=plotfile)
        plotfile = f"{plots_dir}/{stage}/uvwave_amp_{ydatacolumn}_field_{FIELD}_{kind}.jpg"
        plotms(vis=vis, xaxis='uvwave', yaxis='amp', field=FIELD,
                          coloraxis='baseline', correlation='RR,LL',
                          xselfscale=True, yselfscale=True,
                          ydatacolumn=ydatacolumn, avgchannel='9999', avgtime='9999',
                          width=2000, height=800, showgui=False, overwrite=True, dpi=1200,
                          customsymbol=True,symbolsize=3,symbolshape='diamond',
                          highres=True,
                          plotfile=plotfile)
        
        
        
        ydatacolumn2 = 'residual'
        ydatacolumn3 = 'corrected/model'
        ydatacolumn4 = 'model'
        if extra_plot == True:
            
            try:
            
                # plotfile = f"{plots_dir}/{stage}/uvwave_amp_{ydatacolumn2}_field_{FIELD}_{kind}.jpg"
                # plotms(vis=vis, xaxis='uvwave', yaxis='amp', field=FIELD,
                #                 coloraxis='baseline', correlation='RR,LL',
                #                 xselfscale=True, yselfscale=True,
                #                 ydatacolumn=ydatacolumn2, avgchannel='9999', avgtime='9999',
                #                 width=2000, height=800, showgui=False, overwrite=True, dpi=1200,
                #                 customsymbol=True,symbolsize=3,symbolshape='diamond',
                #                 highres=True,
                #                 plotfile=plotfile)
                #
                # plotfile = f"{plots_dir}/{stage}/freq_amp/freq_amp_avg_{ydatacolumn2}_field_{FIELD}_{kind}.jpg"
                # plotms(vis=vis, xaxis='freq', yaxis='amp', ydatacolumn=ydatacolumn2,
                #                 avgtime='9999', coloraxis='baseline', field=FIELD,
                #                 xselfscale=True, yselfscale=True, correlation='RR,LL',
                #                 title='Freq vs Amp, ' + str(FIELD), avgantenna=avgantenna,
                #                 # width=800,height=540,dpi=600,overwrite=True,showgui=False,
                #                 gridrows=1, gridcols=1, width=2000, height=800, showgui=False,
                #                 overwrite=True, dpi=1200,
                #                 customsymbol=True,symbolsize=3,symbolshape='diamond',
                #                 highres=True,
                #                 plotfile=plotfile)
                
                plotfile = f"{plots_dir}/{stage}/freq_amp/freq_amp_avg_{ydatacolumn4}_field_{FIELD}_{kind}.jpg"
                plotms(vis=vis, xaxis='freq', yaxis='amp', ydatacolumn=ydatacolumn4,
                                avgtime='9999', coloraxis='baseline', field=FIELD,
                                xselfscale=True, yselfscale=True, correlation='RR,LL',
                                title='Freq vs Amp, ' + str(FIELD), avgantenna=avgantenna,
                                # width=800,height=540,dpi=600,overwrite=True,showgui=False,
                                gridrows=1, gridcols=1, width=2000, height=800, showgui=False,
                                overwrite=True, dpi=1200,
                                customsymbol=True,symbolsize=3,symbolshape='diamond',
                                highres=True,
                                plotfile=plotfile)
                
                # plotfile = f"{plots_dir}/{stage}/uvwave_amp_corrected_div_model_field_{FIELD}_{kind}.jpg"
                # plotms(vis=vis, xaxis='uvwave', yaxis='amp', field=FIELD,
                #                 coloraxis='baseline', correlation='RR,LL',
                #                 xselfscale=True, yselfscale=True,
                #                 ydatacolumn=ydatacolumn3, avgchannel='9999', avgtime='9999',
                #                 width=2000, height=800, showgui=False, overwrite=True, dpi=1200,
                #                 customsymbol=True,symbolsize=3,symbolshape='diamond',
                #                 highres=True,
                #                 plotfile=plotfile)
            except:
                pass
            
    make_plots_time = time.time() - make_plots_starttime
    logging.info(f"Plotting regarding {kind} for fields {FIELDS} took {make_plots_time / 60:.2f} minutes")
    pass
```
Of course, it needs some organisation; 
I would like to have an adaptation of the module `plot_vis_python` into Synphly, call it `Sy_plot_vis.py` using the same principles as `plot_vis_python`. Be careful, adapt the relevant casacore/ms tool operations exactly, as they contain many fixes for different MS characteristics (e.g. non-homogeneous spectral windows, etc etc). Note however that in the Synphly, we have an extra thing to be very careful; the measurement sets contain multiple fields, so the new sub-module `Sy_plot_vis` must be able to deal with that, and make the same data selection to make the plots (as in `make_plots_stages`). Note that the function `make_plots_stages` is called in `main.py` in different stages. Can you generate this new sub-module? 
as a reference, use this MS as reference: `/home/lucatelli/astronomical_data/LIRGI_Sample_v2/Arp220/VLA_C_Ka/13A-270.sb24196449.eb24739062.56532.0518821875_Sy_v3/13A-270/observation.56532.05191608796/13A-270.sb24196449.eb24739062.56532.0518821875_Ka.avg.ms`; this is a fully finalised calibrated data prodcut, so all collumns data exist on it. PLease, be aware of the averaging parameters in `plot_vis_python` as it handles well large datasets; however, we may need extra memory checks for the new `Sy_plot_vis.py`  as the MS files during phase-referencing calibration can be larger. Can you work on this? 

How can I quickly test this new script in that MS as example? e.g. In the `plot_vis_python` I used something like this (as reference)

```bash
python3 -c "
import sys; sys.path.insert(0, '/path/to/scripts/')
import plot_vis_python as pvp
class S: pass
pvp.plot_visibilities(S(),
                      g_vis='/media/sagauga/starbyte/vis_problems/tab_shape_not_conforming/Mrk231.calibrated.ms',
                      name='Mrk231',
                      with_DATA=True,
                      with_CORRECTED=True,
                      with_MODEL=True,
                      with_RESIDUAL=True)
"
```

Lets simulate the final plotting stage; e.g. 
```python
        make_plots_stages_py(vis=vis_for_cal,
                             stage='after',
                             kind='final_science_after_flag',
                             extra_plot=False,
                             FIELDS=target.split(','),
                             working_directory=working_directory)
```




# v2 improvements 

Hi, I need a small fix to a problem in the Sy_plot_vis module, e.g. `make_plots_stages_py`. For some very weird cases, the name of the fiel can have the charactere /, e.g. NGC6670A/B, which causes a severe error; I need a fix to this, but without breaking the code; note that for these cases we could solve for the filed ID not name:
```
     => Reporting data flagged after applycal.
  ++==>> Reporting flag statistics.
field 3C48:  59.7 percent flagged
field J1835+6119:  36.7 percent flagged
field NGC6670A/B:  22.0 percent flagged
  Sy_plot_vis: n_chan_max=32  chunk(1col)=5650859  avail_ram=24.4 GB  mem_fraction=0.20
  Plotting field '2' (FIELD_ID=[2]) stage=after kind=after_apply_cal_2
    Accumulating time series (field=2)...
  Saved: /media/sagauga/void/astronomical-data/LIRGI_Sample_v2/processing/NGC6670/VLA_A_Ka/23A-375.sb44182072.eb44292339.60129.37890763889_Sy_v5/plots/after/time_amp/time_amp_avg_corrected_field_2_after_apply_cal_2.jpg
  Saved: /media/sagauga/void/astronomical-data/LIRGI_Sample_v2/processing/NGC6670/VLA_A_Ka/23A-375.sb44182072.eb44292339.60129.37890763889_Sy_v5/plots/after/time_phase/time_phase_avg_corrected_field_2_after_apply_cal_2.jpg
    Accumulating freq-amp (field=2)...
  Saved: /media/sagauga/void/astronomical-data/LIRGI_Sample_v2/processing/NGC6670/VLA_A_Ka/23A-375.sb44182072.eb44292339.60129.37890763889_Sy_v5/plots/after/freq_amp/freq_amp_avg_corrected_field_2_after_apply_cal_2.jpg
    Accumulating uvwave-amp (field=2)...
  Saved: /media/sagauga/void/astronomical-data/LIRGI_Sample_v2/processing/NGC6670/VLA_A_Ka/23A-375.sb44182072.eb44292339.60129.37890763889_Sy_v5/plots/after/uvwave_amp_corrected_field_2_after_apply_cal_2.jpg
  Sy_plot_vis: plotting 'after_apply_cal_2' for fields ['2'] took 0.89 minutes
Running rflag
    ** Creating flag backup before rflag...
  ++==>> Reporting flag statistics.
field 3C48:  59.7 percent flagged
field J1835+6119:  36.7 percent flagged
field NGC6670A/B:  22.0 percent flagged
 ++==>> Flagging column residual
2026-06-29 17:50:17     WARN    flagdata::::casa        Disabling savepars for the display
  ++==>> Reporting flag statistics.
field 3C48:  59.7 percent flagged
field J1835+6119:  36.7 percent flagged
field NGC6670A/B:  25.0 percent flagged
  Sy_plot_vis: n_chan_max=32  chunk(1col)=5662728  avail_ram=24.5 GB  mem_fraction=0.20
  Plotting field '2' (FIELD_ID=[2]) stage=after kind=final_science_after_flag
    Accumulating time series (field=2)...
  Saved: /media/sagauga/void/astronomical-data/LIRGI_Sample_v2/processing/NGC6670/VLA_A_Ka/23A-375.sb44182072.eb44292339.60129.37890763889_Sy_v5/plots/after/time_amp/time_amp_avg_corrected_field_2_final_science_after_flag.jpg
  Saved: /media/sagauga/void/astronomical-data/LIRGI_Sample_v2/processing/NGC6670/VLA_A_Ka/23A-375.sb44182072.eb44292339.60129.37890763889_Sy_v5/plots/after/time_phase/time_phase_avg_corrected_field_2_final_science_after_flag.jpg
    Accumulating freq-amp (field=2)...
  Saved: /media/sagauga/void/astronomical-data/LIRGI_Sample_v2/processing/NGC6670/VLA_A_Ka/23A-375.sb44182072.eb44292339.60129.37890763889_Sy_v5/plots/after/freq_amp/freq_amp_avg_corrected_field_2_final_science_after_flag.jpg
    Accumulating uvwave-amp (field=2)...
  Saved: /media/sagauga/void/astronomical-data/LIRGI_Sample_v2/processing/NGC6670/VLA_A_Ka/23A-375.sb44182072.eb44292339.60129.37890763889_Sy_v5/plots/after/uvwave_amp_corrected_field_2_final_science_after_flag.jpg
  Sy_plot_vis: plotting 'final_science_after_flag' for fields ['2'] took 0.87 minutes
 ++==> Reporting data flagged final.
  ++==>> Reporting flag statistics.
field NGC6670A/B:  25.0 percent flagged
The list field  is  ['field_0', 'field_1', 'field_2']
Splitting field 3C48 into -->> /media/sagauga/void/astronomical-data/LIRGI_Sample_v2/processing/NGC6670/VLA_A_Ka/23A-375.sb44182072.eb44292339.60129.37890763889_Sy_v5//fields/3C48/3C48.calibrated.ms
Splitting field J1835+6119 into -->> /media/sagauga/void/astronomical-data/LIRGI_Sample_v2/processing/NGC6670/VLA_A_Ka/23A-375.sb44182072.eb44292339.60129.37890763889_Sy_v5//fields/J1835+6119/J1835+6119.calibrated.ms
Splitting field NGC6670A/B into -->> /media/sagauga/void/astronomical-data/LIRGI_Sample_v2/processing/NGC6670/VLA_A_Ka/23A-375.sb44182072.eb44292339.60129.37890763889_Sy_v5//fields/NGC6670AB/NGC6670AB.calibrated.ms
2026-06-29 17:52:56     SEVERE  split::::casa   Task split raised an exception of class RuntimeError with the following message: Field Expression: No match found for name "NGC6670A"
2026-06-29 17:52:56     SEVERE  split::::casa+  (near char. 8 in string "NGC6670A/B")
Field Expression: No match found for name "NGC6670A"
(near char. 8 in string "NGC6670A/B")
```

Note that I am using this in the config.ini
```
[sources]
flux_calibrator = 3C48
bandpass_calibrator = 3C48
phase_calibrator = J1835+6119
target = 2
; use this to manually set the VALID  transfer fields IDs (flux calibrator itself, phase calibrators + bandpass calibrator)
; this will be used in the fluxscale task
transfer = 0,1
; use this to manually set the VALID reference field ID of the flux calibrator.
; this will be used in the fluxscale task
reference = 0
```
because this is still a problem in CASA itself, e.g. casa can not solve for the field name either and wont fall back to the field ID, that is why I have to set it manually. PLease, you can use this data set as a test (however for the moment it does not have the corrected data column, so if you actually need to use it, just use the data collumn.)



claude --resume 1c28f149-e120-483d-bcfa-7be166f67bca