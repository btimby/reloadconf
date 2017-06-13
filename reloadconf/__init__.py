#!/usr/bin/env python

import errno
import logging
import os
import signal
import subprocess
import time
import shlex
import shutil

from os.path import basename, dirname
from os.path import join as pathjoin
from os.path import splitext
from hashlib import md5


LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())
DEVNULL = open(os.devnull, 'w')


def checksum(path):
    """
    Calculate a checksum for the given path.

    Will eventually use this to ensure config has changed before reloading.
    """
    with open(path, 'r') as f:
        return md5(f.read()).digest()


class ReloadConf(object):
    """
    Simple process manager.

    This class watches a directory for config files. When a file or files
    appear, it will test the new configuration and then reload command. If the
    test fails, the configuration is reverted and command is left running.

    Parameters:
      watch - The directory to watch for inbound configuration files.
      config - The configuration file(s) that the command uses (destination).
      test - The command to run to test the config.

    The high level process is this:
    1. If config is present, it is tested and command is started.
    2. If config is NOT present or NOT valid, command is NOT run.
    3. While command is running, if it dies, it is restarted.
    4. If config files appear in watch, then we attempt to safely swap config:
      A. Backup current running configuration files.
      B. Copy new configuration files into destinations.
      C. Test new configuration files.
      D. If test succeeds, HUP command.
      E. If test fails, revert config.
    """

    def __init__(self, watch, config, command, test=None):
        if isinstance(config, str):
            config = (config,)
        self.watch = watch
        self.config = set(config)
        self.command = command
        self.test = test
        # Extract names for use later.
        self.watch_names = [basename(f) for f in self.config]
        # The process (once started).
        self.process = None

    def start_command(self, wait_for_config=True):
        p = self.process = subprocess.Popen(shlex.split(self.command))
        LOGGER.info('Command (%s) started with pid %s', self.command, p.pid)

    def reload_command(self):
        assert self.process is not None, 'Command not started'
        assert self.process.poll() is None, 'Command dead'
        self.process.send_signal(signal.SIGHUP)
        LOGGER.info('Sent process HUP signal')

    def check_command(self):
        """Return False if command is dead, otherwise True."""
        return self.process is not None and self.process.poll() is None

    def poll(self):
        """Processing loop."""
        # First attempt to install a new config.
        files = os.listdir(self.watch)
        new_config = set()
        for i in range(2):
            for name in self.watch_names:
                if name in files:
                    new_config.add(name)
            if not new_config or i == 1:
                break
            # Sleep a bit to allow for more config files to appear, we want
            # to avoid a race condition with the process that generates
            # these config files.
            time.sleep(1.0)
        if new_config:
            LOGGER.info('New config found %s', ', '.join(new_config))
            # TODO: compare new config checksums with old to see if there are
            # really changes.
            self.test_and_swap(new_config)
        elif not self.check_command() and self.test_command():
            # If command is not running and config is valid, start command.
            self.start_command()

    def test_command(self):
        """Run test command to verify configuration."""
        # If there is no test command, assume the config is good to go.
        if self.test is None:
            return True
        # Attempt parse.
        return subprocess.call(
            shlex.split(self.test),
            stderr=subprocess.STDOUT,
            stdout=DEVNULL
        ) == 0

    def backup_create(self):
        """Backs up entire configuration."""
        prev_config = set()
        for file in self.config:
            backup = file + '.prev'
            LOGGER.debug('Backing up %s to %s', file, backup)
            try:
                shutil.copy(file, backup)
            except IOError as e:
                if e.errno != errno.ENOENT:
                    raise
                # If the config file is missing, we can skip backing it up.
                LOGGER.warning('Config file %s missing, skipping backup', file)
            else:
                prev_config.add(backup)
        return prev_config

    def backup_remove(self, prev_config):
        """Remove backup once command is restarted."""
        for path in prev_config:
            try:
                os.remove(path)
            except IOError as e:
                if e.errno != errno.ENOENT:
                    LOGGER.warning('Could not remove backup: %s', path)

    def backup_restore(self, prev_config):
        """Restores a previous config backup."""
        for backup in prev_config:
            # Remove .prev
            file = splitext(backup)[0]
            LOGGER.debug('Restoring %s from %s', file, backup)
            shutil.move(backup, file)

    def test_and_swap(self, new_config):
        """Backup old config, write new config, test config, HUP or restore."""
        prev_config = self.backup_create()
        # We have backed up ALL config files (not just the ones we might
        # replace). If any error occurs from here out, we will need to restore
        # our config, so we will use exception handling.
        try:
            for file in new_config:
                # Determine which file to overwrite (same names, different
                # directories).
                dst = [p for p in self.config if basename(p) == file][0]
                src = pathjoin(self.watch, file)
                LOGGER.debug('Overwriting %s with %s', src, dst)
                try:
                    os.makedirs(dirname(dst))
                except OSError as e:
                    if e.errno != errno.EEXIST:
                        raise
                shutil.move(src, dst)
            # We have now merged in our new configuration files, lets test this
            # config.
            if self.test_command():
                LOGGER.debug('Config good, reloading')
                if self.check_command():
                    self.reload_command()
                else:
                    self.start_command(wait_for_config=False)
                self.backup_remove(prev_config)
            else:
                LOGGER.debug('Config bad, restoring')
                self.backup_restore(prev_config)
        except:
            LOGGER.exception('Failure, restoring config', exc_info=True)
            self.backup_restore(prev_config)
