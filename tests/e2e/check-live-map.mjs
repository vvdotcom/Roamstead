import { createRequire } from "node:module";

const require = createRequire(new URL("../../apps/web/package.json", import.meta.url));
const { chromium } = require("playwright-core");
const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH ??
    "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  headless: true,
});
const context = await browser.newContext({ viewport: { width: 1280, height: 720 } });
const page = await context.newPage();
const errors = [];
page.on("console", (message) => {
  if (message.type() === "error" && /Google Maps|MapError|maps\.googleapis/i.test(message.text())) {
    errors.push(message.text().replace(/key=[^&\s]+/gi, "key=[redacted]"));
  }
});
await page.goto(
  process.env.ROAMSTEAD_DEMO_URL ?? "https://roamstead-web-tn7ddsxnmq-uc.a.run.app",
  { waitUntil: "domcontentloaded", timeout: 90000 },
);
await page.getByRole("button", { name: /Demo login/i }).click();
const setup = page.locator(".profile-setup.onboarding");
await setup.waitFor({ state: "visible", timeout: 30000 });
const city = setup.getByLabel("Choose city");
for (let attempt = 0; attempt < 40 && !await city.isEnabled(); attempt += 1) {
  await page.waitForTimeout(500);
}
await city.selectOption("Bangkok");
for (let attempt = 0; attempt < 40 && !await city.isEnabled(); attempt += 1) {
  await page.waitForTimeout(500);
}
await setup.getByRole("button", { name: "Rent", exact: true }).click();
const submit = setup.getByRole("button", { name: "Show my matches" });
for (let attempt = 0; attempt < 40 && !await submit.isEnabled(); attempt += 1) {
  await page.waitForTimeout(500);
}
await submit.click();
await page.getByRole("heading", { name: "Properties matched to your profile" })
  .waitFor({ state: "visible", timeout: 90000 });
await page.waitForTimeout(12000);
console.log(JSON.stringify({ errors: [...new Set(errors)] }, null, 2));
await browser.close();
