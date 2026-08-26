import { createRequire } from "node:module";

const require = createRequire(new URL("../../apps/web/package.json", import.meta.url));
const { chromium } = require("playwright-core");

const browser = await chromium.launch({
  executablePath: process.env.CHROME_PATH ?? "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  headless: true,
});

async function completeOnboarding(page, mode) {
  await page.goto("http://127.0.0.1:3000", { waitUntil: "networkidle" });
  if (mode === "RENT") await page.getByRole("button", { name: "Rent first" }).click();
  await page.getByRole("button", { name: "Set up my profile" }).click();
  await page.getByRole("button", { name: "Show my matches" }).click();
  const adaptiveQuestion = page.locator(".clarification-prompt");
  await adaptiveQuestion.waitFor({ timeout: 120_000 });
  await adaptiveQuestion.locator(".option-impact").first().click();
  const approval = page.getByRole("button", { name: "Yes, update my profile" });
  await approval.waitFor({ timeout: 30_000 });
  await approval.click();
  await page.getByText("Why your ranking changed").waitFor({ timeout: 30_000 });
  await page.locator(".listing-card").first().waitFor({ timeout: 30_000 });
  await page.locator(".listing-map-panel").waitFor({ timeout: 30_000 });
}

const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 1 });
await page.goto("http://127.0.0.1:3000");
await page.evaluate(() => localStorage.clear());
await completeOnboarding(page, "BUY");
if (process.env.CAPTURE === "1") await page.screenshot({ path: "artifacts/grand-prize-properties.png", fullPage: true });

if (await page.locator(".listing-card").count() < 12) throw new Error("Buy flow did not fill the first page from the real catalog");
await page.getByText(/\d+ matching listings?/).waitFor();
for (const _ of [0, 1]) {
  const card = page.locator(".listing-card:not(.rejected)").first();
  await card.getByRole("button", { name: "Not for me" }).click();
  await card.getByRole("button", { name: "Too expensive" }).waitFor();
  await card.getByRole("button", { name: "Too expensive" }).click();
}
await page.getByText(/Should “Stricter budget fit” matter more/).waitFor();
await page.getByRole("button", { name: "Yes, update my profile" }).click();
await page.getByText("Why your ranking changed").waitFor();

for (const _ of [0, 1, 2]) {
  await page.getByRole("button", { name: "Compare", exact: true }).first().click();
}
await page.getByRole("button", { name: "Build Decision Brief" }).click();
await page.locator('[data-testid="brief-build-modal"]').waitFor({ timeout: 5_000 });
await page.getByRole("heading", { name: "Building your Decision Brief" }).waitFor();
await page.getByText("Relevant decision memory retrieved", { exact: true }).waitFor();
await page.getByText("Visual evidence audit", { exact: true }).waitFor();
await page.getByText("Decision memory consistency audit", { exact: true }).waitFor();
await page.locator(".brief-stage.running").first().waitFor({ timeout: 30_000 });
await page.getByRole("heading", { name: "Ho Chi Minh City Decision Brief" }).waitFor({ timeout: 120_000 });
if (process.env.CAPTURE === "1") await page.screenshot({ path: "artifacts/grand-prize-decision-brief.png", fullPage: true });
if (await page.locator(".brief-properties article").count() !== 3) throw new Error("Decision Brief did not contain exactly three properties");
if (await page.locator(".claim-status.confirmed").count() < 3) throw new Error("Decision Brief is missing confirmed evidence claims");
if (await page.locator(".claim-status.unknown").count() < 3) throw new Error("Decision Brief is missing explicit unknowns");
if (await page.locator(".property-visual-audit").count() !== 3) throw new Error("Decision Brief is missing property-specific Gemma audits");
await page.getByText(/gemma-4-26b-a4b-it visual audit succeeded/i).waitFor();
await page.getByText(/gemini-embedding-001 memory retrieval succeeded/i).waitFor();
await page.getByText(/gemma-4-31b-it consistency audit succeeded/i).waitFor();
await page.locator(".brief-memory-context.ready").waitFor();
await page.locator(".brief-memory-audit").waitFor();
await page.getByText(/real cached photos? analyzed/i).waitFor();
await page.getByRole("button", { name: "Done" }).click();

await page.reload({ waitUntil: "networkidle" });
await page.locator(".listing-card").first().waitFor({ timeout: 30_000 });
await page.getByRole("button", { name: "Resume saved brief" }).click();
await page.getByRole("heading", { name: "Ho Chi Minh City Decision Brief" }).waitFor();
await page.getByRole("button", { name: "Done" }).click();

await page.evaluate(() => localStorage.clear());
await page.reload({ waitUntil: "networkidle" });
await completeOnboarding(page, "RENT");
if (await page.locator(".listing-card").count() < 12) throw new Error("Rent flow did not fill the first page from the real catalog");
await page.getByText(/\d+ matching listings?/).waitFor();
await page.getByText("$1,500/mo", { exact: false }).first().waitFor();

await browser.close();
console.log("Browser golden flow passed: adaptive clarification, buy/rent, approval-only re-ranking, ADK Decision Brief evidence, and reload persistence.");
