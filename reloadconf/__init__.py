"""ReloadConf"""

import errno
import logging
import os
import signal
import subprocess
import time
import shlex
import shutil
import numbers
import pwd
import grp

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

    def __init__(self, watch, config, command, reload=None, test=None,
                 chown=None, chmod=None):
        if isinstance(config, str):
            config = (config,)
        self.watch = watch
        self.config = set(config)
        self.command = command
        self.reload = reload
        self.test = test
        self.chown, self.chmod = self._setup_permissions(chown, chmod)
        # Extract names for use later.
        self.watch_names = [basename(f) for f in self.config]
        # The process (once started).
        self.process = None

    def _setup_permissions(self, chown, chmod):
        if chown is not None:
            if isinstance(chown, str):
                user, group = chown, None

            else:
                try:
                    # Try to extract tuple.
                    user, group = chown

                except ValueError:
                    # If length of iterable is not 2, then allow 1.
                    assert len(chown) == 1, 'chown must be user or tuple'
                    user, group = chown[0], None

                except TypeError:
                    # If not iterable, use given value as user.
                    user, group = chown, None

            # Lookup user id.
            if isinstance(user, str):
                user_info = pwd.getpwnam(user)
                user = user_info.pw_uid

            # Lookup group id, or use -1 (do not change group)
            if isinstance(group, str):
                group = grp.getgrnam(group).pw_gid

            elif group is None:
                group = -1

            # Return tuple usable by os.chown().
            chown = (user, group)

        # Ensure chmod is numeric if given.
        if chmod is not None:
            assert isinstance(chmod, numbers.Number), 'chmod must be a number'

        return chown, chmod

    def start_command(self, wait_for_config=True):
        p = self.process = subprocess.Popen(shlex.split(self.command))
        LOGGER.info('Command (%s) started with pid %s', self.command, p.pid)

    def reload_command(self):
        """
        Reload configuration.

        If reload command is given, run that, otherwise, signal process with
        HUP.
        """
        if self.reload is None:
            if not self.check_command():
                LOGGER.info('Command dead, restarting...')
                self.start_command(wait_for_config=False)

            else:
                LOGGER.info('Sending HUP signal...')
                self.process.send_signal(signal.SIGHUP)

        else:
            LOGGER.info('Executing reload command...')
            subprocess.call(shlex.split(self.reload))

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
            LOGGER.info('New configuration found %s', ', '.join(new_config))
            # TODO: compare new config checksums with old to see if there are
            # really changes.
            self.test_and_swap(new_config)
        elif not self.check_command():
            if self.test_command():
                LOGGER.debug('Command not running and valid configuration '
                             'found')
                # If command is not running and config is valid, start command.
                self.start_command()

    def test_command(self, quiet=True):
        """Run test command to verify configuration."""
        # If there is no test command, assume the config is good to go.
        if self.test is None:
            return True
        # Attempt parse.
        kwargs = {}
        if quiet:
            kwargs['stdout'] = DEVNULL
            kwargs['stderr'] = subprocess.STDOUT
        return subprocess.call(shlex.split(self.test), **kwargs) == 0

    def backup_config(self):
        """Backs up entire configuration."""
        prev_config = set()
        for src in self.config:
            dst = '%s.prev' % src
            LOGGER.debug('Backing up %s to %s', src, dst)

            try:
                shutil.copy(src, dst)

            except IOError as e:
                if e.errno != errno.ENOENT:
                    raise

                # If the config file is missing, we can skip backing it up.
                LOGGER.warning('File %s missing, skipping backup', src)

            else:
                prev_config.add(dst)
        return prev_config

    def remove_config(self, config):
        """Remove backup once command is restarted."""
        for fn in config:
            try:
                os.remove(fn)
                LOGGER.debug('Removed backup: %s', fn)

            except IOError as e:
                if e.errno != errno.ENOENT:
                    LOGGER.warning('Could not remove backup: %s', fn)

    def restore_config(self, config):
        """Restores a previous config backup."""
        for src in config:
            # Remove .prev
            dst, _ = splitext(src)
            LOGGER.debug('Restoring %s from %s', dst, src)
            shutil.move(src, dst)

    def install_config(self, config):
        """Copy new configuration to location service expects."""
        for fn in config:
            dst = [p for p in self.config if basename(p) == fn][0]
            src = pathjoin(self.watch, fn)

            try:
                os.makedirs(dirname(dst))
            except OSError as e:
                if e.errno != errno.EEXIST:
                    raise

            LOGGER.debug('Overwriting %s with %s', src, dst)
            shutil.move(src, dst)

            if self.chown is not None:
                os.chown(dst, *self.chown)

            if self.chmod is not None:
                os.chmod(dst, self.chmod)

    def test_and_swap(self, config):
        """Backup old config, write new config, test config, HUP or restore."""
        LOGGER.info('Attempting to apply new configuration')
        backup = self.backup_config()
        # We have backed up ALL config files (not just the ones we might
        # replace). If any error occurs from here out, we will need to restore
        # our config, so we will use exception handling.
        try:
            self.install_config(config)

            # We have now merged in our new configuration files, lets test this
            # config.
            if self.test_command(quiet=False):
                LOGGER.debug('Configuration good, reloading')
                self.reload_command()
                self.remove_config(backup)

            else:
                LOGGER.info('Configuration bad, restoring')
                self.restore_config(backup)

        except Exception:
            LOGGER.exception('Failure, restoring config', exc_info=True)
            self.restore_config(backup)
