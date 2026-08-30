import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(new URL("../../apps/web/package.json", import.meta.url));
const { chromium } = require("playwright-core");
const url = process.env.ROAMSTEAD_URL ?? "https://roamstead-web-113080100961.us-central1.run.app";
const chrome = process.env.CHROME_PATH ?? "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";
const browser = await chromium.launch({ executablePath: chrome, headless: true });
const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
const errors = [];
page.on("pageerror", (error) => errors.push(error.message));
page.on("response", (response) => {
  if (response.status() >= 400 && !response.url().endsWith("/favicon.ico")) {
    errors.push(`${response.status()} ${response.url()}`);
  }
});
page.on("console", (message) => {
  if (message.type() === "error" && !message.text().includes("404")) errors.push(message.text());
});
await page.goto(url, { waitUntil: "domcontentloaded", timeout: 90000 });
await page.getByRole("button", { name: /Demo login/i }).click();
await page.getByRole("heading", { name: /What does the right home look like/i }).waitFor();
const select = page.getByLabel("Choose city");
for (const [city, slug] of [
  ["Ho Chi Minh City", "ho-chi-minh-city"],
  ["Bangkok", "bangkok"],
  ["Kuala Lumpur", "kuala-lumpur"],
]) {
  await select.selectOption(city);
  const card = page.locator(`.city-orientation[data-city="${slug}"]`);
  await card.waitFor({ state: "visible", timeout: 30000 });
  await card.getByText("veo-3.1-lite-generate-preview", { exact: true }).waitFor();
  await card.getByText("gemini-3.1-flash-tts-preview", { exact: true }).waitFor();
  await page.waitForFunction(
    (selector) => {
      const video = document.querySelector(selector);
      return video instanceof HTMLVideoElement && video.readyState >= 2 && video.videoWidth > 0;
    },
    `.city-orientation[data-city="${slug}"] video`,
    { timeout: 60000 },
  );
}
fs.mkdirSync("artifacts/screenshots", { recursive: true });
await page.screenshot({
  path: path.resolve("artifacts/screenshots/city-orientation-kuala-lumpur.png"),
  fullPage: true,
});
console.log(JSON.stringify({ city_count: 3, errors }, null, 2));
await browser.close();
if (errors.length) process.exitCode = 1;
