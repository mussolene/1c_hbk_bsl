#!/usr/bin/env python3
"""
Map host workspace file paths <-> MCP-LSP-bridge file:// URIs (e.g. file:///projects/...).

Use when MCP document_diagnostics must use the same URI scheme as the BSL LS inside Cursor/devcontainer.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from urllib.parse import quote, unquote


def host_file_to_bridge_uri(host_file: Path, host_ws: Path, bridge_prefix: str) -> str:
    host_file = host_file.resolve()
    host_ws = host_ws.resolve()
    rel = host_file.relative_to(host_ws)
    parts = [quote(s, safe="") for s in rel.parts]
    tail = "/".join(parts)
    prefix = bridge_prefix.removesuffix("/")
    return f"{prefix}/{tail}"


def bridge_uri_to_host_path(uri: str, host_ws: Path, bridge_prefix: str) -> str:
    prefix = bridge_prefix.removesuffix("/")
    if not uri.startswith(prefix):
        msg = f"URI must start with {prefix!r}, got {uri[:80]!r}"
        raise ValueError(msg)
    tail = uri[len(prefix) :].lstrip("/")
    if not tail:
        return str(host_ws.resolve())
    parts = [unquote(p) for p in tail.split("/")]
    return str((host_ws / Path(*parts)).resolve())


def main() -> int:
    p = argparse.ArgumentParser(description="Host path <-> MCP-LSP-bridge file:// URI")
    p.add_argument(
        "--host-workspace",
        required=True,
        type=Path,
        help="Workspace root on host (same as onec-hbk-bsl WORKSPACE_ROOT)",
    )
    p.add_argument(
        "--bridge-prefix",
        default="file:///projects",
        help="file:// prefix inside LSP (default: file:///projects)",
    )
    p.add_argument(
        "paths",
        nargs="*",
        type=Path,
        help="Absolute file paths under host workspace",
    )
    p.add_argument(
        "--reverse",
        metavar="BRIDGE_URI",
        help="Convert bridge URI back to host path instead",
    )
    args = p.parse_args()

    if args.reverse:
        out = bridge_uri_to_host_path(args.reverse, args.host_workspace, args.bridge_prefix)
        print(f"HOST_PATH={out}")
        return 0

    for f in args.paths:
        uri = host_file_to_bridge_uri(f, args.host_workspace, args.bridge_prefix)
        print(f"HOST_PATH={f.resolve()}")
        print(f"BRIDGE_URI={uri}")
        back = bridge_uri_to_host_path(uri, args.host_workspace, args.bridge_prefix)
        ok = Path(back) == Path(f).resolve()
        print(f"ROUNDTRIP_OK={ok}")
        print("---")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
