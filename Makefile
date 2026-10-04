PY ?= python3

.PHONY: test lint-js check sweep build serve stats

test:
	$(PY) -m unittest discover -s tests -t . -v

lint-js:
	node --check web/app.js

check: test lint-js

sweep:
	$(PY) -m jobradar sweep

build:
	$(PY) -m jobradar build

serve: build
	$(PY) -m http.server 8787 -d dist

stats:
	$(PY) -m jobradar stats
