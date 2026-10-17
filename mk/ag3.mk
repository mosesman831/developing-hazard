# Owned by AG3. Targets for this agent only (see SPEC-fmdplt.md).

.PHONY: serve snapshot deploy smoke

DH_PORT ?= 8000

serve:
	DH_MODE=dev uvicorn dh.server:app --host 0.0.0.0 --port $(DH_PORT)

snapshot:
	@echo "snapshot: dh/snapshot.py lands in Phase 2"

deploy:
	bash deploy/deploy.sh

smoke:
	bash scripts/smoke.sh
