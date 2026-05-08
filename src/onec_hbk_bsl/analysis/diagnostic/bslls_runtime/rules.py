from __future__ import annotations

import re
from bisect import bisect_left
from dataclasses import dataclass
from typing import Any

from onec_hbk_bsl.analysis.diagnostic.bslls_runtime.context import BsllsDocumentContext
from onec_hbk_bsl.analysis.diagnostic.bslls_runtime.storage import DiagnosticStorage
from onec_hbk_bsl.analysis.diagnostic.models import Diagnostic, Severity
from onec_hbk_bsl.analysis.diagnostic.rules.common_module_rules import (
    _xml_bool_tag,
    common_module_execute_external_code_applicable,
    common_module_xml_for_module_bsl,
)
from onec_hbk_bsl.analysis.lsp_positions import utf8_byte_offset_to_lsp_character


class BsllsDiagnosticRule:
    code: str

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        raise NotImplementedError


def _path_is_form_module_bsl(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    return normalized.endswith("/forms/") or "/forms/" in normalized and normalized.endswith(
        "/ext/module.bsl"
    )


def _path_is_bsl272_server_only_module(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    if "/forms/" in normalized or "/commands/" in normalized:
        return False
    if "/commonmodules/" in normalized:
        xml_path = common_module_xml_for_module_bsl(path)
        if xml_path is None:
            return False
        try:
            raw = xml_path.read_text(encoding="utf-8-sig", errors="replace")
        except OSError:
            return False
        if "<commonmodule" not in raw.casefold():
            return False
        return not (
            _xml_bool_tag(raw, "ClientManagedApplication")
            or _xml_bool_tag(raw, "ClientOrdinaryApplication")
        )
    return normalized.endswith(
        (
            "/ext/objectmodule.bsl",
            "/ext/managermodule.bsl",
            "/ext/recordsetmodule.bsl",
            "/ext/valuemanagermodule.bsl",
        )
    )


def _code_mask_without_strings_and_comments(line: str) -> str:
    out: list[str] = []
    pos = 0
    in_string = False
    while pos < len(line):
        char = line[pos]
        if in_string:
            out.append(" ")
            if char == '"':
                if pos + 1 < len(line) and line[pos + 1] == '"':
                    out.append(" ")
                    pos += 2
                    continue
                in_string = False
            pos += 1
            continue
        if char == '"':
            in_string = True
            out.append(" ")
            pos += 1
            continue
        if char == "/" and pos + 1 < len(line) and line[pos + 1] == "/":
            out.extend(" " for _ in line[pos:])
            break
        out.append(char)
        pos += 1
    return "".join(out)


def _line_comment(line: str) -> bool:
    return line.lstrip().startswith("//")


def _ts_node_text(node: Any) -> str:
    text = getattr(node, "text", None)
    if text is None:
        return ""
    return text.decode("utf-8", errors="replace") if isinstance(text, bytes) else str(text)


def _ts_walk(node: Any):
    yield node
    for child in getattr(node, "children", []) or []:
        yield from _ts_walk(child)


def _ts_children(node: Any) -> list[Any]:
    return list(getattr(node, "children", []) or [])


def _point_char(lines: list[str], point: Any) -> int:
    line_idx = int(point[0])
    byte_col = int(point[1])
    if 0 <= line_idx < len(lines):
        return utf8_byte_offset_to_lsp_character(lines[line_idx], byte_col)
    return byte_col


def _add_node_range(
    storage: DiagnosticStorage,
    *,
    code: str,
    message: str,
    severity: Severity,
    lines: list[str],
    start_node: Any,
    end_node: Any,
) -> None:
    start = start_node.start_point
    end = end_node.end_point
    storage.add_range(
        code=code,
        message=message,
        severity=severity,
        line=int(start[0]),
        character=_point_char(lines, start),
        end_line=int(end[0]),
        end_character=_point_char(lines, end),
    )


def _single_line_call_end(line: str, open_paren: int) -> int:
    depth = 0
    pos = open_paren
    in_string = False
    while pos < len(line):
        char = line[pos]
        if in_string:
            if char == '"':
                if pos + 1 < len(line) and line[pos + 1] == '"':
                    pos += 2
                    continue
                in_string = False
            pos += 1
            continue
        if char == '"':
            in_string = True
            pos += 1
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return pos + 1
        pos += 1
    return open_paren + 1


def _comment_start_outside_string(line: str) -> int:
    pos = 0
    in_string = False
    while pos < len(line):
        char = line[pos]
        if in_string:
            if char == '"':
                if pos + 1 < len(line) and line[pos + 1] == '"':
                    pos += 2
                    continue
                in_string = False
            pos += 1
            continue
        if char == '"':
            in_string = True
            pos += 1
            continue
        if char == "/" and pos + 1 < len(line) and line[pos + 1] == "/":
            return pos
        pos += 1
    return -1


def _code_before_comment(line: str) -> str:
    comment_start = _comment_start_outside_string(line)
    return line if comment_start < 0 else line[:comment_start]


_DOUBLE_QUOTED_STRING_RE = re.compile(r'"(?:[^"]|"")*"')
_BSL005_NETWORK_ADDRESS_RE = re.compile(
    r"(([0-9a-fA-F]{1,4}:){7,7}[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,7}:"
    r"|([0-9a-fA-F]{1,4}:){1,6}:[0-9a-fA-F]{1,4}|([0-9a-fA-F]{1,4}:){1,5}"
    r"(:[0-9a-fA-F]{1,4}){1,2}|([0-9a-fA-F]{1,4}:){1,4}(:[0-9a-fA-F]{1,4}){1,3}"
    r"|([0-9a-fA-F]{1,4}:){1,3}(:[0-9a-fA-F]{1,4}){1,4}|([0-9a-fA-F]{1,4}:){1,2}"
    r"(:[0-9a-fA-F]{1,4}){1,5}|[0-9a-fA-F]{1,4}:((:[0-9a-fA-F]{1,4}){1,6})"
    r"|(?<![g-zа-яА-ЯёЁ]):((:[0-9a-fA-F]{1,4}){1,7}|\s:)|fe80:(:[0-9a-fA-F]{0,4}){0,4}%[0-9a-zA-Z]{1,}"
    r"|::(ffff(:0{1,4}){0,1}:){0,1}((25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])\.){3,3}"
    r"(25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])|([0-9a-fA-F]{1,4}:){1,4}:"
    r"((25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])\.){3,3}"
    r"(25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9]))"
    r"|((25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])\.){3,3}"
    r"(25[0-5]|(2[0-4]|1{0,1}[0-9]){0,1}[0-9])",
    re.IGNORECASE,
)
_BSL005_URL_RE = re.compile(r"^(ftp|http|https)://[^ \"].*", re.IGNORECASE)
_BSL005_ALPHABET_RE = re.compile(r"[A-zА-я]", re.IGNORECASE)
_BSL005_POPULAR_VERSION_RE = re.compile(r"^(?:1|2|3|8\.3|11)\.")
_BSL005_LINE_EXCLUSION_RE = re.compile(
    r"ЗапуститьПриложение|RunApp|Пространств|Namespace|Драйвер|Driver",
    re.IGNORECASE,
)
_BSL005_PARAM_VERSION_RE = re.compile(r"Верси|Version", re.IGNORECASE)

_BSL006_UNIX_STD_ROOT_RE = re.compile(
    r"^/(bin|boot|dev|etc|home|lib|lost\+found|misc|mnt|media|opt|proc|root|run|sbin|tmp|usr|var)(?:/|$)",
    re.IGNORECASE,
)
_BSL006_URL_RE = re.compile(r"^(ftp|http|https)://[^ \"].*", re.IGNORECASE)

_BSL024_GOOD_STRICT_RE = re.compile(
    r"(?:(?://[ \t].*)|(?:/{2,}[ \t]*))$",
    re.IGNORECASE,
)
_BSL024_COMMENTED_CODE_RE = re.compile(
    r"^\s*//\s*(?:"
    r"(?:Процедура|Функция|КонецПроцедуры|КонецФункции|Перем"
    r"|Function|Procedure|EndProcedure|EndFunction|Var)\b"
    r"|(?:ВЫБРАТЬ|SELECT)\b"
    r"|\w.*(?:;|:=)"
    r")",
    re.IGNORECASE,
)
_BSL066_DEPRECATED_FIND_RE = re.compile(r"(?<!\.)(?<!\w)\b(найти|find)\s*\(", re.IGNORECASE)
_BSL178_DEPRECATED_METHOD_RE = re.compile(
    r"(?<!\.)(?<!\w)\b("
    r"КраткоеПредставлениеОшибки|BriefErrorDescription|"
    r"ПодробноеПредставлениеОшибки|DetailErrorDescription|"
    r"ПоказатьИнформациюОбОшибке|ShowErrorInfo"
    r")\s*\(",
    re.IGNORECASE,
)
_BSL097_DEPRECATED_CURRENT_DATE_RE = re.compile(
    r"(?<!\.)(?<!\w)\b(ТекущаяДата|CurrentDate)\s*\(",
    re.IGNORECASE,
)
_BSL177_METHOD_REPLACEMENTS: dict[str, str] = {
    "установитькраткийзаголовокприложения": "КлиентскоеПриложение.УстановитьКраткийЗаголовок",
    "получитькраткийзаголовокприложения": "КлиентскоеПриложение.ПолучитьКраткийЗаголовок",
    "установитьзаголовокклиентскогоприложения": "КлиентскоеПриложение.УстановитьЗаголовок",
    "получитьзаголовокклиентскогоприложения": "КлиентскоеПриложение.ПолучитьЗаголовок",
    "текущийвариантосновногошрифтаклиентскогоприложения": (
        "КлиентскоеПриложение.ТекущийВариантОсновногоШрифта"
    ),
    "текущийвариантинтерфейсаклиентскогоприложения": (
        "КлиентскоеПриложение.ТекущийВариантИнтерфейса"
    ),
    "setshortapplicationcaption": "ClientApplication.SetShortCaption",
    "getshortapplicationcaption": "ClientApplication.GetShortCaption",
    "setclientapplicationcaption": "ClientApplication.SetCaption",
    "getclientapplicationcaption": "ClientApplication.GetCaption",
    "clientapplicationbasefontcurrentvariant": "ClientApplication.CurrentBaseFontVariant",
    "clientapplicationinterfacecurrentvariant": "ClientApplication.CurrentInterfaceVariant",
}
_BSL177_DEPRECATED_METHOD_RE = re.compile(
    r"(?<!\.)(?<!\w)\b("
    r"УстановитьКраткийЗаголовокПриложения|ПолучитьКраткийЗаголовокПриложения|"
    r"УстановитьЗаголовокКлиентскогоПриложения|ПолучитьЗаголовокКлиентскогоПриложения|"
    r"ТекущийВариантОсновногоШрифтаКлиентскогоПриложения|"
    r"ТекущийВариантИнтерфейсаКлиентскогоПриложения|"
    r"SetShortApplicationCaption|GetShortApplicationCaption|"
    r"SetClientApplicationCaption|GetClientApplicationCaption|"
    r"ClientApplicationBaseFontCurrentVariant|ClientApplicationInterfaceCurrentVariant"
    r")\s*\(",
    re.IGNORECASE | re.UNICODE,
)
_BSL195_GET_FORM_RE = re.compile(r"\b(ПолучитьФорму|GetForm)\s*\(", re.IGNORECASE | re.UNICODE)
_BSL179_MANAGED_FORM_RE = re.compile(
    r"\b(?:Тип|Type)\s*\(\s*(\"(?:УправляемаяФорма|ManagedForm)\")\s*\)",
    re.IGNORECASE | re.UNICODE,
)
_BSL180_DISABLE_SAFE_MODE_RE = re.compile(
    r"(?<!\.)(?<!\w)\b("
    r"УстановитьБезопасныйРежим|SetSafeMode|"
    r"УстановитьОтключениеБезопасногоРежима|SetSafeModeDisabled"
    r")\s*\(\s*([^)]*)\)",
    re.IGNORECASE | re.UNICODE,
)
_BSL185_EXTERNAL_APP_RE = re.compile(
    r"\b("
    r"КомандаСистемы|System|ЗапуститьСистему|RunSystem|ЗапуститьПриложение|RunApp|"
    r"НачатьЗапускПриложения|BeginRunningApplication|"
    r"ЗапуститьПриложениеАсинх|RunAppAsync|ЗапуститьПрограмму|ОткрытьПроводник|ОткрытьФайл"
    r")\s*\(",
    re.IGNORECASE | re.UNICODE,
)
_BSL188_FILESYSTEM_METHOD_RE = re.compile(
    r"\b("
    r"ЗначениеВФайл|ValueToFile|КопироватьФайл|FileCopy|ОбъединитьФайлы|MergeFiles|"
    r"ПереместитьФайл|MoveFile|РазделитьФайл|SplitFile|СоздатьКаталог|CreateDirectory|"
    r"УдалитьФайлы|DeleteFiles|КаталогПрограммы|BinDir|КаталогВременныхФайлов|TempFilesDir|"
    r"КаталогДокументов|DocumentsDir|РабочийКаталогДанныхПользователя|UserDataWorkDir|"
    r"НачатьПодключениеРасширенияРаботыСФайлами|BeginAttachingFileSystemExtension|"
    r"НачатьУстановкуРасширенияРаботыСФайлами|BeginInstallFileSystemExtension|"
    r"УстановитьРасширениеРаботыСФайлами|InstallFileSystemExtension|"
    r"УстановитьРасширениеРаботыСФайламиАсинх|InstallFileSystemExtensionAsync|"
    r"ПодключитьРасширениеРаботыСФайламиАсинх|AttachFileSystemExtensionAsync|"
    r"КаталогВременныхФайловАсинх|TempFilesDirAsync|КаталогДокументовАсинх|DocumentsDirAsync|"
    r"НачатьПолучениеКаталогаВременныхФайлов|BeginGettingTempFilesDir|"
    r"НачатьПолучениеКаталогаДокументов|BeginGettingDocumentsDir|"
    r"НачатьПолучениеРабочегоКаталогаДанныхПользователя|BeginGettingUserDataWorkDir|"
    r"РабочийКаталогДанныхПользователяАсинх|UserDataWorkDirAsync|"
    r"КопироватьФайлАсинх|CopyFileAsync|НайтиФайлыАсинх|FindFilesAsync|"
    r"НачатьКопированиеФайла|BeginCopyingFile|НачатьПеремещениеФайла|BeginMovingFile|"
    r"НачатьПоискФайлов|BeginFindingFiles|НачатьСозданиеДвоичныхДанныхИзФайла|"
    r"BeginCreateBinaryDataFromFile|НачатьСозданиеКаталога|BeginCreatingDirectory|"
    r"НачатьУдалениеФайлов|BeginDeletingFiles|ПереместитьФайлАсинх|MoveFileAsync|"
    r"СоздатьДвоичныеДанныеИзФайлаАсинх|CreateBinaryDataFromFileAsync|"
    r"СоздатьКаталогАсинх|CreateDirectoryAsync|УдалитьФайлыАсинх|DeleteFilesAsync"
    r")\s*\(",
    re.IGNORECASE | re.UNICODE,
)
_BSL188_FILESYSTEM_NEW_RE = re.compile(
    r"\b(?:Новый|New)\s*(?:\(\s*)?("
    r"File|Файл|xBase|HTMLWriter|ЗаписьHTML|HTMLReader|ЧтениеHTML|"
    r"FastInfosetReader|ЧтениеFastInfoset|FastInfosetWriter|ЗаписьFastInfoset|"
    r"XSLTransform|ПреобразованиеXSL|ZipFileWriter|ЗаписьZipФайла|ZipFileReader|"
    r"ЧтениеZipФайла|TextReader|ЧтениеТекста|TextWriter|ЗаписьТекста|TextExtraction|"
    r"ИзвлечениеТекста|BinaryData|ДвоичныеДанные|FileStream|ФайловыйПоток|"
    r"FileStreamsManager|МенеджерФайловыхПотоков|DataWriter|ЗаписьДанных|DataReader|ЧтениеДанных"
    r")\b",
    re.IGNORECASE | re.UNICODE,
)
_BSL203_INTERNET_NEW_RE = re.compile(
    r"\b(?:Новый|New)\s*(?:\(\s*)?("
    r"FTPСоединение|FTPConnection|HTTPСоединение|HTTPConnection|WSОпределения|WSDefinitions|"
    r"WSПрокси|WSProxy|ИнтернетПочтовыйПрофиль|InternetMailProfile|ИнтернетПочта|"
    r"InternetMail|Почта|Mail|HTTPЗапрос|HTTPRequest|ИнтернетПрокси|InternetProxy"
    r")\b",
    re.IGNORECASE | re.UNICODE,
)
_BSL203_INTERNET_STRING_NEW_RE = re.compile(
    r'\b(?:Новый|New)\s*\(\s*"('
    r"FTPСоединение|FTPConnection|HTTPСоединение|HTTPConnection|WSОпределения|WSDefinitions|"
    r"WSПрокси|WSProxy|ИнтернетПочтовыйПрофиль|InternetMailProfile|ИнтернетПочта|"
    r"InternetMail|Почта|Mail|HTTPЗапрос|HTTPRequest|ИнтернетПрокси|InternetProxy"
    r')"',
    re.IGNORECASE | re.UNICODE,
)
_BSL264_SYSTEM_INFO_NEW_RE = re.compile(
    r"\b(?:Новый|New)\s*(?:\(\s*)?(СистемнаяИнформация|SystemInfo)\b",
    re.IGNORECASE | re.UNICODE,
)
_BSL264_SYSTEM_INFO_STRING_NEW_RE = re.compile(
    r'\b(?:Новый|New)\s*\(\s*"(СистемнаяИнформация|SystemInfo)"',
    re.IGNORECASE | re.UNICODE,
)
_BSL205_ROLE_AVAILABLE_RE = re.compile(
    r"(?<!\.)(?<!\w)\b(РольДоступна|IsInRole)\s*\(",
    re.IGNORECASE | re.UNICODE,
)
_BSL205_PRIVILEGED_MODE_RE = re.compile(
    r"(?<!\.)(?<!\w)\b(ПривилегированныйРежим|PrivilegedMode)\s*\(",
    re.IGNORECASE | re.UNICODE,
)
_BSL205_ASSIGNMENT_RE = re.compile(
    r"^\s*([А-ЯЁа-яёA-Za-z_][А-ЯЁа-яёA-Za-z_0-9]*)\s*=",
    re.UNICODE,
)
_BSL205_IF_RE = re.compile(
    r"^\s*(?:Если|If|ИначеЕсли|ElsIf)\s+(.*?)(?:\bТогда\b|\bThen\b)",
    re.IGNORECASE | re.UNICODE,
)
_BSL183_EXECUTE_EXTERNAL_CODE_RE = re.compile(
    r"(?<![.\w])(Выполнить|Execute|Вычислить|Eval)\s*\(",
    re.IGNORECASE | re.UNICODE,
)
_BSL226_OS_USERS_RE = re.compile(
    r"(?<![.\w])(ПользователиОС|OSUsers)\s*\(",
    re.IGNORECASE | re.UNICODE,
)
_BSL247_SET_PRIVILEGED_RE = re.compile(
    r"(?<![.\w])(УстановитьПривилегированныйРежим|SetPrivilegedMode)\s*\(([^)]*)\)",
    re.IGNORECASE | re.UNICODE,
)
_BSL250_TEMPFILES_RE = re.compile(
    r"(?<![.\w])(КаталогВременныхФайлов|TempFilesDir)\s*\(",
    re.IGNORECASE | re.UNICODE,
)
_BSL267_EXTERNAL_CODE_TOOLS_RE = re.compile(
    r"(?<![.\w])"
    r"(ВнешниеОбработки|ExternalDataProcessors|ВнешниеОтчеты|ExternalReports|"
    r"РасширенияКонфигурации|ConfigurationExtensions)"
    r"\s*\.\s*(Создать|Create|Подключить|Connect)\s*\(",
    re.IGNORECASE | re.UNICODE,
)
_METHOD_CHAIN_RE = re.compile(r"\s*\.\s*[А-ЯЁа-яёA-Za-z_][А-ЯЁа-яёA-Za-z_0-9]*\s*\(", re.UNICODE)
_BSL272_SYNC_REPLACEMENTS: dict[str, str] = {
    "ВОПРОС": "ПоказатьВопрос",
    "DOQUERYBOX": "ShowQueryBox",
    "ОТКРЫТЬФОРМУМОДАЛЬНО": "ОткрытьФорму",
    "OPENFORMMODAL": "OpenForm",
    "ОТКРЫТЬЗНАЧЕНИЕ": "ПоказатьЗначение",
    "OPENVALUE": "ShowValue",
    "ПРЕДУПРЕЖДЕНИЕ": "ПоказатьПредупреждение",
    "DOMESSAGEBOX": "ShowMessageBox",
    "ВВЕСТИДАТУ": "ПоказатьВводДаты",
    "INPUTDATE": "ShowInputDate",
    "ВВЕСТИЗНАЧЕНИЕ": "ПоказатьВводЗначения",
    "INPUTVALUE": "ShowInputValue",
    "ВВЕСТИСТРОКУ": "ПоказатьВводСтроки",
    "INPUTSTRING": "ShowInputString",
    "ВВЕСТИЧИСЛО": "ПоказатьВводЧисла",
    "INPUTNUMBER": "ShowInputNumber",
    "УСТАНОВИТЬВНЕШНЮЮКОМПОНЕНТУ": "НачатьУстановкуВнешнейКомпоненты",
    "INSTALLADDIN": "BeginInstallAddIn",
    "УСТАНОВИТЬРАСШИРЕНИЕРАБОТЫСФАЙЛАМИ": "НачатьУстановкуРасширенияРаботыСФайлами",
    "INSTALLFILESYSTEMEXTENSION": "BeginInstallFileSystemExtension",
    "УСТАНОВИТЬРАСШИРЕНИЕРАБОТЫСКРИПТОГРАФИЕЙ": "НачатьУстановкуРасширенияРаботыСКриптографией",
    "INSTALLCRYPTOEXTENSION": "BeginInstallCryptoExtension",
    "ПОДКЛЮЧИТЬРАСШИРЕНИЕРАБОТЫСКРИПТОГРАФИЕЙ": "НачатьПодключениеРасширенияРаботыСКриптографией",
    "ATTACHCRYPTOEXTENSION": "BeginAttachingCryptoExtension",
    "ПОДКЛЮЧИТЬРАСШИРЕНИЕРАБОТЫСФАЙЛАМИ": "НачатьПодключениеРасширенияРаботыСФайлами",
    "ATTACHFILESYSTEMEXTENSION": "BeginAttachingFileSystemExtension",
    "ПОМЕСТИТЬФАЙЛ": "НачатьПомещениеФайла",
    "PUTFILE": "BeginPutFile",
    "КОПИРОВАТЬФАЙЛ": "НачатьКопированиеФайла",
    "FILECOPY": "BeginCopyingFile",
    "ПЕРЕМЕСТИТЬФАЙЛ": "НачатьПеремещениеФайла",
    "MOVEFILE": "BeginMovingFile",
    "НАЙТИФАЙЛЫ": "НачатьПоискФайлов",
    "FINDFILES": "BeginFindingFiles",
    "УДАЛИТЬФАЙЛЫ": "НачатьУдалениеФайлов",
    "DELETEFILES": "BeginDeletingFiles",
    "СОЗДАТЬКАТАЛОГ": "НачатьСозданиеКаталога",
    "CREATEDIRECTORY": "BeginCreatingDirectory",
    "КАТАЛОГВРЕМЕННЫХФАЙЛОВ": "НачатьПолучениеКаталогаВременныхФайлов",
    "TEMPFILESDIR": "BeginGettingTempFilesDir",
    "КАТАЛОГДОКУМЕНТОВ": "НачатьПолучениеКаталогаДокументов",
    "DOCUMENTSDIR": "BeginGettingDocumentsDir",
    "РАБОЧИЙКАТАЛОГДАННЫХПОЛЬЗОВАТЕЛЯ": "НачатьПолучениеРабочегоКаталогаДанныхПользователя",
    "USERDATAWORKDIR": "BeginGettingUserDataWorkDir",
    "ПОЛУЧИТЬФАЙЛЫ": "НачатьПолучениеФайлов",
    "GETFILES": "BeginGettingFiles",
    "ПОМЕСТИТЬФАЙЛЫ": "НачатьПомещениеФайлов",
    "PUTFILES": "BeginPuttingFiles",
    "ЗАПРОСИТЬРАЗРЕШЕНИЕПОЛЬЗОВАТЕЛЯ": "НачатьЗапросРазрешенияПользователя",
    "REQUESTUSERPERMISSION": "BeginRequestingUserPermission",
    "ЗАПУСТИТЬПРИЛОЖЕНИЕ": "НачатьЗапускПриложения",
    "RUNAPP": "BeginRunningApplication",
}
_BSL272_SYNC_RE = re.compile(
    r"(?<![.\w])(?P<name>"
    + "|".join(re.escape(key) for key in sorted(_BSL272_SYNC_REPLACEMENTS, key=len, reverse=True))
    + r")\s*\(",
    re.IGNORECASE | re.UNICODE,
)
_QUERY_VIRTUAL_TABLE_NAME_PATTERN = (
    r"(?:Регистр(?:Сведений|Накопления|Бухгалтерии|Расчета)|"
    r"InformationRegister|AccumulationRegister|AccountingRegister|CalculationRegister)"
    r"\.\w+(?:\.\w+)+"
)
_BSL273_VIRTUAL_TABLE_RE = re.compile(
    rf"\b(?P<name>{_QUERY_VIRTUAL_TABLE_NAME_PATTERN})\s*(?P<open>\()?",
    re.IGNORECASE | re.UNICODE,
)
_BSL279_IDENTIFIER_RE = re.compile(r"\b\w*[ёЁ]\w*\b", re.UNICODE)
_BSL277_ROLLBACK_NAMES = frozenset({"отменитьтранзакцию", "rollbacktransaction"})
_BSL276_PROCEED_NAMES = frozenset({"продолжитьвызов", "proceedwithcall"})
_BSL276_AROUND_ANNOTATION_RE = re.compile(r"^\s*&(?:Вместо|Instead|Around)\b", re.IGNORECASE)
_BSL060_MESSAGE = "Использование двойных отрицаний усложняет понимание кода"


def bsl024_find_report_comment_col(line: str) -> int | None:
    col = _comment_start_outside_string(line)
    if col < 0:
        return None
    comment_text = line[col:]
    if _BSL024_GOOD_STRICT_RE.match(comment_text):
        return None
    rest = comment_text[2:].lstrip()
    if rest.startswith("@") or rest.lower().startswith("(c)") or rest.startswith("©"):
        return None
    if (
        comment_text.startswith("//|")
        or comment_text.startswith("//!")
        or re.match(r"//\s*noqa\b", comment_text, re.IGNORECASE)
        or re.match(r"//\s*bsl-disable\b", comment_text, re.IGNORECASE)
    ):
        return None
    if _BSL024_COMMENTED_CODE_RE.match(comment_text):
        return None
    if col == len(line) - len(line.lstrip()) and rest.startswith("&"):
        return None
    return col


def _call_chain_end(line: str, open_paren: int) -> int:
    end = _single_line_call_end(line, open_paren)
    while True:
        match = _METHOD_CHAIN_RE.match(line, end)
        if match is None:
            return end
        end = _single_line_call_end(line, match.end() - 1)


def _multi_line_call_end(lines: list[str], start_line: int, open_paren: int) -> tuple[int, int]:
    depth = 0
    line_idx = start_line
    pos = open_paren
    while line_idx < len(lines):
        line = lines[line_idx]
        while pos < len(line):
            char = line[pos]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    return line_idx, pos + 1
            pos += 1
        line_idx += 1
        pos = 0
    return start_line, open_paren + 1


def bsl024_should_report_line(line: str) -> bool:
    return bsl024_find_report_comment_col(line) is not None


@dataclass(frozen=True)
class _TernarySpan:
    start: int
    end: int
    line: int
    col: int
    end_line: int
    end_col: int


def _skip_string(text: str, pos: int) -> int:
    quote = text[pos]
    pos += 1
    while pos < len(text):
        if text[pos] == quote:
            if quote == '"' and pos + 1 < len(text) and text[pos + 1] == '"':
                pos += 2
                continue
            return pos + 1
        pos += 1
    return pos


def _matching_paren(text: str, open_pos: int) -> int:
    depth = 1
    pos = open_pos + 1
    while pos < len(text):
        char = text[pos]
        if char in ('"', "'"):
            pos = _skip_string(text, pos)
            continue
        if char == "/" and pos + 1 < len(text) and text[pos + 1] == "/":
            newline = text.find("\n", pos)
            if newline < 0:
                return len(text)
            pos = newline + 1
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return pos + 1
        pos += 1
    return len(text)


def _split_top_level_args(text: str) -> list[str]:
    args: list[str] = []
    start = 0
    depth = 0
    pos = 0
    while pos < len(text):
        char = text[pos]
        if char in ('"', "'"):
            pos = _skip_string(text, pos)
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif char == "," and depth == 0:
            args.append(text[start:pos])
            start = pos + 1
        pos += 1
    args.append(text[start:])
    return args


def _calls_in_node(
    parent: Any,
    calls: list[dict[str, Any]],
    starts: list[int] | None = None,
) -> list[dict[str, Any]]:
    start = getattr(parent, "start_byte", None)
    end = getattr(parent, "end_byte", None)
    if start is None or end is None:
        return []
    effective_starts = starts or [getattr(call["node"], "start_byte", -1) for call in calls]
    left = bisect_left(effective_starts, start)
    right = bisect_left(effective_starts, end)
    return calls[left:right]


def _ternary_spans(context: BsllsDocumentContext) -> list[_TernarySpan]:
    spans: list[_TernarySpan] = []
    pos = 0
    text = context.content
    while pos < len(text):
        char = text[pos]
        if char in ('"', "'"):
            pos = _skip_string(text, pos)
            continue
        if char == "/" and pos + 1 < len(text) and text[pos + 1] == "/":
            newline = text.find("\n", pos)
            pos = len(text) if newline < 0 else newline + 1
            continue
        if char == "?":
            open_pos = pos + 1
            while open_pos < len(text) and text[open_pos].isspace():
                open_pos += 1
            if open_pos < len(text) and text[open_pos] == "(":
                end = _matching_paren(text, open_pos)
                line, col = context.to_line_col(pos)
                end_line, end_col = context.to_line_col(end)
                spans.append(_TernarySpan(pos, end, line, col, end_line, end_col))
                pos += 1
                continue
        pos += 1
    return spans


class CanonicalSpellingKeywordsRule(BsllsDiagnosticRule):
    code = "BSL153"
    _bool_op_re = re.compile(r"\b(?:И|And|ИЛИ|Or)\b", re.IGNORECASE | re.UNICODE)
    _if_start_re = re.compile(r"^\s*(?:Если|If|ИначеЕсли|ElsIf|ElseIf)\b", re.IGNORECASE)
    _then_re = re.compile(r"\b(?:Тогда|Then)\b", re.IGNORECASE)
    _accepted: dict[str, frozenset[str]] = {
        "если": frozenset({"Если", "If"}),
        "if": frozenset({"If"}),
        "тогда": frozenset({"Тогда", "Then"}),
        "then": frozenset({"Then"}),
        "иначе": frozenset({"Иначе", "Else"}),
        "else": frozenset({"Else"}),
        "иначеесли": frozenset({"ИначеЕсли", "ElsIf", "ElseIf"}),
        "elsif": frozenset({"ElsIf"}),
        "elseif": frozenset({"ElseIf"}),
        "конецесли": frozenset({"КонецЕсли", "EndIf"}),
        "endif": frozenset({"EndIf"}),
        "для": frozenset({"Для", "For"}),
        "for": frozenset({"For"}),
        "каждого": frozenset({"Каждого", "каждого", "Each", "each"}),
        "each": frozenset({"Each", "each"}),
        "из": frozenset({"Из", "In"}),
        "in": frozenset({"In"}),
        "цикл": frozenset({"Цикл", "Do"}),
        "do": frozenset({"Do"}),
        "пока": frozenset({"Пока", "While"}),
        "while": frozenset({"While"}),
        "прервать": frozenset({"Прервать", "Break"}),
        "break": frozenset({"Break"}),
        "продолжить": frozenset({"Продолжить", "Continue"}),
        "continue": frozenset({"Continue"}),
        "конеццикла": frozenset({"КонецЦикла", "EndDo"}),
        "enddo": frozenset({"EndDo"}),
        "по": frozenset({"По", "To"}),
        "to": frozenset({"To"}),
        "процедура": frozenset({"Процедура", "Procedure"}),
        "procedure": frozenset({"Procedure"}),
        "знач": frozenset({"Знач", "Val"}),
        "val": frozenset({"Val"}),
        "экспорт": frozenset({"Экспорт", "Export"}),
        "export": frozenset({"Export"}),
        "перем": frozenset({"Перем", "Var"}),
        "var": frozenset({"Var"}),
        "попытка": frozenset({"Попытка", "Try"}),
        "try": frozenset({"Try"}),
        "выполнить": frozenset({"Выполнить", "Execute"}),
        "execute": frozenset({"Execute"}),
        "возврат": frozenset({"Возврат", "Return"}),
        "return": frozenset({"Return"}),
        "истина": frozenset({"Истина", "True"}),
        "true": frozenset({"True"}),
        "исключение": frozenset({"Исключение", "Except"}),
        "except": frozenset({"Except"}),
        "вызватьисключение": frozenset({"ВызватьИсключение", "Raise"}),
        "raise": frozenset({"Raise"}),
        "конецпопытки": frozenset({"КонецПопытки", "EndTry"}),
        "endtry": frozenset({"EndTry"}),
        "конецпроцедуры": frozenset({"КонецПроцедуры", "EndProcedure"}),
        "endprocedure": frozenset({"EndProcedure"}),
        "функция": frozenset({"Функция", "Function"}),
        "function": frozenset({"Function"}),
        "конецфункции": frozenset({"КонецФункции", "EndFunction"}),
        "endfunction": frozenset({"EndFunction"}),
        "ложь": frozenset({"Ложь", "False"}),
        "false": frozenset({"False"}),
        "добавитьобработчик": frozenset({"ДобавитьОбработчик", "AddHandler"}),
        "addhandler": frozenset({"AddHandler"}),
        "удалитьобработчик": frozenset({"УдалитьОбработчик", "RemoveHandler"}),
        "removehandler": frozenset({"RemoveHandler"}),
        "перейти": frozenset({"Перейти", "Goto"}),
        "goto": frozenset({"Goto"}),
        "и": frozenset({"И"}),
        "and": frozenset({"And", "AND"}),
        "или": frozenset({"Или", "ИЛИ"}),
        "or": frozenset({"Or", "OR"}),
        "не": frozenset({"Не", "НЕ"}),
        "not": frozenset({"Not", "NOT"}),
        "новый": frozenset({"Новый", "New"}),
        "new": frozenset({"New"}),
        "неопределено": frozenset({"Неопределено", "Undefined"}),
        "undefined": frozenset({"Undefined"}),
        "область": frozenset({"Область", "Region"}),
        "region": frozenset({"Region"}),
        "конецобласти": frozenset({"КонецОбласти", "EndRegion"}),
        "endregion": frozenset({"EndRegion"}),
        "сервер": frozenset({"Сервер", "Server"}),
        "server": frozenset({"Server"}),
        "клиент": frozenset({"Клиент", "Client"}),
        "client": frozenset({"Client"}),
        "мобильноеприложениеклиент": frozenset({"МобильноеПриложениеКлиент", "MobileAppClient"}),
        "mobileappclient": frozenset({"MobileAppClient"}),
        "мобильноеприложениесервер": frozenset({"МобильноеПриложениеСервер", "MobileAppServer"}),
        "mobileappserver": frozenset({"MobileAppServer"}),
        "мобильныйклиент": frozenset({"МобильныйКлиент", "MobileClient"}),
        "mobileclient": frozenset({"MobileClient"}),
        "толстыйклиентобычноеприложение": frozenset(
            {"ТолстыйКлиентОбычноеПриложение", "ThickClientOrdinaryApplication"}
        ),
        "thickclientordinaryapplication": frozenset({"ThickClientOrdinaryApplication"}),
        "толстыйклиентуправляемоеприложение": frozenset(
            {"ТолстыйКлиентУправляемоеПриложение", "ThickClientManagedApplication"}
        ),
        "thickclientmanagedapplication": frozenset({"ThickClientManagedApplication"}),
        "внешнеесоединение": frozenset({"ВнешнееСоединение", "ExternalConnection"}),
        "externalconnection": frozenset({"ExternalConnection"}),
        "тонкийклиент": frozenset({"ТонкийКлиент", "ThinClient"}),
        "thinclient": frozenset({"ThinClient"}),
        "вебклиент": frozenset({"ВебКлиент", "WebClient"}),
        "webclient": frozenset({"WebClient"}),
        "наклиенте": frozenset({"НаКлиенте", "AtClient"}),
        "atclient": frozenset({"AtClient"}),
        "насервере": frozenset({"НаСервере", "AtServer"}),
        "atserver": frozenset({"AtServer"}),
        "насерверебезконтекста": frozenset({"НаСервереБезКонтекста", "AtServerNoContext"}),
        "atservernocontext": frozenset({"AtServerNoContext"}),
        "наклиентенасерверебезконтекста": frozenset(
            {"НаКлиентеНаСервереБезКонтекста", "AtClientAtServerNoContext"}
        ),
        "atclientatservernocontext": frozenset({"AtClientAtServerNoContext"}),
        "наклиентенасервере": frozenset({"НаКлиентеНаСервере", "AtClientAtServer"}),
        "atclientatserver": frozenset({"AtClientAtServer"}),
    }
    _word_re = re.compile(
        r"\b(?:"
        + "|".join(re.escape(key) for key in sorted(_accepted, key=len, reverse=True))
        + r")\b",
        re.IGNORECASE | re.UNICODE,
    )

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        if _path_is_form_module_bsl(context.path):
            return []
        skipped_lines = self._bsl036_condition_lines(context) if context.bsl036_enabled else set()
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            if _line_comment(line) or idx in skipped_lines:
                continue
            clean = _code_mask_without_strings_and_comments(line)
            for match in self._word_re.finditer(clean):
                word = match.group()
                if word in self._accepted.get(word.lower(), ()):
                    continue
                storage.add_match(
                    code=self.code,
                    line=idx,
                    start=match.start(),
                    end=match.end(),
                    severity=Severity.INFORMATION,
                    message=f'Ключевое слово "{word}" написано не канонически',
                )
        return storage.diagnostics

    @classmethod
    def _bsl036_condition_lines(cls, context: BsllsDocumentContext) -> set[int]:
        skipped: set[int] = set()
        for start, line in enumerate(context.lines):
            if not cls._if_start_re.match(line):
                continue
            chunk_lines: list[str] = []
            end = start
            while end < len(context.lines):
                chunk_lines.append(context.lines[end])
                if cls._then_re.search(context.lines[end]):
                    break
                end += 1
            chunk = "\n".join(chunk_lines)
            if len(cls._bool_op_re.findall(chunk)) <= context.max_bool_ops:
                continue
            skipped.update(range(start, min(end + 1, len(context.lines))))
        return skipped


class UsingGotoRule(BsllsDiagnosticRule):
    code = "BSL027"
    _goto_re = re.compile(r"^\s*(?:Перейти|Goto)\s+~", re.IGNORECASE)

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            if _line_comment(line):
                continue
            match = self._goto_re.match(_code_mask_without_strings_and_comments(line))
            if match is None:
                continue
            storage.add_range(
                code=self.code,
                line=idx,
                character=len(line) - len(line.lstrip()),
                end_line=idx,
                end_character=match.end(),
                severity=Severity.WARNING,
                message='Оператор "Перейти" не должен использоваться',
            )
        return storage.diagnostics


class DoubleNegativesRule(BsllsDiagnosticRule):
    code = "BSL060"

    @staticmethod
    def _operator(node: Any) -> Any | None:
        return next((child for child in _ts_children(node) if child.type == "operator"), None)

    @classmethod
    def _operator_text(cls, node: Any) -> str:
        operator = cls._operator(node)
        return _ts_node_text(operator).casefold().strip() if operator is not None else ""

    @classmethod
    def _is_not_unary(cls, node: Any) -> bool:
        return getattr(node, "type", None) == "unary_expression" and cls._operator_text(node) in {
            "не",
            "not",
        }

    @classmethod
    def _expression_child(cls, node: Any) -> Any | None:
        return next((child for child in _ts_children(node) if child.type == "expression"), None)

    @classmethod
    def _single_expression_term(cls, expr: Any) -> Any | None:
        if getattr(expr, "type", None) != "expression":
            return None
        terms = [child for child in _ts_children(expr) if child.type != ";"]
        return terms[0] if len(terms) == 1 else None

    @classmethod
    def _text_starts_with_not_paren(cls, node: Any) -> bool:
        text = _ts_node_text(node).casefold().lstrip()
        return text.startswith("не (") or text.startswith("not (")

    @classmethod
    def _parent_binary_operator(cls, node: Any) -> str:
        current = node
        while getattr(current, "parent", None) is not None:
            current = current.parent
            if getattr(current, "type", None) == "binary_expression":
                return cls._operator_text(current)
            if getattr(current, "type", None) != "expression":
                return ""
        return ""

    @classmethod
    def _is_nested_in_logical_expression(cls, node: Any) -> bool:
        return cls._parent_binary_operator(node) in {"и", "and", "или", "or"}

    @classmethod
    def _binary_parts(cls, node: Any) -> tuple[Any, Any, Any] | None:
        children = _ts_children(node)
        for idx, child in enumerate(children):
            if getattr(child, "type", None) != "operator":
                continue
            if _ts_node_text(child).strip() != "<>":
                return None
            if idx == 0 or idx + 1 >= len(children):
                return None
            return children[idx - 1], child, children[idx + 1]
        return None

    @classmethod
    def _binary_diagnostic_nodes(cls, node: Any) -> tuple[Any, Any] | None:
        parts = cls._binary_parts(node)
        if parts is None:
            return None
        left, _operator, right = parts
        left_unary = cls._single_expression_term(left)
        if not cls._is_not_unary(left_unary):
            return None
        if cls._is_nested_in_logical_expression(node) and cls._text_starts_with_not_paren(node):
            return None
        start = cls._operator(left_unary)
        if start is None:
            return None
        return start, right

    @classmethod
    def _nested_unary_diagnostic_nodes(cls, node: Any) -> tuple[Any, Any] | None:
        if not cls._is_not_unary(node):
            return None
        if cls._parent_binary_operator(node):
            return None
        expr = cls._expression_child(node)
        inner = cls._single_expression_term(expr)
        if not cls._is_not_unary(inner):
            return None
        start = cls._operator(node)
        operand = cls._expression_child(inner)
        if start is None or operand is None:
            return None
        return start, operand

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        root = getattr(getattr(context, "tree", None), "root_node", None)
        if root is None:
            return []
        storage = DiagnosticStorage(context.path)
        seen: set[tuple[int, int, int, int]] = set()

        def add(start: Any, end: Any) -> None:
            key = (
                int(start.start_point[0]),
                _point_char(context.lines, start.start_point),
                int(end.end_point[0]),
                _point_char(context.lines, end.end_point),
            )
            if key in seen:
                return
            seen.add(key)
            _add_node_range(
                storage,
                code=self.code,
                message=_BSL060_MESSAGE,
                severity=Severity.WARNING,
                lines=context.lines,
                start_node=start,
                end_node=end,
            )

        for node in _ts_walk(root):
            if getattr(node, "type", None) == "binary_expression":
                nodes = self._binary_diagnostic_nodes(node)
                if nodes is not None:
                    add(*nodes)
            elif getattr(node, "type", None) == "unary_expression":
                nodes = self._nested_unary_diagnostic_nodes(node)
                if nodes is not None:
                    add(*nodes)
        return storage.diagnostics


class DeprecatedMessageRule(BsllsDiagnosticRule):
    code = "BSL041"
    _message_re = re.compile(r"\b(?:Сообщить|Message)\s*\(", re.IGNORECASE)

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            if _line_comment(line):
                continue
            clean = _code_mask_without_strings_and_comments(line)
            match = self._message_re.search(clean)
            if match is None:
                continue
            if clean[: match.start()].rstrip().endswith("."):
                continue
            storage.add_match(
                code=self.code,
                line=idx,
                start=match.start(),
                end=match.end(),
                severity=Severity.INFORMATION,
                message='Не следует использовать устаревший метод "Сообщить"',
            )
        return storage.diagnostics


class UsingHardcodeNetworkAddressRule(BsllsDiagnosticRule):
    code = "BSL005"

    @staticmethod
    def _string_context(line: str, start: int, end: int) -> str:
        left = max(line.rfind(",", 0, start), line.rfind("(", 0, start))
        right_candidates = [pos for pos in (line.find(",", end), line.find(")", end)) if pos >= 0]
        right = min(right_candidates) if right_candidates else len(line)
        return line[left + 1 : right]

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            if _line_comment(line) or _BSL005_LINE_EXCLUSION_RE.search(line):
                continue
            for string_match in _DOUBLE_QUOTED_STRING_RE.finditer(line):
                if _BSL005_PARAM_VERSION_RE.search(
                    self._string_context(line, string_match.start(), string_match.end())
                ):
                    continue
                content = string_match.group()[1:-1]
                if len(content) <= 2 or _BSL005_URL_RE.match(content):
                    continue
                network_match = _BSL005_NETWORK_ADDRESS_RE.search(content)
                if network_match is None:
                    continue
                first_value = network_match.group(0)
                dot_count = first_value.count(".")
                if dot_count > 0 and (
                    content.count(".") > 3 or _BSL005_ALPHABET_RE.search(first_value)
                ):
                    continue
                if _BSL005_POPULAR_VERSION_RE.search(content):
                    continue
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=string_match.start(),
                    end_line=idx,
                    end_character=string_match.end(),
                    severity=Severity.ERROR,
                    message="Используется хранение в коде ip-адреса",
                )
        return storage.diagnostics


class UsingHardcodePathRule(BsllsDiagnosticRule):
    code = "BSL006"

    @staticmethod
    def _is_path(content: str) -> bool:
        if len(content) <= 2 or _BSL006_URL_RE.match(content):
            return False
        if content.startswith("\\\\"):
            return True
        if re.match(r"^[A-Za-z]:(?:[\\/]|//|$)", content):
            return True
        if content.startswith("~/") or content.startswith("~\\"):
            return True
        if re.match(r"^%[^%]+%(?:[\\/]|//)", content):
            return True
        return bool(_BSL006_UNIX_STD_ROOT_RE.match(content))

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            if _line_comment(line):
                continue
            for match in _DOUBLE_QUOTED_STRING_RE.finditer(line):
                if not self._is_path(match.group()[1:-1]):
                    continue
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=match.start(),
                    end_line=idx,
                    end_character=match.end(),
                    severity=Severity.ERROR,
                    message="Используется хранение в коде пути к файлу",
                )
        return storage.diagnostics


class UsingServiceTagRule(BsllsDiagnosticRule):
    code = "BSL023"
    _service_tag_re = re.compile(
        r"//\s*("
        r"todo|fixme|!!|mrg|@|отладка|debug|для\s*отладки"
        r"|(?:\{\{|\}\})КОНСТРУКТОР_|(?:\{\{|\}\})MRG"
        r"|Вставить\s*содержимое\s*обработчика"
        r"|Paste\s*handler\s*content|Insert\s*handler\s*code"
        r"|Insert\s*handler\s*content|Insert\s*handler\s*contents"
        r")",
        re.IGNORECASE,
    )

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            comment_start = _comment_start_outside_string(line)
            if comment_start < 0:
                continue
            match = self._service_tag_re.search(line, comment_start)
            if match is None:
                continue
            storage.add_range(
                code=self.code,
                line=idx,
                character=match.start(),
                end_line=idx,
                end_character=len(line),
                severity=Severity.INFORMATION,
                message=f'Найден служебный тег "{match.group(0)}"',
            )
        return storage.diagnostics


class SpaceAtStartCommentRule(BsllsDiagnosticRule):
    code = "BSL024"

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            col = bsl024_find_report_comment_col(line)
            if col is None:
                continue
            storage.add_range(
                code=self.code,
                line=idx,
                character=col,
                end_line=idx,
                end_character=len(line),
                severity=Severity.INFORMATION,
                message=(
                    "Между символами комментария '//' и самим текстом комментария "
                    "должен быть пробел."
                ),
            )
        return storage.diagnostics


class EmptyStatementRule(BsllsDiagnosticRule):
    code = "BSL025"
    _compound_semicolon_re = re.compile(
        r"^\s*(?:Если|If|ИначеЕсли|ElsIf|ElseIf|Для(?:\s+Каждого)?|For(?:\s+Each)?|Пока|While)\b.*(?:Тогда|Then|Цикл|Do)\s*;\s*$",
        re.IGNORECASE,
    )
    _header_semicolon_re = re.compile(
        r"^\s*(?:Процедура|Функция|Procedure|Function)\b.*;\s*$",
        re.IGNORECASE,
    )

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            if _line_comment(line):
                continue
            comment_start = _comment_start_outside_string(line)
            code_part = line if comment_start < 0 else line[:comment_start]
            stripped = code_part.rstrip()
            if not stripped:
                continue
            semi = -1
            if self._header_semicolon_re.match(stripped) or self._compound_semicolon_re.match(
                stripped
            ):
                semi = stripped.rfind(";")
            elif ";;" in stripped:
                semi = stripped.find(";;") + 1
            if semi < 0:
                continue
            storage.add_range(
                code=self.code,
                line=idx,
                character=semi,
                end_line=idx,
                end_character=semi + 1,
                severity=Severity.HINT,
                message='Удалите ";"',
            )
        return storage.diagnostics


class ConsecutiveEmptyLinesRule(BsllsDiagnosticRule):
    code = "BSL055"

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        blank_flags = (
            context.snapshot.blank_line_flags
            if context.snapshot is not None and hasattr(context.snapshot, "blank_line_flags")
            else [line.strip() == "" for line in context.lines]
        )
        storage = DiagnosticStorage(context.path)
        blank_run = 0
        run_start = 0
        for idx, is_blank in enumerate(blank_flags):
            if is_blank:
                if blank_run == 0:
                    run_start = idx
                blank_run += 1
                continue
            if blank_run > 1:
                self._add_issue(storage, run_start, run_start + blank_run - 1)
            blank_run = 0
        if blank_run > 1:
            self._add_issue(storage, run_start, run_start + blank_run - 1)
        if len(context.lines) >= 2 and blank_flags[-1] and not blank_flags[-2]:
            self._add_issue(storage, len(context.lines) - 1, len(context.lines))
        return storage.diagnostics

    @classmethod
    def _add_issue(cls, storage: DiagnosticStorage, start_line: int, end_line: int) -> None:
        storage.add_range(
            code=cls.code,
            line=start_line,
            character=0,
            end_line=end_line,
            end_character=0,
            severity=Severity.INFORMATION,
            message="Удалите лишние последовательные пустые строки",
        )


class NestedTernaryOperatorRule(BsllsDiagnosticRule):
    code = "BSL039"

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        ternaries = _ternary_spans(context)
        flagged: dict[int, _TernarySpan] = {}
        for inner in ternaries:
            if any(outer.start < inner.start and inner.end <= outer.end for outer in ternaries):
                flagged[inner.start] = inner

        if_start_re = re.compile(r"^\s*(?:Если|If|ИначеЕсли|ElsIf|ElseIf)\b", re.IGNORECASE)
        then_re = re.compile(r"\b(?:Тогда|Then)\b", re.IGNORECASE)
        for idx, line in enumerate(context.lines):
            if not if_start_re.match(line):
                continue
            end_idx = idx
            while end_idx < len(context.lines) and not then_re.search(context.lines[end_idx]):
                end_idx += 1
            if end_idx >= len(context.lines):
                continue
            for ternary in ternaries:
                if idx <= ternary.line <= end_idx:
                    flagged[ternary.start] = ternary

        storage = DiagnosticStorage(context.path)
        for span in sorted(flagged.values(), key=lambda item: item.start):
            storage.add_range(
                code=self.code,
                line=span.line,
                character=span.col,
                end_line=span.end_line,
                end_character=span.end_col,
                severity=Severity.WARNING,
                message="Не рекомендуется использовать вложенный тернарный оператор",
            )
        return storage.diagnostics


class MagicDateRule(BsllsDiagnosticRule):
    code = "BSL047"
    _authorized = {"00010101", "00010101000000", "000101010000"}
    _date_literal_re = re.compile(r"'([^']*)'")
    _string_literal_re = re.compile(r'"([0-9]{8}|[0-9]{14})"')

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            if line.lstrip().startswith("//"):
                continue
            code_part = line.split("//", 1)[0]
            for regex, is_string in (
                (self._date_literal_re, False),
                (self._string_literal_re, True),
            ):
                for match in regex.finditer(code_part):
                    value = match.group(1)
                    if self._line_prefix_skips(line, match.start(), value, is_string):
                        continue
                    storage.add_match(
                        code=self.code,
                        line=idx,
                        start=match.start(),
                        end=match.end(),
                        severity=Severity.INFORMATION,
                        message=(
                            "Создайте переменную с понятным названием, присвойте ей "
                            f'значение "{match.group(0)}" и используйте эту константу '
                            "вместо магической даты."
                        ),
                    )
        return storage.diagnostics

    @classmethod
    def _valid_date(cls, value: str) -> bool:
        try:
            year = int(value[:4].lstrip("0") or "0")
            month = int(value[4:6])
            day = int(value[6:8])
        except ValueError:
            return False
        if year < 1 or year > 9999 or month < 1 or month > 12 or day < 1 or day > 31:
            return False
        if len(value) == 8:
            return True
        try:
            hour = int(value[8:10])
            minute = int(value[10:12])
            second = int(value[12:14])
        except ValueError:
            return False
        return hour <= 24 and minute <= 60 and second <= 60

    @classmethod
    def _line_prefix_skips(cls, line: str, start: int, value: str, is_string: bool) -> bool:
        prefix = line[:start]
        code = line.split("//", 1)[0]
        if value in cls._authorized:
            return True
        digits = re.sub(r"\D", "", value)
        if digits in cls._authorized:
            return True
        if not is_string and len(digits) not in (8, 14):
            return True
        if re.search(r"\b(?:Возврат|Return)\b", prefix, re.IGNORECASE):
            return True
        if re.search(r"\b(?:Функция|Function|Процедура|Procedure)\b", prefix, re.IGNORECASE):
            return True
        if re.match(r"^\s*Структура\w*\.[\wА-Яа-яЁё]+\s*=\s*$", prefix, re.IGNORECASE):
            return True
        if re.search(r"\b(?:ФиксированнаяСтруктура|FixedStructure)\s*\(", line, re.IGNORECASE):
            return True
        if re.search(r"\b(?:Новый\s+)?(?:Структура|Structure|Соответствие|Map)\b", line, re.IGNORECASE):
            return True
        if re.search(r"\.(?:Вставить|Insert)\s*\(", prefix, re.IGNORECASE):
            return True
        if is_string and not cls._valid_date(value):
            return True
        if re.match(r"^\s*[\wА-Яа-яЁё.]+\s*=\s*$", prefix, re.IGNORECASE):
            suffix = line[start + len(value) + 2 :].split("//", 1)[0].strip()
            if suffix.startswith(";") or suffix == "":
                return True
        if re.match(
            r"^\s*[\wА-Яа-яЁё.]+\s*=\s*(?:Дата|Date)\s*\(\s*$",
            prefix,
            re.IGNORECASE,
        ):
            suffix = code[start + len(value) + 2 :].strip()
            if suffix.startswith(")"):
                tail = suffix[1:].strip()
                if tail.startswith(";") or tail == "":
                    return True
        return False


class UselessTernaryOperatorRule(BsllsDiagnosticRule):
    code = "BSL265"
    _boolean_operand_re = re.compile(r"\b(?:Истина|True|Ложь|False)\b", re.IGNORECASE | re.UNICODE)
    _comment_re = re.compile(r"^\s*//")

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for span in _ternary_spans(context):
            line_text = context.lines[span.line] if span.line < len(context.lines) else ""
            if self._comment_re.match(line_text):
                continue
            ternary_text = context.content[span.start : span.end]
            if self._boolean_operand_re.search(ternary_text):
                storage.add_range(
                    code=self.code,
                    line=span.line,
                    character=span.col,
                    end_line=span.end_line,
                    end_character=span.end_col,
                    severity=Severity.INFORMATION,
                    message="Бесполезный тернарный оператор",
                )
        return storage.diagnostics


class DeprecatedFindRule(BsllsDiagnosticRule):
    code = "BSL066"

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            if _line_comment(line):
                continue
            clean = _code_mask_without_strings_and_comments(line)
            for match in _BSL066_DEPRECATED_FIND_RE.finditer(clean):
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=match.start(1),
                    end_line=idx,
                    end_character=match.end(1),
                    severity=Severity.INFORMATION,
                    message='Используйте "СтрНайти" вместо устаревшего "Найти"',
                )
        return storage.diagnostics


class DeprecatedMethods8317Rule(BsllsDiagnosticRule):
    code = "BSL178"

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            if _line_comment(line):
                continue
            clean = _code_mask_without_strings_and_comments(line)
            for match in _BSL178_DEPRECATED_METHOD_RE.finditer(clean):
                method_name = match.group(1)
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=match.start(1),
                    end_line=idx,
                    end_character=match.end(1),
                    severity=Severity.INFORMATION,
                    message=(
                        f'Метод "{method_name}" устарел. Следует использовать одноименный '
                        "метод объекта типа МенеджерОбработкиОшибок"
                    ),
                )
        return storage.diagnostics


class DeprecatedMethods8310Rule(BsllsDiagnosticRule):
    code = "BSL177"

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            if _line_comment(line):
                continue
            clean = _code_mask_without_strings_and_comments(line)
            for match in _BSL177_DEPRECATED_METHOD_RE.finditer(clean):
                method_name = match.group(1)
                replacement = _BSL177_METHOD_REPLACEMENTS.get(method_name.casefold(), "")
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=match.start(1),
                    end_line=idx,
                    end_character=_single_line_call_end(clean, match.end() - 1),
                    severity=Severity.INFORMATION,
                    message=f'Метод "{method_name}" устарел. Следует использовать "{replacement}".',
                )
        return storage.diagnostics


class GetFormMethodRule(BsllsDiagnosticRule):
    code = "BSL195"

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            if _line_comment(line):
                continue
            clean = _code_mask_without_strings_and_comments(line)
            for match in _BSL195_GET_FORM_RE.finditer(clean):
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=match.start(1),
                    end_line=idx,
                    end_character=match.end(1),
                    severity=Severity.ERROR,
                    message="Не рекомендуемое использование метода ПолучитьФорму",
                )
        return storage.diagnostics


class DeprecatedTypeManagedFormRule(BsllsDiagnosticRule):
    code = "BSL179"

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            if _line_comment(line):
                continue
            comment_pos = _comment_start_outside_string(line)
            clean = line if comment_pos < 0 else line[:comment_pos]
            for match in _BSL179_MANAGED_FORM_RE.finditer(clean):
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=match.start(1),
                    end_line=idx,
                    end_character=match.end(1),
                    severity=Severity.INFORMATION,
                    message='Замените устаревшее использование типа "УправляемаяФорма"',
                )
        return storage.diagnostics


class DisableSafeModeRule(BsllsDiagnosticRule):
    code = "BSL180"

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            if _line_comment(line):
                continue
            clean = _code_mask_without_strings_and_comments(line)
            for match in _BSL180_DISABLE_SAFE_MODE_RE.finditer(clean):
                method_name = match.group(1)
                arg = match.group(2).strip().casefold()
                if method_name.casefold() in {"установитьбезопасныйрежим", "setsafemode"}:
                    if arg in {"истина", "true"}:
                        continue
                elif arg in {"ложь", "false"}:
                    continue
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=match.start(1),
                    end_line=idx,
                    end_character=match.end(1),
                    severity=Severity.ERROR,
                    message="Проверьте отключение безопасного режима",
                )
        return storage.diagnostics


class ExternalAppStartingRule(BsllsDiagnosticRule):
    code = "BSL185"

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            if _line_comment(line):
                continue
            clean = _code_mask_without_strings_and_comments(line)
            for match in _BSL185_EXTERNAL_APP_RE.finditer(clean):
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=match.start(1),
                    end_line=idx,
                    end_character=match.end(1),
                    severity=Severity.ERROR,
                    message="Проверьте запуск внешнего приложения",
                )
        return storage.diagnostics


class FileSystemAccessRule(BsllsDiagnosticRule):
    code = "BSL188"

    @staticmethod
    def _new_end(clean: str, type_end: int) -> int:
        pos = type_end
        while pos < len(clean) and clean[pos].isspace():
            pos += 1
        if pos < len(clean) and clean[pos] == "(":
            return _single_line_call_end(clean, pos)
        return type_end

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            if _line_comment(line):
                continue
            clean = _code_mask_without_strings_and_comments(line)
            for match in _BSL188_FILESYSTEM_METHOD_RE.finditer(clean):
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=match.start(1),
                    end_line=idx,
                    end_character=match.end(1),
                    severity=Severity.ERROR,
                    message="Проверьте обращение к файловой системе",
                )
            for match in _BSL188_FILESYSTEM_NEW_RE.finditer(clean):
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=match.start(),
                    end_line=idx,
                    end_character=self._new_end(clean, match.end(1)),
                    severity=Severity.WARNING,
                    message="Проверьте обращение к файловой системе",
                )
        return storage.diagnostics


class InternetAccessRule(BsllsDiagnosticRule):
    code = "BSL203"

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            if _line_comment(line):
                continue
            clean = _code_mask_without_strings_and_comments(line)
            for match in _BSL203_INTERNET_NEW_RE.finditer(clean):
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=match.start(),
                    end_line=idx,
                    end_character=FileSystemAccessRule._new_end(clean, match.end(1)),
                    severity=Severity.WARNING,
                    message="Проверьте обращение к Интернет-ресурсам",
                )
            code_part = _code_before_comment(line)
            for match in _BSL203_INTERNET_STRING_NEW_RE.finditer(code_part):
                open_paren = code_part.find("(", match.start())
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=match.start(),
                    end_line=idx,
                    end_character=_single_line_call_end(code_part, open_paren),
                    severity=Severity.WARNING,
                    message="Проверьте обращение к Интернет-ресурсам",
                )
        return storage.diagnostics


class UseSystemInformationRule(BsllsDiagnosticRule):
    code = "BSL264"

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            if _line_comment(line):
                continue
            clean = _code_mask_without_strings_and_comments(line)
            for match in _BSL264_SYSTEM_INFO_NEW_RE.finditer(clean):
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=match.start(),
                    end_line=idx,
                    end_character=FileSystemAccessRule._new_end(clean, match.end(1)),
                    severity=Severity.ERROR,
                    message="Избавьтесь от использования объекта `СистемнаяИнформация`",
                )
            code_part = _code_before_comment(line)
            for match in _BSL264_SYSTEM_INFO_STRING_NEW_RE.finditer(code_part):
                open_paren = code_part.find("(", match.start())
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=match.start(),
                    end_line=idx,
                    end_character=_single_line_call_end(code_part, open_paren),
                    severity=Severity.ERROR,
                    message="Избавьтесь от использования объекта `СистемнаяИнформация`",
                )
        return storage.diagnostics


class IsInRoleMethodRule(BsllsDiagnosticRule):
    code = "BSL205"

    @staticmethod
    def _has_privileged_var(expression: str, privileged_vars: set[str]) -> bool:
        return any(re.search(rf"(?<!\w){re.escape(var)}(?!\w)", expression) for var in privileged_vars)

    @staticmethod
    def _next_privileged_call_start(expression: str, start: int) -> int | None:
        match = _BSL205_PRIVILEGED_MODE_RE.search(expression, start)
        return None if match is None else match.start()

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        is_in_role_vars: set[str] = set()
        privileged_mode_vars: set[str] = set()

        for idx, line in enumerate(context.lines):
            if _line_comment(line):
                continue
            code_part = _code_before_comment(line)
            clean = _code_mask_without_strings_and_comments(line)

            assignment = _BSL205_ASSIGNMENT_RE.match(clean)
            if assignment is not None:
                assigned_name = assignment.group(1)
                is_in_role_vars.discard(assigned_name)
                privileged_mode_vars.discard(assigned_name)
                if _BSL205_ROLE_AVAILABLE_RE.search(clean) is not None:
                    is_in_role_vars.add(assigned_name)
                elif _BSL205_PRIVILEGED_MODE_RE.search(clean) is not None:
                    privileged_mode_vars.add(assigned_name)

            if_match = _BSL205_IF_RE.match(clean)
            if if_match is None:
                continue

            expression_start = if_match.start(1)
            expression = code_part[expression_start : if_match.end(1)]
            clean_expression = clean[expression_start : if_match.end(1)]
            has_privileged_var = self._has_privileged_var(clean_expression, privileged_mode_vars)

            for match in _BSL205_ROLE_AVAILABLE_RE.finditer(clean_expression):
                if has_privileged_var:
                    continue
                if self._next_privileged_call_start(clean_expression, match.end()) is not None:
                    continue
                open_paren = expression.find("(", match.start())
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=expression_start + match.start(1),
                    end_line=idx,
                    end_character=expression_start + _single_line_call_end(expression, open_paren),
                    severity=Severity.WARNING,
                    message="Для проверки прав доступа в коде следует использовать метод ПравоДоступа",
                )

            if has_privileged_var:
                continue
            for var in is_in_role_vars:
                for match in re.finditer(rf"(?<!\w){re.escape(var)}(?!\w)", clean_expression):
                    if self._next_privileged_call_start(clean_expression, match.end()) is not None:
                        continue
                    storage.add_range(
                        code=self.code,
                        line=idx,
                        character=expression_start + match.start(),
                        end_line=idx,
                        end_character=expression_start + match.end(),
                        severity=Severity.WARNING,
                        message="Для проверки прав доступа в коде следует использовать метод ПравоДоступа",
                    )
        return storage.diagnostics


class ExecuteExternalCodeRule(BsllsDiagnosticRule):
    code = "BSL183"

    @staticmethod
    def _client_only_method(lines: list[str], start_idx: int) -> bool:
        idx = start_idx - 1
        while idx >= 0:
            stripped = lines[idx].strip()
            if not stripped or stripped.startswith("//"):
                idx -= 1
                continue
            if not stripped.startswith("&"):
                return False
            directive = stripped[1:].split()[0].casefold()
            if directive in {"наклиенте", "atclient"}:
                return True
            idx -= 1
        return False

    @staticmethod
    def _fallback_procs(lines: list[str]) -> list[Any]:
        proc_re = re.compile(
            r"^\s*(?:Процедура|Procedure|Функция|Function)\s+"
            r"([А-ЯЁа-яёA-Za-z_][А-ЯЁа-яёA-Za-z_0-9]*)",
            re.IGNORECASE | re.UNICODE,
        )
        end_re = re.compile(r"^\s*(?:КонецПроцедуры|EndProcedure|КонецФункции|EndFunction)\b", re.IGNORECASE)
        out: list[Any] = []
        idx = 0
        while idx < len(lines):
            match = proc_re.match(lines[idx])
            if match is None:
                idx += 1
                continue
            end_idx = idx
            scan = idx + 1
            while scan < len(lines):
                if end_re.match(lines[scan]):
                    end_idx = scan
                    break
                scan += 1
            out.append(
                type(
                    "ProcLike",
                    (),
                    {
                        "name": match.group(1),
                        "start_idx": idx,
                        "end_idx": end_idx,
                        "header_col": match.start(1),
                    },
                )()
            )
            idx = max(scan, idx + 1)
        return out

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        procs = (
            list(getattr(context.snapshot, "procs", []) or [])
            if context.snapshot is not None
            else self._fallback_procs(context.lines)
        )
        if not procs:
            procs = self._fallback_procs(context.lines)

        for proc in procs:
            if self._client_only_method(context.lines, int(proc.start_idx)):
                continue
            for idx in range(int(proc.start_idx) + 1, min(int(proc.end_idx) + 1, len(context.lines))):
                clean = _code_mask_without_strings_and_comments(context.lines[idx])
                for match in _BSL183_EXECUTE_EXTERNAL_CODE_RE.finditer(clean):
                    open_paren = clean.find("(", match.start())
                    storage.add_range(
                        code=self.code,
                        line=idx,
                        character=match.start(1),
                        end_line=idx,
                        end_character=_single_line_call_end(clean, open_paren),
                        severity=Severity.ERROR,
                        message="Запрещено выполнение произвольного кода на сервере",
                    )
        return storage.diagnostics


class ExecuteExternalCodeInCommonModuleRule(BsllsDiagnosticRule):
    code = "BSL184"

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        if not common_module_execute_external_code_applicable(context.path):
            return []

        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            clean = _code_mask_without_strings_and_comments(line)
            for match in _BSL183_EXECUTE_EXTERNAL_CODE_RE.finditer(clean):
                open_paren = clean.find("(", match.start())
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=match.start(1),
                    end_line=idx,
                    end_character=_single_line_call_end(clean, open_paren),
                    severity=Severity.WARNING,
                    message=(
                        "Выполнение произвольного кода в общем модуле на сервере "
                        "является потенциальной уязвимостью"
                    ),
                )
        return storage.diagnostics


class OSUsersMethodRule(BsllsDiagnosticRule):
    code = "BSL226"

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            clean = _code_mask_without_strings_and_comments(line)
            for match in _BSL226_OS_USERS_RE.finditer(clean):
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=match.start(1),
                    end_line=idx,
                    end_character=match.end(1),
                    severity=Severity.WARNING,
                    message="Проверить потенциально вредоносное использование метода ПользователиОС",
                )
        return storage.diagnostics


class SetPrivilegedModeRule(BsllsDiagnosticRule):
    code = "BSL247"

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            clean = _code_mask_without_strings_and_comments(line)
            for match in _BSL247_SET_PRIVILEGED_RE.finditer(clean):
                arg = match.group(2).strip().casefold()
                if arg in {"ложь", "false"}:
                    continue
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=match.start(1),
                    end_line=idx,
                    end_character=match.end(1),
                    severity=Severity.WARNING,
                    message="Проверьте установку привилегированного режима",
                )
        return storage.diagnostics


class TempFilesDirRule(BsllsDiagnosticRule):
    code = "BSL250"

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            clean = _code_mask_without_strings_and_comments(line)
            for match in _BSL250_TEMPFILES_RE.finditer(clean):
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=match.start(1),
                    end_line=idx,
                    end_character=match.end(1),
                    severity=Severity.WARNING,
                    message="Не рекомендуемый вызов функции КаталогВременныхФайлов()",
                )
        return storage.diagnostics


class UsingExternalCodeToolsRule(BsllsDiagnosticRule):
    code = "BSL267"

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            code_part = _code_before_comment(line)
            clean = _code_mask_without_strings_and_comments(code_part)
            for match in _BSL267_EXTERNAL_CODE_TOOLS_RE.finditer(clean):
                open_paren = clean.find("(", match.start())
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=match.start(1),
                    end_line=idx,
                    end_character=_call_chain_end(clean, open_paren),
                    severity=Severity.ERROR,
                    message="Запрещено использование возможности выполнения внешнего кода",
                )
        return storage.diagnostics


class UsingSynchronousCallsRule(BsllsDiagnosticRule):
    code = "BSL272"

    @staticmethod
    def _server_only_method(lines: list[str], start_idx: int) -> bool:
        idx = start_idx - 1
        while idx >= 0:
            stripped = lines[idx].strip()
            if not stripped or stripped.startswith("//"):
                idx -= 1
                continue
            if not stripped.startswith("&"):
                return False
            directive = stripped[1:].split()[0].casefold()
            return directive in {
                "насервере",
                "atserver",
                "насерверебезконтекста",
                "atservernocontext",
            }
        return False

    @staticmethod
    def _server_only_lines(context: BsllsDocumentContext) -> set[int]:
        procs = (
            list(getattr(context.snapshot, "procs", []) or [])
            if context.snapshot is not None
            else ExecuteExternalCodeRule._fallback_procs(context.lines)
        )
        if not procs:
            procs = ExecuteExternalCodeRule._fallback_procs(context.lines)
        skipped: set[int] = set()
        for proc in procs:
            if UsingSynchronousCallsRule._server_only_method(context.lines, int(proc.start_idx)):
                skipped.update(range(int(proc.start_idx), min(int(proc.end_idx) + 1, len(context.lines))))
        return skipped

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        if _path_is_bsl272_server_only_module(context.path):
            return []
        storage = DiagnosticStorage(context.path)
        skipped_lines = self._server_only_lines(context)
        clean_lines = [_code_mask_without_strings_and_comments(_code_before_comment(line)) for line in context.lines]
        for idx, clean in enumerate(clean_lines):
            if idx in skipped_lines:
                continue
            for match in _BSL272_SYNC_RE.finditer(clean):
                method_name = context.lines[idx][match.start("name") : match.end("name")]
                replacement = _BSL272_SYNC_REPLACEMENTS.get(method_name.upper(), "")
                open_paren = clean.find("(", match.start("name"))
                end_line, end_character = _multi_line_call_end(clean_lines, idx, open_paren)
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=match.start("name"),
                    end_line=end_line,
                    end_character=end_character,
                    severity=Severity.WARNING,
                    message=(
                        f"Вместо синхронного метода `{method_name}` необходимо "
                        f"использовать `{replacement}`"
                    ),
                )
        return storage.diagnostics


class VirtualTableCallWithoutParametersRule(BsllsDiagnosticRule):
    code = "BSL273"

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for line_no, content_base, _content, head, _ended_query in self._content_lines(context):
            for match in _BSL273_VIRTUAL_TABLE_RE.finditer(head):
                open_match = match.group("open")
                if open_match is None:
                    storage.add_range(
                        code=self.code,
                        message="Обращение к виртуальной таблице без параметров",
                        severity=Severity.WARNING,
                        line=line_no - 1,
                        character=content_base + match.start("name"),
                        end_line=line_no - 1,
                        end_character=content_base + match.end("name"),
                    )
                    continue

                open_idx = match.end("open") - 1
                close_idx = _matching_paren(head, open_idx) - 1
                if close_idx < open_idx:
                    continue
                args = head[open_idx + 1 : close_idx]
                parts = [part.strip() for part in _split_top_level_args(args)]
                if not parts or all(not part for part in parts):
                    violation = True
                elif len(parts) == 1:
                    violation = False
                else:
                    violation = all(not part for part in parts[1:])
                if violation:
                    storage.add_range(
                        code=self.code,
                        message="Обращение к виртуальной таблице без параметров",
                        severity=Severity.WARNING,
                        line=line_no - 1,
                        character=content_base + match.start("name"),
                        end_line=line_no - 1,
                        end_character=content_base + close_idx + 1,
                    )
        return storage.diagnostics

    @staticmethod
    def _content_lines(context: BsllsDocumentContext) -> list[tuple[int, int, str, str, bool]]:
        snapshot = context.snapshot
        if snapshot is not None:
            return [
                (line.line_no, line.content_base, line.content, line.head, line.ended_query)
                for block in snapshot.query_text_blocks
                for line in block.content_lines
            ]

        from onec_hbk_bsl.analysis import diagnostics as _diag

        return [
            content_line
            for start_idx, block_lines in _diag._iter_query_text_blocks(context.lines)
            for content_line in _diag._iter_query_text_content_lines(start_idx, block_lines)
        ]


class WrongUseOfRollbackTransactionMethodRule(BsllsDiagnosticRule):
    code = "BSL277"
    message = "Метод ОтменитьТранзакцию() должен быть в попытке и первым методом блока исключения"

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        root = getattr(getattr(context.tree, "root_node", None), "text", None)
        if not isinstance(root, (bytes, bytearray)):
            return []
        global_calls, call_starts, _proc_nodes, try_nodes = self._runtime_context(context)
        storage = DiagnosticStorage(context.path)
        rollback_in_except_ids: set[int] = set()

        for try_node in try_nodes:
            except_calls = self._except_calls(try_node, global_calls, call_starts)
            if not except_calls:
                continue
            rollback_is_first = str(except_calls[0]["name"]).casefold() in _BSL277_ROLLBACK_NAMES
            for call in except_calls:
                if str(call["name"]).casefold() not in _BSL277_ROLLBACK_NAMES:
                    continue
                rollback_in_except_ids.add(id(call["node"]))
                if not rollback_is_first:
                    self._add_call(storage, call)

        for call in global_calls:
            if str(call["name"]).casefold() not in _BSL277_ROLLBACK_NAMES:
                continue
            if id(call["node"]) in rollback_in_except_ids:
                continue
            self._add_call(storage, call)
        return storage.diagnostics

    @staticmethod
    def _runtime_context(context: BsllsDocumentContext) -> tuple[list[Any], list[int], list[Any], list[Any]]:
        cached = context.runtime_call_context
        if cached is not None:
            return cached
        if context.ts_nodes_for_types and context.global_method_calls_from_nodes:
            nodes = context.ts_nodes_for_types(
                context.tree,
                {"method_call", "procedure_definition", "function_definition", "try_statement"},
            )
            global_calls = context.global_method_calls_from_nodes(nodes["method_call"], context.lines)
            call_starts = [getattr(call["node"], "start_byte", -1) for call in global_calls]
            proc_nodes = nodes["procedure_definition"] + nodes["function_definition"]
            return global_calls, call_starts, proc_nodes, nodes["try_statement"]

        from onec_hbk_bsl.analysis import diagnostics as _diag

        root = context.tree.root_node
        global_calls = _diag._ts_global_method_calls(root, context.lines)
        call_starts = [getattr(call["node"], "start_byte", -1) for call in global_calls]
        try_nodes = [node for node in _diag._ts_walk(root) if getattr(node, "type", None) == "try_statement"]
        return global_calls, call_starts, [], try_nodes

    @staticmethod
    def _except_calls(
        try_node: Any,
        global_calls: list[dict[str, Any]],
        call_starts: list[int],
    ) -> list[dict[str, Any]]:
        children = list(getattr(try_node, "children", []) or [])
        except_idx = next(
            (
                idx
                for idx, child in enumerate(children)
                if getattr(child, "type", None) == "EXCEPT_KEYWORD"
            ),
            None,
        )
        if except_idx is None:
            return []
        endtry_idx = next(
            (
                idx
                for idx, child in enumerate(children)
                if getattr(child, "type", None) == "ENDTRY_KEYWORD"
            ),
            len(children),
        )
        calls: list[dict[str, Any]] = []
        for child in children[except_idx + 1 : endtry_idx]:
            calls.extend(_calls_in_node(child, global_calls, call_starts))
        return calls

    def _add_call(self, storage: DiagnosticStorage, call: dict[str, Any]) -> None:
        storage.add_range(
            code=self.code,
            message=self.message,
            severity=Severity.ERROR,
            line=int(call["line"]) - 1,
            character=int(call["character"]),
            end_line=int(call["line"]) - 1,
            end_character=int(call["end_character"]),
        )


class WrongUseFunctionProceedWithCallRule(BsllsDiagnosticRule):
    code = "BSL276"
    message = (
        "Использовать функцию ПродолжитьВызов() можно только в расширениях "
        "и только в методах с аннотацией &Вместо."
    )

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        root = getattr(getattr(context.tree, "root_node", None), "text", None)
        if not isinstance(root, (bytes, bytearray)):
            return []
        global_calls, _call_starts, _proc_nodes, _try_nodes = (
            WrongUseOfRollbackTransactionMethodRule._runtime_context(context)
        )
        storage = DiagnosticStorage(context.path)
        procs = list(getattr(context.snapshot, "procedures", []) or [])
        if not procs:
            procs = ExecuteExternalCodeRule._fallback_procs(context.lines)

        for call in global_calls:
            if str(call["name"]).casefold() not in _BSL276_PROCEED_NAMES:
                continue
            line = int(call["line"]) - 1
            proc = self._proc_containing_line(procs, line)
            if proc is None:
                continue
            if self._has_around_annotation(context.lines, int(proc.start_idx)):
                continue
            storage.add_range(
                code=self.code,
                message=self.message,
                severity=Severity.ERROR,
                line=line,
                character=int(call["character"]),
                end_line=line,
                end_character=int(call["end_character"]),
            )
        return storage.diagnostics

    @staticmethod
    def _proc_containing_line(procs: list[Any], line: int) -> Any | None:
        for proc in procs:
            if int(proc.start_idx) <= line <= int(proc.end_idx):
                return proc
        return None

    @staticmethod
    def _has_around_annotation(lines: list[str], proc_start_idx: int) -> bool:
        annotation_lines = lines[max(0, proc_start_idx - 3) : proc_start_idx + 1]
        return any(_BSL276_AROUND_ANNOTATION_RE.match(line) for line in annotation_lines)


class DeprecatedCurrentDateRule(BsllsDiagnosticRule):
    code = "BSL097"

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            if _line_comment(line):
                continue
            clean = _code_mask_without_strings_and_comments(line)
            for match in _BSL097_DEPRECATED_CURRENT_DATE_RE.finditer(clean):
                storage.add_range(
                    code=self.code,
                    line=idx,
                    character=match.start(1),
                    end_line=idx,
                    end_character=match.end(1),
                    severity=Severity.ERROR,
                    message='Используйте "ТекущаяДатаСеанса" вместо устаревшего "ТекущаяДата"',
                )
        return storage.diagnostics


class ExtraCommasRule(BsllsDiagnosticRule):
    code = "BSL186"
    _trailing_comma_re = re.compile(r",\s*[)\];]")

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            if _line_comment(line):
                continue
            clean = _code_mask_without_strings_and_comments(line)
            match = self._trailing_comma_re.search(clean)
            if match is None:
                continue
            storage.add_range(
                code=self.code,
                line=idx,
                character=match.start(),
                end_line=idx,
                end_character=match.start() + 1,
                severity=Severity.WARNING,
                message="Не используйте запятые для параметров по умолчанию в конце вызова метода.",
            )
        return storage.diagnostics


class YoLetterUsageRule(BsllsDiagnosticRule):
    code = "BSL279"

    def run(self, context: BsllsDocumentContext) -> list[Diagnostic]:
        storage = DiagnosticStorage(context.path)
        for idx, line in enumerate(context.lines):
            if _line_comment(line):
                continue
            clean = _code_mask_without_strings_and_comments(line)
            for match in _BSL279_IDENTIFIER_RE.finditer(clean):
                storage.add_range(
                    code=self.code,
                    message='В текстах модулях не допускается использовать букву "Ё".',
                    severity=Severity.INFORMATION,
                    line=idx,
                    character=match.start(),
                    end_line=idx,
                    end_character=match.end(),
                )
        return storage.diagnostics
