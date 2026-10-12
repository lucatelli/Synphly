"""
Command line interface.

    synphly init NAME --wd DIR [--asdm PATH] [--band B] [--hanning] [-o OUT]
                                         write a starter config for a new dataset
    synphly prepare CFG                  import the data, write the listobs, show the fields and suggested roles
    synphly run CFG [--from STEP] [--only STEP[,STEP]] [--force STEP[,STEP]|all] [--dry-run]
    synphly info CFG                     like prepare, for an existing MS, read-only (imports and writes nothing)
    synphly convert-config IN OUT [--minimal]
                                         convert a legacy INI config to TOML
    synphly steps                        list the pipeline steps

(``python -m synphly ...`` is equivalent.) CFG may be a TOML file or a legacy v0.5 INI file
(see ``synphly.config.load_config``).

--from STEP   resume at STEP; earlier outputs are read from <wd>/synphly_state.json
--only S1,S2  run only these steps (outputs of the other steps from the state)
--force S|all recompute the calibration tables of these steps (reuse_tables='never' for them)
--dry-run     show the steps that would run and the resolved field roles; runs no CASA task that modifies data
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

# Synphly is a batch pipeline: never let matplotlib pick a GUI backend. With DISPLAY set it defaults to Qt as
# soon as casatasks (plotweather) imports pyplot; Qt then registers with the X session manager, whose error
# handler calls exit(1) at interpreter shutdown, so a finished run returned status 1. Must run before any CASA or
# matplotlib import; an explicit MPLBACKEND from the user is respected.
os.environ.setdefault('MPLBACKEND', 'Agg')

log = logging.getLogger(__name__)


def _load(path):
    from .config import load_config
    return load_config(path)


def _console_logging():
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=logging.INFO, format='%(levelname)s %(message)s')


def cmd_run(args) -> int:
    from .pipeline import PipelineError, dry_run, run_pipeline
    cfg = _load(args.config)
    try:
        if args.dry_run:
            _console_logging()
            log.info(dry_run(cfg, from_step=args.from_step, only=args.only, force=args.force))
            return 0
        run_pipeline(cfg, from_step=args.from_step, only=args.only, force=args.force)
    except PipelineError as e:
        _console_logging()
        log.error(str(e))
        return 2
    return 0


def cmd_init(args) -> int:
    from .prepare import init_config
    _console_logging()
    out = init_config(args.name, args.wd, asdm_file=args.asdm or '', band=args.band or '', hanning=args.hanning,
                      output=args.output or '', force=args.force)
    log.info(f"Wrote {out}\nNext: synphly prepare {out}")
    return 0


def cmd_prepare(args) -> int:
    from .prepare import prepare
    _, text = prepare(_load(args.config))
    _console_logging()
    log.info('\n' + text)
    return 0


def cmd_info(args) -> int:
    from .prepare import inspect
    text = inspect(_load(args.config))
    _console_logging()
    log.info('\n' + text)
    return 0


def cmd_convert_config(args) -> int:
    from .config import convert_config
    _console_logging()
    convert_config(args.input, args.output, minimal=args.minimal)
    log.info(f"Wrote {args.output}")
    return 0


def cmd_steps(args) -> int:
    from .pipeline import steps_table
    _console_logging()
    log.info("Pipeline steps (in order) and the config switch enabling each:\n" + steps_table())
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog='synphly',
                                     description='Synphly: CASA pipeline for VLA continuum calibration.')
    from . import __version__
    parser.add_argument('--version', action='version', version=f'synphly {__version__}')
    sub = parser.add_subparsers(dest='command', metavar='COMMAND')
    sub.required = True

    p_init = sub.add_parser('init', help='write a starter config for a new dataset')
    p_init.add_argument('name', help='experiment name = MS name without .ms (e.g. 21A-024.sb...._K)')
    p_init.add_argument('--wd', required=True, help='working directory (all products are written here)')
    p_init.add_argument('--asdm', help='path of the SDM (default: <wd>/<name>); not needed if the MS exists')
    p_init.add_argument('--band', help='VLA band letter: L S C X U K A Q (default: guessed from the frequency)')
    p_init.add_argument('--hanning', action='store_true', help='Hanning-smooth the data after the import')
    p_init.add_argument('-o', '--output', help='config file to write (default: configs/datasets/<name>.toml)')
    p_init.add_argument('--force', action='store_true', help='overwrite an existing config file')
    p_init.set_defaults(func=cmd_init)

    p_prep = sub.add_parser('prepare', help='import the data (if needed), write the listobs, show the fields '
                                            'and the suggested [sources]; no flagging or calibration')
    p_prep.add_argument('config', help='config file (TOML or legacy INI)')
    p_prep.set_defaults(func=cmd_prepare)

    p_run = sub.add_parser('run', help='run the pipeline')
    p_run.add_argument('config', help='config file (TOML or legacy INI)')
    sel = p_run.add_mutually_exclusive_group()
    sel.add_argument('--from', dest='from_step', metavar='STEP',
                     help='resume at STEP (earlier outputs from <wd>/synphly_state.json)')
    sel.add_argument('--only', metavar='STEP[,STEP]', help='run only these steps')
    p_run.add_argument('--force', metavar='STEP[,STEP]|all',
                       help="recompute the calibration tables of these steps ('all' = every step)")
    p_run.add_argument('--dry-run', action='store_true',
                       help='show the steps that would run and the field roles; modify nothing')
    p_run.set_defaults(func=cmd_run)

    p_info = sub.add_parser('info', help='like prepare, for an MS that already exists; read-only')
    p_info.add_argument('config', help='config file (TOML or legacy INI)')
    p_info.set_defaults(func=cmd_info)

    p_conv = sub.add_parser('convert-config', help='convert a legacy INI config to TOML')
    p_conv.add_argument('input', help='legacy INI config')
    p_conv.add_argument('output', help='output TOML file')
    p_conv.add_argument('--minimal', action='store_true',
                        help='write only the keys that differ from the defaults')
    p_conv.set_defaults(func=cmd_convert_config)

    p_steps = sub.add_parser('steps', help='list the pipeline steps')
    p_steps.set_defaults(func=cmd_steps)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    from .config import ConfigError
    from .fields import FieldModelError
    try:
        return args.func(args)
    except (ConfigError, FieldModelError) as e:
        # problems with the user's input: the message says what to fix, a traceback adds nothing
        _console_logging()
        log.error(str(e))
        return 2
    except FileExistsError as e:
        _console_logging()
        log.error(str(e))
        return 2
    except FileNotFoundError:
        if getattr(args, 'config', None) and not os.path.exists(args.config):
            _console_logging()
            log.error(f"Config file not found: {args.config}")
            return 2
        raise


if __name__ == '__main__':
    sys.exit(main())
