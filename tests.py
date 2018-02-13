from __future__ import absolute_import

import errno
import logging
import os
import shutil
import signal
import stat
import sys
import stat
import tempfile
import time
import unittest
import numbers

import contextlib

from unittest import skipIf

from docopt import DocoptExit

from os.path import exists as pathexists
from os.path import join as pathjoin
from os.path import basename, isdir

from reloadconf import ReloadConf
from reloadconf import TimeoutExpired
from reloadconf.__main__ import main


# Test file name used during tests.
TESTFN = "rconf-testfile"

# Program to indicate HUP signal received.
TEST_PROGRAM = b"""#!/usr/bin/env python

import signal, time, sys

def _touch(*args):
    with open(sys.argv[1], 'wb') as f:
        f.write(b'')

signal.signal(signal.SIGHUP, _touch)

while True:
    time.sleep(1)

"""
TEST_UID = 2000


# Useful to debug threading issues.
logging.basicConfig(
    stream=sys.stderr,
    # Change level to DEBUG here if you need to.
    level=logging.CRITICAL,
    format='%(thread)d: %(message)s'
)
LOGGER = logging.getLogger(__name__)


class TestTimeoutError(Exception):
    def __init__(self):
        super().__init__('Timeout exceeded')


@contextlib.contextmanager
def timeout(timeout=2):

    def _alarm(*args):
        raise TestTimeoutError()

    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(timeout)

    # Let the code run, but our alarm will interrupt it if it exceeds timeout.
    yield

    signal.signal(signal.SIGALRM, signal.SIG_IGN)


class TestCase(unittest.TestCase):

    # Print a full path representation of the single unit tests
    # being run, e.g. tests.TestReloadConf.test_fail.
    def __str__(self):
        mod = self.__class__.__module__
        if mod == '__main__':
            mod = os.path.splitext(os.path.basename(__file__))[0]
        return "%s.%s.%s" % (
            mod, self.__class__.__name__, self._testMethodName)

    # Avoid printing docstrings.
    def shortDescription(self):
        return None

    def assertStartsWith(self, start, text, message=None):
        if message is None:
            message = 'text does not start with %s' % start
        self.assertTrue(text.startswith(start), message)


def safe_rmpath(path):
    "Convenience function for removing temporary test files or dirs"
    try:
        st = os.stat(path)
        if stat.S_ISDIR(st.st_mode):
            os.rmdir(path)
        else:
            os.remove(path)
    except OSError as err:
        if err.errno != errno.ENOENT:
            raise


class TestReloadConf(TestCase):

    @classmethod
    def setUp(cls):
        cls.dir = tempfile.mkdtemp()
        cls.file = tempfile.mkstemp()[1]
        cls.sig = tempfile.mktemp()
        with tempfile.NamedTemporaryFile(delete=False) as p:
            p.write(TEST_PROGRAM)
            cls.prog = p.name
        os.chmod(cls.prog, 0o700)
        safe_rmpath(TESTFN)

    @classmethod
    def tearDown(cls):
        safe_rmpath(TESTFN)
        safe_rmpath(cls.file)
        safe_rmpath(cls.prog)

        try:
            shutil.rmtree(cls.dir)
        except OSError:
            pass

    def run_cli(self, watch=None, config=None, command=None, test=None,
                others=None):
        """Helper to run realoadconf as if it were run from the cmdline."""
        if watch is None:
            watch = '--watch=%s' % self.dir
        if config is None:
            config = '--config=%s' % self.file
        if command is None:
            command = '--command=/bin/sleep 1'
        if test is None:
            test = '--test=/bin/true'

        sysargv = [
            watch,
            config,
            command,
            test,
        ]

        if others:
            assert isinstance(others, list), others
            sysargv.extend(others)

        for x in sysargv:
            assert isinstance(x, str), x

        # run
        main(sysargv)


    # ---

    def test_fail(self):
        """Ensure command is NOT run when test fails."""
        rc = ReloadConf(self.dir, self.file, '/bin/sleep 1', test='/bin/false')
        rc.poll()
        # Command should NOT have run.
        self.assertFalse(rc.check_command())

    def test_success(self):
        """Ensure command is run when test succeeds."""
        rc = ReloadConf(self.dir, self.file, '/bin/sleep 1', test='/bin/true')
        rc.poll()
        # Command should have run.
        self.assertTrue(rc.check_command())

    def test_no_test(self):
        """Ensure command is run when test is omitted."""
        rc = ReloadConf(self.dir, self.file, '/bin/sleep 1')
        rc.poll()
        # Command should have run.
        self.assertTrue(rc.check_command())

    def test_hup(self):
        """Ensure command is reloaded with valid config."""
        command = '%s %s' % (self.prog, self.sig)
        with ReloadConf(self.dir, self.file, command) as rc:
            rc.poll()
            # Command should now be running.
            self.assertTrue(rc.check_command())
            # Write out "config" file.
            with open(pathjoin(self.dir, basename(self.file)), 'wb') as f:
                f.write(b'foo')
            # Command should receive HUP.
            rc.poll()
            time.sleep(0.1)
            self.assertTrue(pathexists(self.sig))

    def test_inotify(self):
        """Ensure command is reloaded with valid config (inotify)."""
        command = '%s %s' % (self.prog, self.sig)
        with ReloadConf(self.dir, self.file, command, inotify=True) as rc:
            rc.poll()
            # Command should now be running.
            self.assertTrue(rc.check_command())
            # Write out "config" file.
            with open(pathjoin(self.dir, basename(self.file)), 'wb') as f:
                f.write(b'foo')
            # Command should receive HUP.
            rc.poll()
            time.sleep(0.1)
            self.assertTrue(pathexists(self.sig))

    def test_reload(self):
        """Ensure reload command is run (instead of HUP) when provided."""
        reload = '/bin/touch %s' % self.sig
        with ReloadConf(self.dir, self.file, '/bin/sleep 1', reload=reload) as rc:
            rc.poll()
            # Command should now be running.
            self.assertTrue(rc.check_command())
            self.assertFalse(pathexists(self.sig))
            # Write out "config" file.
            with open(pathjoin(self.dir, basename(self.file)), 'wb') as f:
                f.write(b'foo')
            # Reload command should be executed.
            rc.poll()
            time.sleep(0.1)
            self.assertTrue(pathexists(self.sig))

    def test_nohup(self):
        """Ensure that command is not reloaded with invalid config."""
        command = '%s %s' % (self.prog, self.sig)
        with ReloadConf(self.dir, self.file, command, '/bin/true') as rc:
            rc.poll()
            # Command should now be running.
            self.assertTrue(rc.check_command())
            # A bit nasty, but we want the check to fail this time...
            rc.test = '/bin/false'
            # Write out "config" file.
            with open(pathjoin(self.dir, basename(self.file)), 'wb') as f:
                f.write(b'foo')
            # Command should NOT receive HUP.
            rc.poll()
            time.sleep(0.1)
            self.assertFalse(pathexists(self.sig))

    def test_chown_fail(self):
        """Test chown validation."""
        # Ensure chown must have len() == 2:
        with self.assertRaises(AssertionError):
            ReloadConf(self.dir, [], None, chown=(1, 2, 3))

    def test_chown_user(self):
        """Test chown argument handling (user only)."""
        # Ensure chown handles a user name:
        with ReloadConf(self.dir, self.file, '/bin/true', chown='nobody') as rc:
            self.assertIsInstance(rc.chown[0], numbers.Number)
            self.assertEqual(-1, rc.chown[1])

        with ReloadConf(self.dir, self.file, '/bin/true', chown=TEST_UID) as rc:
            self.assertEqual((TEST_UID, -1), rc.chown)

    @skipIf(os.getuid() != 0, 'Only works as root')
    def test_chown(self):
        """Test chown capability."""
        with ReloadConf(self.dir, self.file, '/bin/true',
                        chown=(TEST_UID, TEST_UID)) as rc:
            with open(pathjoin(self.dir, basename(self.file)), 'wb') as f:
                f.write(b'foo')
            rc.poll()
            self.assertEqual(TEST_UID, os.stat(self.file).st_uid)
            self.assertEqual(TEST_UID, os.stat(self.file).st_gid)

    def test_chmod(self):
        """Test chmod capability."""
        # Ensure chmod must be numeric:
        with self.assertRaises(AssertionError):
            ReloadConf(self.dir, [], None, chmod='foo')
        # Ensure config files are properly chmod()ed:
        with ReloadConf(self.dir, self.file, '/bin/true', chmod=0o700) as rc:
            watch = pathjoin(self.dir, basename(self.file))
            with open(watch, 'wb') as f:
                f.write(b'foo')
            os.chmod(watch, 0o755)
            rc.poll()
            self.assertEqual(stat.S_IMODE(os.stat(self.file).st_mode), 0o700)

    def test_nodir(self):
        """Test that watch directory does not need to exist."""
        # Remove the watch directory.
        os.rmdir(self.dir)

        # Ensure reloadconf creates the watch directory.
        with ReloadConf(self.dir, self.file, '/bin/sleep 1',
                        chown=(TEST_UID, TEST_UID), chmod=0o700) as rc:
            rc.poll()
            self.assertTrue(rc.check_command())
            self.assertTrue(isdir(self.dir))

    def test_main(self):
        """Test that reloadconf blocks on command."""
        with timeout():
            with self.assertRaises(TestTimeoutError):
                self.run_cli()

    def test_wait_timeout(self):
        with timeout():
            with self.assertRaises(DocoptExit) as exc:
                self.run_cli(others=['--wait-timeout=-1'])
            self.assertStartsWith("Invalid timeout", exc.exception.args[0])

        with timeout():
            with self.assertRaises(DocoptExit) as exc:
                self.run_cli(others=['--wait-timeout=string'])
            self.assertStartsWith("Invalid timeout", exc.exception.args[0])

    def test_wait_for_path_fail(self):
        with self.assertRaises(TimeoutExpired):
            self.run_cli(others=['--wait-for-path=non-existent-file',
                                 '--wait-timeout=0.1'])

    def test_wait_for_path_ok(self):
        with open(TESTFN, "w"):
            pass

        with timeout():
            with self.assertRaises(TestTimeoutError):
                self.run_cli(others=['--wait-for-path=' + TESTFN,
                                    '--wait-timeout=0.1'])

    def test_wait_for_sock_fail(self):
        with self.assertRaises(TimeoutExpired):
            self.run_cli(others=['--wait-for-sock=localhost:65000',
                                 '--wait-timeout=0.1'])

    def test_wait_for_sock_ok(self):
        with timeout():
            with self.assertRaises(TestTimeoutError):
                self.run_cli(others=['--wait-for-sock=google.com:80',
                                    '--wait-timeout=3'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
