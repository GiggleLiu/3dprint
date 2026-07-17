// Headless verification of a viewer page: open it, click through every
// scene, assert that WebGL rendered meaningful pixels, screenshot each,
// and fail on any console/page/render error.
//
// Usage:  NODE_PATH=$(npm root -g) node verify_page.cjs viewer.html out_dir
// Needs a global playwright install (npm i -g playwright && npx playwright
// install chromium). CommonJS on purpose: `node script.cjs` with NODE_PATH
// works everywhere; ESM import of a globally installed package does not.
const path = require("path");
const fs = require("fs");
const { chromium } = require("playwright");

async function canvasPixelStats(page) {
  return page.evaluate(() => {
    const canvas = document.querySelector("canvas");
    if (!canvas) throw new Error("viewer has no canvas");
    const gl = canvas.getContext("webgl");
    if (!gl) throw new Error("WebGL context is unavailable");
    gl.finish();
    const w = gl.drawingBufferWidth, h = gl.drawingBufferHeight;
    const pixels = new Uint8Array(w * h * 4);
    gl.readPixels(0, 0, w, h, gl.RGBA, gl.UNSIGNED_BYTE, pixels);
    const error = gl.getError();
    if (error !== gl.NO_ERROR) throw new Error(`WebGL readPixels failed: ${error}`);

    const clear = Array.from(gl.getParameter(gl.COLOR_CLEAR_VALUE),
                             (value) => Math.round(value * 255));
    let nonBackground = 0;
    for (let i = 0; i < pixels.length; i += 4) {
      const difference = Math.abs(pixels[i] - clear[0])
        + Math.abs(pixels[i + 1] - clear[1])
        + Math.abs(pixels[i + 2] - clear[2])
        + Math.abs(pixels[i + 3] - clear[3]);
      if (difference > 8) nonBackground++;
    }
    return { width: w, height: h, nonBackground };
  });
}

async function saveCanvas(page, output) {
  const png = await page.evaluate(() => {
    const canvas = document.querySelector("canvas");
    if (!canvas) throw new Error("viewer has no canvas");
    return canvas.toDataURL("image/png").split(",", 2)[1];
  });
  fs.writeFileSync(output, Buffer.from(png, "base64"));
}

(async () => {
  const [html, outDir] = process.argv.slice(2);
  if (!html || !outDir) {
    console.error("usage: node verify_page.cjs <viewer.html> <screenshot-dir>");
    process.exit(2);
  }
  fs.mkdirSync(outDir, { recursive: true });
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  const errors = [];
  const renders = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  await page.goto("file://" + path.resolve(html));
  await page.waitForTimeout(1500); // first scene decompresses async
  const scenes = page.locator(".scene");
  const n = await scenes.count();
  if (n === 0) errors.push("viewer has no scenes");
  for (let i = 0; i < n; i++) {
    await scenes.nth(i).click();
    await page.waitForTimeout(700);
    try {
      const stats = await canvasPixelStats(page);
      const minimum = Math.max(64, Math.floor(stats.width * stats.height * 0.0001));
      renders.push(stats.nonBackground);
      if (stats.nonBackground < minimum) {
        errors.push(
          `scene ${i} rendered ${stats.nonBackground} non-background pixels `
          + `(minimum ${minimum})`
        );
      }
    } catch (error) {
      renders.push("error");
      errors.push(`scene ${i} render probe failed: ${error}`);
    }
    try {
      await saveCanvas(page, `${outDir}/scene${String(i).padStart(2, "0")}.png`);
    } catch (error) {
      errors.push(`scene ${i} canvas capture failed: ${error}`);
    }
  }
  console.log("scenes:", n, "| rendered pixels:", renders.join(", "),
              "| errors:", errors.length ? errors : "none");
  await browser.close();
  process.exit(errors.length ? 1 : 0);
})();
