def run_aoflagger_sif(vis):

    """
    Executes singularity containers from python

    """
    

    try:
        container = aoflagger_sif
        if os.path.exists(container):
            logging.info(f"Found {container}")
            singularity_bind = os.path.join(os.path.dirname(os.path.dirname(aoflagger_sif)))
            logging.info(f"You are binding singularity to {singularity_bind}")

    except FileNotFoundError:
        logging.critical(f"AOflagger singularity container not found")
 
    
    strategy = ['aoflagger', '-v', '-indirect-read', '-fields', '', '-strategy', aoflagger_strategy, vis]

    command_to_execute = ['singularity', 'exec', '-B', singularity_bind, container] + strategy
    try:
        logging.info("Executing: %s", ' '.join(command_to_execute))
        process = subprocess.Popen(command_to_execute, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True)
        stdout, stderr = process.communicate()
        logging.info("stdout: %s", stdout)
        logging.info("stderr: %s", stderr)

        return_code = process.returncode
        if return_code == 0:
            logging.info(f"Strategy executed successfully. Output:\n{stdout}")
        else:
            logging.critical(f"Error executing strategy. Return code: {return_code}\nError message: {stderr}")  

    except Exception as e:
        logging.critical(f"An error occurred: {e}")


def run_aoflagger_nat(vis):
    """
    Executes aoflagger in native mode (this is for debugging purposes only).

    """

    if report_verbosity >= 2:
        logging.info('Reporting data flagged before running aoflagger ...')
        summary_before_aoflagger = flagdata(vis=vis, mode='summary')
        report_flag(summary_before_aoflagger, 'field')

    strategy = (['aoflagger', '-v', '-j','6', '-direct-read', '-fields', '', '-strategy',
                aoflagger_strategy,vis])

    command_to_execute =  strategy
    try:
        logging.info("Executing: %s", ' '.join(command_to_execute))
        process = subprocess.Popen(command_to_execute, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, universal_newlines=True)
        stdout, stderr = process.communicate()
        logging.info("stdout: %s", stdout)
        logging.info("stderr: %s", stderr)

        return_code = process.returncode
        if return_code == 0:
            logging.info(f"Strategy executed successfully. Output:\n{stdout}")
        else:
            logging.critical(
                f"Error executing strategy. Return code: {return_code}\nError message: {stderr}")

        if report_verbosity >= 2:
            logging.info('Reporting data flagged after running aoflagger ...')
            summary_after_aoflagger = flagdata(vis=vis, mode='summary')
            report_flag(summary_after_aoflagger, 'field')

    except Exception as e:
        logging.critical(f"An error occurred: {e}")

def tfcrop_raw(vis,field):
    logging.info("Running tfcrop on raw data.")

    logging.info("Creating flag backup before tfcrop.")
    flagmanager(vis=vis, mode='save',
                versionname='flags_before_tfcrop_init',
                comment='Flagbackup before initial tfcrop.')

    summary_before_tfcrop = flagdata(vis=vis, mode='summary')
    report_flag(summary_before_tfcrop, 'field')

    flagdata(vis=vis, mode='tfcrop', field=field, display='', spw='',
                       datacolumn='data', ntime='scan', combinescans=False,
                       extendflags=False, flagnearfreq=False, flagneartime=False,
                       growaround=False,
                       timecutoff=3.0, freqcutoff=3.0, maxnpieces=5, winsize=7,
                       action='apply', flagbackup=False, savepars=True
                       )

    flagdata(vis=vis, mode='extend', field=field, spw='', display='report',
                       action='apply', datacolumn='data', combinescans=False, flagbackup=False,
                       growtime=75.0, growfreq=75.0, extendpols=True)

    summary_after_tfcrop = flagdata(vis=vis, mode='summary')
    report_flag(summary_after_tfcrop, 'field')

    logging.info("Creating flag backup after tfcrop.")
    flagmanager(vis=vis, mode='save', versionname='flags_after_tfcrop_init',
                comment='Flags after tfcrop on raw flagged data')
    pass


def report_flag(summary, axis):
    logging.info("REPORTING FLAGGING STATS")
    try:
        for id, stats in summary[axis].items():
            logging.info('%s %s: %5.1f percent flagged' % (axis, id, 100. * stats['flagged'] / stats['total']))
    except Exception as e:
        logging.info(f"Exception {e} while reporting flags")
    

def run_rflag(vis,i, field):
    logging.info("Running rflag")
    summary_before_rflag = flagdata(vis=vis, mode='summary')
    report_flag(summary_before_rflag, 'field')

    datacolumn_to_flag = 'corrected'
    
    try:
        logging.info(f"Flagging column {datacolumn_to_flag}")
        flagdata(vis=vis, mode='rflag', field=field, spw='', display='report',
                datacolumn=datacolumn_to_flag, ntime='scan', combinescans=False,
                extendflags=False, winsize=7, timedevscale=3.0, freqdevscale=3.0,
                flagnearfreq=False, flagneartime=False, growaround=True,
                action='apply', flagbackup=False, savepars=True
                )

        flagdata(vis=vis, field=field, spw='',
                datacolumn=datacolumn_to_flag,
                mode='extend', action='apply', display='report',
                flagbackup=False, growtime=75.0,
                growfreq=75.0, extendpols=False)
    except Exception as e:
        logging.error(f"Exception {e} occured while running flagdata")

    summary_after_rflag = flagdata(vis=vis, mode='summary')
    report_flag(summary_after_rflag, 'field')


def manual_flagging():
    
    logging.info(f'Flagging using user supplied flagging file {manual}')
    try:
        flagdata(vis=vis, mode='list',inpfile=manual_file, flagbackup=False)
        versionname = 'manual_flagging_1'
        logging.info(f'Creating new flagbackup file version {manual_flagging_1}')
        flagmanager(vis=vis, mode='save', versionname=versionname,
                    comment='First run of manual flagging.')
        if report_verbosity >= 1:
            summary_after_manual = flagdata(vis=vis, mode='summary')
            report_flag(summary_after_manual, 'field')
            # report_flag(summary_after_manual,'scan')
            # report_flag(summary_after_manual,'antenna')
    except:
        logging.warning('Supply a manual flagging file')




def pre_flagging(vis):

    """
    Pre-flagging to the data.
    """
    flags_dir = os.path.join(working_directory).rstrip('/')+'/'+'flags'
    plots_dir = os.path.join(working_directory).rstrip('/')+'/'+ 'plots'

    pre_flagging_starttime = time.time()

    try:
        logging.info('Creating flagbackup file for original ms')
        flagmanager(vis=vis, mode='save', versionname='original_flags_import',
                    comment='Original flags from import.')
    except Exception as e:
        logging.warning("Exception {e} when saving flags")

    logging.info('Starting pre-flagging to the data.')

    if report_verbosity >= 2:
        logging.info('Reporting data flagged at start ...')
        summary_0 = flagdata(vis=vis, mode='summary')
        report_flag(summary_0, 'field')
        # report_flag(summary_0,'scan')
        # report_flag(summary_0,'antenna')

    plotants(vis=vis, logpos=True, figfile=plots_dir.rstrip('/')+'/'+'_plotant_log.pdf')
    plotants(vis=vis, logpos=False, figfile=plots_dir.rstrip('/')+'/'+'_plotant.pdf')

    # if report_verbosity >= 2:
    #     print('     ## Reporting data flagged after online flagging...')
    #     summary_online = flagdata(vis=vis, mode='summary')
    #     report_flag(summary_online,'field')
    #     # report_flag(summary_online,'scan')
    #     # report_flag(summary_online,'antenna')

    try:
        logging.info('Flagging autocorrelations')
        flagdata(vis=vis, mode='manual', autocorr=True,
                reason='autocorr', flagbackup=False, action='apply',
                name='autocorr')
    except Exception as e:
        logging.error(f"Exception {e} while flagging autocorrelations")

    if report_verbosity >= 2:
        logging.info('Reporting flagged data after autocorr flagging...')
        summary_autocorr = flagdata(vis=vis, mode='summary')
        report_flag(summary_autocorr, 'field')
        # report_flag(summary_autocorr,'scan')
        # report_flag(summary_autocorr,'antenna')
    try:   
        logging.info('Shadow flagging the data')
        flagdata(vis=vis, mode='shadow', reason='shadow', tolerance=0.0,
             flagbackup=False, name='shadow', action='apply')
    except Exception as e:
        logging.error(f"Exception {e} while shadow flagging")

    if report_verbosity >= 2:
        logging.info('Reporting data flagged after shadow flagging...')
        summary_2 = flagdata(vis=vis, mode='summary')
        report_flag(summary_2, 'field')
        # report_flag(summary_2,'scan')

    # flag zeros data (flagm data with zero values/amplitudes)
    try:
        print('Clipping the data')
        flagdata(vis=vis, mode='clip', correlation='ABS_ALL', clipzeros=True,
                reason='clip', flagbackup=False, action='apply', name='clip')
    except Exception as e:
        logging.error(f"Exception {e} while clipping")

    if report_verbosity >= 2:
        logging.info('Reporting data flagged after clipping')
        summary_4 = flagdata(vis=vis, mode='summary')
        report_flag(summary_4, 'field')
        # report_flag(summary_4,'scan')

    # quack flagging (time to the telescope to go to the source)
    #  get scan length -- change the quack

    try:
        logging.info('Quacking the data')
        flagdata(vis=vis, mode='quack', quackinterval=5.0, quackmode='beg',
                reason='quack', flagbackup=False, action='apply', name='quack')
    except Exception as e:
        logging.error(f"Exception {e} while quacking")

    if report_verbosity >= 2:
        logging.info('Reporting data flagged after quack flagging...')
        summary_5 = flagdata(vis=vis, mode='summary')
        report_flag(summary_5, 'field')
        # report_flag(summary_5,'scan')

    try:
        logging.info('Creating new flagbackup file after pre-flagging.')
        flagmanager(vis=vis, mode='save', versionname='pre_flagging',
                    comment='Pre-flags applied: Autocorr,clipping, quack, shadow.')
    except Exception as e:
        logging.error(f"Exception {e} encountered while backing up flags")

    # Further flagging (manual inspections)

    # if apply_tfcrop_init == True:
    #     print(' >> Performing tfcrop on raw data...')

    #     summary_before_tfcrop = flagdata(vis=vis, mode='summary')
    #     if report_verbosity >= 1:
    #         print('     => Reporting flags before tfcrop')
    #         report_flag(summary_before_tfcrop, 'field')
    #         # report_flag(summary_before_tfcrop,'scan')
    #         # report_flag(summary_before_tfcrop,'antenna')
    #         # report_flag(summary_before_tfcrop,'spw')
    #     flagmanager(vis=vis, mode='save', versionname='flags_before_tfcrop_init',
    #                 comment='Flags beforet tfcrop on raw flagged data')
    #     # flagdata(vis=vis, mode='tfcrop',datacolumn='data',
    #     #     action='apply',display='',reason='tfcrop',
    #     #     name='tfcrop',flagbackup=False,outfile='tfcrop_flag')
    #     flagdata(vis=vis, mode='tfcrop', field=calibrators_all, display='', spw='',
    #              datacolumn='data', ntime='scan', combinescans=False,
    #              extendflags=False, flagnearfreq=False, flagneartime=False,
    #              growaround=False,
    #              timecutoff=3.0, freqcutoff=3.0, maxnpieces=5, winsize=7,
    #              action='apply', flagbackup=False, savepars=True
    #              )

    #     flagdata(vis=vis, mode='extend', field=calibrators_all, spw='', display='report',
    #              action='apply', datacolumn='data', combinescans=False, flagbackup=False,
    #              growtime=75.0, growfreq=75.0, extendpols=True)

    #     flagmanager(vis=vis, mode='save', versionname='flags_after_tfcrop_init',
    #                 comment='Flags after tfcrop on raw flagged data')

    #     print('     => Reporting flags after applied tfcrop')
    #     summary_after_tfcrop = flagdata(vis=vis, mode='summary')
    #     report_flag(summary_after_tfcrop, 'field')
    #     report_flag(summary_after_tfcrop, 'scan')
        # report_flag(summary_after_tfcrop,'antenna')
        # report_flag(summary_after_tfcrop,'spw')
    # summary_7 = flagdata(vis=vis, mode='summary',field='')



    logging.info('Total data after initial flagging')
    summary_pre_cal = flagdata(vis=vis, mode='summary')
    report_flag(summary_pre_cal, 'field')
    report_flag(summary_pre_cal, 'scan')
    # report_flag(summary_pre_cal,'antenna')

    pre_flagging_endtime = time.time() 
    pre_flagging_time = pre_flagging_endtime - pre_flagging_starttime 
    
    logging.info(f"Initial flagging took {pre_flagging_time/ 60:.2f} minutes")
    
    """Remember to flag edge channels in each spw
    Also, we need to flag congig/pointing scans intent. 
    If not flagging pointing scans, weird things can happen. 
    """