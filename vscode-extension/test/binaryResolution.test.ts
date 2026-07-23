import assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import test from "node:test";

import { findExecutableOnPath, isExecutable } from "../src/binaryResolution";

test("custom executable path is accepted", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "onec-hbk-bsl-custom-"));
  const executable = path.join(root, process.platform === "win32" ? "custom.cmd" : "custom");
  fs.writeFileSync(executable, process.platform === "win32" ? "@echo off\r\n" : "#!/bin/sh\n");
  if (process.platform !== "win32") {
    fs.chmodSync(executable, 0o755);
  }
  assert.equal(isExecutable(executable), true);
});

test("PATH resolution selects the bundled command candidate deterministically", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "onec-hbk-bsl-path-"));
  const command = process.platform === "win32" ? "onec-hbk-bsl.cmd" : "onec-hbk-bsl";
  const executable = path.join(root, command);
  fs.writeFileSync(executable, process.platform === "win32" ? "@echo off\r\n" : "#!/bin/sh\n");
  if (process.platform !== "win32") {
    fs.chmodSync(executable, 0o755);
  }
  assert.equal(findExecutableOnPath(command, root), executable);
  assert.equal(findExecutableOnPath(command, ""), null);
});
