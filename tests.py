from __future__ import absolute_import

import errno
import logging
import os
import shutil
import signal
import stat
import sys
import tempfile
import time
import unittest

from os.path import exists as pathexists
from os.path import join as pathjoin
from os.path import basename

from reloadconf import ReloadConf
from reloadconf import TimeoutExpired


# Test file name used during tests.
TESTFN = "rconf-testfile"

# Program to indicate HUP signal received.
TEST_PROGRAM = b"""#!/usr/bin/env python

import signal, time, sys

def _touch(*args):
    with open(sys.argv[1], 'wb') as f:
        f.write(b'')

signal.signal(signal.SIGHUP, _touch)

time.sleep(2)

"""


# Useful to debug threading issues.
logging.basicConfig(
    stream=sys.stderr,
    # Change level to DEBUG here if you need to.
    level=logging.CRITICAL,
    format='%(thread)d: %(message)s'
)
LOGGER = logging.getLogger(__name__)


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
        except IOError:
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

        sysargv = sys.argv

        try:
            sys.argv = [
                'reloadconf',
                watch,
                config,
                command,
                test,
            ]

            if others:
                assert isinstance(others, list), others
                sys.argv.extend(others)

            for x in sys.argv:
                assert isinstance(x, str), x

            # run
            import reloadconf.__main__  # NOQA
        finally:
            sys.argv = sysargv

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
        rc = ReloadConf(self.dir, self.file, command)
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
        rc = ReloadConf(self.dir, self.file, '/bin/sleep 1', reload=reload)
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
        rc = ReloadConf(self.dir, self.file, command, '/bin/true')
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

    def test_main(self):
        """Test that reloadconf blocks on command."""
        class Sentinal(Exception):
            pass

        def _alarm(*args):
            raise Sentinal()

        signal.signal(signal.SIGALRM, _alarm)
        signal.alarm(2)

        with self.assertRaises(Sentinal):
            self.run_cli()

    def test_wait_timeout(self):
        with self.assertRaises(AssertionError) as exc:
            self.run_cli(others=['--wait-timeout=-1'])
        self.assertEqual(exc.exception.message, "invalid timeout '-1'")

        with self.assertRaises(AssertionError) as exc:
            self.run_cli(others=['--wait-timeout=string'])
        self.assertEqual(exc.exception.message, "invalid timeout 'string'")

    def test_wait_for_path_fail(self):
        with self.assertRaises(TimeoutExpired):
            self.run_cli(others=['--wait-for-path=non-existent-file',
                                 '--wait-timeout=0.1'])

    def test_wait_for_path_ok(self):
        class Sentinal(Exception):
            pass

        def _alarm(*args):
            raise Sentinal()

        signal.signal(signal.SIGALRM, _alarm)
        signal.alarm(1)

        with open(TESTFN, "w"):
            pass

        with self.assertRaises(Sentinal):
            self.run_cli(others=['--wait-for-path=' + TESTFN,
                                 '--wait-timeout=0.1'])

    def test_wait_for_sock_fail(self):
        with self.assertRaises(TimeoutExpired):
            self.run_cli(others=['--wait-for-sock=localhost:65000',
                                 '--wait-timeout=0.1'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
