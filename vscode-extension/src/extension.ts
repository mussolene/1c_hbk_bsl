/**
 * BSL Analyzer VSCode Extension
 *
 * Launch strategy (in order):
 *   1. Binary bundled in extension's bin/ directory
 *   2. Path explicitly set in bslAnalyzer.serverPath
 *   3. bsl-analyzer on system PATH
 *   4. Auto-download from GitHub Releases (first activation only)
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
  ServerOptions,
  TransportKind,
} from "vscode-languageclient/node";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const EXTENSION_ID = "bslAnalyzer";
const CLIENT_ID = "bslAnalyzer";
const CLIENT_NAME = "BSL Analyzer";
const BINARY_NAME = process.platform === "win32" ? "bsl-analyzer.exe" : "bsl-analyzer";

/** GitHub release tag to download when no binary is found locally. */
const RELEASE_TAG = "v0.1.0";

/** Map from Node platform+arch → asset filename in GitHub Releases. */
const PLATFORM_ASSETS: Record<string, string> = {
  "darwin-arm64": "bsl-analyzer-darwin-arm64",
  "darwin-x64":   "bsl-analyzer-darwin-x64",
  "linux-x64":    "bsl-analyzer-linux-x64",
  "win32-x64":    "bsl-analyzer-win32-x64.exe",
};

// ---------------------------------------------------------------------------
// Module-level state
// ---------------------------------------------------------------------------

let client: LanguageClient | undefined;
let statusBarItem: vscode.StatusBarItem | undefined;

// ---------------------------------------------------------------------------
// Activation
// ---------------------------------------------------------------------------

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  // Status bar
  statusBarItem = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 100);
  statusBarItem.command = `${EXTENSION_ID}.showStatus`;
  statusBarItem.text = "$(loading~spin) BSL";
  statusBarItem.tooltip = "BSL Analyzer — click to show index status";
  statusBarItem.show();
  context.subscriptions.push(statusBarItem);

  // Resolve binary path (download if needed)
  const binaryPath = await resolveBinaryPath(context);
  if (!binaryPath) {
    vscode.window.showErrorMessage(
      "BSL Analyzer: could not find or download the server binary. " +
      "Set bslAnalyzer.serverPath manually in settings."
    );
    return;
  }

  const config = vscode.workspace.getConfiguration(EXTENSION_ID);
  const serverOptions = buildServerOptions(binaryPath, config);
  const clientOptions = buildClientOptions();

  client = new LanguageClient(CLIENT_ID, CLIENT_NAME, serverOptions, clientOptions);

  // Commands
  context.subscriptions.push(
    vscode.commands.registerCommand(`${EXTENSION_ID}.reindexWorkspace`, reindexWorkspace),
    vscode.commands.registerCommand(`${EXTENSION_ID}.reindexCurrentFile`, reindexCurrentFile),
    vscode.commands.registerCommand(`${EXTENSION_ID}.showStatus`, showStatus),
  );

  await client.start();

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
}

// ---------------------------------------------------------------------------
// Binary resolution
// ---------------------------------------------------------------------------

/**
 * Resolve path to the bsl-analyzer binary using the priority chain:
 *   settings → bundled → PATH → auto-download.
 *
 * Explicit settings override comes first so developers can point at a
 * freshly-built binary or the Python venv entry-point without repackaging.
 */
async function resolveBinaryPath(context: vscode.ExtensionContext): Promise<string | null> {
  const config = vscode.workspace.getConfiguration(EXTENSION_ID);

  // 1. Explicit settings override (highest priority)
  const configured = config.get<string>("serverPath", "");
  if (configured && configured !== "bsl-analyzer") {
    if (fs.existsSync(configured) && isExecutable(configured)) {
      return configured;
    }
    vscode.window.showWarningMessage(
      `BSL Analyzer: configured serverPath "${configured}" not found, falling back.`
    );
  }

  // 2. Bundled binary alongside the extension
  const bundled = path.join(context.extensionPath, "bin", BINARY_NAME);
  if (fs.existsSync(bundled) && isExecutable(bundled)) {
    return bundled;
  }

  // 3. System PATH
  const onPath = findOnPath(BINARY_NAME);
  if (onPath) {
    return onPath;
  }

  // 4. Previously downloaded into global storage
  const downloaded = path.join(context.globalStorageUri.fsPath, "bin", BINARY_NAME);
  if (fs.existsSync(downloaded) && isExecutable(downloaded)) {
    return downloaded;
  }

  // 5. Offer to download
  const choice = await vscode.window.showInformationMessage(
    `BSL Analyzer server binary not found. Download ${RELEASE_TAG} automatically?`,
    "Download",
    "Set Path Manually",
  );

  if (choice === "Download") {
    return downloadBinary(context, downloaded);
  }

  if (choice === "Set Path Manually") {
    const result = await vscode.window.showOpenDialog({
      canSelectMany: false,
      openLabel: "Select bsl-analyzer binary",
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

function findOnPath(name: string): string | null {
  const dirs = (process.env.PATH ?? "").split(path.delimiter);
  for (const dir of dirs) {
    const full = path.join(dir, name);
    if (fs.existsSync(full) && isExecutable(full)) {
      return full;
    }
  }
  return null;
}

async function downloadBinary(
  _context: vscode.ExtensionContext,
  destPath: string,
): Promise<string | null> {
  const platformKey = `${process.platform}-${os.arch()}`;
  const assetName = PLATFORM_ASSETS[platformKey];

  if (!assetName) {
    vscode.window.showErrorMessage(
      `BSL Analyzer: no pre-built binary for platform "${platformKey}". ` +
      `Install manually and set bslAnalyzer.serverPath.`
    );
    return null;
  }

  const repoOwner = "your-org";
  const repoName = "1c_hbk_bsl";
  const url = `https://github.com/${repoOwner}/${repoName}/releases/download/${RELEASE_TAG}/${assetName}`;

  return vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: `BSL Analyzer: Downloading server binary (${RELEASE_TAG})…`,
      cancellable: false,
    },
    async (progress) => {
      try {
        fs.mkdirSync(path.dirname(destPath), { recursive: true });
        await httpDownload(url, destPath, (pct) => {
          progress.report({ increment: pct, message: `${pct}%` });
        });
        fs.chmodSync(destPath, 0o755);
        vscode.window.showInformationMessage("BSL Analyzer: binary downloaded successfully.");
        return destPath;
      } catch (err) {
        vscode.window.showErrorMessage(`BSL Analyzer: download failed: ${err}`);
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

function buildServerOptions(
  binaryPath: string,
  config: vscode.WorkspaceConfiguration,
): ServerOptions {
  const useDocker = config.get<boolean>("useDocker", false);
  const containerName = config.get<string>("dockerContainer", "bsl-analyzer-default");

  const env: NodeJS.ProcessEnv = {
    ...process.env,
    LOG_LEVEL: config.get<string>("logLevel", "info"),
    INDEX_DB_PATH: resolveIndexDbPath(config),
  };

  const select = config.get<string[]>("diagnostics.select", []);
  const ignore = config.get<string[]>("diagnostics.ignore", []);
  if (select.length > 0) { env["BSL_SELECT"] = select.join(","); }
  if (ignore.length > 0) { env["BSL_IGNORE"] = ignore.join(","); }

  if (useDocker) {
    const srv: Executable = {
      command: "docker",
      args: ["exec", "-i", containerName, "bsl-analyzer", "--lsp"],
      transport: TransportKind.stdio,
    };
    return { run: srv, debug: srv };
  }

  const srv: Executable = {
    command: binaryPath,
    args: ["--lsp"],
    transport: TransportKind.stdio,
    options: { env },
  };
  return {
    run: srv,
    debug: { ...srv, args: ["--lsp", "--log-level", "debug"] },
  };
}

// ---------------------------------------------------------------------------
// Client options
// ---------------------------------------------------------------------------

function buildClientOptions(): LanguageClientOptions {
  return {
    documentSelector: [
      { scheme: "file", language: "bsl" },
      { scheme: "file", pattern: "**/*.bsl" },
      { scheme: "file", pattern: "**/*.os" },
    ],
    synchronize: {
      fileEvents: vscode.workspace.createFileSystemWatcher("**/*.{bsl,os}"),
    },
  };
}

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------

async function reindexWorkspace(): Promise<void> {
  const folders = vscode.workspace.workspaceFolders;
  if (!folders || folders.length === 0) {
    vscode.window.showWarningMessage("No workspace folder open.");
    return;
  }
  const root = folders[0].uri.fsPath;
  await vscode.window.withProgress(
    { location: vscode.ProgressLocation.Notification, title: "BSL Analyzer: Reindexing…", cancellable: false },
    async () => {
      if (!client) { return; }
      try {
        await client.sendRequest("bsl/reindexWorkspace", { root });
        vscode.window.showInformationMessage("BSL Analyzer: Workspace reindex complete.");
        updateStatusBar();
      } catch {
        const terminal = vscode.window.createTerminal("BSL Reindex");
        terminal.sendText(`bsl-analyzer --index "${root}" --force`);
        terminal.show();
      }
    }
  );
}

async function reindexCurrentFile(): Promise<void> {
  const editor = vscode.window.activeTextEditor;
  if (!editor) { vscode.window.showWarningMessage("No active editor."); return; }
  if (!client) { return; }
  try {
    await client.sendRequest("bsl/reindexFile", { filePath: editor.document.uri.fsPath });
    vscode.window.showInformationMessage(
      `BSL Analyzer: Reindexed ${path.basename(editor.document.uri.fsPath)}.`
    );
  } catch (err) {
    vscode.window.showErrorMessage(`BSL Analyzer: Reindex failed: ${err}`);
  }
}

async function showStatus(): Promise<void> {
  if (!client) { vscode.window.showWarningMessage("BSL Analyzer is not running."); return; }
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
    vscode.window.showErrorMessage(`BSL Analyzer: Status request failed: ${err}`);
  }
}

// ---------------------------------------------------------------------------
// Status bar
// ---------------------------------------------------------------------------

async function updateStatusBar(): Promise<void> {
  if (!client || !statusBarItem) { return; }
  try {
    const status = await client.sendRequest<{ symbol_count: number; file_count: number }>(
      "bsl/status", {}
    );
    statusBarItem.text = `$(database) BSL: ${status.symbol_count}`;
    statusBarItem.tooltip = `BSL Analyzer: ${status.symbol_count} symbols in ${status.file_count} files`;
  } catch {
    statusBarItem.text = "$(warning) BSL";
    statusBarItem.tooltip = "BSL Analyzer: server not responding";
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function resolveIndexDbPath(config: vscode.WorkspaceConfiguration): string {
  const configured = config.get<string>("indexDbPath", "");
  if (configured) { return configured; }
  const folders = vscode.workspace.workspaceFolders;
  if (folders && folders.length > 0) {
    return path.join(folders[0].uri.fsPath, "bsl_index.sqlite");
  }
  return "bsl_index.sqlite";
}
