# `scripts/`

## Версия (автоматизация по git-тегу)

**Источник правды — аннотированный тег** вида `vMAJOR.MINOR.PATCH` (например `v0.7.2`).

- **Python-пакет:** версия берётся через **setuptools-scm** при сборке и попадает в wheel/sdist и в `importlib.metadata` после `pip install`.
- **Расширение VS Code:** в репозитории в **`package.json`** зафиксирован плейсхолдер **`0.0.0`** (не номер релиза). Реальная версия подставляется скриптом **`scripts/sync_version.py`** (или **`make sync-version`**) в `package.json` и в корень **`package-lock.json`** по той же строке, что даёт setuptools-scm или `git describe`.
- **Локальная сборка VSIX:** цель **`make vsix`** вызывает **`sync-version`** перед сборкой, затем после успешной упаковки **`reset_extension_placeholder.py`** — в git снова остаются **`0.0.0`** в `package.json` и в корне `package-lock.json`, без ручного отката. Вручную плейсхолдер: **`make reset-extension-placeholder`**.
- Если собираете VSIX **не** через Makefile, после **`vsce package`** выполните **`make reset-extension-placeholder`** (или сначала **`make sync-version`**, если не подставляли версию).

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
python scripts/dev_corpus_bench.py /path/to/1c/config --limit=200
python scripts/dev_corpus_bench.py /path/to/1c/config --sample=500 --profile strict-bslls
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
PYTHONPATH=src python scripts/bslls_oracle_parity.py tests/fixtures \
  --output-dir .agent/reports/bslls-oracle/fixtures
```

Скрипт запускает `onec-agent bslls` в образе
`ghcr.io/mussolene/1c-developer:8.5.1.1302`, читает `bsl-json.json`, запускает
локальные диагностики и пишет `parity.json` с категориями:
`only_ours`, `only_bslls`, `message_mismatch`, `severity_mismatch`,
`anchor_mismatch`.
