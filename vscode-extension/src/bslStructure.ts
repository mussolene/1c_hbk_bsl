export type BslStructureKind = "procedure" | "function" | "region";

export interface BslStructureItem {
  kind: BslStructureKind;
  name: string;
  detail: string;
  startLine: number;
  startCharacter: number;
  endLine: number;
  endCharacter: number;
  selectionStartCharacter: number;
  children: BslStructureItem[];
}

export interface BslFoldingItem {
  startLine: number;
  endLine: number;
  kind?: "region";
}

const METHOD_START_RE =
  /^(\s*)(Процедура|Функция|Procedure|Function)\s+([А-ЯЁа-яёA-Za-z_][А-ЯЁа-яёA-Za-z0-9_]*)(?=\s|\()/i;
const PROCEDURE_END_RE = /^\s*(КонецПроцедуры|EndProcedure)(?=\s|;|$)/i;
const FUNCTION_END_RE = /^\s*(КонецФункции|EndFunction)(?=\s|;|$)/i;
const REGION_START_RE = /^\s*#(?:Область|Region)(?=\s|$)\s*(.*)$/i;
const REGION_END_RE = /^\s*#(?:КонецОбласти|EndRegion)(?=\s|$)/i;
const FOLD_MARKER_START_RE = /^\s*(?:#(?:Вставка|Удаление)(?=\s|$)|\/\/\{)/i;
const FOLD_MARKER_END_RE = /^\s*(?:#Конец(?:Вставки|Удаления)(?=\s|$)|\/\/\})/i;
const IF_START_RE = /^\s*(Если|If)(?=\s|$)/i;
const IF_END_RE = /^\s*(КонецЕсли|EndIf)(?=\s|;|$)/i;
const LOOP_START_RE =
  /^\s*(Для\s+Каждого|Для|Пока|For\s+Each|For|While)(?=\s|$)/i;
const LOOP_END_RE = /^\s*(КонецЦикла|EndDo)(?=\s|;|$)/i;
const TRY_START_RE = /^\s*(Попытка|Try)(?=\s|$)/i;
const TRY_END_RE = /^\s*(КонецПопытки|EndTry)(?=\s|;|$)/i;

interface StackItem {
  item: BslStructureItem;
  parent: BslStructureItem[];
}

export function parseBslStructure(text: string): BslStructureItem[] {
  const root: BslStructureItem[] = [];
  const regionStack: StackItem[] = [];
  const methodStack: BslStructureItem[] = [];
  const lines = text.split(/\r\n|\r|\n/);

  for (let lineNo = 0; lineNo < lines.length; lineNo += 1) {
    const line = lines[lineNo];
    if (isFullLineComment(line)) {
      continue;
    }
    const regionStart = REGION_START_RE.exec(line);
    if (regionStart) {
      const name = regionStart[1]?.trim() || "Область";
      const item = makeItem("region", name, line.trim(), lineNo, firstNonWhitespace(line), line);
      const parent = regionStack.length > 0 ? regionStack[regionStack.length - 1].item.children : root;
      parent.push(item);
      regionStack.push({ item, parent });
      continue;
    }

    if (REGION_END_RE.test(line)) {
      const open = regionStack.pop();
      if (open) {
        closeItem(open.item, lineNo, line);
      }
      continue;
    }

    const methodStart = METHOD_START_RE.exec(line);
    if (methodStart) {
      const keyword = methodStart[2].toLocaleLowerCase();
      const kind: BslStructureKind =
        keyword === "функция" || keyword === "function" ? "function" : "procedure";
      const name = methodStart[3];
      const item = makeItem(
        kind,
        name,
        line.trim(),
        lineNo,
        methodStart.index + methodStart[0].lastIndexOf(name),
        line,
      );
      const parent = regionStack.length > 0 ? regionStack[regionStack.length - 1].item.children : root;
      parent.push(item);
      methodStack.push(item);
      continue;
    }

    if (PROCEDURE_END_RE.test(line)) {
      closeLastMethod(methodStack, "procedure", lineNo, line);
      continue;
    }
    if (FUNCTION_END_RE.test(line)) {
      closeLastMethod(methodStack, "function", lineNo, line);
    }
  }

  const lastLine = Math.max(0, lines.length - 1);
  const lastText = lines[lastLine] ?? "";
  for (const method of methodStack) {
    closeItem(method, lastLine, lastText);
  }
  for (const region of regionStack) {
    closeItem(region.item, lastLine, lastText);
  }

  return root;
}

export function parseBslFoldingRanges(text: string): BslFoldingItem[] {
  const ranges: BslFoldingItem[] = [];
  const stack: Array<{ type: "if" | "loop" | "try"; line: number }> = [];
  const markerStack: number[] = [];
  const lines = text.split(/\r\n|\r|\n/);

  const structure = parseBslStructure(text);
  collectStructureFolds(structure, ranges);

  for (let lineNo = 0; lineNo < lines.length; lineNo += 1) {
    const line = lines[lineNo];
    if (FOLD_MARKER_START_RE.test(line)) {
      markerStack.push(lineNo);
      continue;
    }
    if (FOLD_MARKER_END_RE.test(line)) {
      const startLine = markerStack.pop();
      if (startLine !== undefined && lineNo > startLine) {
        ranges.push({ startLine, endLine: lineNo, kind: "region" });
      }
      continue;
    }
    if (isFullLineComment(line)) {
      continue;
    }

    if (IF_END_RE.test(line)) {
      closeBlock(stack, ranges, "if", lineNo);
      continue;
    }
    if (LOOP_END_RE.test(line)) {
      closeBlock(stack, ranges, "loop", lineNo);
      continue;
    }
    if (TRY_END_RE.test(line)) {
      closeBlock(stack, ranges, "try", lineNo);
      continue;
    }

    if (IF_START_RE.test(line)) {
      stack.push({ type: "if", line: lineNo });
      continue;
    }
    if (LOOP_START_RE.test(line)) {
      stack.push({ type: "loop", line: lineNo });
      continue;
    }
    if (TRY_START_RE.test(line)) {
      stack.push({ type: "try", line: lineNo });
    }
  }

  return ranges.sort((left, right) => left.startLine - right.startLine || left.endLine - right.endLine);
}

function makeItem(
  kind: BslStructureKind,
  name: string,
  detail: string,
  line: number,
  selectionStartCharacter: number,
  lineText: string,
): BslStructureItem {
  return {
    kind,
    name,
    detail,
    startLine: line,
    startCharacter: firstNonWhitespace(lineText),
    endLine: line,
    endCharacter: lineText.length,
    selectionStartCharacter,
    children: [],
  };
}

function closeLastMethod(
  stack: BslStructureItem[],
  kind: "procedure" | "function",
  line: number,
  lineText: string,
): void {
  for (let i = stack.length - 1; i >= 0; i -= 1) {
    if (stack[i].kind === kind) {
      const [item] = stack.splice(i, 1);
      closeItem(item, line, lineText);
      return;
    }
  }
}

function closeItem(item: BslStructureItem, line: number, lineText: string): void {
  item.endLine = Math.max(item.startLine, line);
  item.endCharacter = lineText.length;
}

function firstNonWhitespace(line: string): number {
  const match = /\S/.exec(line);
  return match ? match.index : 0;
}

function isFullLineComment(line: string): boolean {
  return /^\s*\/\//.test(line);
}

function collectStructureFolds(items: BslStructureItem[], out: BslFoldingItem[]): void {
  for (const item of items) {
    if (item.endLine > item.startLine) {
      out.push({
        startLine: item.startLine,
        endLine: item.endLine,
        kind: item.kind === "region" ? "region" : undefined,
      });
    }
    collectStructureFolds(item.children, out);
  }
}

function closeBlock(
  stack: Array<{ type: "if" | "loop" | "try"; line: number }>,
  out: BslFoldingItem[],
  type: "if" | "loop" | "try",
  endLine: number,
): void {
  for (let i = stack.length - 1; i >= 0; i -= 1) {
    if (stack[i].type === type) {
      const [open] = stack.splice(i, 1);
      if (endLine > open.line) {
        out.push({ startLine: open.line, endLine });
      }
      return;
    }
  }
}
