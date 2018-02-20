PYTHON = python3
ARGS ?=
# In not in a virtualenv, add --user options for install commands.
INSTALL_OPTS = `$(PYTHON) -c "import sys; print('' if hasattr(sys, 'real_prefix') else '--user')"`


coverage:
	$(PYTHON) -m coverage run tests.py
	$(PYTHON) -m coverage html
	firefox htmlcov/index.html

install:
	$(PYTHON) setup.py develop $(INSTALL_OPTS)

test:
	PYTHONWARNINGS=all $(PYTHON) tests.py

# E.g. make test-by-name ARGS=tests.TestReloadConf.test_wait_timeout
test-by-name:
	PYTHONWARNINGS=all $(PYTHON) -m unittest -v $(ARGS)

lint:
	$(PYTHON) -m flake8 reloadconf

dependencies:
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m pip install coveralls
	$(PYTHON) -m pip install flake8
	$(PYTHON) -m pip install coverage

travis:
	$(MAKE) dependencies
	$(MAKE) install
	$(MAKE) test
	$(PYTHON) -m flake8 reloadconf

coveralls:
	$(PYTHON) -m coveralls -v

clean:
	rm -rf dist/ *.egg-info htmlcov .coverage

install-pip:  ## Install pip (no-op if already installed).
	$(PYTHON) -c \
		"import sys, ssl, os, pkgutil, tempfile, atexit; \
		sys.exit(0) if pkgutil.find_loader('pip') else None; \
		pyexc = 'from urllib.request import urlopen' if sys.version_info[0] == 3 else 'from urllib2 import urlopen'; \
		exec(pyexc); \
		ctx = ssl._create_unverified_context() if hasattr(ssl, '_create_unverified_context') else None; \
		kw = dict(context=ctx) if ctx else {}; \
		req = urlopen('https://bootstrap.pypa.io/get-pip.py', **kw); \
		data = req.read(); \
		f = tempfile.NamedTemporaryFile(suffix='.py'); \
		atexit.register(f.close); \
		f.write(data); \
		f.flush(); \
		print('downloaded %s' % f.name); \
		code = os.system('%s %s --user' % (sys.executable, f.name)); \
		f.close(); \
		sys.exit(code);"
