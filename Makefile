.PHONY: install run figures test lint all ingest integration

install:
	pip install -e ".[dev]"

run:          ## warehouse + quality gates + all analyses -> outputs/
	cellrel run

figures:
	cellrel figures

test:
	pytest -q

lint:
	ruff check src tests

ingest:       ## refresh the NHTSA snapshot from api.nhtsa.gov (needs internet)
	cellrel ingest-nhtsa --out data/raw

all: lint run figures test

integration:  ## needs MYSQL_URL, MONGO_URI, KAFKA_BOOTSTRAP (see .github/workflows/ci.yml)
	pip install -e ".[services]"
	pytest -v -rs tests/integration
