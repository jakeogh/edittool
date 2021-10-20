#!/usr/bin/env python3
# -*- coding: utf8 -*-

# flake8: noqa           # flake8 has no per file settings :(
# pylint: disable=C0111  # docstrings are always outdated and wrong
# pylint: disable=C0114  #      Missing module docstring (missing-module-docstring)
# pylint: disable=W0511  # todo is encouraged
# pylint: disable=C0301  # line too long
# pylint: disable=R0902  # too many instance attributes
# pylint: disable=C0302  # too many lines in module
# pylint: disable=C0103  # single letter var names, func name too descriptive
# pylint: disable=R0911  # too many return statements
# pylint: disable=R0912  # too many branches
# pylint: disable=R0915  # too many statements
# pylint: disable=R0913  # too many arguments
# pylint: disable=R1702  # too many nested blocks
# pylint: disable=R0914  # too many local variables
# pylint: disable=R0903  # too few public methods
# pylint: disable=E1101  # no member for base
# pylint: disable=W0201  # attribute defined outside __init__
# pylint: disable=R0916  # Too many boolean expressions in if statement
# pylint: disable=C0305  # Trailing newlines editor should fix automatically, pointless warning
# pylint: disable=C0413  # TEMP isort issue [wrong-import-position] Import "from pathlib import Path" should be placed at the top of the module [C0413]

import os
import shutil
import sys
import time
from signal import SIG_DFL
from signal import SIGPIPE
from signal import signal

import click
import sh
from walkup_until_found import walkup_until_found

signal(SIGPIPE, SIG_DFL)
from pathlib import Path
from typing import ByteString
from typing import Generator
from typing import Iterable
from typing import List
from typing import Optional
from typing import Sequence
from typing import Tuple
from typing import Union

from asserttool import eprint
from asserttool import ic
from asserttool import nevd
from asserttool import not_root
from asserttool import validate_slice
from asserttool import verify
from click_default_group import DefaultGroup
from configtool import click_read_config
from configtool import click_write_config_entry
from enumerate_input import enumerate_input
from hashtool import sha3_256_hash_file
from licenseguesser import license_list
from retry_on_exception import retry_on_exception
#from with_sshfs import sshfs
from with_chdir import chdir

#from pathtool import write_line_to_file
#from getdents import files


CFG, CONFIG_MTIME = click_read_config(click_instance=click,
                                      app_name='edittool',
                                      verbose=False,
                                      debug=False,)


# https://github.com/mitsuhiko/click/issues/441
CONTEXT_SETTINGS = dict(default_map=CFG)
    #dict(help_option_names=['--help'],
    #     terminal_width=shutil.get_terminal_size((80, 20)).columns)


ic(CFG)

@click.group(context_settings=CONTEXT_SETTINGS, cls=DefaultGroup, default='edit', default_if_no_args=True)
@click.option('--verbose', is_flag=True)
@click.option('--debug', is_flag=True)
@click.pass_context
def cli(ctx,
        verbose: bool,
        debug: bool,
        ):

    null, end, verbose, debug = nevd(ctx=ctx,
                                     printn=False,
                                     ipython=False,
                                     verbose=verbose,
                                     debug=debug,)


@cli.command()
@click.argument("path", type=click.Path(path_type=Path), nargs=1)
@click.option('--apps-folder', type=str, required=True)
@click.option('--gentoo-overlay-repo', type=str, required=True)
@click.option('--github-user', type=str, required=True)
@click.option('--license', type=click.Choice(license_list(verbose=False, debug=False,)), default="ISC")
@click.option('--verbose', is_flag=True)
@click.option('--debug', is_flag=True)
@click.pass_context
def edit(ctx,
         path: str,
         apps_folder: str,
         gentoo_overlay_repo: str,
         github_user: str,
         license: str,
         verbose: bool,
         debug: bool,
         ):

    not_root()

    null, end, verbose, debug = nevd(ctx=ctx,
                                     printn=False,
                                     ipython=False,
                                     verbose=verbose,
                                     debug=debug,)

    #global APP_NAME
    #config, config_mtime = click_read_config(click_instance=click,
    #                                         app_name=APP_NAME,
    #                                         verbose=verbose,
    #                                         debug=debug,)
    #if verbose:
    #    ic(config, config_mtime)

    #if add:
    #    section = "test_section"
    #    key = "test_key"
    #    value = "test_value"
    #    config, config_mtime = click_write_config_entry(click_instance=click,
    #                                                    app_name=APP_NAME,
    #                                                    section=section,
    #                                                    key=key,
    #                                                    value=value,
    #                                                    verbose=verbose,
    #                                                    debug=debug,)
    #    if verbose:
    #        ic(config)

    path = Path(os.fsdecode(path)).expanduser().resolve()
    if not path.is_file():
        eprint('ERROR:', path.as_posix(), 'is not a regular file.')
        sys.exit(1)

    try:
        _editor = os.environ['EDITOR']
    except KeyError:
        eprint('WARNING: $EDITOR enviromental variable is not set. Defaulting to /usr/bin/vim')
        _editor = '/usr/bin/vim'
    else:   # no exception happened
        if not Path(_editor).is_absolute():
            editor = shutil.which(_editor)
            eprint('WARNING: $EDITOR is {}, which is not an absolute path. Resolving to {}'.format(_editor, editor))
        else:
            editor = _editor
        del _editor

    if verbose:
        ic(editor, path)


    def parse_sh_var(*, item, var_name):
        if '{}="'.format(var_name) in item:
            result = item.split('=')[-1].strip('"').strip("'")
            return result

    edit_config = walkup_until_found(path=path.parent, name='.edit_config', verbose=verbose, debug=debug)
    ic(edit_config)
    project_folder = edit_config.parent

    with open(edit_config, 'r') as fh:
        edit_config_content = fh.read()

    ic(edit_config_content)
    edit_config_content = edit_config_content.splitlines()
    ic(edit_config_content)
    short_package = None
    group = None
    remote = None
    for item in edit_config_content:
        ic(item)
        if not short_package:
            short_package = parse_sh_var(item=item, var_name='short_package')
        if not group:
            group = parse_sh_var(item=item, var_name='group')
        if not remote:
            remote = parse_sh_var(item=item, var_name='remote')

        #if 'short_package="' in item:
        #    short_package = item.split('=')[-1].strip('"').strip("'")

    ic(short_package)
    ic(group)
    ic(remote)

    pre_edit_hash = sha3_256_hash_file(path=path, verbose=verbose, debug=debug)
    os.system(editor + ' ' + path.as_posix())
    post_edit_hash = sha3_256_hash_file(path=path, verbose=verbose, debug=debug)
    if pre_edit_hash != post_edit_hash:
        ic('file changed:', path)
        sh.git.diff(_out=sys.stdout, _err=sys.stderr)
        sh.isort('--remove-redundant-aliases', '--trailing-comma', '--force-single-line-imports', '--combine-star', '--verbose', path, _out=sys.stdout, _err=sys.stderr)  # https://pycqa.github.io/isort/
        sh.chown('user:user', path)  # fails if cant
        with chdir(project_folder):
            pylint_command = sh.Command('pylint')
            try:
                pylint_result = pylint_command(path, _out=sys.stdout, _err=sys.stderr, _tee=True, _ok_code=[0])
            #except sh.ErrorReturnCode_28:
            #    ic(28)
            #    pass
            except sh.ErrorReturnCode as e:
                ic(e)
                ic(e.exit_code)
                ic(dir(e))
                if (e.exit_code & 0b00011) > 0:
                    ic('pylint returned an error or worse, exiting')
                    exit(e.exit_code)

            ic(pylint_command)
            ic(dir(pylint_command))
            ic(pylint_command.stdout)
            ic(pylint_command.stderr)



            #sh.grep(sh.pylint(path, _exit_ok=[0]), '--color', '-E', '": E|$"', _out=sys.stdout, _err=sys.stderr)
