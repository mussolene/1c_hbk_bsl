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
