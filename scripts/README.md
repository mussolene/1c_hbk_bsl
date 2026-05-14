# `scripts/`

## Версия (автоматизация по git-тегу)

**Источник правды — аннотированный тег** вида `vMAJOR.MINOR.PATCH` (например `v0.7.2`).

- **Python-пакет:** версия берётся через **setuptools-scm** при сборке и попадает в wheel/sdist и в `importlib.metadata` после `pip install`.
- **Расширение VS Code:** версия хранится в **`vscode-extension/package.json`** и корне **`vscode-extension/package-lock.json`**. Перед релизной или локальной VSIX-сборкой обновляйте их скриптом **`scripts/sync_version.py`** (или **`make sync-version`**) по той же строке, что даёт setuptools-scm или `git describe`.
- **Локальная сборка VSIX:** цель **`make vsix`** вызывает **`sync-version`** перед сборкой, затем собирает бинарник, копирует его в `vscode-extension/bin/`, запускает webpack и `vsce package`.
- Если собираете VSIX **не** через Makefile, сначала выполните **`make sync-version`** и **`make sync-extension-bin`** (или **`make extension-bin`**), чтобы manifests и вложенный бинарник соответствовали собираемой версии.

Типичный релиз:

1. Закоммитить изменения на `main`.
2. `git tag -a vX.Y.Z -m "release"` и `git push origin vX.Y.Z`.
3. GitHub Actions **Release** собирает артефакты, публикует Python-пакет в PyPI через Trusted Publishing и публикует платформенные VSIX; job VSIX перед сборкой вызывает `scripts/sync_version.py`, чтобы `package.json` совпадал с тегом.

Для PyPI в настройках проекта PyPI должен быть добавлен Trusted Publisher:
репозиторий `mussolene/1c_hbk_bsl`, workflow `.github/workflows/release.yml`,
environment `pypi`. API-токен в GitHub secrets для этого пути не нужен.

Локально без тега на коммите после последнего тега setuptools-scm может выдать версию вида `X.Y.Z.devN+gHASH` — это нормально для разработки.

## Dev-only корпус

Для большого внешнего корпуса, который не должен попадать в `tests/fixtures`, используйте **`dev_corpus_bench.py`**.

Примеры:

```bash
python3 scripts/dev_corpus_bench.py /path/to/1c/config --limit=200
python3 scripts/dev_corpus_bench.py /path/to/1c/config --sample=500
```

Скрипт считает:
- суммарное время диагностик
- суммарное время форматирования
- сколько файлов меняет форматтер
- throughput по файлам, строкам и мегабайтам

Это именно исследовательский / development-only прогон, не тестовый fixture pipeline.

## BSLLS oracle / parity

Источник правды для сравнения с Java BSLLS — контейнер `1c-develop`, а не
локальный Java/JAR на машине разработчика.

```bash
PYTHONPATH=src python3 scripts/bslls_oracle_parity.py tests/fixtures \
  --output-dir .agent/reports/bslls-oracle/fixtures
```

Скрипт запускает `onec-agent bslls` в образе
`ghcr.io/mussolene/1c-developer:8.5.1.1302`, читает `bsl-json.json`, запускает
локальные диагностики и пишет `parity.json` с категориями:
`only_ours`, `only_bslls`, `message_mismatch`, `severity_mismatch`,
`anchor_mismatch`.
