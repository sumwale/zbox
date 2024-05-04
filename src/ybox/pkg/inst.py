"""
Methods for package installation on an active ybox container.
"""

import argparse
import io
import os
import re
import subprocess
import sys
from configparser import ConfigParser, SectionProxy
from pathlib import Path
from typing import Optional, Tuple, Union

from simple_term_menu import TerminalMenu  # type: ignore

from ybox.cmd import PkgMgr, run_command
from ybox.config import Consts, StaticConfiguration
from ybox.print import print_info, print_notice, print_warn
from ybox.state import RuntimeConfiguration, YboxStateManagement
from ybox.util import check_installed_package, ini_file_reader


def install_package(args: argparse.Namespace, pkgmgr: SectionProxy, docker_cmd: str,
                    conf: StaticConfiguration, runtime_conf: RuntimeConfiguration,
                    state: YboxStateManagement) -> int:
    """
    Install package specified by `args.package` on a ybox container with given docker/podman
    command. Additional flags honored are `args.quiet` to bypass user confirmation during install,
    `args.skip_opt_deps` to skip installing optional dependencies of the package,
    `args.skip_executables` to skip creating wrapper executables for the package executables,
    `args.skip_desktop_files` to skip creating wrapper desktop files for the package ones.

    When the `args.skip_opt_deps` flag is not enabled, then the package databases are searched
    for optional dependencies of the package as well as those of the new required dependencies
    being installed. Recursion level for this search is fixed to 2 for now else the number
    of packages can be overwhelming with most being largely irrelevant. A selection menu
    presented to the user allows choosing the optional dependencies to be installed after
    the main package installation has completed successfully.

    :param args: arguments having `package` and all other attributes passed by the user
    :param pkgmgr: the `pkgmgr` section from `distro.ini` configuration file of the distribution
    :param docker_cmd: the docker/podman executable to use
    :param conf: the `StaticConfiguration` of the container
    :param runtime_conf: the `RuntimeConfiguration` of the container
    :param state: instance of the `YboxStateManagement` class having the state of all yboxes

    :return: integer exit status of install command where 0 represents success
    """
    quiet_flag = pkgmgr[PkgMgr.QUIET_FLAG.value] if args.quiet else ""
    # restore the {opt_dep} placeholder in the installation command which will be replaced
    # before actual execution by _install_package(...)
    install_cmd = pkgmgr[PkgMgr.INSTALL.value].format(quiet=quiet_flag, opt_dep="{opt_dep}")
    list_cmd = pkgmgr[PkgMgr.LIST_FILES.value]
    selected_deps = args.with_opt_deps.split(",") if args.with_opt_deps else None
    opt_deps_cmd, opt_dep_flag = ("", "") if args.skip_opt_deps and not selected_deps else (
        pkgmgr[PkgMgr.OPT_DEPS.value], pkgmgr[PkgMgr.OPT_DEP_FLAG.value])
    check_cmd = pkgmgr[PkgMgr.INFO.value] if args.check_package else ""
    return _install_package(args.package, args, install_cmd, list_cmd, docker_cmd, conf,
                            runtime_conf, state, opt_deps_cmd, opt_dep_flag, False, check_cmd,
                            selected_deps, args.quiet)


def _install_package(package: str, args: argparse.Namespace, install_cmd: str, list_cmd: str,
                     docker_cmd: str, conf: StaticConfiguration, rt_conf: RuntimeConfiguration,
                     state: YboxStateManagement, opt_deps_cmd: str, opt_dep_flag: str,
                     opt_dep_install: bool, check_cmd: str, selected_deps: Optional[list[str]],
                     quiet: bool) -> int:
    """
    Real workhorse for :func:`install_package` that is invoked recursively for
    optional dependencies if required.

    :param package: the package to be installed
    :param args: arguments having all the attributes passed by the user (`package` is ignored)
    :param install_cmd: installation command as read from `distro.ini` configuration file of the
                        distribution which should have an unresolved `{opt_dep}` placeholder
                        for the `opt_dep_flag`
    :param list_cmd: command to list files for an installed package read from `distro.ini`
    :param docker_cmd: the docker/podman executable to use
    :param conf: the `StaticConfiguration` of the container
    :param rt_conf: the `RuntimeConfiguration` of the container
    :param state: instance of the `YboxStateManagement` class having the state of all yboxes
    :param opt_deps_cmd: command to determine optional dependencies as read from `distro.ini`
    :param opt_dep_flag: flag to be added during installation of an optional dependency to mark
                         it as a dependency (as read from `distro.ini`)
    :param opt_dep_install: true if installation is for an optional dependency
    :param check_cmd: command to check if package exists before installation
    :param selected_deps: list of dependencies to install if user has already provided them
    :param quiet: perform some operations quietly

    :return: exit code of install command for the main package
    """
    # need to determine optional dependencies before installation else second level or higher
    # dependencies will never be found (as the dependencies are already installed)
    optional_deps: list[Tuple[str, str, int]] = []
    if opt_deps_cmd and selected_deps is None:
        optional_deps = get_optional_deps(package, docker_cmd, conf.box_name, opt_deps_cmd)
    if opt_dep_install:
        resolved_install_cmd = install_cmd.format(opt_dep=opt_dep_flag)
    else:
        resolved_install_cmd = install_cmd.format(opt_dep="")
    # don't exit on error here because the caller may have further actions to perform before exit
    code = -1
    if check_cmd and (code := check_installed_package(docker_cmd, check_cmd, package,
                                                      conf.box_name)) == 0 and not quiet:
        print_notice(f"'{package}' is already installed in '{conf.box_name}")
    if code != 0:
        if not quiet:
            print_info(f"Installing '{package}' in '{conf.box_name}'")
        code = int(run_command([docker_cmd, "exec", "-it", conf.box_name, "/bin/bash", "-c",
                                f"{resolved_install_cmd} {package}"], exit_on_error=False,
                               error_msg=f"installing '{package}'"))
    if code == 0:
        # TODO: wrappers for newly installed required dependencies should also be created
        # check if need to create wrappers for optional dependencies
        local_copies: list[str] = []
        if not opt_dep_install or args.add_dep_wrappers:
            local_copies = wrap_container_files(package, args, list_cmd, docker_cmd, conf,
                                                rt_conf.ini_config)
        package_type = state.optional_package_type(args.package) if opt_dep_install else ""
        state.register_package(conf.box_name, package, shared_root=rt_conf.shared_root,
                               local_copies=local_copies, package_type=package_type)
        if optional_deps and selected_deps is None:
            selected_deps = select_optional_deps(package, optional_deps)
        if selected_deps:
            for dep in selected_deps:
                _install_package(dep, args, install_cmd, list_cmd, docker_cmd, conf, rt_conf,
                                 state, "", opt_dep_flag, True, check_cmd, None, quiet)

    return code


def get_optional_deps(package: str, docker_cmd: str, container_name: str,
                      opt_deps_cmd: str) -> list[tuple[str, str, int]]:
    """
    Find the optional dependencies recursively, removing the ones already installed.

    :param package: package to be installed
    :param docker_cmd: the docker/podman executable to use
    :param container_name: name of the ybox container
    :param opt_deps_cmd: command to determine optional dependencies as read from `distro.ini`

    :return: list of tuples having the name of optional dependency, its description and
             an integer `level` denoting its depth in the dependency tree
             (i.e. level 1 means immediate dependency of the package, 2 means dependency of
              another dependency which is being newly installed and so on)
    """
    optional_deps: list[Tuple[str, str, int]] = []
    pkg_start = "Found optional dependencies"
    pkg_prefix = "PKG: "
    # Expected format of output below is -- PKG: <name>::::<description>::::<level>.
    # This is preceded by a line "Found optional dependencies".
    # Print other lines on output as is which are for informational purpose.
    # Code below does progressive display of output which is required for showing stuff like
    # download progress properly.
    # The following alternatives were considered:
    #  1) print PKG: lines to stderr: this works only if "-t" is removed from docker exec
    #          otherwise both stdout and stderr are combined to tty, but if it is removed
    #          then you can no longer see the progressive download due to buffering
    #  2) redirect PKG: lines somewhere else like a common file: this can be done but will
    #          likely be more messy than the code below (e.g. handle concurrent executions),
    #          but still can be considered in future
    with subprocess.Popen([docker_cmd, "exec", "-it", container_name, "/bin/bash", "-c",
                           f"{opt_deps_cmd} {package}"], stdout=subprocess.PIPE) as deps_result:
        line = bytearray()
        eol = b"\n"[0]  # end of line
        buffered = 0
        assert deps_result.stdout is not None
        # readline does not work for in-place updates like from aria2
        while char := deps_result.stdout.read(1):
            sys.stdout.buffer.write(char)
            buffered += 1
            if char[0] == eol:
                sys.stdout.flush()
                buffered = 0
                output = line.decode("utf-8")
                line.clear()
                if output.startswith(pkg_start):  # output can have a trailing '\r'
                    break
            else:
                line.append(char[0])
                if buffered >= 4:  # flush frequently to show download progress, for example
                    sys.stdout.flush()
                    buffered = 0
        sys.stdout.flush()
        while pkg_out := deps_result.stdout.readline():
            output = pkg_out.decode("utf-8")
            name, desc, level = output[len(pkg_prefix):].split("::::")
            optional_deps.append((name, desc, int(level.strip())))

        if deps_result.wait(60) != 0:
            print_warn(f"FAILED to determine optional dependencies of {package} -- "
                       "see above output for details. Skipping optional dependencies.")
            optional_deps = []

    return optional_deps


def select_optional_deps(package: str, deps: list[Tuple[str, str, int]]) -> list[str]:
    """
    Show a selection menu to the user having optional dependencies of a package to be installed.

    :param package: package that is being installed
    :param deps: list of dependencies as tuples from :func:`get_optional_deps`

    :return: list of names of the selected optional dependencies (or empty list for no selection)
    """
    menu_options = [f"{'*' if level <= 1 else ''} {name} ({desc})" for name, desc, level in deps]
    print_info(f"Select optional dependencies of {package} "
               "(starred ones are the immediate dependencies):")
    # don't select on <Enter> (multi_select_select_on_accept) and allow for empty selection
    terminal_menu = TerminalMenu(menu_options, multi_select=True, show_multi_select_hint=True,
                                 multi_select_select_on_accept=False, multi_select_empty_ok=True)
    selection = terminal_menu.show()
    return [deps[index][0] for index in selection] if selection else []


def wrap_container_files(package: str, args: argparse.Namespace, list_cmd: str,
                         docker_cmd: str, conf: StaticConfiguration,
                         box_conf: Union[str, ConfigParser]) -> list[str]:
    """
    Create wrappers in host environment to invoke container's desktop files and executables.

    :param package: the package to be installed
    :param args: arguments having all the attributes passed by the user (`package` is ignored)
    :param list_cmd: command to list files for an installed package read from `distro.ini`
    :param docker_cmd: the docker/podman executable to use
    :param conf: the `StaticConfiguration` of the container
    :param box_conf: the resolved INI format configuration of the container as a string or
                     a `ConfigParser` object

    :return: the list of paths of the wrapper files
    """
    skip_desktop_files = args.skip_desktop_files
    skip_executables = args.skip_executables
    if skip_desktop_files and skip_executables:
        return []
    # skip on errors below and do not fail the installation
    package_files = run_command(
        [docker_cmd, "exec", conf.box_name, "/bin/bash", "-c", f"{list_cmd} {package}"],
        capture_output=True, exit_on_error=False, error_msg=f"listing files of '{package}'")
    if isinstance(package_files, int):
        return []
    wrapper_files: list[str] = []
    desktop_dirs = Consts.container_desktop_dirs()
    executable_dirs = Consts.container_executable_dirs()
    # match both "Exec=" and "TryExec=" lines
    exec_re = re.compile(r"^(\s*(Try)?Exec\s*=\s*)(.+?)((\s%[a-zA-Z])?\s*)$")
    # read the container configuration for [app_flags] section
    app_flags = _get_app_flags(box_conf)
    # the "-it" flag is used for both desktop file and executable for docker/podman exec
    # since it is safe (unless the app may need stdin in which case Terminal must be true
    #   in its desktop file in which case a terminal will be opened during execution)
    for file in str(package_files).splitlines():
        file_dir = os.path.dirname(file)
        filename = os.path.basename(file).strip()
        if not filename:  # the case of directories
            continue
        # check if this is a .desktop directory and copy it over adding appropriate
        # "docker exec" prefix to the command
        if not skip_desktop_files and file_dir in desktop_dirs:
            _wrap_desktop_file(filename, file, package, exec_re, docker_cmd, conf, app_flags,
                               wrapper_files)
            continue
        if not skip_executables and file_dir in executable_dirs:
            _wrap_executable(filename, file, docker_cmd, conf, app_flags, wrapper_files)

    return wrapper_files


def _get_app_flags(box_conf: Union[str, ConfigParser]) -> Optional[SectionProxy]:
    """
    Get the [app_flags] section from the container configuration.

    :param box_conf: the resolved INI format configuration of the container as a string or
                     a `ConfigParser` object
    :return: the [app_flags] section as a `SectionProxy` object
    """
    if isinstance(box_conf, ConfigParser):
        box_config = box_conf
    else:
        with io.StringIO(box_conf) as box_conf_fd:
            box_config = ini_file_reader(box_conf_fd, interpolation=None,
                                         case_sensitive=False)  # case-insensitive
    return box_config["app_flags"] if box_config.has_section("app_flags") else None


def _wrap_desktop_file(filename: str, file: str, package: str, exec_re: re.Pattern[str],
                       docker_cmd: str, conf: StaticConfiguration,
                       app_flags: Optional[SectionProxy], wrapper_files: list[str]) -> None:
    """
    For a desktop file, add "docker/podman exec ..." to its Exec/TryExec lines. Also read
    the additional flags for the command passed in `app_flags` and add them to an appropriate
    position in the Exec/TryExec lines.

    :param filename: name of the desktop file being wrapped
    :param file: full path of the desktop file being wrapped
    :param package: the package being installed
    :param exec_re: the regular expression to use for matching Exec/TryExec lines
    :param docker_cmd: the docker/podman executable to use
    :param conf: the `StaticConfiguration` of the container
    :param app_flags: the [app_flags] section from the container configuration as a `SectionProxy`
    :param wrapper_files: the accumulated list of all wrapper files so far
    """
    # container name is added to desktop file to make it unique
    wrapper_name = f"ybox.{conf.box_name}.{filename}"
    tmp_file = Path(f"/tmp/{wrapper_name}")
    tmp_file.unlink(missing_ok=True)
    if run_command([docker_cmd, "cp", f"{conf.box_name}:{file}", str(tmp_file)],
                   exit_on_error=False, error_msg=f"copying of file from '{package}'") != 0:
        return
    try:
        # check for additional flags to be added
        if app_flags and (flags := app_flags.get(filename.removesuffix(".desktop"))):
            repl = rf"\1{docker_cmd} exec -it {conf.box_name} \3 {flags}\4"
        else:
            repl = rf"\1{docker_cmd} exec -it {conf.box_name} \3\4"
        # the destination will be $HOME/.local/share/applications
        wrapper_file = f"{conf.env.user_applications_dir}/{wrapper_name}"
        print_warn(f"Linking container desktop file {file} to {wrapper_file}")
        with open(wrapper_file, "w", encoding="utf-8") as wrapper_fd:
            wrapper_fd.writelines(
                exec_re.sub(repl, line) for line in tmp_file.open("r", encoding="utf-8"))
        wrapper_files.append(wrapper_file)
    finally:
        tmp_file.unlink(missing_ok=True)


def _wrap_executable(filename: str, file: str, docker_cmd: str, conf: StaticConfiguration,
                     app_flags: Optional[SectionProxy], wrapper_files: list[str]) -> bool:
    """
    For an executable, create a wrapper executable that invokes "docker/podman exec".

    :param filename: name of the executable file being wrapped
    :param file: full path of the executable file being wrapped
    :param docker_cmd: the docker/podman executable to use
    :param conf: the `StaticConfiguration` of the container
    :param app_flags: the [app_flags] section from the container configuration as a `SectionProxy`
    :param wrapper_files: the accumulated list of all wrapper files so far

    :return: true if a wrapper for executable file was created else false if skipped by the user
    """
    wrapper_exec = f"{conf.env.user_executables_dir}/{filename}"
    print_warn(f"Linking container executable {file} to {wrapper_exec}")
    if os.path.exists(wrapper_exec):
        resp = input(f"Target file {wrapper_exec} already exists. Overwrite? (y/N) ")
        if resp.lower() != "y":
            print_warn(f"Skipping local wrapper for {file}")
            return False
    # check for additional flags to be added
    flags = app_flags.get(filename, "") if app_flags else ""
    exec_content = ("#!/bin/sh\n",
                    f'exec {docker_cmd} exec -it {conf.box_name} "{file}" {flags} "$@"')
    with open(wrapper_exec, "w", encoding="utf-8") as wrapper_fd:
        wrapper_fd.writelines(exec_content)
    os.chmod(wrapper_exec, mode=0o755, follow_symlinks=True)
    wrapper_files.append(wrapper_exec)
    return True