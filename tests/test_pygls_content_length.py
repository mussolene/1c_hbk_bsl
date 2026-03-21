"""LSP stdio framing: Content-Length must count UTF-8 bytes, not Python str length."""

from __future__ import annotations

import json

from onec_hbk_bsl.lsp.pygls_content_length import _encode_lsp_stdio_message


def test_lsp_frame_non_ascii_content_length_matches_utf8_body() -> None:
    """Regression: pygls used len(str); Cyrillic JSON must use octet length."""
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "result": "кириллица"}, ensure_ascii=False)
    assert len(body) != len(body.encode("utf-8"))

    raw = _encode_lsp_stdio_message(
        body=body,
        include_headers=True,
        charset="utf-8",
        content_type="application/vscode-jsonrpc",
    )
    sep = raw.index(b"\r\n\r\n")
    header = raw[:sep].decode("ascii")
    payload = raw[sep + 4 :]

    line0 = header.split("\r\n")[0]
    assert line0.startswith("Content-Length: ")
    n = int(line0.split(":", 1)[1].strip())
    assert n == len(payload) == len(body.encode("utf-8"))


def test_lsp_frame_ascii_same_as_codepoint_length() -> None:
    body = '{"jsonrpc":"2.0","id":0,"result":"ok"}'
    assert len(body) == len(body.encode("utf-8"))
    raw = _encode_lsp_stdio_message(
        body=body,
        include_headers=True,
        charset="utf-8",
        content_type="application/vscode-jsonrpc",
    )
    sep = raw.index(b"\r\n\r\n")
    n = int(raw[:sep].decode("ascii").split("\r\n")[0].split(":", 1)[1].strip())
    assert n == len(raw[sep + 4 :])
