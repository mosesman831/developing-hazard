# Shared, frozen. Each agent adds targets only in its own mk/agN.mk.
.PHONY: test
test:
	python -m pytest -q tests

-include mk/ag1.mk
-include mk/ag2.mk
-include mk/ag3.mk
