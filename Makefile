.PHONY: install run figures test lint all ingest

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
