// Renders docs/brand/*.svg to PNG with Playwright's Chromium (already installed for the browser tests):
//   cd ui && node scripts/make-logo.mjs
import { chromium } from "@playwright/test";
import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const brand = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "docs", "brand");
const browser = await chromium.launch();
async function render(svgFile, pngFile, width, height, background = null) {
  const page = await browser.newPage({ viewport: { width, height }, deviceScaleFactor: 1 });
  const svg = readFileSync(join(brand, svgFile), "utf8");
  await page.setContent(`<body style="margin:0;background:${background ?? "transparent"}">${svg.replace("<svg ", `<svg width="${width}" height="${height}" `)}</body>`);
  writeFileSync(join(brand, pngFile), await page.screenshot({ omitBackground: background === null }));
  await page.close();
}
await render("obsergent-mark.svg", "obsergent-512.png", 512, 512);
await render("obsergent-mark.svg", "obsergent-180.png", 180, 180, "#0a0f1e"); // iOS touch icon needs a solid background
await render("obsergent-mark.svg", "obsergent-32.png", 32, 32);
await render("obsergent-logo.svg", "obsergent-logo.png", 840, 192, "#ffffff");
await browser.close();
console.log("wrote the PNGs in", brand);
