# Voltage's launch gate (launch item 11). `make launch-check` runs, in order:
#   1. the backend suite            2. the front end: vitest, build, lint, the layout tests
#   3. migrations up and down on a copy of the database (DB=..., never changed)
#   4. the em dash check            5. the launch profile's flags, printed
#   6. the production variables (ENV_FILE=...; fails while any is missing)
# SKIP_ENV=1 skips step 6 (for a laptop with no production keys).

VENV   ?= $(CURDIR)/backend/.venv
PY     ?= $(VENV)/bin/python
DB     ?= $(CURDIR)/backend/var/ave.db
ENV_FILE ?= $(CURDIR)/.env
PW_PORT ?= 5194
BACKEND = cd backend && PYTHONPATH="$(CURDIR)/backend"

.PHONY: launch-check backend-tests frontend-tests migrations-check em-dash-check profile env-check

launch-check: backend-tests frontend-tests migrations-check em-dash-check profile env-check
	@echo "launch-check: all steps passed"

backend-tests:
	$(BACKEND) "$(PY)" -m pytest -q -p no:cacheprovider

frontend-tests:
	cd frontend && npx vitest run && npm run build && npm run lint && PW_PORT=$(PW_PORT) npx playwright test

migrations-check:
	$(BACKEND) "$(PY)" -m app.tools.migration_check --db "$(DB)"

em-dash-check:
	$(BACKEND) "$(PY)" -m pytest -q -p no:cacheprovider tests/test_no_em_dashes.py

profile:
	$(BACKEND) "$(PY)" -m app.flags profile public

env-check:
ifeq ($(SKIP_ENV),1)
	@echo "env-check: skipped (SKIP_ENV=1)"
else
	$(BACKEND) "$(PY)" -m app.tools.env_check --env-file "$(ENV_FILE)"
endif
