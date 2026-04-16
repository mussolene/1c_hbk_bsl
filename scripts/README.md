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
3. GitHub Actions **Release** собирает артефакты; job VSIX перед сборкой вызывает `scripts/sync_version.py`, чтобы `package.json` совпадал с тегом.

Локально без тега на коммите после последнего тега setuptools-scm может выдать версию вида `X.Y.Z.devN+gHASH` — это нормально для разработки.

## Паритет с BSLLS (форматтер и диагностики)

Скрипт **`run_bslls_parity.sh`** теперь запускает встроенный parity-runner из репозитория. Для больших внешних корпусов используйте **`dev_corpus_parity.py`**. Отчёты пишутся в **`.nosync/reports/dev-corpus/`**. Подробности: [docs/FORMATTER_DIAGNOSTICS.md](../docs/FORMATTER_DIAGNOSTICS.md).

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

Для parity-сверки с Java BSLLS:

```bash
python scripts/dev_corpus_parity.py /path/to/1c/config --limit=20
python scripts/dev_corpus_parity.py /path/to/1c/config --sample=100 --profile strict-bslls
```

Скрипт:
- сам находит `exec.jar` через `BSLLS_JAR`, `~/.cache/onec-hbk-bsl/bslls` или `.nosync/bsl-language-server/build/libs`
- сравнивает нормализованные diagnostics нашего движка и BSLLS
- сравнивает итоговый текст full-document formatting
- сохраняет JSON-отчёт для разбора несовпадений
