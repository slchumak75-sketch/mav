.PHONY: extract fill-purchase verify test web-install web-test build dev preview ci

extract:
	python3 tools/extract_xlsx.py

fill-purchase:
	python3 tools/extract_xlsx.py --fill-purchase

verify:
	python3 tools/extract_xlsx.py --verify

web-install:
	cd web && npm ci

web-test:
	cd web && npm test

test: verify
	python3 -m unittest discover -s tests -v
	cd web && npm test

build: extract
	cd web && npm run build

dev:
	cd web && npm run dev

preview:
	cd web && npm run preview

ci: verify test build
