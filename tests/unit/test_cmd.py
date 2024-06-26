"""Tests for `ybox/cmd.py`"""

import argparse
import io
import os
import subprocess
import time
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from typing import Tuple
from uuid import uuid4

from ybox.cmd import YboxLabel, get_docker_command, run_command, verify_ybox_state


def proc_run(cmd: list[str], capture_output=False, **kwargs) -> subprocess.CompletedProcess[bytes]:
    """shortcut to invoke `subprocess.run`"""
    return subprocess.run(cmd, capture_output=capture_output, check=False, **kwargs)


class TestCmd(unittest.TestCase):
    """unit tests for the `ybox.cmd` module"""

    _TEST_IMAGE = "busybox"

    @staticmethod
    def _get_docker_cmd() -> Tuple[str, argparse.ArgumentParser]:
        """build `argparse` and obtain docker/podman path using `get_docker_command`"""
        parser = argparse.ArgumentParser()
        parser.add_argument("-d", "--docker-path")
        args = parser.parse_args([])
        docker_cmd = get_docker_command(args, "-d")
        return docker_cmd, parser

    @staticmethod
    def _stop_container(docker_cmd: str, name: str, check_removed: bool = False) -> None:
        """stop given container and wait for it to disappear from container running list"""
        proc_run([docker_cmd, "container", "stop", name])
        end = datetime.now() + timedelta(seconds=30)
        docker_args = [docker_cmd, "container", "ls", "-q", "-f", f"name={name}"]
        if check_removed:
            docker_args.append("-a")
        while datetime.now() < end:
            output = proc_run(docker_args, capture_output=True)
            if not output.stdout.decode("utf-8").strip():
                return
            time.sleep(0.5)
        raise ChildProcessError(f"Failed to stop container {name}")

    def test_get_docker_command(self) -> None:
        """check `get_docker_command` result"""
        docker_cmd, parser = self._get_docker_cmd()
        self.assertIsNotNone(docker_cmd)
        self.assertRegex(docker_cmd, r"/usr/bin/(docker|podman)")
        self.assertTrue(os.access(docker_cmd, os.X_OK))
        # try with explicit -d option
        args = parser.parse_args(["-d", "/bin/true"])
        docker_cmd = get_docker_command(args, "-d")
        self.assertEqual("/bin/true", docker_cmd)

    def test_verify_ybox_state(self) -> None:
        """check various cases for `verify_ybox_state` function"""
        docker_cmd, _ = self._get_docker_cmd()
        cnt_name = f"ybox-test-cmd-{uuid4()}"
        # command to run in containers which allows them to stop immediately
        sh_cmd = 'tail -s10 -f /dev/null & childPID=$!; trap "kill -TERM $childPID" 1 2 3 15; wait'
        try:
            # check failure to match ybox without label
            proc_run([docker_cmd, "run", "-itd", "--rm", "--name", cnt_name, self._TEST_IMAGE,
                      "/bin/sh", "-c", sh_cmd])
            self.assertFalse(verify_ybox_state(docker_cmd, cnt_name, expected_states=["running"],
                                               exit_on_error=False))
            self.assertRaises(SystemExit, verify_ybox_state, docker_cmd, cnt_name,
                              expected_states=["running"])
            self._stop_container(docker_cmd, cnt_name, check_removed=True)
            # check success with primary label
            proc_run([docker_cmd, "run", "-itd", "--rm", "--name", cnt_name, "--label",
                      YboxLabel.CONTAINER_PRIMARY.value, self._TEST_IMAGE, "/bin/sh", "-c",
                      sh_cmd])
            self.assertTrue(verify_ybox_state(docker_cmd, cnt_name, expected_states=["running"],
                                              exit_on_error=False))
            self._stop_container(docker_cmd, cnt_name, check_removed=True)
            # check success with primary label and stopped state
            proc_run([docker_cmd, "run", "-itd", "--name", cnt_name, "--label",
                      YboxLabel.CONTAINER_PRIMARY.value, self._TEST_IMAGE, "/bin/sh", "-c",
                      sh_cmd])
            self._stop_container(docker_cmd, cnt_name)
            self.assertFalse(verify_ybox_state(docker_cmd, cnt_name, expected_states=["running"],
                                               exit_on_error=False))
            self.assertRaises(SystemExit, verify_ybox_state, docker_cmd, cnt_name,
                              expected_states=["running"])
            self.assertTrue(verify_ybox_state(docker_cmd, cnt_name,
                                              expected_states=["stopped", "exited"],
                                              exit_on_error=False))
            self.assertTrue(verify_ybox_state(docker_cmd, cnt_name, expected_states=[],
                                              exit_on_error=False))
            proc_run([docker_cmd, "container", "rm", cnt_name])
            # check failure with non-primary label
            proc_run([docker_cmd, "run", "-itd", "--rm", "--name", cnt_name, "--label",
                      YboxLabel.CONTAINER_BASE.value, self._TEST_IMAGE, "/bin/sh", "-c", sh_cmd])
            self.assertFalse(verify_ybox_state(docker_cmd, cnt_name, expected_states=["running"],
                                               exit_on_error=False))
            self.assertRaises(SystemExit, verify_ybox_state, docker_cmd, cnt_name,
                              expected_states=["running"])
        finally:
            proc_run([docker_cmd, "container", "stop", cnt_name])
            proc_run([docker_cmd, "container", "rm", cnt_name], stderr=subprocess.DEVNULL)

    def test_run_command(self) -> None:
        """check various cases for `run_command` function"""
        # check string and list arguments for run_command
        expected = [f for f in os.listdir("/") if not f.startswith('.')]
        expected.sort()
        output = run_command("/bin/ls /", capture_output=True)
        self.assertTrue(isinstance(output, str))
        self.assertEqual(expected, str(output).splitlines())
        output = run_command(["/bin/ls", "/"], capture_output=True)
        self.assertTrue(isinstance(output, str))
        self.assertEqual(expected, str(output).splitlines())

        # check capture_output=True and default/False
        pwd = os.getcwd()
        self.assertEqual([pwd], str(run_command("/bin/pwd", capture_output=True)).splitlines())
        self.assertEqual(0, run_command(["/bin/sh", "-c", f"[ \"`pwd`\" = \"{pwd}\" ]"]))
        self.assertEqual(0, run_command(["/bin/sh", "-c", f"[ \"`pwd`\" = \"{pwd}\" ]"],
                                        capture_output=False))
        self.assertEqual("", str(run_command(["/bin/sh", "-c", f"[ \"`pwd`\" = \"{pwd}\" ]"],
                                             capture_output=True)))
        str_io = io.StringIO()
        with redirect_stdout(str_io):
            self.assertRaises(SystemExit, run_command, ["/bin/sh", "-c", "[ \"`pwd`\" = \"\" ]"])
        self.assertTrue("FAILURE in '/bin/sh -c" in str_io.getvalue())

        # check exit_on_error=False
        str_io.truncate(0)
        with redirect_stdout(str_io):
            self.assertNotEqual(0, run_command(["/bin/sh", "-c", "[ \"`pwd`\" = \"\" ]"],
                                               exit_on_error=False))
        # check default error_msg
        self.assertTrue("FAILURE in '/bin/sh -c" in str_io.getvalue())

        # check with specified error_msg
        str_io.truncate(0)
        non_existent = f"/{uuid4()}"
        with redirect_stdout(str_io):
            self.assertRaises(SystemExit, run_command, f"/bin/ls {non_existent}",
                              capture_output=True, error_msg="running /bin/ls")
        out = str_io.getvalue()
        self.assertTrue("No such file or directory" in out)
        self.assertTrue("FAILURE in running /bin/ls" in out)

        # check error_msg=SKIP
        str_io.truncate(0)
        with redirect_stdout(str_io):
            self.assertRaises(SystemExit, run_command, f"/bin/ls {non_existent}",
                              capture_output=True, error_msg="SKIP")
        out = str_io.getvalue()
        self.assertTrue("No such file or directory" in out)
        self.assertFalse("FAILURE in" in out)


if __name__ == '__main__':
    unittest.main()
