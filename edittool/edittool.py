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
import subprocess
import sys
from pathlib import Path
#import time
from signal import SIG_DFL
from signal import SIGPIPE
from signal import signal
from typing import ByteString
from typing import Generator
from typing import Iterable
from typing import List
from typing import Optional
from typing import Sequence
from typing import Tuple
from typing import Union

import click
import sh
from asserttool import eprint
from asserttool import ic
from asserttool import not_root
from asserttool import tv
from asserttool import validate_slice
from click_default_group import DefaultGroup
from clicktool import click_add_options
from clicktool import click_global_options
from configtool import click_read_config
#from configtool import click_write_config_entry
#from enumerate_input import enumerate_input
from hashtool import sha3_256_hash_file
from licenseguesser import license_list
from retry_on_exception import retry_on_exception
from walkup_until_found import walkup_until_found
from with_chdir import chdir

signal(SIGPIPE, SIG_DFL)
#from pathtool import write_line_to_file


CFG, CONFIG_MTIME = click_read_config(click_instance=click,
                                      app_name='edittool',
                                      verbose=False,
                                      )


# https://github.com/mitsuhiko/click/issues/441
CONTEXT_SETTINGS = dict(default_map=CFG)
    #dict(help_option_names=['--help'],
    #     terminal_width=shutil.get_terminal_size((80, 20)).columns)


ic(CFG)

import errno
import os
import pty
import select
import subprocess


def tty_capture(cmd, bytes_input):
    """Capture the output of cmd with bytes_input to stdin,
    with stdin, stdout and stderr as TTYs.

    Based on Andy Hayden's gist:
    https://gist.github.com/hayd/4f46a68fc697ba8888a7b517a414583e
    """
    mo, so = pty.openpty()  # provide tty to enable line-buffering
    me, se = pty.openpty()
    mi, si = pty.openpty()

    p = subprocess.Popen(
        cmd,
        bufsize=1, stdin=si, stdout=so, stderr=se,
        close_fds=True)
    for fd in [so, se, si]:
        os.close(fd)
    os.write(mi, bytes_input)

    timeout = 0.04  # seconds
    readable = [mo, me]
    result = {mo: b'', me: b''}
    try:
        while readable:
            ready, _, _ = select.select(readable, [], [], timeout)
            for fd in ready:
                try:
                    data = os.read(fd, 512)
                except OSError as e:
                    if e.errno != errno.EIO:
                        raise
                    # EIO means EOF on some systems
                    readable.remove(fd)
                else:
                    if not data: # EOF
                        readable.remove(fd)
                    result[fd] += data

    finally:
        for fd in [mo, me, mi]:
            os.close(fd)
        if p.poll() is None:
            p.kill()
        p.wait()

    return result[mo], result[me]

#out, err = tty_capture(["python", "test.py"], b"abc\n")
#print((out, err))




def unstaged_commits_exist(path):
    _git = sh.Command("/home/cfg/git/unstaged_changes_exist_for_file.sh")
    try:
        _git(path.as_posix())
    except sh.ErrorReturnCode_1:
        return True
    return False


def parse_sh_var(*, item, var_name):
    if f'{var_name}="' in item:
        result = item.split('=')[-1].strip('"').strip("'")
        return result


def parse_edit_config(*,
                      path: Path,
                      verbose: bool,
                      ):
    edit_config = walkup_until_found(path=path.parent, name='.edit_config', verbose=verbose,)
    #ic(edit_config)

    with open(edit_config, 'r', encoding='utf8') as fh:
        edit_config_content = fh.read()

    #ic(edit_config_content)
    edit_config_content = edit_config_content.splitlines()
    #ic(edit_config_content)
    short_package = None
    group = None
    remote = None
    test_command_arg = None
    for item in edit_config_content:
        #ic(item)
        if not short_package:
            short_package = parse_sh_var(item=item, var_name='short_package')
        if not group:
            group = parse_sh_var(item=item, var_name='group')
        if not remote:
            remote = parse_sh_var(item=item, var_name='remote')
        if not test_command_arg:
            test_command_arg = parse_sh_var(item=item, var_name='test_command_arg')

    ic(short_package)
    ic(group)
    ic(remote)
    ic(test_command_arg)
    return edit_config, short_package, group, remote, test_command_arg


def autogenerate_readme(*,
                        path: Path,
                        verbose: bool,
                        ):

    def append_line_to_readme(line, readme):
        with open(readme, 'a', encoding='utf8') as fh:
            fh.write(line)

    autogenerate_readme = walkup_until_found(path=path.parent, name='.autogenerate_readme', verbose=verbose,)
    with open(autogenerate_readme, 'r', encoding='utf8') as fh:
        commands = [cmd.strip() for cmd in fh if cmd.strip()]
    ic(commands)
    readme = autogenerate_readme.parent / Path('README.md')
    ic(readme)

    edit_config, short_package, group, remote, test_command_arg = parse_edit_config(path=path, verbose=verbose,)
    try:
        readme.unlink()
    except FileNotFoundError:
        pass
    #with open(readme, 'w', encoding='utf8') as fh:
    append_line_to_readme(f'```\n$ {short_package}\n', readme)

    test_command = sh.Command(short_package)
    ic(test_command)
    test_command = test_command.bake(test_command_arg)
    ic(test_command)
    with open(readme, 'a', encoding='utf8') as fh:
        test_command(_err=fh, _ok_code=[0, 1])

    tty = False
    for command in commands[1:]:
        ic(command)
        if tty:
            #out, err = tty_capture(command, b'')
            os.system('colorpipe ' + command + ' >> ' + readme.as_posix())
            tty = False
            #ic(out, err)
            continue
        if command == '#tty:':
            tty = True
            continue

        append_line_to_readme(f'\n$ {command}\n', readme)

        with open(readme, 'a', encoding='utf8') as fh:
            popen_instance = subprocess.Popen(command,
                                              stdout=fh,
                                              stderr=fh,
                                              shell=True,)
            output, errors = popen_instance.communicate()
            exit_code = popen_instance.returncode
            ic(output, errors, exit_code)

    append_line_to_readme('\n```\n', readme)

    return


def run_pylint(*,
               path: Path,
               ignore_pylint: bool,
               verbose: int,
               ):
    pylint_command = sh.Command('pylint')
    try:
        pylint_result = pylint_command(path, _ok_code=[0])
        sh.grep('--color', '-E', ': E|$', _out=sys.stdout, _err=sys.stderr, _in=pylint_result.stdout)

    except sh.ErrorReturnCode as e:
        ic(e.exit_code)
        sh.grep('--color', '-E', ': E|$', _out=sys.stdout, _err=sys.stderr, _in=e.stdout)
        exit_code = e.exit_code
        if (exit_code & 0b00011) > 0:
            ic('pylint returned an error or worse, exiting')
            if not ignore_pylint:
                sys.exit(exit_code)



@click.group(context_settings=CONTEXT_SETTINGS, cls=DefaultGroup, default='edit', default_if_no_args=True)
@click_add_options(click_global_options)
@click.pass_context
def cli(ctx,
        verbose: int,
        verbose_inf: bool,
        ):

    tty, verbose = tv(ctx=ctx,
                      verbose=verbose,
                      verbose_inf=verbose_inf,
                      )


@cli.command()
@click.argument("path", type=click.Path(path_type=Path), nargs=1)
@click.option('--apps-folder', type=str, required=True)
@click.option('--gentoo-overlay-repo', type=str, required=True)
@click.option('--github-user', type=str, required=True)
@click.option('--license', type=click.Choice(license_list(verbose=False,)), default="ISC")
@click.option('--disable-change-detection', is_flag=True)
@click.option('--ignore-pylint', is_flag=True)
@click.option('--skip-isort', is_flag=True)
@click.option('--skip-pylint', is_flag=True)
@click.option('--ignore-checks', 'skip_code_checks', is_flag=True)
@click_add_options(click_global_options)
@click.pass_context
def edit(ctx,
         path: Path,
         apps_folder: str,
         gentoo_overlay_repo: str,
         github_user: str,
         license: str,
         verbose: bool,
         verbose_inf: bool,
         disable_change_detection: bool,
         ignore_pylint: bool,
         skip_isort: bool,
         skip_pylint: bool,
         skip_code_checks: bool,
         ):

    not_root()
    tty, verbose = tv(ctx=ctx,
                      verbose=verbose,
                      verbose_inf=verbose_inf,
                      )

    if skip_code_checks:
        skip_isort = True
        skip_pylint = True

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

    edit_config = None
    project_folder = None
    group = None
    remote = None
    try:
        edit_config, short_package, group, remote, test_command_arg = parse_edit_config(path=path, verbose=verbose,)
        project_folder = edit_config.parent
    except FileNotFoundError:
        if not path.as_posix().endswith('.ebuild'):
            ic('NO .edit_config found, and its not an ebuild, exiting...')
            return

    pre_edit_hash = sha3_256_hash_file(path=path, verbose=verbose,)
    os.system(editor + ' ' + path.as_posix())
    post_edit_hash = sha3_256_hash_file(path=path, verbose=verbose,)
    if pre_edit_hash != post_edit_hash:
        ic('file changed:', path, pre_edit_hash, post_edit_hash,)
    if unstaged_commits_exist(path):
        ic('unstaged_commits_exist() returned True')
    if (pre_edit_hash != post_edit_hash) or disable_change_detection or unstaged_commits_exist(path):
        if project_folder:
            os.chdir(project_folder)
            #with chdir(project_folder):
            sh.git.diff(_out=sys.stdout, _err=sys.stderr)

        sh.chown('user:user', path)  # fails if cant

        if path.as_posix().endswith('.py'):
            if not skip_isort:
                sh.isort('--remove-redundant-aliases', '--trailing-comma', '--force-single-line-imports', '--combine-star', '--verbose', path, _out=sys.stdout, _err=sys.stderr, _in=sys.stdin)  # https://pycqa.github.io/isort/

            if not skip_pylint:
                run_pylint(path=path, ignore_pylint=ignore_pylint, verbose=verbose,)
                # Pylint should leave with following status code:
                #   * 0 if everything went fine
                # F * 1 if a fatal message was issued
                # E * 2 if an error message was issued
                # W * 4 if a warning message was issued
                # R * 8 if a refactor message was issued
                # C * 16 if a convention message was issued
                #   * 32 on usage error
                # status 1 to 16 will be bit-ORed

        elif  path.as_posix().endswith('.ebuild'):
            with chdir(path.resolve().parent):
                sh.ebuild(path, 'manifest')
                sh.git.add(path.parent / Path('Manifest'))
                sh.git.add(path)
                #cd "${file_dirname}" # should already be here...
                try:
                    sh.repoman(_out=sys.stdout, _err=sys.stderr, _in=sys.stdin, _ok_code=[0, 1])
                except sh.ErrorReturnCode_1 as e:
                    ic(e)
                    print(e.stdout)

                sh.git.add('-u', _out=sys.stdout, _err=sys.stderr, _in=sys.stdin)
                sh.git.commit('--verbose', '-m', 'auto-commit', _out=sys.stdout, _err=sys.stderr, _in=sys.stdin)
                sh.git.push(_out=sys.stdout, _err=sys.stderr, _in=sys.stdin)
                #sh.git.push(_out=sys.stdout, _err=sys.stderr, _in=sys.stdin, _tty_in=True)
                #sh.git.push(_out=sys.stdout, _err=sys.stderr, _tty_in=True)
                sh.sudo.emaint('sync', '-A', _fg=True)
                sys.exit(0)

        elif path.as_posix().endswith('.c'):
            splint_command = sh.Command('splint')
            splint_result = splint_command(path, _out=sys.stdout, _err=sys.stderr, _in=sys.stdin, _tee=True, _ok_code=[0, 1])

        elif path.as_posix().endswith('.sh'):
            shellcheck_command = sh.Command('shellcheck')
            shellcheck_result = shellcheck_command(path, _out=sys.stdout, _err=sys.stderr, _in=sys.stdin, _tee=True, _ok_code=[0, 1])  # TODO

        sh.git.add(path)  # covered below too
        sh.git.add('-u')  # all tracked files

        unstaged_changes_exist_command = sh.Command('git')
        unstaged_changes_exist_command_result = unstaged_changes_exist_command('diff-index', 'HEAD', '--')
        print(unstaged_changes_exist_command_result)
        if path.as_posix() in unstaged_changes_exist_command_result:
            sh.git.add(path)

        sh.git.diff('--cached')
        try:
            staged_but_uncomitted_changes_exist_command = sh.git.diff('--cached', '--exit-code')
        except sh.ErrorReturnCode_1:
            ic('comitting')
            sh.git.add('-u')  # all tracked files
            sh.git.commit('--verbose', '-m', 'auto-commit')
            if remote and Path(edit_config.parent / Path('.enable_push')).is_file():
                try:
                    sh.git.push()
                    sh.sudo.emaint('sync', '-A', _fg=True)
                except sh.ErrorReturnCode_128 as e:
                    ic(e)
                    ic(e.stdout)
                    ic(e.stderr)
                    ic('remote not found')

            else:
                ic('push is not enabled, changes comitted locally')

            #with sh.contrib.sudo:
            #    sh.emerge('--tree', '--quiet-build=y', '--usepkg=n', '-1', '{group}/{short_package}'.format(group=group, short_package=short_package), _out=sys.stdout, _err=sys.stderr)

            sh.sudo.emerge('--tree', '--quiet-build=y', '--usepkg=n', '-1', '{group}/{short_package}'.format(group=group, short_package=short_package), _fg=True)
            try:
                help_command = sh.Command(short_package)
            except sh.CommandNotFound as e:
                ic(e)
            else:
                help_command_result = help_command('--help', _out=sys.stdout, _err=sys.stderr, _in=sys.stdin)


@cli.command()
@click.argument("path", type=click.Path(path_type=Path), nargs=1)
@click_add_options(click_global_options)
@click.pass_context
def generate_readme(ctx,
                    path: Path,
                    verbose: bool,
                    verbose_inf: bool,
                    ):

    not_root()
    tty, verbose = tv(ctx=ctx,
                      verbose=verbose,
                      verbose_inf=verbose_inf,
                      )

    path = Path(os.fsdecode(path)).expanduser().resolve()
    if not path.is_file():
        eprint('ERROR:', path.as_posix(), 'is not a regular file.')
        sys.exit(1)

    autogenerate_readme(path=path, verbose=verbose)

