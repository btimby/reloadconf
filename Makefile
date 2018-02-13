PYTHON = python

coverage:
	$(PYTHON) -m coverage run tests.py
	$(PYTHON) -m coverage html
	firefox htmlcov/index.html

install:
	$(PYTHON) setup.py develop

test:
	$(PYTHON) tests.py

lint:
	$(PYTHON) -m flake8 reloadconf

dependencies:
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
