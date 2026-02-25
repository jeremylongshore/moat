# Moat Project Makefile
#
# Design decisions:
#   - All paths are relative to the project root (this file's location).
#   - `make ci` is the canonical gate that mirrors GitHub Actions.
#   - Docker targets use the docker-compose file in infra/local/ with
#     project root as the build context.
#   - `make dev` starts uvicorn reloaders; Ctrl-C kills all background jobs.

.PHONY: help dev docker-up docker-down test lint format format-check \
        typecheck ci clean demo install setup

# ── Colours ─────────────────────────────────────────────────────────────────
RESET  := \033[0m
BOLD   := \033[1m
GREEN  := \033[32m
YELLOW := \033[33m
CYAN   := \033[36m

# ── Docker Compose shorthand ─────────────────────────────────────────────────
COMPOSE        := docker compose -f infra/local/docker-compose.yml
# If .env exists, pass it; otherwise fall back to .env.example
ENV_FILE       := $(shell test -f infra/local/.env && echo "infra/local/.env" || echo "infra/local/.env.example")
COMPOSE_RUN    := $(COMPOSE) --env-file $(ENV_FILE)

# ── Python / Pytest settings ──────────────────────────────────────────────────
PYTHON         := python3
PYTEST_FLAGS   := -v --tb=short
COVERAGE_FLAGS := --cov=packages/core/moat_core --cov-report=term-missing --cov-report=html

# ── All package / service dirs for installs ───────────────────────────────────
ALL_INSTALLABLE := packages/core \
                   packages/cli \
                   services/control-plane \
                   services/gateway \
                   services/trust-plane \
                   services/mcp-server

# ─────────────────────────────────────────────────────────────────────────────
# help  (default target)
# ─────────────────────────────────────────────────────────────────────────────
help:
	@printf "$(BOLD)Moat – available targets$(RESET)\n\n"
	@printf "  $(CYAN)make dev$(RESET)           Start all 4 services locally (uvicorn --reload)\n"
	@printf "  $(CYAN)make docker-up$(RESET)     Start full stack via docker-compose (detached)\n"
	@printf "  $(CYAN)make docker-down$(RESET)   Stop and remove docker-compose containers\n"
	@printf "\n"
	@printf "  $(CYAN)make test$(RESET)          Run pytest across all packages and services\n"
	@printf "  $(CYAN)make lint$(RESET)          ruff check + ruff format --check\n"
	@printf "  $(CYAN)make format$(RESET)        ruff format (writes changes)\n"
	@printf "  $(CYAN)make format-check$(RESET)  ruff format --check (CI-safe, no writes)\n"
	@printf "  $(CYAN)make typecheck$(RESET)     mypy on packages/ and services/\n"
	@printf "  $(CYAN)make ci$(RESET)            lint + typecheck + test  (mirrors CI)\n"
	@printf "\n"
	@printf "  $(CYAN)make install$(RESET)       pip install -e all packages + services + dev deps\n"
	@printf "  $(CYAN)make setup$(RESET)         Full dev environment setup (venv + install)\n"
	@printf "  $(CYAN)make clean$(RESET)         Remove pycache, .pytest_cache, coverage artefacts\n"
	@printf "  $(CYAN)make demo$(RESET)          Run the end-to-end demo script\n"

# ─────────────────────────────────────────────────────────────────────────────
# setup / install
# ─────────────────────────────────────────────────────────────────────────────
setup:
	@printf "$(BOLD)Setting up dev environment...$(RESET)\n"
	$(PYTHON) -m venv .venv
	@printf "$(YELLOW)Activate with: source .venv/bin/activate$(RESET)\n"
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -r requirements-dev.txt
	@for pkg in $(ALL_INSTALLABLE); do \
	    printf "  Installing $$pkg\n"; \
	    .venv/bin/pip install -e "$$pkg"; \
	done
	@printf "$(GREEN)Setup complete.$(RESET)\n"

install:
	@printf "$(BOLD)Installing packages (editable)...$(RESET)\n"
	pip install -r requirements-dev.txt
	@for pkg in $(ALL_INSTALLABLE); do \
	    printf "  pip install -e $$pkg\n"; \
	    pip install -e "$$pkg"; \
	done

# ─────────────────────────────────────────────────────────────────────────────
# dev  – local uvicorn (no Docker)
# ─────────────────────────────────────────────────────────────────────────────
dev:
	@printf "$(BOLD)Starting all Moat services locally...$(RESET)\n"
	@bash scripts/dev.sh

# ─────────────────────────────────────────────────────────────────────────────
# docker
# ─────────────────────────────────────────────────────────────────────────────
docker-up:
	@printf "$(BOLD)Starting docker-compose stack...$(RESET)\n"
	@# Auto-copy .env.example → .env on first run so operators don't have to.
	@test -f infra/local/.env || (cp infra/local/.env.example infra/local/.env && \
	    printf "$(YELLOW)Created infra/local/.env from .env.example. Edit it before production use.$(RESET)\n")
	$(COMPOSE) up --build -d
	@printf "$(GREEN)Services up. Logs: docker compose -f infra/local/docker-compose.yml logs -f$(RESET)\n"

docker-down:
	@printf "$(BOLD)Stopping docker-compose stack...$(RESET)\n"
	$(COMPOSE_RUN) down --remove-orphans

# ─────────────────────────────────────────────────────────────────────────────
# lint
# ─────────────────────────────────────────────────────────────────────────────
lint:
	@printf "$(BOLD)Running ruff check...$(RESET)\n"
	ruff check packages/ services/
	@printf "$(BOLD)Running ruff format --check...$(RESET)\n"
	ruff format --check packages/ services/

format:
	@printf "$(BOLD)Formatting with ruff...$(RESET)\n"
	ruff format packages/ services/
	ruff check --fix packages/ services/

format-check:
	ruff format --check packages/ services/

# ─────────────────────────────────────────────────────────────────────────────
# typecheck
# ─────────────────────────────────────────────────────────────────────────────
typecheck:
	@printf "$(BOLD)Running mypy...$(RESET)\n"
	mypy packages/ services/

# ─────────────────────────────────────────────────────────────────────────────
# test
# ─────────────────────────────────────────────────────────────────────────────
test:
	@printf "$(BOLD)Running pytest...$(RESET)\n"
	pytest $(PYTEST_FLAGS) packages/core/tests/
	PYTHONPATH=services/control-plane pytest $(PYTEST_FLAGS) services/control-plane/tests/
	PYTHONPATH=services/gateway pytest $(PYTEST_FLAGS) services/gateway/tests/

test-coverage:
	@printf "$(BOLD)Running pytest with coverage...$(RESET)\n"
	pytest $(PYTEST_FLAGS) $(COVERAGE_FLAGS) packages/ services/
	@printf "$(GREEN)HTML report: htmlcov/index.html$(RESET)\n"

# ─────────────────────────────────────────────────────────────────────────────
# ci  – mirrors GitHub Actions (fail-fast)
# ─────────────────────────────────────────────────────────────────────────────
ci: lint typecheck test
	@printf "$(GREEN)$(BOLD)CI passed.$(RESET)\n"

# ─────────────────────────────────────────────────────────────────────────────
# demo
# ─────────────────────────────────────────────────────────────────────────────
demo:
	@printf "$(BOLD)Running Moat end-to-end demo...$(RESET)\n"
	bash scripts/demo.sh

# ─────────────────────────────────────────────────────────────────────────────
# clean
# ─────────────────────────────────────────────────────────────────────────────
clean:
	@printf "$(BOLD)Cleaning build artefacts...$(RESET)\n"
	find . -type d -name "__pycache__"  -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".mypy_cache"   -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info"    -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov"       -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc"         -delete 2>/dev/null || true
	find . -type f -name ".coverage"     -delete 2>/dev/null || true
	@printf "$(GREEN)Clean.$(RESET)\n"
