/**
 * BSL Analyzer VSCode Extension
 *
 * Connects VSCode to the bsl-analyzer LSP server.
 * The server is launched as a child process running `bsl-analyzer --lsp`,
 * or optionally via `docker exec` when useDocker is enabled.
 */

import * as path from "path";
import * as vscode from "vscode";
import {
  LanguageClient,
  LanguageClientOptions,
  ServerOptions,
  TransportKind,
  Executable,
} from "vscode-languageclient/node";

let client: LanguageClient | undefined;

// ---------------------------------------------------------------------------
// Activation
// ---------------------------------------------------------------------------

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  const config = vscode.workspace.getConfiguration("bslAnalyzer");

  const serverOptions = buildServerOptions(config);
  const clientOptions = buildClientOptions();

  client = new LanguageClient(
    "bslAnalyzer",
    "BSL Analyzer",
    serverOptions,
    clientOptions
  );

  // Register commands
  context.subscriptions.push(
    vscode.commands.registerCommand("bslAnalyzer.reindexWorkspace", async () => {
      await reindexWorkspace(config);
    }),
    vscode.commands.registerCommand(
      "bslAnalyzer.reindexCurrentFile",
      async () => {
        await reindexCurrentFile(config);
      }
    ),
    vscode.commands.registerCommand("bslAnalyzer.showStatus", async () => {
      await showStatus();
    })
  );

  // Start the language client (this also launches the server process)
  await client.start();

  vscode.window.showInformationMessage("BSL Analyzer is active.");
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
// Server options
// ---------------------------------------------------------------------------

function buildServerOptions(
  config: vscode.WorkspaceConfiguration
): ServerOptions {
  const useDocker = config.get<boolean>("useDocker", false);
  const containerName = config.get<string>(
    "dockerContainer",
    "bsl-analyzer-default"
  );
  const serverPath = config.get<string>("serverPath", "bsl-analyzer");

  if (useDocker) {
    // Run `docker exec -i <container> bsl-analyzer --lsp` on stdio
    const dockerServer: Executable = {
      command: "docker",
      args: ["exec", "-i", containerName, "bsl-analyzer", "--lsp"],
      transport: TransportKind.stdio,
    };
    return {
      run: dockerServer,
      debug: dockerServer,
    };
  }

  // Use the local binary
  const localServer: Executable = {
    command: serverPath,
    args: ["--lsp"],
    transport: TransportKind.stdio,
    options: {
      env: {
        ...process.env,
        LOG_LEVEL: config.get<string>("logLevel", "info"),
        INDEX_DB_PATH: resolveIndexDbPath(config),
      },
    },
  };
  return {
    run: localServer,
    debug: { ...localServer, args: ["--lsp", "--log-level", "debug"] },
  };
}

// ---------------------------------------------------------------------------
// Client options
// ---------------------------------------------------------------------------

function buildClientOptions(): LanguageClientOptions {
  return {
    // Activate for .bsl and .os files
    documentSelector: [
      { scheme: "file", language: "bsl" },
      { scheme: "file", pattern: "**/*.bsl" },
      { scheme: "file", pattern: "**/*.os" },
    ],
    synchronize: {
      // Watch for changes to .bsl/.os files in the workspace
      fileEvents: vscode.workspace.createFileSystemWatcher("**/*.{bsl,os}"),
    },
  };
}

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------

async function reindexWorkspace(
  config: vscode.WorkspaceConfiguration
): Promise<void> {
  const workspaceFolders = vscode.workspace.workspaceFolders;
  if (!workspaceFolders || workspaceFolders.length === 0) {
    vscode.window.showWarningMessage("No workspace folder open.");
    return;
  }
  const root = workspaceFolders[0].uri.fsPath;
  await vscode.window.withProgress(
    {
      location: vscode.ProgressLocation.Notification,
      title: "BSL Analyzer: Reindexing workspace…",
      cancellable: false,
    },
    async () => {
      // Send a custom LSP request to trigger reindex
      if (client) {
        try {
          await client.sendRequest("bsl/reindexWorkspace", { root });
          vscode.window.showInformationMessage(
            "BSL Analyzer: Workspace reindex complete."
          );
        } catch {
          // Fallback: open terminal and run CLI
          const terminal = vscode.window.createTerminal("BSL Reindex");
          terminal.sendText(`bsl-analyzer --index "${root}" --force`);
          terminal.show();
        }
      }
    }
  );
}

async function reindexCurrentFile(
  config: vscode.WorkspaceConfiguration
): Promise<void> {
  const editor = vscode.window.activeTextEditor;
  if (!editor) {
    vscode.window.showWarningMessage("No active editor.");
    return;
  }
  const filePath = editor.document.uri.fsPath;
  if (client) {
    try {
      await client.sendRequest("bsl/reindexFile", { filePath });
      vscode.window.showInformationMessage(
        `BSL Analyzer: Reindexed ${path.basename(filePath)}.`
      );
    } catch (err) {
      vscode.window.showErrorMessage(`BSL Analyzer: Reindex failed: ${err}`);
    }
  }
}

async function showStatus(): Promise<void> {
  if (!client) {
    vscode.window.showWarningMessage("BSL Analyzer is not running.");
    return;
  }
  try {
    const status = await client.sendRequest<{
      ready: boolean;
      symbol_count: number;
      file_count: number;
      last_commit?: string;
    }>("bsl/status", {});
    vscode.window.showInformationMessage(
      `BSL Index: ${status.symbol_count} symbols in ${status.file_count} files` +
        (status.last_commit ? ` (commit ${status.last_commit.substring(0, 8)})` : "")
    );
  } catch (err) {
    vscode.window.showErrorMessage(`BSL Analyzer: Status request failed: ${err}`);
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function resolveIndexDbPath(
  config: vscode.WorkspaceConfiguration
): string {
  const configured = config.get<string>("indexDbPath", "");
  if (configured) {
    return configured;
  }
  const folders = vscode.workspace.workspaceFolders;
  if (folders && folders.length > 0) {
    return path.join(folders[0].uri.fsPath, "bsl_index.sqlite");
  }
  return "bsl_index.sqlite";
}
