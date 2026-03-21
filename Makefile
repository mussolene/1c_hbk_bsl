.PHONY: install install-build dev test lint fmt check-all build build-check extension-bin sync-extension-bin vsix dist clean docker-build docker-up docker-down

# ── Зависимости ──────────────────────────────────────────────────────────────

install:
	uv pip install -e ".[dev]"

install-build:
	uv pip install -e ".[dev,build]"

dev: install
	@echo "Dev environment ready. Run: onec-hbk-bsl --help"

# ── Тесты и линтинг ──────────────────────────────────────────────────────────

test:
	python -m pytest

lint:
	ruff check src tests

fmt:
	ruff format src tests

check-all: lint test

# ── Сборка нативного бинаря (Nuitka) ─────────────────────────────────────────

ENTRY     = src/onec_hbk_bsl/__main__.py
DIST_DIR  = dist
BIN_NAME  = onec-hbk-bsl

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

# Бинарник для локальной упаковки VSIX (совпадает с путём в extension.ts → bin/)
EXTENSION_BIN_DIR = vscode-extension/bin
EXTENSION_BIN = $(EXTENSION_BIN_DIR)/$(BIN_NAME)$(BIN_SUFFIX)

NUITKA_COMMON = \
		--standalone \
		--output-dir=$(DIST_DIR) \
		--include-package=onec_hbk_bsl \
		--include-package=tree_sitter \
		--include-package=tree_sitter_bsl \
		--include-package=fastmcp \
		--include-package=pygls \
		--include-package=watchfiles \
		--include-package=rich \
		--nofollow-import-to=tkinter,test,unittest,pydoc,doctest,distutils \
		--include-data-dir=data=data \
		--assume-yes-for-downloads \
		--jobs=4

build:
	@echo "→ Компиляция через Nuitka ($(PLATFORM))..."
	@mkdir -p $(DIST_DIR)
	.venv/bin/python -m nuitka \
		$(NUITKA_COMMON) \
		--onefile \
		--deployment \
		--python-flag=no_site,no_warnings \
		--output-filename=$(BIN_NAME)$(BIN_SUFFIX) \
		$(ENTRY)
	@echo "✓ Готово: $(BUILD_OUT)"
	@ls -lh $(BUILD_OUT)

# Скопировать свежий бинарник в vscode-extension/bin/ (для vsce package / отладки расширения)
sync-extension-bin:
	@test -f $(BUILD_OUT) || (echo "Нет $(BUILD_OUT) — сначала: make build" >&2 && exit 1)
	@mkdir -p $(EXTENSION_BIN_DIR)
	@cp -f $(BUILD_OUT) $(EXTENSION_BIN)
	@cmp -s $(BUILD_OUT) $(EXTENSION_BIN) || (echo "Ошибка: $(EXTENSION_BIN) не совпадает с $(BUILD_OUT)" >&2 && exit 1)
	@chmod +x $(EXTENSION_BIN) 2>/dev/null || true
	@echo "✓ Синхронизировано: $(EXTENSION_BIN) ← $(BUILD_OUT)"

# Сборка Nuitka + копирование в расширение одной командой
extension-bin: build sync-extension-bin

# Собрать webpack и упаковать VSIX с бинарником из extension-bin (не используйте голый vsce без sync)
vsix: extension-bin
	cd vscode-extension && npm run compile && \
		VERSION=$$(node -p "require('./package.json').version") && \
		npx @vscode/vsce package --no-dependencies \
			-o onec-hbk-bsl-$$VERSION-local.vsix && \
		echo "✓ VSIX: vscode-extension/onec-hbk-bsl-$$VERSION-local.vsix"

# Быстрая сборка без --onefile (для отладки — не нужна упаковка onefile)
build-dev:
	@mkdir -p $(DIST_DIR)/dev
	.venv/bin/python -m nuitka \
		--standalone \
		--output-dir=$(DIST_DIR)/dev \
		--include-package=onec_hbk_bsl \
		--include-data-dir=data=data \
		--jobs=4 \
		$(ENTRY)
	@echo "✓ Готово: $(DIST_DIR)/dev/__main__.dist/$(BIN_NAME)$(BIN_SUFFIX)"

# Проверить что бинарь работает
build-check: build
	$(BUILD_OUT) --help
	$(BUILD_OUT) --version

# Пакет для дистрибуции с версией из pyproject.toml
dist: build
	@VERSION=$$(python -c "import importlib.metadata; print(importlib.metadata.version('onec-hbk-bsl'))"); \
	ARCHIVE=$(DIST_DIR)/onec-hbk-bsl-$$VERSION-$(PLATFORM).tar.gz; \
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
	rm -f $(EXTENSION_BIN)
	rmdir $(EXTENSION_BIN_DIR) 2>/dev/null || true
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
	onec-hbk-bsl --index $(WORKSPACE)

mcp:
	onec-hbk-bsl --mcp --port 8051

lsp:
	onec-hbk-bsl --lsp
