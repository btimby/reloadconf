#!/usr/bin/env python

from __future__ import absolute_import

import sys
import time
import logging

from docopt import docopt

from reloadconf import ReloadConf


LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.NullHandler())


def validate_opts(opts):
    # mandatory
    assert opts.get('command', '').strip(), "empty command opt"
    assert opts.get('watch', '').strip(), "empty watch opt"
    # others
    addr = opts.get('wait_for_sock')
    if addr:
        assert addr.count(':') == 1, "invalid address %r" % addr
        host, port = addr.split(':')
        assert port.isdigit(), "invalid port" % port
        assert int(port) > 0, "invalid port %r" % port
        assert int(port) < 65536, "invalid port %r" % port
    timeout = opts.get('wait_timeout')
    if timeout:
        try:
            float(timeout)
        except ValueError:
            assert 0, "invalid timeout %r" % timeout
        assert int(timeout) > 0, "invalid timeout %r" % timeout


def main(opt):
    """
    reloadconf - Monitor config changes and safely restart.

    Usage:
        reloadconf --command=<cmd> --watch=<dir> (--config=<file> ...)
                   [--reload=<cmd> --test=<cmd> --wait-for-path=<file>
                    --wait-for-sock=<host:port> --wait-timeout=<secs> --debug]

    Options:
        --command=<cmd>  The program to run when configuration is valid.
        --watch=<dir>    The directory to watch for incoming files.
        --config=<file>  A destination config file path.
        --reload=<cmd>   The command to reload configuration (defaults to HUP
                         signal).
        --test=<cmd>     The command to test configuration.
        --wait-for-path=<file>
                         Delay start until file or directory appears on disk.
        --wait-for-sock=<host:port>
                         Delay start until connection succeeds.
        --wait-timeout=<secs>
                         Timeout for wait-* commands [default: 5].
        --debug          Verbose output.

    Assumptions:
     - The command accepts HUP signal to reload it's configuration.
     - Config files don't have the same name (if two config files in different
       directories have the same name, reloadconf will have issues.)

    Upon startup reloadconf will test the configuration and if valid, will run
    command. If command dies for any reason, reloadconf re-runs it. If the
    configuration is invalid (test command fails) then reloadconf waits for new
    files to appear in it's input directory, merges those and re-tests the
    config. If --test is omitted, then the configuration test is skipped, but
    reloadconf still monitors for new config files and reloads command. Command
    is reloaded by sending a HUP signal.

    Config files are matched by name. For example, if the input directory is
    /tmp, and a given config file is /etc/foo.conf, then reloadconf will watch
    for /tmp/foo.conf to appear, and will overwrite /etc/foo.conf with it and
    then test the config. Reloadconf can handle multiple config files, but
    since it uses the file name to determine a file's destination, names must
    be unique.

    Reloadconf will wait for 1 second after seeing any configuration file
    appear to give the configuration generator time to complete all files for
    a configuration file set. If it takes more than 1 second to generate a full
    configuration, then the generator program should write them to temporary
    space before moving them into the input directory.
    """

    # Convert from CLI arguments to kwargs.
    kwargs = {}
    for k in opt.keys():
        kwargs[k.lstrip('-').replace('-', '_')] = opt[k]

    validate_opts(kwargs)
    control = ReloadConf(**kwargs)
    LOGGER.info('Reloadconf monitoring %s for %s', kwargs['watch'],
                kwargs['command'])

    while True:
        try:
            control.poll()
        except Exception:
            LOGGER.exception('Error polling', exc_info=True)
        # Check 20 times a minute.
        time.sleep(3.0)


opt = docopt(main.__doc__)

logger = logging.getLogger()
# Set up logging so we can see output.
logger.addHandler(logging.StreamHandler(sys.stdout))

logger.setLevel(logging.INFO)
if opt.pop('--debug', None):
    logger.setLevel(logging.DEBUG)

main(opt)
