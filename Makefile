coverage:
	coverage run tests.py
	coverage html
	firefox htmlcov/index.html

test:
	python tests.py

lint:
	flake8 reloadconf

dependencies:
	pip install -r requirements.txt
	pip install coveralls
	pip install flake8
	pip install coverage

travis:
	flake8 reloadconf
	coverage run tests.py

coveralls:
	coveralls -v

clean:
	rm -rf dist/ *.egg-info htmlcov .coverage
