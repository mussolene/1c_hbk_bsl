import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as path from "node:path";
import test from "node:test";

import {
  COMMAND_IDS,
  ConfigurationReader,
  buildLocalLaunch,
  buildServerEnvironment,
  dockerExecEnvArgs,
} from "../src/extensionContract";

class TestConfig implements ConfigurationReader {
  constructor(private readonly values: Record<string, unknown>) {}

  get<T>(section: string, defaultValue: T): T {
    return (this.values[section] as T | undefined) ?? defaultValue;
  }
}

test("activation command contract matches the extension manifest", () => {
  const manifest = JSON.parse(
    fs.readFileSync(path.resolve(__dirname, "../../package.json"), "utf8"),
  ) as { contributes: { commands: Array<{ command: string }> } };
  assert.deepEqual(
    manifest.contributes.commands.map((item) => item.command),
    [...COMMAND_IDS],
  );
});

test("settings propagate to server environment, arguments and workspace", () => {
  const config = new TestConfig({
    logLevel: "warning",
    indexDbPath: "/tmp/index.sqlite",
    indexMode: "symbols",
    indexMaxBytes: 4096,
    "diagnostics.enabled": false,
    "diagnostics.select": ["BSL001", "BSL009"],
    "diagnostics.ignore": ["BSL014"],
  });
  const env = buildServerEnvironment(config, { PATH: "/usr/bin" });
  assert.deepEqual(
    {
      LOG_LEVEL: env.LOG_LEVEL,
      INDEX_DB_PATH: env.INDEX_DB_PATH,
      BSL_INDEX_MODE: env.BSL_INDEX_MODE,
      BSL_INDEX_MAX_BYTES: env.BSL_INDEX_MAX_BYTES,
      BSL_DIAGNOSTICS_ENABLED: env.BSL_DIAGNOSTICS_ENABLED,
      BSL_SELECT: env.BSL_SELECT,
      BSL_IGNORE: env.BSL_IGNORE,
    },
    {
      LOG_LEVEL: "warning",
      INDEX_DB_PATH: "/tmp/index.sqlite",
      BSL_INDEX_MODE: "symbols",
      BSL_INDEX_MAX_BYTES: "4096",
      BSL_DIAGNOSTICS_ENABLED: "0",
      BSL_SELECT: "BSL001,BSL009",
      BSL_IGNORE: "BSL014",
    },
  );
  const launch = buildLocalLaunch("/opt/onec-hbk-bsl", "/workspace/project", env);
  assert.equal(launch.command, "/opt/onec-hbk-bsl");
  assert.deepEqual(launch.args, ["lsp"]);
  assert.equal(launch.options.cwd, path.resolve("/workspace/project"));
  assert.equal(launch.options.env, env);
  assert.deepEqual(
    buildLocalLaunch("/opt/onec-hbk-bsl", undefined, env, true).args,
    ["lsp", "--log-level", "debug"],
  );
});

test("docker propagation is allowlisted and deterministic", () => {
  assert.deepEqual(
    dockerExecEnvArgs({
      PATH: "/secret/path",
      LOG_LEVEL: "debug",
      BSL_SELECT: "BSL001",
      BSL_DIAGNOSTICS_ENABLED: "1",
    }),
    [
      "-e",
      "LOG_LEVEL=debug",
      "-e",
      "BSL_SELECT=BSL001",
      "-e",
      "BSL_DIAGNOSTICS_ENABLED=1",
    ],
  );
});
