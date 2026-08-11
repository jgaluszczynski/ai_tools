#!/usr/bin/env node
/**
 * Verify reduce.js output matches har_utils/reduce_har.py on the same fixture.
 */

import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { reduceHarFromObject } from "../reduce.js";

const here = dirname(fileURLToPath(import.meta.url));
const repoRoot = join(here, "..", "..");
const fixturePath = join(here, "fixture.har");

const har = JSON.parse(readFileSync(fixturePath, "utf-8"));
const longBody = "REPEATME".repeat(2500);
har.log.entries[3].response.content.text = longBody;
har.log.entries[3].response.content.size = longBody.length;

const tempDir = mkdtempSync(join(tmpdir(), "harrecorder-parity-"));
const tempHarPath = join(tempDir, "fixture.har");
const pyOutputPath = join(tempDir, "fixture_reduced.json");
writeFileSync(tempHarPath, `${JSON.stringify(har, null, 2)}\n`, "utf-8");

const jsResult = reduceHarFromObject(har, {
  source: "fixture.har",
  redactSecrets: true,
  maxBodyChars: 20_000,
});

execFileSync(
  "poetry",
  ["run", "python", "har_utils/reduce_har.py", tempHarPath],
  { cwd: repoRoot, stdio: "inherit" },
);

const pyResult = JSON.parse(readFileSync(pyOutputPath, "utf-8"));

function stableStringify(value) {
  return JSON.stringify(value, (_key, val) => {
    if (val && typeof val === "object" && !Array.isArray(val)) {
      return Object.keys(val)
        .sort()
        .reduce((acc, key) => {
          acc[key] = val[key];
          return acc;
        }, {});
    }
    return val;
  });
}

if (stableStringify(jsResult) !== stableStringify(pyResult)) {
  writeFileSync(
    join(here, "js_reduced.json"),
    `${JSON.stringify(jsResult, null, 2)}\n`,
  );
  console.error("Parity mismatch: wrote js_reduced.json for diff");
  rmSync(tempDir, { recursive: true, force: true });
  process.exit(1);
}

rmSync(tempDir, { recursive: true, force: true });
console.log(`Parity OK (${jsResult.entry_count} entries)`);
