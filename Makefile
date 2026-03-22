.PHONY: install install-build dev test lint fmt check-all sync-version reset-extension-placeholder build build-check extension-bin sync-extension-bin vsix dist clean docker-build docker-up docker-down

# ── Зависимости ──────────────────────────────────────────────────────────────

install:
	uv pip install -e ".[dev]"

install-build:
	uv pip install -e ".[dev,build]"

dev: install
	@echo "Dev environment ready. Run: onec-hbk-bsl --help"

# Версия из git-тега (setuptools-scm); синхронизировать vscode-extension/package.json + lock
sync-version:
	$(PYTHON3) scripts/sync_version.py

# Вернуть package.json / lock к плейсхолдеру 0.0.0 (после vsix вызывается само)
reset-extension-placeholder:
	$(PYTHON3) scripts/reset_extension_placeholder.py

# ── Тесты и линтинг ──────────────────────────────────────────────────────────
# Prefer python3 when `python` is not on PATH (e.g. some macOS setups).
PYTHON3 ?= python3

test:
	$(PYTHON3) -m pytest

lint:
	ruff check src tests

fmt:
	ruff format src tests

check-all: lint test

# ── Сборка standalone-бинаря (PyInstaller onefile) ──────────────────────────

ENTRY     = src/onec_hbk_bsl/__main__.py
SPEC      = packaging/onec-hbk-bsl.spec
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

build:
	@echo "→ PyInstaller onefile ($(PLATFORM))..."
	@mkdir -p $(DIST_DIR)
	.venv/bin/python -m PyInstaller --clean --noconfirm \
		--workpath build/pyinstaller \
		--distpath $(DIST_DIR) \
		$(SPEC)
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

# Сборка PyInstaller + копирование в расширение одной командой
extension-bin: build sync-extension-bin

# Собрать webpack и упаковать VSIX с бинарником из extension-bin (sync → сборка → сброс плейсхолдера)
vsix: sync-version extension-bin
	cd vscode-extension && npm run compile && \
		VERSION=$$(node -p "require('./package.json').version") && \
		npx @vscode/vsce package --no-dependencies \
			-o onec-hbk-bsl-$$VERSION-local.vsix && \
		echo "✓ VSIX: vscode-extension/onec-hbk-bsl-$$VERSION-local.vsix"
	$(PYTHON3) scripts/reset_extension_placeholder.py

# Проверить что бинарь работает
build-check: build
	$(BUILD_OUT) --help
	$(BUILD_OUT) --version

# Пакет для дистрибуции с версией из установленного пакета (setuptools-scm / git)
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
