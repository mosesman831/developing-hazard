# Owned by AG2. Targets for this agent only (see SPEC-riyud1.md).

.PHONY: mine build freeze

mine:
	python -m dh.mine

build:
	python -m dh.mine build
	python -m dh.frames

freeze:
	python -m dh.api.labels
