# Owned by AG1. Targets for this agent only (see SPEC-mosesman831.md).

.PHONY: detect grid propose run eval

detect:
	python -m dh.dets

grid:
	python -m dh.grid

propose:
	@echo not yet

run:
	python -m dh.evals --agent "$(AGENT)" --split "$(SPLIT)"

eval:
	python -m dh.evals --agent "$(AGENT)" --split "$(SPLIT)"
