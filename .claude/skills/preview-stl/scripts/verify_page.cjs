// Headless verification of a viewer page: open it, click through every
// scene, screenshot each, and fail on any console/page error.
//
// Usage:  NODE_PATH=$(npm root -g) node verify_page.cjs viewer.html out_dir
// Needs a global playwright install (npm i -g playwright && npx playwright
// install chromium). CommonJS on purpose: `node script.cjs` with NODE_PATH
// works everywhere; ESM import of a globally installed package does not.
const path = require("path");
const { chromium } = require("playwright");

(async () => {
  const [html, outDir] = process.argv.slice(2);
  if (!html || !outDir) {
    console.error("usage: node verify_page.cjs <viewer.html> <screenshot-dir>");
    process.exit(2);
  }
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  await page.goto("file://" + path.resolve(html));
  await page.waitForTimeout(1500); // first scene decompresses async
  const scenes = page.locator(".scene");
  const n = await scenes.count();
  for (let i = 0; i < n; i++) {
    await scenes.nth(i).click();
    await page.waitForTimeout(700);
    await page.screenshot({ path: `${outDir}/scene${String(i).padStart(2, "0")}.png` });
  }
  console.log("scenes:", n, "| errors:", errors.length ? errors : "none");
  await browser.close();
  process.exit(errors.length ? 1 : 0);
})();
