const assert = require("assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { spawnSync } = require("child_process");

const root = path.resolve(__dirname, "..");
const verifier = path.join(root, "scripts", "verify_page.cjs");
const blank = path.join(__dirname, "fixtures", "blank-viewer.html");
const triangle = path.join(__dirname, "fixtures", "triangle-viewer.html");
const screenshots = fs.mkdtempSync(path.join(os.tmpdir(), "preview-stl-verify-"));

try {
  const positive = spawnSync(process.execPath, [verifier, triangle, screenshots], {
    encoding: "utf8",
    env: process.env,
  });
  const positiveOutput = positive.stdout + positive.stderr;
  assert.strictEqual(positive.status, 0, positiveOutput);
  assert.match(positiveOutput, /errors: none/, positiveOutput);

  const negative = spawnSync(process.execPath, [verifier, blank, screenshots], {
    encoding: "utf8",
    env: process.env,
  });
  const negativeOutput = negative.stdout + negative.stderr;
  assert.strictEqual(negative.status, 1, negativeOutput);
  assert.match(negativeOutput, /rendered 0 non-background pixels/, negativeOutput);
  console.log("controls: rendered triangle accepted; blank WebGL viewer rejected");
} finally {
  fs.rmSync(screenshots, { recursive: true, force: true });
}
