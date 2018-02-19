PYTHON = python
ARGS ?=

coverage:
	$(PYTHON) -m coverage run tests.py
	$(PYTHON) -m coverage html
	firefox htmlcov/index.html

install:
	$(PYTHON) setup.py develop

test:
	$(PYTHON) tests.py

# E.g. make test-by-name ARGS=tests.TestReloadConf.test_wait_timeout
test-by-name:
	$(PYTHON) -m unittest -v $(ARGS)

lint:
	$(PYTHON) -m flake8 reloadconf

pydeps:
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m pip install coveralls
	$(PYTHON) -m pip install flake8
	$(PYTHON) -m pip install coverage

travis:
	$(PYTHON) -m flake8 reloadconf
	$(PYTHON) -m coverage run tests.py

coveralls:
	$(PYTHON) -m coveralls -v

clean:
	rm -rf dist/ *.egg-info htmlcov .coverage

ci:
	$(MAKE) pydeps
	$(MAKE) install
	$(MAKE) test
