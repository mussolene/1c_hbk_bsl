import * as vscode from "vscode";

/** Configuration section — must match contributes.configuration keys in package.json */
export const CONFIG_SECTION = "onecHbkBsl";

/** Human-readable product name from manifest (single source of truth). */
export function displayName(ctx: vscode.ExtensionContext): string {
  const pkg = ctx.extension.packageJSON as { displayName?: string };
  return pkg.displayName ?? "1C HBK BSL";
}

export function outputChannelName(ctx: vscode.ExtensionContext): string {
  return displayName(ctx);
}

/** Prefix for user-facing messages, e.g. "1C HBK BSL: …" */
export function msgPrefix(ctx: vscode.ExtensionContext): string {
  return `${displayName(ctx)}:`;
}

/** Language client id (internal, stable). */
export const LANGUAGE_CLIENT_ID = "onecHbkBsl";
