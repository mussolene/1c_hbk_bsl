"""
Generate platform API JSON files from the 1c-help MCP server.

Run once to collect platform type/method documentation and store it as
static JSON in data/platform_api/. The LSP server loads these files at
startup — no runtime dependency on MCP.

Usage:
    python scripts/generate_platform_api.py

Requirements:
    1c-help MCP server running at localhost:8050 (see external-help-service project)
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MCP_BASE = "http://localhost:8050/mcp"
MCP_HEADERS = {
    "Accept": "application/json, text/event-stream",
    "Content-Type": "application/json",
}
OUTPUT_DIR = Path(__file__).parent.parent / "data" / "platform_api"

# Platform types to fetch (ru name, en name)
# Extend this list to add more types
PLATFORM_TYPES: list[tuple[str, str, str]] = [
    # (name_ru, name_en, kind)
    ("Запрос", "Query", "class"),
    ("РезультатЗапроса", "QueryResult", "class"),
    ("ВыборкаИзРезультатаЗапроса", "QueryResultSelection", "class"),
    ("ТаблицаЗначений", "ValueTable", "class"),
    ("КолонкаТаблицыЗначений", "ValueTableColumn", "class"),
    ("СтрокаТаблицыЗначений", "ValueTableRow", "class"),
    ("ДеревоЗначений", "ValueTree", "class"),
    ("СтрокаДереваЗначений", "ValueTreeRow", "class"),
    ("СписокЗначений", "ValueList", "class"),
    ("Структура", "Structure", "class"),
    ("Соответствие", "Map", "class"),
    ("Массив", "Array", "class"),
    ("Файл", "File", "class"),
    ("HTTPСоединение", "HTTPConnection", "class"),
    ("HTTPЗапрос", "HTTPRequest", "class"),
    ("HTTPОтвет", "HTTPResponse", "class"),
    ("ЧтениеJSON", "JSONReader", "class"),
    ("ЗаписьJSON", "JSONWriter", "class"),
    ("ЧтениеXML", "XMLReader", "class"),
    ("ЗаписьXML", "XMLWriter", "class"),
    ("ЧтениеДанных", "DataReader", "class"),
    ("ЗаписьДанных", "DataWriter", "class"),
    ("ПотокВПамяти", "MemoryStream", "class"),
    ("ФайловыйПоток", "FileStream", "class"),
    ("ДвоичныеДанные", "BinaryData", "class"),
    ("УникальныйИдентификатор", "UUID", "class"),
    ("Дата", "Date", "class"),
    ("Число", "Number", "class"),
    ("Строка", "String", "class"),
    ("Булево", "Boolean", "class"),
    ("ФорматированнаяСтрока", "FormattedString", "class"),
    ("ТекстовыйДокумент", "TextDocument", "class"),
    ("ТабличныйДокумент", "SpreadsheetDocument", "class"),
    ("ЗащищенноеСоединениеOpenSSL", "OpenSSLSecureConnection", "class"),
    ("СистемнаяИнформация", "SystemInfo", "class"),
    ("ДополнительноеПраво", "AdditionalRight", "class"),
    ("ПостроительОтчета", "ReportBuilder", "class"),
    ("ПостроительЗапроса", "QueryBuilder", "class"),
    ("СхемаКомпоновкиДанных", "DataCompositionSchema", "class"),
    ("КомпоновщикНастроекКомпоновкиДанных", "DataCompositionSettingsComposer", "class"),
    ("ПроцессорКомпоновкиДанных", "DataCompositionProcessor", "class"),
    ("ПроцессорВыводаРезультатаКомпоновкиДанных", "DataCompositionResultSpreadsheetDocumentOutputProcessor", "class"),
    ("МенеджерВременныхТаблиц", "TempTablesManager", "class"),
    ("ВнешняяКомпонента", "AddIn", "class"),
    ("Сокет", "Socket", "class"),
    ("ТаблицаЦветов", "ColorTable", "class"),
    ("СправочникМенеджер", "CatalogManager", "class"),
    ("РегистрСведенийМенеджер", "InformationRegisterManager", "class"),
]

GLOBAL_FUNCTIONS_QUERY = "глобальные функции встроенного языка"

# ---------------------------------------------------------------------------
# MCP client
# ---------------------------------------------------------------------------


class McpClient:
    def __init__(self) -> None:
        self._session_id: str | None = None

    def _post(self, payload: dict, timeout: float = 5.0) -> dict | None:
        body = json.dumps(payload).encode()
        headers = dict(MCP_HEADERS)
        if self._session_id:
            headers["mcp-session-id"] = self._session_id
        req = urllib.request.Request(MCP_BASE, data=body, headers=headers, method="POST")  # noqa: S310
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                # Capture session id
                if not self._session_id:
                    self._session_id = resp.headers.get("mcp-session-id")
                raw = resp.read().decode("utf-8", errors="replace")
                for line in raw.splitlines():
                    if line.startswith("data: "):
                        return json.loads(line[6:])
        except Exception as exc:
            print(f"  [MCP error] {exc}", file=sys.stderr)
        return None

    def init(self) -> bool:
        resp = self._post({
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "generate_platform_api", "version": "1"},
            },
        })
        return resp is not None

    def search_keyword(self, query: str, limit: int = 1) -> str:
        resp = self._post({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {
                "name": "search_1c_help_keyword",
                "arguments": {"query": query, "limit": limit},
            },
        })
        if not resp:
            return ""
        content = resp.get("result", {}).get("content", [])
        if content and isinstance(content, list):
            return content[0].get("text", "")
        return ""

    def get_topic(self, path: str) -> str:
        resp = self._post({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {
                "name": "get_1c_help_topic",
                "arguments": {"path": path},
            },
        })
        if not resp:
            return ""
        content = resp.get("result", {}).get("content", [])
        if content and isinstance(content, list):
            return content[0].get("text", "")
        return ""


# ---------------------------------------------------------------------------
# Text parsing helpers
# ---------------------------------------------------------------------------

_RE_METHOD_SIGNATURE = re.compile(
    r'^([А-ЯЁа-яёA-Za-z]\w*)\s*\(([^)]*)\)',
    re.UNICODE,
)
_RE_RETURNS = re.compile(r'(?:Тип|Returns?|Возвращаемое значение):\s*([^\n]+)', re.IGNORECASE)
_RE_AVAILABILITY = re.compile(r'Доступность:\s*([^\n]+)', re.IGNORECASE)


def parse_type_from_mcp_text(text: str, type_name_ru: str, type_name_en: str, kind: str) -> dict:
    """
    Parse MCP search result text into a platform_api.py compatible dict.
    """
    result: dict = {
        "name": type_name_ru,
        "name_en": type_name_en,
        "kind": kind,
        "description": "",
        "methods": [],
        "properties": [],
    }

    # Extract description from first few lines
    lines = text.splitlines()
    desc_lines: list[str] = []
    for line in lines[:15]:
        line = line.strip()
        if not line or line.startswith("#") or line == type_name_ru or line == type_name_en:
            continue
        if any(k in line for k in ["Синтаксис:", "Описание:", "Пример:", "Связанные:"]):
            break
        desc_lines.append(line)
    if desc_lines:
        result["description"] = " ".join(desc_lines[:3])

    return result


def parse_method_from_mcp_text(text: str) -> dict | None:
    """Parse a method entry from MCP result text."""
    lines = text.splitlines()

    # Find method name from heading
    name_ru = ""
    name_en = ""
    for line in lines[:5]:
        line = line.strip().lstrip("#").strip()
        if "." in line and "(" not in line:
            # "ТипОбъекта.МетодОбъекта (TypeName.MethodName)"
            parts = line.split()
            ru_part = parts[0].split(".")[-1] if parts else ""
            en_part = ""
            if len(parts) > 1:
                m = re.search(r'\([\w.]+\.([\w]+)\)', line)
                if m:
                    en_part = m.group(1)
            if ru_part:
                name_ru = ru_part
                name_en = en_part
                break
        elif line and re.match(r'^[А-ЯЁа-яёA-Za-z]\w+$', line):
            name_ru = line
            break

    if not name_ru:
        return None

    # Find signature
    signature = f"{name_ru}()"
    for line in lines:
        line = line.strip()
        if line.startswith("Синтаксис:") or line.startswith("Syntax:"):
            # Next non-empty line has the signature
            continue
        m = _RE_METHOD_SIGNATURE.match(line)
        if m and m.group(1).lower() == name_ru.lower():
            signature = line
            break

    # Find description
    description = ""
    in_desc = False
    for line in lines:
        line = line.strip()
        if line.startswith("Описание:") or line.startswith("Description:"):
            in_desc = True
            rest = line.split(":", 1)[1].strip()
            if rest:
                description = rest
            continue
        if in_desc:
            if not line or any(k in line for k in ["Пример:", "Связанные:", "Доступность:", "Примечание:"]):
                break
            description = (description + " " + line).strip()

    # Find return type
    returns = ""
    m = _RE_RETURNS.search(text)
    if m:
        returns = m.group(1).strip().split(".")[0].strip()

    return {
        "name": name_ru,
        "name_en": name_en,
        "signature": signature,
        "description": description[:300],
        "returns": returns,
    }


# ---------------------------------------------------------------------------
# Main generation logic
# ---------------------------------------------------------------------------

def fetch_type_methods(client: McpClient, type_name_ru: str, type_name_en: str) -> list[dict]:
    """Fetch all methods of a platform type from MCP."""
    query = f"{type_name_ru} методы"
    text = client.search_keyword(query, limit=5)
    if not text:
        return []

    methods: list[dict] = []
    # Each result block starts with "N. **Title**"
    blocks = re.split(r'\n(?=\d+\. \*\*)', text)
    for block in blocks:
        # Remove the "N. **Title** ..." header line
        lines = block.splitlines()
        content = "\n".join(lines[1:]) if lines else block
        m = parse_method_from_mcp_text(content)
        if m and m["name"].lower() != type_name_ru.lower():
            methods.append(m)

    return methods


def generate_type_json(
    client: McpClient,
    name_ru: str,
    name_en: str,
    kind: str,
) -> dict:
    print(f"  Fetching type: {name_ru} ({name_en})...")
    # Get type overview
    text = client.search_keyword(name_ru, limit=1)
    type_data = parse_type_from_mcp_text(text, name_ru, name_en, kind)

    # Get methods (search for "TypeName.Method" pattern)
    time.sleep(0.3)  # rate limiting
    methods = fetch_type_methods(client, name_ru, name_en)
    if methods:
        print(f"    Found {len(methods)} methods")
        type_data["methods"] = methods

    return type_data


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    client = McpClient()
    print("Connecting to 1c-help MCP at", MCP_BASE)
    if not client.init():
        print("ERROR: Cannot connect to MCP. Is external-help-service running?", file=sys.stderr)
        sys.exit(1)
    print("Connected.\n")

    generated = 0
    skipped = 0
    for name_ru, name_en, kind in PLATFORM_TYPES:
        out_file = OUTPUT_DIR / f"{name_ru.lower()}.json"
        if out_file.exists():
            print(f"  Skip {name_ru} (already exists)")
            skipped += 1
            continue

        type_data = generate_type_json(client, name_ru, name_en, kind)
        if not type_data.get("methods") and not type_data.get("description"):
            print(f"  WARNING: No data for {name_ru}, skipping")
            continue

        out_file.write_text(json.dumps(type_data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  Written: {out_file.name}")
        generated += 1
        time.sleep(0.2)

    print(f"\nDone. Generated: {generated}, Skipped: {skipped}")
    print(f"Output: {OUTPUT_DIR}")
    print("\nNext step: review files, then commit to repo.")
    print("The LSP server will load them automatically from data/platform_api/")


if __name__ == "__main__":
    main()
