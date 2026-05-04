SKILLS_SRC := $(shell dirname $(abspath $(lastword $(MAKEFILE_LIST))))/../skills
SKILLS_DST := $(HOME)/.claude/skills

.PHONY: install link unlink

install:
	cd $(shell dirname $(abspath $(lastword $(MAKEFILE_LIST)))) && uv tool install -e .

link:
	mkdir -p $(SKILLS_DST)
	ln -sf $(SKILLS_SRC)/huh $(SKILLS_DST)/huh
	@echo "Linked $(SKILLS_SRC)/huh -> $(SKILLS_DST)/huh"

unlink:
	rm -f $(SKILLS_DST)/huh

dev: install link
