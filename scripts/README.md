# `scripts/`

## Версия (автоматизация по git-тегу)

**Источник правды — аннотированный тег** вида `vMAJOR.MINOR.PATCH` (например `v0.7.2`).

- **Python-пакеты:** версия берётся через **setuptools-scm** при сборке и попадает в wheel/sdist и в `importlib.metadata` после `pip install`. Release workflow публикует slim-пакет `onec-hbk-bsl-core` и полный backwards-compatible метапакет `onec-hbk-bsl`. Метапакет собирается только через **`scripts/build_python_dist.sh`**, который временно пинит зависимости `onec-hbk-bsl-core[mcp]` / `onec-hbk-bsl-core[all]` к той же release-версии и проверяет `Requires-Dist` в wheel metadata.
- **Committed metadata:** в `src/onec_hbk_bsl/_version.py`, `vscode-extension/package.json` и корне `vscode-extension/package-lock.json` хранится placeholder `0.0.0`. Это не релизная версия и ее не нужно менять руками.
- **Расширение VS Code:** `vsce` требует literal `version` в **`vscode-extension/package.json`**; release workflow перед VSIX-сборкой генерирует build-time metadata скриптом **`scripts/sync_version.py`** из `GITHUB_REF_NAME`. Эти изменения живут только в рабочей директории CI и не коммитятся.
- **Локальная сборка VSIX:** цель **`make vsix`** вызывает **`sync-version`** перед сборкой, затем собирает бинарник, копирует его в `vscode-extension/bin/`, запускает webpack и `vsce package`.
- Если собираете VSIX **не** через Makefile, сначала выполните **`make sync-version`** и **`make sync-extension-bin`** (или **`make extension-bin`**), чтобы manifests и вложенный бинарник соответствовали собираемой версии. После локальной упаковки не коммитьте generated version metadata.

Типичный релиз:

1. Закоммитить изменения на `main`.
2. `./scripts/release.sh X.Y.Z "release: vX.Y.Z"`. Не создавайте release tag вручную без локального release script: он запускает тот же Python distribution builder, что и CI, и ловит рассинхрон meta/core dependency metadata до публикации.
3. GitHub Actions **Release** собирает артефакты, публикует Python-пакет в PyPI через Trusted Publishing и публикует платформенные VSIX; build jobs вызывают `scripts/sync_version.py`, чтобы frozen runtime и VSIX metadata совпадали с тегом.

Для PyPI в настройках проекта PyPI должен быть добавлен Trusted Publisher:
репозиторий `mussolene/1c_hbk_bsl`, workflow `.github/workflows/release.yml`,
environment `pypi`. API-токен в GitHub secrets для этого пути не нужен.

Локально без тега на коммите после последнего тега setuptools-scm может выдать версию вида `X.Y.Z.devN+gHASH` — это нормально для Python-разработки. В публикуемые release artifacts такая строка не записывается: `scripts/sync_version.py` генерирует metadata по стабильному release tag.

## Dev-only корпус

Для большого внешнего корпуса, который не должен попадать в `tests/fixtures`, используйте **`dev_corpus_bench.py`**.

Примеры:

```bash
./.venv/bin/python scripts/dev_corpus_bench.py /path/to/1c/config --limit=200
./.venv/bin/python scripts/dev_corpus_bench.py /path/to/1c/config --sample=500
```

Скрипт считает:
- суммарное время диагностик
- суммарное время форматирования
- сколько файлов меняет форматтер
- throughput по файлам, строкам и мегабайтам

Это именно исследовательский / development-only прогон, не тестовый fixture pipeline.

## Матрица диагностических правил

**`diagnostic_rule_matrix.py`** строит development-only карту правил по текущей
топологии исполнения:

```bash
./.venv/bin/python scripts/diagnostic_rule_matrix.py --format summary
./.venv/bin/python scripts/diagnostic_rule_matrix.py --format csv > /tmp/rules.csv
```

Матрица связывает `BSL###` с `registry phase`, фактической группой в
`diagnostic_runtime.runner`, используемыми `DocumentSnapshot`-фактами,
режимом исполнения и рекомендуемой пачкой доработки. Ее нужно использовать
перед изменением семейства правил, чтобы планировать работу по shared runtime
facts, а не по красивым, но неисполнительным фазам.

## BSLLS parity для диагностик

**`compare_diag_bslls.py`** сравнивает выбранные правила onec-hbk-bsl и BSLLS:

```bash
BSLLS_JAR=/path/to/bsl-language-server-*-exec.jar \
  ./.venv/bin/python scripts/compare_diag_bslls.py \
  --workspace /path/to/workspace \
  --preserve-source-root \
  --select BSL216,CommentedCode \
  /path/to/workspace/src
```

Правило для audit-итераций: всегда задавайте `--select`. Скрипт запускает наш
CLI как `onec-hbk-bsl check --no-config --format json --select ...`,
генерирует для BSLLS конфигурацию `diagnostics.mode=ONLY` с совместимыми
именами правил, запускает BSLLS `analyze`, нормализует BSLLS diagnostics
обратно в `BSL###`, затем сравнивает выбранные правила по
`file,line,column,end,code`.

Для path-sensitive правил, завязанных на EDT layout/metadata, используйте
`--preserve-source-root`, чтобы BSLLS анализировал исходный workspace, а не
временную копию `.bsl` файлов. Для небольших синтетических наборов можно
оставить режим временной копии: входные файлы копируются с сохранением
относительного пути от `--workspace`.

Скрипт ищет jar в `--jar`, `BSLLS_JAR`, `.nosync/bsl-language-server/**`,
затем в локальном пользовательском cache.
