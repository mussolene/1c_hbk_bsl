/**
 * 1C HBK BSL — VS Code extension (LSP host).
 *
 * Launch strategy (in order):
 *   1. Path explicitly set in onecHbkBsl.serverPath (if not a bare placeholder)
 *   2. Binary bundled in extension's bin/ directory
 *   3. Previously downloaded binary in global storage
 *   4. Prompt to download from GitHub Releases (first activation only)
 *
 * No Python runtime required at run time — only the compiled native binary.
 */

import * as fs from "fs";
import * as https from "https";
import * as os from "os";
import * as path from "path";
import * as vscode from "vscode";
import {
  Executable,
  LanguageClient,
  LanguageClientOptions,
  RevealOutputChannelOn,
  ServerOptions,
  TransportKind,
} from "vscode-languageclient/node";
import {
  CONFIG_SECTION,
  LANGUAGE_CLIENT_ID,
  displayName,
  msgPrefix,
  outputChannelName,
} from "./brand";

/** Shared log channel (also passed to LanguageClient for stderr/LSP trace). */
let logChannel: vscode.OutputChannel | undefined;

let extensionContext: vscode.ExtensionContext | undefined;

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const BINARY_NAME = process.platform === "win32" ? "onec-hbk-bsl.exe" : "onec-hbk-bsl";

/**
 * Release tag on GitHub (`v` + extension version from package.json next to this build).
 * Keeps fallback download aligned with the published VSIX version.
 */
function readExtensionReleaseTag(extensionPath: string): string {
  try {
    const pkgPath = path.join(extensionPath, "package.json");
    const raw = fs.readFileSync(pkgPath, "utf8");
    const pkg = JSON.parse(raw) as { version?: string };
    if (pkg.version && /^\d+\.\d+/.test(pkg.version)) {
      return `v${pkg.version}`;
    }
  } catch {
    // ignore
  }
  return "v0.0.0";
}

/** Map from Node platform+arch → asset filename in GitHub Releases. */
const PLATFORM_ASSETS: Record<string, string> = {
  "darwin-arm64": "onec-hbk-bsl-darwin-arm64",
  "darwin-x64": "onec-hbk-bsl-darwin-x64",
  "linux-x64": "onec-hbk-bsl-linux-x64",
  "win32-x64": "onec-hbk-bsl-win32-x64.exe",
};

// ---------------------------------------------------------------------------
// Module-level state
// ---------------------------------------------------------------------------

let client: LanguageClient | undefined;
let statusBarItem: vscode.StatusBarItem | undefined;

/** Set after a successful `resolveBinaryPath` — used by commands when falling back to CLI (no PATH). */
let resolvedBinaryPath: string | undefined;

// ---------------------------------------------------------------------------
// Activation
// ---------------------------------------------------------------------------

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  extensionContext = context;
  const channel = vscode.window.createOutputChannel(outputChannelName(context));
  logChannel = channel;
  context.subscriptions.push(channel);
  logLine("Extension activating…");

  const brand = displayName(context);

  // Status bar
  statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  statusBarItem.command = `${CONFIG_SECTION}.showStatus`;
  statusBarItem.text = "$(loading~spin) BSL";
  statusBarItem.tooltip = `${brand} — click to show index status`;
  statusBarItem.show();
  context.subscriptions.push(statusBarItem);

  // Resolve binary path (download if needed)
  const binaryPath = await resolveBinaryPath(context);
  if (!binaryPath) {
    const msg =
      `${msgPrefix(context)} could not find or download the server binary. ` +
      `Set ${CONFIG_SECTION}.serverPath manually in settings.`;
    logLine(msg);
    channel.show(true);
    vscode.window.showErrorMessage(msg);
    return;
  }
  resolvedBinaryPath = binaryPath;
  logLine(`binary: ${binaryPath}`);
  logLine(
    `workspaceFolders: ${vscode.workspace.workspaceFolders?.map((f) => f.uri.fsPath).join(", ") ?? "(none)"}`,
  );

  const config = vscode.workspace.getConfiguration(CONFIG_SECTION);
  const serverOptions = buildServerOptions(binaryPath, config);
  const clientOptions = buildClientOptions(channel, context);

  client = new LanguageClient(LANGUAGE_CLIENT_ID, brand, serverOptions, clientOptions);

  // Commands
  context.subscriptions.push(
    vscode.commands.registerCommand(`${CONFIG_SECTION}.reindexWorkspace`, reindexWorkspace),
    vscode.commands.registerCommand(`${CONFIG_SECTION}.reindexCurrentFile`, reindexCurrentFile),
    vscode.commands.registerCommand(`${CONFIG_SECTION}.showStatus`, showStatus),
    vscode.commands.registerCommand(`${CONFIG_SECTION}.showOutput`, () => {
      logChannel?.show(true);
    }),
  );

  try {
    logLine("Starting language client…");
    await client.start();
    logLine("Language client started.");
  } catch (err) {
    const detail = err instanceof Error ? err.stack ?? err.message : String(err);
    logLine(`client.start() failed:\n${detail}`);
    logChannel?.show(true);
    vscode.window.showErrorMessage(
      `${msgPrefix(context)} server failed to start. See Output → "${brand}". ${err instanceof Error ? err.message : err}`,
      "Open Log",
    ).then((choice) => {
      if (choice === "Open Log") { logChannel?.show(true); }
    });
    return;
  }

  updateStatusBar();
  const interval = setInterval(updateStatusBar, 30_000);
  context.subscriptions.push({ dispose: () => clearInterval(interval) });
}

// ---------------------------------------------------------------------------
// Deactivation
// ---------------------------------------------------------------------------

export async function deactivate(): Promise<void> {
  if (client) {
    await client.stop();
    client = undefined;
  }
  resolvedBinaryPath = undefined;
}

// ---------------------------------------------------------------------------
// Binary resolution
// ---------------------------------------------------------------------------

/**
 * Resolve path to the onec-hbk-bsl binary using the priority chain:
 *   settings → bundled → cached download → prompt to download.
 *
 * System PATH is not searched — use an explicit `serverPath` to point at a
 * binary outside the extension (e.g. `pip install` / `uv tool` / local build).
 */
async function resolveBinaryPath(ctx: vscode.ExtensionContext): Promise<string | null> {
  const releaseTag = readExtensionReleaseTag(ctx.extensionPath);
  const config = vscode.workspace.getConfiguration(CONFIG_SECTION);

  // 1. Explicit settings override (highest priority)
  const configured = config.get<string>("serverPath", "");
  if (configured && configured !== "onec-hbk-bsl") {
    if (fs.existsSync(configured) && isExecutable(configured)) {
      return configured;
    }
    vscode.window.showWarningMessage(
      `${msgPrefix(ctx)} configured serverPath "${configured}" not found, falling back.`
    );
  }

  // 2. Bundled binary alongside the extension
  const bundled = path.join(ctx.extensionPath, "bin", BINARY_NAME);
  if (fs.existsSync(bundled) && isExecutable(bundled)) {
    return bundled;
  }

  // 3. Previously downloaded into global storage
  const downloaded = path.join(ctx.globalStorageUri.fsPath, "bin", BINARY_NAME);
  if (fs.existsSync(downloaded) && isExecutable(downloaded)) {
    return downloaded;
  }

  // 4. Offer to download
  const choice = await vscode.window.showInformationMessage(
    `${msgPrefix(ctx)} server binary not found. Download ${releaseTag} automatically?`,
    "Download",
    "Set Path Manually",
  );

  if (choice === "Download") {
    return downloadBinary(downloaded, releaseTag);
  }

  if (choice === "Set Path Manually") {
    const result = await vscode.window.showOpenDialog({
      canSelectMany: false,
      openLabel: "Select onec-hbk-bsl binary",
      filters: process.platform === "win32" ? { Executable: ["exe"] } : {},
    });
    if (result && result[0]) {
      await config.update("serverPath", result[0].fsPath, vscode.ConfigurationTarget.Global);
      return result[0].fsPath;
    }
  }

  return null;
}

function isExecutable(filePath: string): boolean {
  try {
    fs.accessSync(filePath, fs.constants.X_OK);
    return true;
  } catch {
    return false;
  }
}

async function downloadBinary(destPath: string, releaseTag: string): Promise<string | null> {
  const ctx = extensionContext;
  if (!ctx) { return null; }
  const platformKey = `${process.platform}-${os.arch()}`;
  const assetName = PLATFORM_ASSETS[platformKey];

  if (!assetName) {
    vscode.window.showErrorMessage(
      `${msgPrefix(ctx)} no pre-built binary for platform "${platformKey}". ` +
      `Install manually and set ${CONFIG_SECTION}.serverPath.`
    );
    return null;
  }

  const repoOwner = "mussolene";
  const repoName = "1c_hbk_bsl";
  const url = `https://github.com/${repoOwner}/${repoName}/releases/download/${releaseTag}/${assetName}`;

  return vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: `${msgPrefix(ctx)} Downloading server binary (${releaseTag})…`,
      cancellable: false,
    },
    async (progress) => {
      try {
        fs.mkdirSync(path.dirname(destPath), { recursive: true });
        await httpDownload(url, destPath, (pct) => {
          progress.report({ increment: pct, message: `${pct}%` });
        });
        fs.chmodSync(destPath, 0o755);
        vscode.window.showInformationMessage(`${msgPrefix(ctx)} binary downloaded successfully.`);
        return destPath;
      } catch (err) {
        vscode.window.showErrorMessage(`${msgPrefix(ctx)} download failed: ${err}`);
        return null;
      }
    }
  );
}

function httpDownload(
  url: string,
  dest: string,
  onProgress: (pct: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const follow = (u: string) => {
      https.get(u, (res) => {
        // Follow redirects (GitHub releases redirect to cdn)
        if (res.statusCode === 301 || res.statusCode === 302) {
          follow(res.headers.location!);
          return;
        }
        if (res.statusCode !== 200) {
          reject(new Error(`HTTP ${res.statusCode}`));
          return;
        }
        const total = parseInt(res.headers["content-length"] ?? "0", 10);
        let received = 0;
        const out = fs.createWriteStream(dest);
        res.on("data", (chunk: Buffer) => {
          received += chunk.length;
          if (total > 0) {
            onProgress(Math.round((received / total) * 100));
          }
          out.write(chunk);
        });
        res.on("end", () => { out.end(); resolve(); });
        res.on("error", reject);
        out.on("error", reject);
      }).on("error", reject);
    };
    follow(url);
  });
}

// ---------------------------------------------------------------------------
// Server options
// ---------------------------------------------------------------------------

/** Env vars passed into `docker exec -e …` so Docker LSP matches local binary parity. */
const DOCKER_LSP_ENV_KEYS = ["LOG_LEVEL", "INDEX_DB_PATH", "BSL_SELECT", "BSL_IGNORE"] as const;

/**
 * Build `-e KEY=value` pairs for `docker exec` from the same env we would pass to a local process.
 * Only forwards keys the server reads (avoids leaking the full host `process.env` into the container).
 */
function dockerExecEnvArgs(env: NodeJS.ProcessEnv): string[] {
  const out: string[] = [];
  for (const key of DOCKER_LSP_ENV_KEYS) {
    const v = env[key];
    if (v !== undefined && v !== "") {
      out.push("-e", `${key}=${v}`);
    }
  }
  return out;
}

function buildServerOptions(
  binaryPath: string,
  config: vscode.WorkspaceConfiguration,
): ServerOptions {
  const useDocker = config.get<boolean>("useDocker", false);
  const containerName = config.get<string>("dockerContainer", "onec-hbk-bsl-default");
  const indexDb = resolveIndexDbPath(config);
  logLine(
    indexDb.trim()
      ? `INDEX_DB_PATH (env): ${indexDb}`
      : "INDEX_DB_PATH: (unset — server uses .git/onec-hbk-bsl_index.sqlite or ~/.cache/onec-hbk-bsl/…)",
  );

  const env: NodeJS.ProcessEnv = {
    ...process.env,
    LOG_LEVEL: config.get<string>("logLevel", "info"),
  };
  if (indexDb.trim()) {
    env.INDEX_DB_PATH = indexDb;
  }

  const select = config.get<string[]>("diagnostics.select", []);
  const ignore = config.get<string[]>("diagnostics.ignore", []);
  if (select.length > 0) { env["BSL_SELECT"] = select.join(","); }
  if (ignore.length > 0) { env["BSL_IGNORE"] = ignore.join(","); }

  if (useDocker) {
    const envArgs = dockerExecEnvArgs(env);
    const runArgs = ["exec", "-i", ...envArgs, containerName, "onec-hbk-bsl", "--lsp"];
    const debugArgs = [
      "exec",
      "-i",
      ...envArgs,
      containerName,
      "onec-hbk-bsl",
      "--lsp",
      "--log-level",
      "debug",
    ];
    const srv: Executable = {
      command: "docker",
      args: runArgs,
      transport: TransportKind.stdio,
    };
    const debugSrv: Executable = {
      command: "docker",
      args: debugArgs,
      transport: TransportKind.stdio,
    };
    return { run: srv, debug: debugSrv };
  }

  const workspaceRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
  const srv: Executable = {
    command: binaryPath,
    args: ["--lsp"],
    transport: TransportKind.stdio,
    options: {
      env,
      // Helps onefile/relative paths; harmless when unset.
      ...(workspaceRoot ? { cwd: workspaceRoot } : {}),
    },
  };
  return {
    run: srv,
    debug: { ...srv, args: ["--lsp", "--log-level", "debug"] },
  };
}

// ---------------------------------------------------------------------------
// Client options
// ---------------------------------------------------------------------------

function buildClientOptions(
  outputChannel: vscode.OutputChannel,
  ctx: vscode.ExtensionContext,
): LanguageClientOptions {
  return {
    // Include common 1C extension language ids so LSP binds even if another ext. set the mode.
    documentSelector: [
      { scheme: "file", language: "bsl" },
      { scheme: "file", language: "1c-bsl" },
      { scheme: "file", language: "1c" },
      { scheme: "file", pattern: "**/*.bsl" },
      { scheme: "file", pattern: "**/*.os" },
    ],
    outputChannel,
    revealOutputChannelOn: RevealOutputChannelOn.Error,
    initializationFailedHandler: (error) => {
      const text = error instanceof Error ? error.stack ?? error.message : String(error);
      logLine(`LSP initialization failed:\n${text}`);
      outputChannel.show(true);
      vscode.window.showErrorMessage(
        `${msgPrefix(ctx)} LSP init failed — ${error instanceof Error ? error.message : error}`,
        "Open Log",
      ).then((c) => { if (c === "Open Log") { outputChannel.show(true); } });
      return false;
    },
    ...(vscode.workspace.workspaceFolders?.length
      ? {
          synchronize: {
            fileEvents: vscode.workspace.createFileSystemWatcher("**/*.{bsl,os}"),
          },
        }
      : {}),
  };
}

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------

async function reindexWorkspace(): Promise<void> {
  const ctx = extensionContext;
  if (!ctx) { return; }
  const folders = vscode.workspace.workspaceFolders;
  if (!folders || folders.length === 0) {
    vscode.window.showWarningMessage("No workspace folder open.");
    return;
  }
  const root = folders[0].uri.fsPath;

  const runCliIndex = async (hint: string): Promise<void> => {
    const bin = resolvedBinaryPath ?? (await resolveBinaryPath(ctx));
    if (!bin) {
      vscode.window.showErrorMessage(
        `${msgPrefix(ctx)} Cannot index workspace (${hint}). Set ${CONFIG_SECTION}.serverPath to the onec-hbk-bsl binary.`,
      );
      return;
    }
    const terminal = vscode.window.createTerminal(`${displayName(ctx)} Reindex`);
    terminal.sendText(`${shellQuotePath(bin)} --index ${shellQuotePath(root)} --force`);
    terminal.show();
    vscode.window.showInformationMessage(
      `${msgPrefix(ctx)} Started in terminal — full path to binary (not system PATH).`,
    );
  };

  await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: `${msgPrefix(ctx)} Reindexing…`, cancellable: false },
    async () => {
      if (!client) {
        await runCliIndex("LSP client not running");
        return;
      }
      try {
        await client.sendRequest("bsl/reindexWorkspace", { root });
        vscode.window.showInformationMessage(`${msgPrefix(ctx)} Workspace reindex complete.`);
        updateStatusBar();
      } catch {
        await runCliIndex("LSP request failed");
      }
    }
  );
}

async function reindexCurrentFile(): Promise<void> {
  const ctx = extensionContext;
  if (!ctx) { return; }
  const editor = vscode.window.activeTextEditor;
  if (!editor) { vscode.window.showWarningMessage("No active editor."); return; }
  if (!client) { return; }
  try {
    await client.sendRequest("bsl/reindexFile", { filePath: editor.document.uri.fsPath });
    vscode.window.showInformationMessage(
      `${msgPrefix(ctx)} Reindexed ${path.basename(editor.document.uri.fsPath)}.`
    );
  } catch (err) {
    vscode.window.showErrorMessage(`${msgPrefix(ctx)} Reindex failed: ${err}`);
  }
}

async function showStatus(): Promise<void> {
  const ctx = extensionContext;
  if (!ctx) { return; }
  if (!client) { vscode.window.showWarningMessage(`${displayName(ctx)} is not running.`); return; }
  try {
    const status = await client.sendRequest<{ ready: boolean; symbol_count: number; file_count: number }>(
      "bsl/status", {}
    );
    vscode.window.showInformationMessage(
      `BSL Index: ${status.symbol_count} symbols in ${status.file_count} files`
    );
    if (statusBarItem) {
      statusBarItem.text = `$(database) BSL: ${status.symbol_count}`;
    }
  } catch (err) {
    vscode.window.showErrorMessage(`${msgPrefix(ctx)} Status request failed: ${err}`);
  }
}

// ---------------------------------------------------------------------------
// Status bar
// ---------------------------------------------------------------------------

async function updateStatusBar(): Promise<void> {
  const ctx = extensionContext;
  if (!client || !statusBarItem || !ctx) { return; }
  try {
    const status = await client.sendRequest<{ symbol_count: number; file_count: number }>(
      "bsl/status", {}
    );
    statusBarItem.text = `$(database) BSL: ${status.symbol_count}`;
    statusBarItem.tooltip = `${displayName(ctx)}: ${status.symbol_count} symbols in ${status.file_count} files`;
  } catch {
    statusBarItem.text = "$(warning) BSL";
    statusBarItem.tooltip = `${displayName(ctx)}: server not responding`;
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Quote a filesystem path for use in the integrated terminal.
 * Uses POSIX single-quoted form (works in zsh/bash); Windows cmd-style double quotes otherwise.
 */
function shellQuotePath(fsPath: string): string {
  // PowerShell (VS Code default on Windows): single-quoted literal; `'` → `''`
  if (process.platform === "win32") {
    return `'${fsPath.replace(/'/g, "''")}'`;
  }
  // POSIX sh/zsh/bash
  return `'${fsPath.replace(/'/g, `'\\''`)}'`;
}

function logLine(message: string): void {
  const line = `[${new Date().toISOString()}] ${message}`;
  logChannel?.appendLine(line);
  console.log(line);
}

function resolveIndexDbPath(config: vscode.WorkspaceConfiguration): string {
  const configured = (config.get<string>("indexDbPath", "") ?? "").trim();
  if (configured) {
    return configured;
  }
  // Empty: do not set INDEX_DB_PATH — Python resolves to `.git/onec-hbk-bsl_index.sqlite`
  // (inside a git repo) or `~/.cache/onec-hbk-bsl/<hash>/onec-hbk-bsl_index.sqlite`.
  return "";
}
