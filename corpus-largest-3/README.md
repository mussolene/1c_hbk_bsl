# corpus-largest-3

Локальный development-only корпус для parity smoke-check.

Содержимое не хранится в git и должно синхронизироваться локально:

```bash
make corpus-largest-3-sync CONFIG_ROOT=/path/to/1c/config
```

После синхронизации можно запускать:

```bash
make parity-largest-3
```
