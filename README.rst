.. image:: https://travis-ci.org/btimby/reloadconf.svg?branch=master
   :alt: Travis CI Status
   :target: https://travis-ci.org/btimby/reloadconf

.. image:: https://coveralls.io/repos/github/btimby/reloadconf/badge.svg?branch=master
    :target: https://coveralls.io/github/btimby/reloadconf?branch=master
    :alt: Code Coverage

.. image:: https://badge.fury.io/py/reloadconf.svg
    :target: https://badge.fury.io/py/reloadconf

ReloadConf
==========
Simple process manager. Reloadconf is a front-end for arbitrary commands. It
will watch a directory for configuration files and optionally run a command
to test those configuration files. When the configuration is valid a
command (daemon) is executed. Whenever new configuration files are detected
this procedure is repeated.

Here is an example usage for nginx.

::

    $ reloadconf --config=/etc/nginx/nginx.conf --command="nginx -g nodaemon: true" --test="nginx -t" --watch=/tmp/nginx

First of all, if ``/etc/nginx/nginx.conf`` exists, it will be verified using
``nginx -t`` and if successful, nginx will be started. In either case
reloadconf will then proceed to watch ``/tmp/nginx`` for a file name
``nginx.conf``. If present, that fill will be tested, and a if successful
a HUP signal will be sent to nginx (or nginx will be started).

Docker
======
ReloadConf is generally useful whenever you want a process to recieve a HUP
signal after new configuration is written. It was written to be used with
docker where one container generates a config file for a process in another
container. To use it for this purpose, simply install then utilize
reloadconf in your Dockerfile.

::

    # Install reloadconf.
    RUN pip install reloadconf

    # Map a volume into the container.
    VOLUME /mnt/data/nginx/:/conf/

    # Watch for another container to modify the conf and reload nginx.
    CMD reloadconf --command="nginx -c /conf/nginx.conf -g'nodaemon: true;'" --watch=/conf/in --test="nginx -c /conf/nginx.conf -t" --config=/conf/nginx.conf

