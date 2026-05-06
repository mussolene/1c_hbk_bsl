import * as fs from "fs";
import * as path from "path";

export const SERVER_COMMAND = process.platform === "win32" ? "onec-hbk-bsl.exe" : "onec-hbk-bsl";
export const SERVER_PATH_PLACEHOLDERS = new Set(["", "onec-hbk-bsl", "onec-hbk-bsl.exe"]);

export function isExecutable(filePath: string): boolean {
  if (!fs.existsSync(filePath)) {
    return false;
  }
  // Windows has no Unix execute bit; X_OK is unreliable for .exe (often fails and blocks LSP).
  if (process.platform === "win32") {
    const lower = filePath.toLowerCase();
    return lower.endsWith(".exe") || lower.endsWith(".cmd") || lower.endsWith(".bat");
  }
  try {
    fs.accessSync(filePath, fs.constants.X_OK);
    return true;
  } catch {
    return false;
  }
}

export function findExecutableOnPath(
  command = SERVER_COMMAND,
  envPath = process.env.PATH ?? "",
): string | null {
  if (path.isAbsolute(command) || command.includes(path.sep)) {
    return isExecutable(command) ? command : null;
  }

  const pathExt = process.platform === "win32"
    ? (process.env.PATHEXT ?? ".EXE;.CMD;.BAT;.COM").split(";")
    : [""];
  const candidates = command.includes(".")
    ? [command]
    : pathExt.map((ext) => `${command}${ext.toLowerCase()}`);

  for (const dir of envPath.split(path.delimiter)) {
    if (!dir) {
      continue;
    }
    for (const candidate of candidates) {
      const fullPath = path.join(dir, candidate);
      if (isExecutable(fullPath)) {
        return fullPath;
      }
    }
  }
  return null;
}
