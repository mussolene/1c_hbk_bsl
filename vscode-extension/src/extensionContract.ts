import * as path from "path";

export const COMMAND_IDS = [
  "onecHbkBsl.reindexWorkspace",
  "onecHbkBsl.reindexCurrentFile",
  "onecHbkBsl.showStatus",
  "onecHbkBsl.showOutput",
] as const;

export interface ConfigurationReader {
  get<T>(section: string, defaultValue: T): T;
}

export function buildServerEnvironment(
  config: ConfigurationReader,
  baseEnv: NodeJS.ProcessEnv = process.env,
): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = {
    ...baseEnv,
    LOG_LEVEL: config.get<string>("logLevel", "info"),
    BSL_DIAGNOSTICS_ENABLED: config.get<boolean>("diagnostics.enabled", true) ? "1" : "0",
  };
  const indexDb = config.get<string>("indexDbPath", "").trim();
  if (indexDb) {
    env.INDEX_DB_PATH = indexDb;
  }
  const indexMode = config.get<string>("indexMode", "project");
  if (indexMode !== "project") {
    env.BSL_INDEX_MODE = indexMode;
  }
  const indexMaxBytes = config.get<number>("indexMaxBytes", -1);
  if (indexMaxBytes >= 0) {
    env.BSL_INDEX_MAX_BYTES = String(indexMaxBytes);
  }
  const select = config.get<string[]>("diagnostics.select", []);
  const ignore = config.get<string[]>("diagnostics.ignore", []);
  if (select.length > 0) {
    env.BSL_SELECT = select.join(",");
  }
  if (ignore.length > 0) {
    env.BSL_IGNORE = ignore.join(",");
  }
  return env;
}

const DOCKER_LSP_ENV_KEYS = [
  "LOG_LEVEL",
  "INDEX_DB_PATH",
  "BSL_SELECT",
  "BSL_IGNORE",
  "BSL_DIAGNOSTICS_ENABLED",
  "BSL_INDEX_MODE",
  "BSL_INDEX_MAX_BYTES",
] as const;

export function dockerExecEnvArgs(env: NodeJS.ProcessEnv): string[] {
  const out: string[] = [];
  for (const key of DOCKER_LSP_ENV_KEYS) {
    const value = env[key];
    if (value !== undefined && value !== "") {
      out.push("-e", `${key}=${value}`);
    }
  }
  return out;
}

export interface LocalLaunch {
  command: string;
  args: string[];
  options: {
    env: NodeJS.ProcessEnv;
    cwd?: string;
  };
}

export function buildLocalLaunch(
  binaryPath: string,
  workspaceRoot: string | undefined,
  env: NodeJS.ProcessEnv,
  debug = false,
): LocalLaunch {
  return {
    command: binaryPath,
    args: debug ? ["lsp", "--log-level", "debug"] : ["lsp"],
    options: {
      env,
      ...(workspaceRoot ? { cwd: path.resolve(workspaceRoot) } : {}),
    },
  };
}
