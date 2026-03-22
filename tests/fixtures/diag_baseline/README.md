# Фикстуры baseline диагностик

Сюда можно класть **офлайн** JSON-файлы эталона BSLLS для регрессионной сверки (не обязательны для CI).

## Формат `baseline.json`

Минимальная схема (версия 1):

```json
{
  "version": 1,
  "description": "optional note",
  "diagnostics": [
    {
      "file": "src/YourConfig/CommonModules/Example/Ext/Module.bsl",
      "line": 10,
      "code": "MethodSize"
    }
  ]
}
```

- `file` — путь **относительно workspace** или абсолютный; при сравнении пути нормализуются.
- `line` — 1-based, как в Problems.
- `code` — имя правила BSLLS (`MethodSize`) или внутренний код onec (`BSL002`); нормализация через `normalize_rule_code_set`.

Поле `message` в baseline **не обязательно** — сравнение по умолчанию по ключу `(file, line, code)`.

## Генерация

См. [docs/BSLLS_BASELINE.md](../../docs/BSLLS_BASELINE.md).
