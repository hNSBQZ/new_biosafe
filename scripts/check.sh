#!/usr/bin/env bash
set -euo pipefail

conda run -n biosafe python -m ruff check biosafe services scripts tests
conda run -n biosafe python -m pytest
npm --prefix web test -- --run
npm --prefix web run build
