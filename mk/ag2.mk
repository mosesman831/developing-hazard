# Owned by AG2. Targets for this agent only (see SPEC-riyud1.md).

.PHONY: mine build freeze

mine:
	@echo "mine: candidate discovery (dh/mine.py) lands in Phase 2"

build:
	@echo "build: clips.json and local joined clips land in Phase 2"

freeze:
	@echo "freeze: test set freeze (POST /api/testset/freeze) lands in Phase 2"
