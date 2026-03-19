.PHONY: install install-build dev test lint fmt check-all build dist clean docker-build docker-up docker-down

# ── Зависимости ──────────────────────────────────────────────────────────────

install:
	uv pip install -e ".[dev]"

install-build:
	uv pip install -e ".[dev,build]"

dev: install
	@echo "Dev environment ready. Run: bsl-analyzer --help"

# ── Тесты и линтинг ──────────────────────────────────────────────────────────

test:
	python -m pytest

lint:
	ruff check src tests

fmt:
	ruff format src tests

check-all: lint test

# ── Сборка нативного бинаря (Nuitka) ─────────────────────────────────────────

ENTRY     = src/bsl_analyzer/__main__.py
DIST_DIR  = dist
BIN_NAME  = bsl-analyzer

# Определяем ОС для суффикса
UNAME := $(shell uname -s)
ifeq ($(UNAME), Darwin)
  BIN_SUFFIX =
  PLATFORM   = macos
else ifeq ($(UNAME), Linux)
  BIN_SUFFIX =
  PLATFORM   = linux
else
  BIN_SUFFIX = .exe
  PLATFORM   = windows
endif

BUILD_OUT = $(DIST_DIR)/$(BIN_NAME)$(BIN_SUFFIX)

build:
	@echo "→ Компиляция через Nuitka ($(PLATFORM))..."
	@mkdir -p $(DIST_DIR)
	.venv/bin/python -m nuitka \
		--standalone \
		--onefile \
		--output-filename=$(BIN_NAME)$(BIN_SUFFIX) \
		--output-dir=$(DIST_DIR) \
		--include-package=bsl_analyzer \
		--include-package=tree_sitter \
		--include-package=tree_sitter_bsl \
		--include-package=fastmcp \
		--include-package=pygls \
		--include-package=watchfiles \
		--include-package=rich \
		--include-data-dir=data=data \
		--assume-yes-for-downloads \
		--jobs=4 \
		$(ENTRY)
	@echo "✓ Готово: $(BUILD_OUT)"
	@ls -lh $(BUILD_OUT)

# Быстрая сборка без --onefile (для отладки, быстрее компилируется)
build-dev:
	@mkdir -p $(DIST_DIR)
	.venv/bin/python -m nuitka \
		--standalone \
		--output-dir=$(DIST_DIR)/dev \
		--include-package=bsl_analyzer \
		--include-data-dir=data=data \
		$(ENTRY)
	@echo "✓ Готово: $(DIST_DIR)/dev/__main__.dist/$(BIN_NAME)$(BIN_SUFFIX)"

# Проверить что бинарь работает
build-check: build
	$(BUILD_OUT) --help
	$(BUILD_OUT) --version

# Пакет для дистрибуции с версией из pyproject.toml
dist: build
	@VERSION=$$(python -c "import importlib.metadata; print(importlib.metadata.version('bsl-analyzer'))"); \
	ARCHIVE=$(DIST_DIR)/bsl-analyzer-$$VERSION-$(PLATFORM).tar.gz; \
	tar -czf $$ARCHIVE -C $(DIST_DIR) $(BIN_NAME)$(BIN_SUFFIX); \
	echo "✓ Архив: $$ARCHIVE"; \
	ls -lh $$ARCHIVE

# ── Docker ───────────────────────────────────────────────────────────────────

docker-build:
	docker compose -f docker/docker-compose.yml build

docker-up:
	docker compose -f docker/docker-compose.yml up -d

docker-down:
	docker compose -f docker/docker-compose.yml down

docker-logs:
	docker compose -f docker/docker-compose.yml logs -f

# ── Очистка ──────────────────────────────────────────────────────────────────

clean:
	rm -rf $(DIST_DIR)
	rm -rf build/
	rm -rf *.build *.dist *.onefile-build
	find . -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	find . -name "*.sqlite" -delete 2>/dev/null || true
	@echo "✓ Очищено"

# ── Индексация (для разработки) ───────────────────────────────────────────────

index:
	@if [ -z "$(WORKSPACE)" ]; then \
		echo "Использование: make index WORKSPACE=/path/to/1c/config"; \
		exit 1; \
	fi
	bsl-analyzer --index $(WORKSPACE)

mcp:
	bsl-analyzer --mcp --port 8051

lsp:
	bsl-analyzer --lsp
