"""
pygls sends JSON-RPC over stdio with an LSP-style header:

    Content-Length: <N>\\r\\n
    Content-Type: application/vscode-jsonrpc; charset=utf-8\\r\\n
    \\r\\n
    <body>

<N> must be the length of the **UTF-8-encoded** body in octets. pygls uses
``len(body)`` on the JSON string, which counts Unicode code points — so any
non-ASCII in LSP payloads (Cyrillic hovers, symbols, etc.) makes *N* too small.
The client then reads short, mis-aligns the stream, and VS Code reports errors
like "Header must provide a Content-Length property" with corrupted fragments.

We monkey-patch ``JsonRPCProtocol._send_data`` once at LSP startup to use byte
length. Upstream: same bug in pygls 2.1.0 (see ``pygls.protocol.json_rpc``).
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_PATCHED = False


def _encode_lsp_stdio_message(
    *,
    body: str,
    include_headers: bool,
    charset: str,
    content_type: str,
) -> bytes:
    """Build the exact bytes written to the LSP stdio pipe (headers + body)."""
    body_bytes = body.encode(charset)
    if not include_headers:
        return body_bytes
    header = (
        f"Content-Length: {len(body_bytes)}\r\n"
        f"Content-Type: {content_type}; charset={charset}\r\n\r\n"
    )
    return header.encode(charset) + body_bytes


def apply_pygls_utf8_content_length_patch() -> None:
    """Idempotent: replace pygls ``_send_data`` with UTF-8-correct framing."""
    global _PATCHED
    if _PATCHED:
        return

    from pygls.exceptions import JsonRpcInternalError
    from pygls.protocol.json_rpc import JsonRPCProtocol

    def _send_data(self: Any, data: Any) -> None:
        if not data:
            return

        if self.writer is None:
            logger.error("Unable to send data, no available transport!")
            return

        try:
            body = json.dumps(data, default=self._serialize_message)
            logger.info("Sending data: %s", body)

            out = _encode_lsp_stdio_message(
                body=body,
                include_headers=self._include_headers,
                charset=self.CHARSET,
                content_type=self.CONTENT_TYPE,
            )
            res = self.writer.write(out)
            if inspect.isawaitable(res):
                asyncio.ensure_future(res)

        except BrokenPipeError:
            logger.exception("Error sending data. BrokenPipeError", exc_info=True)
            raise
        except Exception as error:
            logger.exception("Error sending data", exc_info=True)
            self._server._report_server_error(error, JsonRpcInternalError)

    JsonRPCProtocol._send_data = _send_data  # type: ignore[method-assign, assignment]
    _PATCHED = True
