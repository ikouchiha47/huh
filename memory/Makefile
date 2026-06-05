SKILLS_SRC := $(shell dirname $(abspath $(lastword $(MAKEFILE_LIST))))/../skills
SKILLS_DST := $(HOME)/.claude/skills

.PHONY: install link unlink

install:
	cd $(shell dirname $(abspath $(lastword $(MAKEFILE_LIST)))) && uv tool install -e .

link:
	mkdir -p $(SKILLS_DST)
	ln -sf $(SKILLS_SRC)/memory $(SKILLS_DST)/memory
	@echo "Linked $(SKILLS_SRC)/memory -> $(SKILLS_DST)/memory"

unlink:
	rm -f $(SKILLS_DST)/memory

dev: install link
