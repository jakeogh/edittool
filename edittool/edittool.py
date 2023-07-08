#!/usr/bin/env python3
# -*- coding: utf8 -*-

# pylint: disable=useless-suppression             # [I0021]
# pylint: disable=missing-docstring               # [C0111] docstrings are always outdated and wrong
# pylint: disable=missing-module-docstring        # [C0114] Missing module docstring
# pylint: disable=fixme                           # [W0511] todo is encouraged
# pylint: disable=line-too-long                   # [C0301]
# pylint: disable=too-many-instance-attributes    # [R0902]
# pylint: disable=too-many-lines                  # [C0302] too many lines in module
# pylint: disable=invalid-name                    # [C0103] single letter var names, func name too descriptive
# pylint: disable=too-many-return-statements      # [R0911]
# pylint: disable=too-many-branches               # [R0912]
# pylint: disable=too-many-statements             # [R0915]
# pylint: disable=too-many-arguments              # [R0913]
# pylint: disable=too-many-nested-blocks          # [R1702]
# pylint: disable=too-many-locals                 # [R0914]
# pylint: disable=too-few-public-methods          # [R0903]
# pylint: disable=no-member                       # [E1101] no member for base
# pylint: disable=attribute-defined-outside-init  # [W0201]
# pylint: disable=too-many-boolean-expressions    # [R0916] in if statement

from __future__ import annotations

import errno
import logging
import os
import pty
import select
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from signal import SIG_DFL
from signal import SIGPIPE
from signal import signal

import click
import sh
from asserttool import gvd
from asserttool import ic
from asserttool import icp
from asserttool import not_root
from byte_vector_replacer import GuardFoundError
from byte_vector_replacer import byte_vector_replacer
from byte_vector_replacer import get_pairs
from click_default_group import DefaultGroup
from clicktool import click_add_options
from clicktool import click_global_options
from clicktool import tv
from configtool import click_read_config
from eprint import eprint
from gittool import unstaged_commits_exist
from hashtool import sha3_256_hash_file
from licenseguesser import license_list
from portagetool import package_atom_installed
from unmp import unmp
from walkup_until_found import walkup_until_found
from with_chdir import chdir

# from retry_on_exception import retry_on_exception
logging.basicConfig(level=logging.INFO)

signal(SIGPIPE, SIG_DFL)

# pylint: disable=no-name-in-module  # E0611 # No name 'ErrorReturnCode_1' in module 'sh'
from sh import ErrorReturnCode_1

# pylint: enable=no-name-in-module

CFG, CONFIG_MTIME = click_read_config(
    click_instance=click,
    app_name="edittool",
)


# https://github.com/mitsuhiko/click/issues/441
CONTEXT_SETTINGS = dict(default_map=CFG)
# dict(help_option_names=['--help'],
#     terminal_width=shutil.get_terminal_size((80, 20)).columns)


ic(CFG)


def append_line_to_readme(*, line: str, readme: Path):
    with open(readme, "a", encoding="utf8") as fh:
        fh.write(line)


def tty_capture(cmd, bytes_input):
    """Capture the output of cmd with bytes_input to stdin,
    with stdin, stdout and stderr as TTYs.

    Based on Andy Hayden's gist:
    https://gist.github.com/hayd/4f46a68fc697ba8888a7b517a414583e
    """
    mo, so = pty.openpty()  # provide tty to enable line-buffering
    me, se = pty.openpty()
    mi, si = pty.openpty()

    p = subprocess.Popen(cmd, bufsize=1, stdin=si, stdout=so, stderr=se, close_fds=True)
    for fd in [so, se, si]:
        os.close(fd)
    os.write(mi, bytes_input)

    timeout = 0.04  # seconds
    readable = [mo, me]
    result = {mo: b"", me: b""}
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
                    if not data:  # EOF
                        readable.remove(fd)
                    result[fd] += data

    finally:
        for fd in [mo, me, mi]:
            os.close(fd)
        if p.poll() is None:
            p.kill()
        p.wait()

    return result[mo], result[me]


# out, err = tty_capture(["python", "test.py"], b"abc\n")
# print((out, err))


def parse_sh_var(*, item, var_name):
    if f'{var_name}="' in item:
        result = item.split("=")[-1].strip('"').strip("'")
        return result


def parse_edit_config(
    *,
    path: Path,
    verbose: bool | int | float = False,
):
    edit_config = walkup_until_found(
        path=path.parent,
        name=".edit_config",
    )
    # ic(edit_config)

    with open(edit_config, "r", encoding="utf8") as fh:
        edit_config_content = fh.read()

    # ic(edit_config_content)
    edit_config_content = edit_config_content.splitlines()
    # ic(edit_config_content)
    short_package = None
    group = None
    remote = None
    test_command_arg = None
    dont_reformat = None
    install_command = None
    for item in edit_config_content:
        # ic(item)
        if not short_package:
            short_package = parse_sh_var(item=item, var_name="short_package")
        if not group:
            group = parse_sh_var(item=item, var_name="group")
        if not remote:
            remote = parse_sh_var(item=item, var_name="remote")
        if not test_command_arg:
            test_command_arg = parse_sh_var(item=item, var_name="test_command_arg")
        if not dont_reformat:
            dont_reformat = parse_sh_var(item=item, var_name="dont_reformat")
        if not install_command:
            install_command = parse_sh_var(item=item, var_name="install_command")

    ic(short_package)
    ic(group)
    ic(remote)
    ic(test_command_arg)
    ic(dont_reformat)
    ic(install_command)

    return (
        edit_config,
        short_package,
        group,
        remote,
        test_command_arg,
        dont_reformat,
        install_command,
    )


def autogenerate_readme(
    *,
    path: Path,
    verbose: bool | int | float = False,
):
    try:
        autogenerate_readme_script = walkup_until_found(
            path=path.parent,
            name=".autogenerate_readme.sh",
        )
    except FileNotFoundError as e:
        ic(e)
        return

    (
        edit_config,
        short_package,
        group,
        remote,
        test_command_arg,
        dont_reformat,
        install_command,
    ) = parse_edit_config(
        path=path,
    )

    package_atom = f"{group}/{short_package}"
    if not package_atom_installed(package_atom):
        return

    with open(autogenerate_readme_script, "r", encoding="utf8") as fh:
        commands = [cmd.strip() for cmd in fh if cmd.strip()]
    ic(commands)

    readme_comment = (
        """<!--- NOTE! THIS FILE IS AUTOMATICALLY GENERATED, IF YOU ARE READING THIS, YOU ARE EDITING THE WRONG FILE --->"""
        + "\n"
    )

    readme_md = autogenerate_readme_script.parent / Path("README.md")
    ic(readme_md)

    description_md = autogenerate_readme_script.parent / Path(".description.md")
    ic(description_md)

    install_md = autogenerate_readme_script.parent / Path(".install.md")
    ic(install_md)

    _postprocess_readme_script = autogenerate_readme_script.parent / Path(
        ".postprocess_readme.sh"
    )
    ic(_postprocess_readme_script)
    _validate_readme_script = autogenerate_readme_script.parent / Path(
        ".validate_readme.sh"
    )
    ic(_validate_readme_script)

    try:
        readme_md.unlink()
    except FileNotFoundError:
        pass

    with open(description_md, "r", encoding="utf8") as fh:
        append_line_to_readme(line=readme_comment, readme=readme_md)
        append_line_to_readme(line=fh.read(), readme=readme_md)

    with open(install_md, "r", encoding="utf8") as fh:
        append_line_to_readme(line=fh.read(), readme=readme_md)

    append_line_to_readme(line="### Examples:\n", readme=readme_md)
    # append_line_to_readme(line=f"```\n$ {short_package}\n", readme=readme_md)
    append_line_to_readme(line="```", readme=readme_md)

    # test_command = sh.Command(short_package)
    # ic(test_command)
    # test_command = test_command.bake(test_command_arg)
    # ic(test_command)
    # with open(readme_md, "a", encoding="utf8") as fh:
    #    test_command(_err=fh, _ok_code=[0, 1])

    tty = False
    for command in commands[1:]:
        ic(command)
        if tty:
            # out, err = tty_capture(command, b'')
            append_line_to_readme(line=f"\n$ {command}\n", readme=readme_md)
            ic(command)

            # colorpipe needs to be inserted after the last |
            _command_split = command.split("|")
            ic(_command_split)
            _command_split[-1] = "colorpipe " + _command_split[-1]
            ic(_command_split)
            _command = " | ".join(_command_split)
            ic(_command)
            # os.system("colorpipe " + command + " >> " + readme.as_posix())
            os.system(_command + " >> " + readme_md.as_posix())

            tty = False
            # ic(out, err)
            continue
        if command == "#tty:":
            tty = True
            continue

        if command == "# <br>":
            result = ("\n", readme_md)
        elif command.startswith("#"):
            result = (f"\n$ {command}", readme_md)
        else:
            result = (f"\n$ {command}\n", readme_md)
        ic(result)

        _result = {"line": result[0], "readme": result[1]}
        append_line_to_readme(**_result)

        with open(readme_md, "a", encoding="utf8") as fh:
            popen_instance = subprocess.Popen(
                command,
                stdout=fh,
                stderr=fh,
                shell=True,
            )
            output, errors = popen_instance.communicate()
            exit_code = popen_instance.returncode
            ic(output, errors, exit_code)

    append_line_to_readme(line="\n```\n", readme=readme_md)
    if _postprocess_readme_script.exists():
        _postprocess_readme_command = sh.Command(_postprocess_readme_script)
        _postprocessed_readme = _postprocess_readme_command(sh.cat(readme_md))
        # ic(_postprocessed_readme)
        with open(readme_md, "w", encoding="utf8") as fh:
            fh.write(str(_postprocessed_readme))
    if _validate_readme_script.exists():
        _validate_readme_command = sh.Command(_validate_readme_script)
        _postprocessed_readme = _validate_readme_command(sh.cat(readme_md))
        # ic(_postprocessed_readme)
        with open(readme_md, "w", encoding="utf8") as fh:
            fh.write(str(_postprocessed_readme))
    if unstaged_commits_exist(readme_md):
        sh.git.status(_out=sys.stdout, _err=sys.stderr)
        sh.git.add(readme_md)
        # sh.git.commit("-m", "autoupdate README.md")
        sh.git.status(_out=sys.stdout, _err=sys.stderr)

    return


def run_pylint(
    *,
    path: Path,
    ignore_pylint: bool,
    verbose: bool | int | float = False,
):
    # pylint: disable=too-many-function-args
    git_py_files = " ".join(sh.git("ls-files", "*.py").strip().split('\n'))
    # pylint: enable=too-many-function-args
    pylint_command = sh.Command("pylint")
    pylint_command.bake('--output-format=colorized', git_py_files)
    try:
        pylint_result = pylint_command(path, _ok_code=[0])
        icp(pylint_result)
        sh.grep(
            "--color",
            "-E",
            ": E|$",
            _out=sys.stdout,
            _err=sys.stderr,
            _in=pylint_result,
        )
            #_in=pylint_result.stdout,

    except sh.ErrorReturnCode as e:
        ic(e.exit_code)
        sh.grep(
            "--color", "-E", ": E|$", _out=sys.stdout, _err=sys.stderr, _in=e.stdout
        )
        exit_code = e.exit_code
        if (exit_code & 0b00011) > 0:
            ic("pylint returned an error or worse, exiting")
            if not ignore_pylint:
                sys.exit(exit_code)


def run_byte_vector_replacer(
    *,
    ctx,
    path: Path,
    verbose: bool | int | float = False,
) -> None:
    pair_dict = get_pairs()
    try:
        byte_vector_replacer(path=path, pair_dict=pair_dict)
    except GuardFoundError as e:
        ic(e)


def isort_path(
    path: Path,
    verbose: bool | int | float = False,
) -> None:
    sh.isort(
        "--remove-redundant-aliases",
        "--trailing-comma",
        "--force-single-line-imports",
        "--combine-star",
        "--verbose",
        path,
        _out=sys.stdout,
        _err=sys.stderr,
        _in=sys.stdin,
    )  # https://pycqa.github.io/isort/


def black_path(
    path: Path,
    verbose: bool | int | float = False,
) -> None:
    guard = b"# disable: black\n"
    ic(guard)
    if guard in path.read_bytes():
        ic(f"skipping black, found guard: {guard}")
        return
        # raise GuardFoundError(path.as_posix(), guard)

    sh.black(
        path, _out=sys.stdout, _err=sys.stderr, _in=sys.stdin
    )  # https://github.com/psf/black


@click.group(
    context_settings=CONTEXT_SETTINGS,
    cls=DefaultGroup,
    default="edit",
    default_if_no_args=True,
)
@click_add_options(click_global_options)
@click.pass_context
def cli(
    ctx,
    verbose_inf: bool,
    dict_output: bool,
    verbose: bool | int | float = False,
):
    tty, verbose = tv(
        ctx=ctx,
        verbose=verbose,
        verbose_inf=verbose_inf,
    )


def autoformat_python(
    path: Path,
    skip_black: bool,
    skip_isort: bool,
    verbose: bool | int | float = False,
):
    if not skip_black:
        black_path(path=path)
    if not skip_isort:
        isort_path(path=path)


@cli.command()
@click.argument("paths", type=click.Path(path_type=Path), nargs=-1)
@click_add_options(click_global_options)
@click.pass_context
def isort(
    ctx,
    paths: tuple[Path, ...],
    verbose_inf: bool,
    dict_output: bool,
    verbose: bool | int | float = False,
):
    not_root()
    tty, verbose = tv(
        ctx=ctx,
        verbose=verbose,
        verbose_inf=verbose_inf,
    )
    for path in paths:
        isort_path(path=path)


def edit_file(
    *,
    ctx,
    path: Path,
    disable_change_detection: bool,
    ignore_pylint: bool,
    skip_pylint: bool,
    skip_isort: bool,
    skip_black: bool,
    skip_text_replace: bool,
    non_interactive: bool,
    ignore_exit_code: bool,
    verbose: bool | int | float = False,
) -> None:
    path = path.resolve()
    if not path.is_file():
        eprint("ERROR:", path.as_posix(), "is not a regular file.")
        sys.exit(1)

    try:
        _editor = os.environ["EDITOR"]
    except KeyError:
        eprint(
            "WARNING: $EDITOR enviromental variable is not set. Defaulting to /usr/bin/vim"
        )
        _editor = "/usr/bin/vim"
    else:  # no exception happened
        if not Path(_editor).is_absolute():
            editor = shutil.which(_editor)
            eprint(
                "WARNING: $EDITOR is {}, which is not an absolute path. Resolving to {}".format(
                    _editor, editor
                )
            )
        else:
            editor = _editor
        del _editor

    if verbose:
        ic(editor, path)

    project_folder = None
    group = None
    remote = None
    dont_reformat = None
    try:
        (
            edit_config,
            short_package,
            group,
            remote,
            test_command_arg,
            dont_reformat,
            install_command,
        ) = parse_edit_config(
            path=path,
        )
        project_folder = edit_config.parent
    except FileNotFoundError:
        if not path.as_posix().endswith(".ebuild"):
            icp("NO .edit_config found, and its not an ebuild, exiting...")
            return

    if dont_reformat:
        skip_isort = True
        skip_black = True

    if path.as_posix().endswith(".py"):
        autoformat_python(
            path=path,
            skip_black=skip_black,
            skip_isort=skip_isort,
        )

    if not skip_text_replace:
        run_byte_vector_replacer(
            ctx=ctx,
            path=path,
        )

    pre_edit_hash = sha3_256_hash_file(path=path)
    if not non_interactive:
        os.system(editor + " " + path.as_posix())
    post_edit_hash = sha3_256_hash_file(
        path=path,
    )
    if pre_edit_hash != post_edit_hash:
        ic(
            "file changed:",
            path,
            pre_edit_hash,
            post_edit_hash,
        )
    if unstaged_commits_exist(
        path,
    ):
        ic("unstaged_commits_exist() returned True")
    else:
        ic("unstaged_commits_exist() returned False")
    if (
        (pre_edit_hash != post_edit_hash)
        or disable_change_detection
        or unstaged_commits_exist(path)
    ):
        if project_folder:
            os.chdir(project_folder)
            # with chdir(project_folder):

        ic(path.as_posix())
        sh.chown("user:user", path)  # fails if cant

        if path.as_posix().endswith(".py"):
            autoformat_python(
                path=path,
                skip_black=skip_black,
                skip_isort=skip_isort,
            )

            if not skip_pylint:
                run_pylint(
                    path=path,
                    ignore_pylint=ignore_pylint,
                )
                # Pylint should leave with following status code:
                #   * 0 if everything went fine
                # F * 1 if a fatal message was issued
                # E * 2 if an error message was issued
                # W * 4 if a warning message was issued
                # R * 8 if a refactor message was issued
                # C * 16 if a convention message was issued
                #   * 32 on usage error
                # status 1 to 16 will be bit-ORed

        elif path.as_posix().endswith(".ebuild"):
            with chdir(
                path.resolve().parent,
            ):
                sh.ebuild(path, "manifest")
                # sh.git.add(path.parent / Path('Manifest'))
                sh.git.add(Path("Manifest"))
                sh.git.add(path.name)
                _files = Path(path / Path("files"))
                if _files.exists():
                    sh.git.add("files/*")
                # cd "${file_dirname}" # should already be here...
                # dev-util/pkgcheck and dev-util/pkgdev
                # try:
                #    sh.repoman(
                #        "fix",
                #        _out=sys.stdout,
                #        _err=sys.stderr,
                #        _in=sys.stdin,
                #        _ok_code=[0, 1],
                #    )
                # except sh.ErrorReturnCode_1 as e:
                #    ic(e)
                #    print(e.stdout)
                # try:
                #    sh.repoman(
                #        _out=sys.stdout, _err=sys.stderr, _in=sys.stdin, _ok_code=[0, 1]
                #    )
                # except sh.ErrorReturnCode_1 as e:
                #    ic(e)
                #    print(e.stdout)

                sh.git.add("-u", _out=sys.stdout, _err=sys.stderr, _in=sys.stdin)
                sh.git.commit(
                    "--verbose",
                    "-m",
                    "auto-commit",
                    _out=sys.stdout,
                    _err=sys.stderr,
                    _in=sys.stdin,
                )
                sh.git.push(_out=sys.stdout, _err=sys.stderr, _in=sys.stdin)
                # sh.git.push(_out=sys.stdout, _err=sys.stderr, _in=sys.stdin, _tty_in=True)
                # sh.git.push(_out=sys.stdout, _err=sys.stderr, _tty_in=True)
                sh.sudo.emaint("sync", "-A", _fg=True)
                sys.exit(0)

        elif path.as_posix().endswith(".c"):
            splint_command = sh.Command("splint")
            splint_result = splint_command(
                path,
                _out=sys.stdout,
                _err=sys.stderr,
                _in=sys.stdin,
                _tee=True,
                _ok_code=[0, 1],
            )

        elif path.as_posix().endswith(".sh"):
            shellcheck_command = sh.Command("shellcheck")
            shellcheck_result = shellcheck_command(
                path,
                _out=sys.stdout,
                _err=sys.stderr,
                _in=sys.stdin,
                _tee=True,
                _ok_code=[0, 1],
            )  # TODO

        ic(os.getcwd())
        autogenerate_readme(
            path=path,
        )
        command = sh.git.diff
        ic(command)
        command(_out=sys.stdout, _err=sys.stderr)

        sh.git.add(path)  # covered below too
        sh.git.add("-u")  # all tracked files

        unstaged_changes_exist_command = sh.Command("git")
        unstaged_changes_exist_command_result = unstaged_changes_exist_command(
            "diff-index", "HEAD", "--"
        )
        print(unstaged_changes_exist_command_result)
        if path.as_posix() in unstaged_changes_exist_command_result:
            sh.git.add(path)

        sh.git.diff("--cached")
        try:
            staged_but_uncomitted_changes_exist_command = sh.git.diff(
                "--cached", "--exit-code"
            )
            ic(staged_but_uncomitted_changes_exist_command)
        except sh.ErrorReturnCode_1:
            ic("comitting")
            sh.git.add("-u")  # all tracked files
            sh.git.commit("--verbose", "-m", "auto-commit")
            if remote and Path(edit_config.parent / Path(".push")).is_file():
                try:
                    sh.git.push()
                    sh.sudo.emaint("sync", "-A", _fg=True)
                except sh.ErrorReturnCode_128 as e:
                    ic(e)
                    ic(e.stdout)
                    ic(e.stderr)
                    ic("remote not found")

            else:
                ic(
                    ".push not found: push is not enabled, changes comitted locally"
                )

            if install_command:
                os.system(install_command)
            else:
                sh.sudo.portagetool(
                    "install",
                    "--oneshot",
                    f"{group}/{short_package}",
                    _fg=True,
                )
            try:
                help_command = sh.Command(short_package)
            except sh.CommandNotFound as e:
                ic(e)
            else:
                try:
                    help_command_result = help_command(
                        "--help", _out=sys.stdout, _err=sys.stderr, _in=sys.stdin
                    )
                except ErrorReturnCode_1 as e:
                    if ignore_exit_code:
                        ic(e)
                    else:
                        ic(ignore_exit_code)
                        raise e


@cli.command()
@click.argument("paths", type=click.Path(path_type=Path), nargs=-1)
@click.option("--apps-folder", type=str, required=True)
@click.option("--gentoo-overlay-repo", type=str, required=True)
@click.option("--github-user", type=str, required=True)
@click.option(
    "--license",
    type=click.Choice(
        license_list(
            verbose=False,
        )
    ),
    default="ISC",
)
@click.option("--disable-change-detection", is_flag=True)
@click.option("--ignore-pylint", is_flag=True)
@click.option("--non-interactive", is_flag=True)
@click.option("--skip-isort", is_flag=True)
@click.option("--skip-black", is_flag=True)
@click.option("--skip-pylint", is_flag=True)
@click.option("--skip-text-replace", is_flag=True)
@click.option("--ignore-exit-code", is_flag=True)
@click.option("--ignore-checks", "skip_code_checks", is_flag=True)
@click_add_options(click_global_options)
@click.pass_context
def edit(
    ctx,
    paths: Sequence[Path],
    apps_folder: str,
    gentoo_overlay_repo: str,
    github_user: str,
    license: str,
    verbose_inf: bool,
    disable_change_detection: bool,
    ignore_pylint: bool,
    non_interactive: bool,
    skip_isort: bool,
    skip_black: bool,
    skip_text_replace: bool,
    ignore_exit_code: bool,
    skip_pylint: bool,
    skip_code_checks: bool,
    dict_output: bool,
    verbose: bool | int | float = False,
):
    if not verbose:
        ic.disable()

    not_root()
    tty, verbose = tv(
        ctx=ctx,
        verbose=verbose,
        verbose_inf=verbose_inf,
    )

    if skip_code_checks:
        skip_isort = True
        skip_pylint = True

    if paths:
        iterator = paths
    else:
        iterator = unmp(
            valid_types=[
                bytes,
            ],
        )

    width, height = shutil.get_terminal_size((80, 20))
    for _ in range(height):
        print("")

    for index, path in enumerate(iterator):
        icp(index, path)
        _path = Path(os.fsdecode(path))

        edit_file(
            ctx=ctx,
            path=_path,
            disable_change_detection=disable_change_detection,
            ignore_pylint=ignore_pylint,
            skip_pylint=skip_pylint,
            skip_isort=skip_isort,
            skip_black=skip_black,
            skip_text_replace=skip_text_replace,
            non_interactive=non_interactive,
            ignore_exit_code=ignore_exit_code,
        )


@cli.command()
@click.argument("path", type=click.Path(path_type=Path), nargs=1)
@click_add_options(click_global_options)
@click.pass_context
def generate_readme(
    ctx,
    path: Path,
    verbose_inf: bool,
    dict_output: bool,
    verbose: bool | int | float = False,
):
    if not verbose:
        ic.disable()

    not_root()
    tty, verbose = tv(
        ctx=ctx,
        verbose=verbose,
        verbose_inf=verbose_inf,
    )

    path = Path(os.fsdecode(path)).expanduser().resolve()
    if not path.is_file():
        eprint("ERROR:", path.as_posix(), "is not a regular file.")
        sys.exit(1)

    autogenerate_readme(path=path)
