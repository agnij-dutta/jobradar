PY ?= python3

.PHONY: help test lint format typecheck lint-web format-web check sweep build build-sample serve stats deploy

help:
	@echo "test        unit tests"
	@echo "lint        ruff check + ruff format --check (Python), biome check (web)"
	@echo "format      ruff format + biome format"
	@echo "typecheck   mypy"
	@echo "check       lint + typecheck + test + build-sample (what CI runs)"
	@echo "sweep       fetch every board (network, a few minutes)"
	@echo "build       build dist/ from data/snapshot.json"
	@echo "serve       build and serve dist/ on http://localhost:8787"
	@echo "deploy      build dist/ and deploy it to the Vercel project jobradar (Vercel CLI, logged in)"

test:
	$(PY) -m unittest discover -s tests -t . -v

lint:
	ruff check .
	ruff format --check .
	npx --no-install biome check web

format:
	ruff format .
	npx --no-install biome format --write web

typecheck:
	mypy

build-sample:
	$(PY) -m jobradar build --snapshot tests/fixtures/sample_snapshot.json --out dist-sample

check: lint typecheck test build-sample

sweep:
	$(PY) -m jobradar sweep

build:
	$(PY) -m jobradar build

serve: build
	$(PY) -m http.server 8787 -d dist

stats:
	$(PY) -m jobradar stats

# The sweep in data/ is local only (gitignored), so the site is deployed prebuilt from dist/.
deploy: build
	cd dist && vercel link --yes --project jobradar >/dev/null && vercel deploy --prod --yes
