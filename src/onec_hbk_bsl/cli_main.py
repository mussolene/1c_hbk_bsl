"""Thin CLI entrypoint wrapper."""

from __future__ import annotations

from onec_hbk_bsl.__main__ import main as _main


def main() -> None:
    _main()


if __name__ == "__main__":
    main()
