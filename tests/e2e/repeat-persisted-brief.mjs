import { createRequire } from "node:module";

const require = createRequire(new URL("../../apps/web/package.json", import.meta.url));
const { chromium } = require("playwright-core");
const profileId = process.env.ROAMSTEAD_GOLDEN_PROFILE_ID;
const mode = process.env.ROAMSTEAD_GOLDEN_MODE ?? "BUY";
const repetitions = Number(process.env.ROAMSTEAD_GOLDEN_REPETITIONS ?? "20");

if (!profileId) throw new Error("Set ROAMSTEAD_GOLDEN_PROFILE_ID to a profile with a successful persisted Gemma brief.");

const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH ?? "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  headless: true,
});

for (let iteration = 1; iteration <= repetitions; iteration += 1) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.addInitScript(({ profileId, mode }) => {
    localStorage.setItem("roamstead_profile_id", profileId);
    localStorage.setItem("roamstead_housing_mode", mode);
  }, { profileId, mode });
  const page = await context.newPage();
  await page.goto("http://127.0.0.1:3000");
  await page.getByRole("button", { name: "Resume saved brief" }).waitFor({ timeout: 30_000 });
  await page.getByRole("button", { name: "Resume saved brief" }).click();
  await page.getByRole("heading", { name: "Ho Chi Minh City Decision Brief" }).waitFor();
  if (await page.locator(".brief-properties article").count() !== 3) throw new Error(`Run ${iteration}: expected three properties.`);
  if (await page.locator(".property-visual-audit").count() !== 3) throw new Error(`Run ${iteration}: expected three persisted visual audits.`);
  await page.getByText(/gemma-4-26b-a4b-it visual audit succeeded/i).waitFor();
  await page.getByText(/gemini-embedding-001 memory retrieval succeeded/i).waitFor();
  await page.getByText(/gemma-4-31b-it consistency audit succeeded/i).waitFor();
  await page.locator(".brief-memory-context.ready").waitFor();
  await page.locator(".brief-memory-audit.consistent").waitFor();
  for (const model of ["gemini-embedding-001", "gemma-4-26b-a4b-it", "gemma-4-31b-it"]) {
    await page.locator(".brief-model-proof").getByText(model, { exact: true }).waitFor();
  }
  await page.locator(".brief-events > div").nth(7).waitFor({ timeout: 10_000 });
  if (await page.locator(".brief-events > div").count() < 8) throw new Error(`Run ${iteration}: persisted agent trace is incomplete.`);
  await context.close();
}

await browser.close();
console.log(`${repetitions} persisted real-data browser golden checks passed.`);
