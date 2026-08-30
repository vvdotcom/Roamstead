import { createRequire } from "node:module";

const require = createRequire(new URL("../../apps/web/package.json", import.meta.url));
const { chromium } = require("playwright-core");
const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH ?? "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  headless: true,
});
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
const mapErrors = [];
page.on("console", (message) => {
  if (message.type() === "error" && /Google Maps|MapError|maps\.googleapis/i.test(message.text())) {
    mapErrors.push(message.text().replace(/key=[^&\s]+/gi, "key=[redacted]"));
  }
});
const url = process.env.ROAMSTEAD_DEMO_URL ?? "https://roamstead-web-113080100961.us-central1.run.app";

await page.goto(url, { waitUntil: "networkidle", timeout: 90000 });
await page.getByRole("heading", { name: /Find your place in/i }).waitFor();
if (process.env.CAPTURE === "1") {
  await page.screenshot({ path: "artifacts/public-landing-live.png", fullPage: true });
}
await page.getByRole("button", { name: /Demo login/i }).click();
await page.getByRole("heading", { name: /Where in HCMC/i }).waitFor();

for (const city of ["Bangkok", "Kuala Lumpur"]) {
  await page.getByLabel("Choose city").selectOption(city);
  await page.getByRole("heading", { name: new RegExp(`Where in ${city}`) }).waitFor();
  await page.getByRole("button", { name: /Set up my profile/i }).click();
  await page.getByRole("button", { name: /Show my matches/i }).waitFor({ timeout: 90000 });
  await page.getByRole("button", { name: /Show my matches/i }).click();
  await page.getByRole("heading", { name: "Properties matched to your profile" }).waitFor({ timeout: 90000 });
  await page.locator(".listing-card").first().waitFor({ timeout: 90000 });
  await page.waitForTimeout(7000);
  const cards = await page.locator(".listing-card").count();
  const selectedCity = await page.getByLabel("Choose city").inputValue();
  const borrowedClarification = await page.locator(".adaptive-clarification").count();
  if (selectedCity !== city || cards < 8 || borrowedClarification) {
    throw new Error(`${city} rendered ${cards} cards with selected market ${selectedCity} and ${borrowedClarification} borrowed clarifications`);
  }
}

const mapState = await page.locator(".google-listing-map").evaluate((element) => ({
  childElements: element.querySelectorAll("*").length,
  images: element.querySelectorAll("img").length,
  canvases: element.querySelectorAll("canvas").length,
  text: element.textContent?.trim() || "",
}));
if (mapErrors.length || mapState.childElements < 10) {
  throw new Error(`Google Map did not render: ${JSON.stringify({ mapErrors, mapState })}`);
}

if (process.env.CAPTURE === "1") {
  await page.screenshot({ path: "artifacts/expansion-markets-live.png", fullPage: true });
}
console.log("Public landing, demo login, Bangkok, and Kuala Lumpur flows passed.");
await browser.close();
