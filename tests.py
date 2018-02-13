from __future__ import absolute_import

import os
import shutil
import signal
import sys
import tempfile
import time
import logging
import unittest

from os.path import exists as pathexists
from os.path import join as pathjoin
from os.path import basename

from reloadconf import ReloadConf

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


class TestReloadConf(unittest.TestCase):
    @classmethod
    def setUp(cls):
        cls.dir = tempfile.mkdtemp()
        cls.file = tempfile.mkstemp()[1]
        cls.sig = tempfile.mktemp()
        with tempfile.NamedTemporaryFile(delete=False) as p:
            p.write(TEST_PROGRAM)
            cls.prog = p.name
        os.chmod(cls.prog, 0o700)

    @classmethod
    def tearDown(cls):
        for path in (cls.file, cls.prog):
            try:
                os.remove(path)
            except IOError:
                pass
        try:
            shutil.rmtree(cls.dir)
        except IOError:
            pass

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

        sysargv = sys.argv

        sys.argv = [
            'reloadconf',
            '--watch=%s' % self.dir,
            '--config=%s' % self.file,
            '--command=/bin/sleep 1',
            '--test=/bin/true',
        ]

        try:
            try:
                import reloadconf.__main__
                self.fail('Should never reach this')
            except Sentinal:
                pass

        finally:
            sys.argv = sysargv

if __name__ == '__main__':
    unittest.main()
