import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { pathToFileURL } from "node:url";

const require = createRequire(new URL("../../apps/web/package.json", import.meta.url));
const { chromium } = require("playwright-core");

const baseUrl = process.env.ROAMSTEAD_DEMO_URL ??
  "https://roamstead-web-113080100961.us-central1.run.app";
const profileId = process.env.ROAMSTEAD_DEMO_PROFILE_ID;
const fromStart = process.env.ROAMSTEAD_DEMO_FROM_START === "1";
const outputRoot = path.resolve(
  process.env.ROAMSTEAD_DEMO_OUTPUT ?? "artifacts/demo-video",
);
const architecturePath = path.resolve(
  process.env.ROAMSTEAD_ARCHITECTURE_PATH ??
    "infra/roamstead-google-cloud-architecture.png",
);
const chromePath = process.env.CHROME_PATH ??
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe";

if (!fromStart && !profileId) {
  throw new Error("Set ROAMSTEAD_DEMO_PROFILE_ID to a fresh persisted profile.");
}

fs.mkdirSync(outputRoot, { recursive: true });

const browser = await chromium.launch({
  executablePath: chromePath,
  headless: true,
  args: ["--hide-scrollbars"],
});

const context = await browser.newContext({
  viewport: { width: 1920, height: 1080 },
  recordVideo: {
    dir: outputRoot,
    size: { width: 1920, height: 1080 },
  },
  colorScheme: "light",
  locale: "en-US",
  timezoneId: "America/Phoenix",
});

if (!fromStart) {
  await context.addInitScript((id) => {
    window.localStorage.setItem("roamstead_profile_id", id);
    window.localStorage.setItem("roamstead_housing_mode", "RENT");
  }, profileId);
}

const page = await context.newPage();
const video = page.video();
const recordingStartedAt = Date.now();
let narrationAudioOffsetMs = 0;

async function installCursor() {
  await page.evaluate(() => {
    const old = document.getElementById("roamstead-demo-cursor");
    old?.remove();
    const cursor = document.createElement("div");
    cursor.id = "roamstead-demo-cursor";
    cursor.setAttribute("aria-hidden", "true");
    Object.assign(cursor.style, {
      position: "fixed",
      left: "0",
      top: "0",
      width: "26px",
      height: "26px",
      borderRadius: "50%",
      border: "3px solid white",
      background: "rgba(235, 112, 44, 0.92)",
      boxShadow: "0 3px 14px rgba(0,0,0,.35)",
      transform: "translate(-60px,-60px)",
      transition: "transform 120ms ease-out",
      pointerEvents: "none",
      zIndex: "2147483647",
    });
    document.body.appendChild(cursor);
    document.addEventListener("mousemove", (event) => {
      cursor.style.transform = `translate(${event.clientX - 13}px, ${event.clientY - 13}px)`;
    });
  });
}

async function pause(ms = 1800) {
  await page.waitForTimeout(ms);
}

async function point(locator, options = {}) {
  const target = locator.first();
  await target.waitFor({ state: "visible", timeout: options.timeout ?? 30000 });
  await target.scrollIntoViewIfNeeded();
  await pause(350);
  const box = await target.boundingBox();
  if (!box) throw new Error("Visible target has no bounding box.");
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2, { steps: 14 });
  await pause(options.hoverMs ?? 500);
}

async function click(locator, options = {}) {
  const target = locator.first();
  await point(target, options);
  await target.click();
  await pause(options.afterMs ?? 1000);
}

async function wheelInside(locator, amount, repeats = 1) {
  await point(locator, { hoverMs: 200 });
  for (let index = 0; index < repeats; index += 1) {
    await page.mouse.wheel(0, amount);
    await pause(900);
  }
}

let rawVideoPath = "";
try {
  await page.goto(baseUrl, { waitUntil: "domcontentloaded", timeout: 90000 });
  await installCursor();
  if (fromStart) {
    // Establish the three-market platform, then enter the focused profile
    // setup and deliberately choose HCMC for the full decision journey.
    await page.getByRole("heading", { name: /Find your place in/i })
      .waitFor({ state: "visible", timeout: 90000 });
    await pause(2600);
    const markets = page.locator(".market-ribbon > div");
    for (let index = 0; index < 3; index += 1) {
      await point(markets.nth(index), { hoverMs: 850 });
    }
    await pause(1200);
    await click(page.getByRole("button", { name: /Demo login/i }), {
      afterMs: 1200,
    });

    const setup = page.locator(".profile-setup.onboarding");
    await setup.waitFor({ state: "visible", timeout: 30000 });
    await page.getByRole("heading", { name: /What does the right home look like/i })
      .waitFor({ state: "visible", timeout: 30000 });
    await pause(1800);

    const citySelect = page.getByLabel("Choose city");
    await citySelect.waitFor({ state: "visible", timeout: 30000 });
    await page.waitForFunction(() => {
      const select = document.querySelector('select[aria-label="Choose city"]');
      return select && !select.disabled;
    }, { timeout: 30000 });

    // Start with the two additional Google models doing real product work:
    // a cached Veo city orientation and a persisted Gemini TTS briefing.
    const hcmcOrientation = page.locator('.city-orientation[data-city="ho-chi-minh-city"]');
    await hcmcOrientation.waitFor({ state: "visible", timeout: 60000 });
    await point(hcmcOrientation.locator("video"), { hoverMs: 900 });
    await point(hcmcOrientation.locator(".city-model-proof"), { hoverMs: 900 });
    const playNarration = hcmcOrientation.getByRole("button", {
      name: /Play Ho Chi Minh City narrated brief/i,
    });
    await point(playNarration, { hoverMs: 500 });
    narrationAudioOffsetMs = Date.now() - recordingStartedAt;
    await playNarration.click();
    await pause(9000);
    await click(
      hcmcOrientation.getByRole("button", { name: /Pause Ho Chi Minh City narrated brief/i }),
      { afterMs: 600 },
    );

    await point(citySelect, { hoverMs: 500 });
    await citySelect.selectOption("Bangkok");
    await page.getByText(/Verified listings are ready for Bangkok/i).waitFor();
    const bangkokOrientation = page.locator('.city-orientation[data-city="bangkok"]');
    await bangkokOrientation.waitFor({ state: "visible", timeout: 30000 });
    await point(bangkokOrientation.locator("video"), { hoverMs: 1000 });
    await point(bangkokOrientation.locator(".city-model-proof"), { hoverMs: 700 });
    await page.waitForFunction(() => {
      const select = document.querySelector('select[aria-label="Choose city"]');
      return select && !select.disabled;
    }, { timeout: 30000 });
    await pause(1500);
    await point(citySelect, { hoverMs: 400 });
    await citySelect.selectOption("Kuala Lumpur");
    await page.getByText(/Verified listings are ready for Kuala Lumpur/i).waitFor();
    const klOrientation = page.locator('.city-orientation[data-city="kuala-lumpur"]');
    await klOrientation.waitFor({ state: "visible", timeout: 30000 });
    await point(klOrientation.locator("video"), { hoverMs: 1000 });
    await point(klOrientation.locator(".city-model-proof"), { hoverMs: 700 });
    await page.waitForFunction(() => {
      const select = document.querySelector('select[aria-label="Choose city"]');
      return select && !select.disabled;
    }, { timeout: 30000 });
    await pause(1500);
    await point(citySelect, { hoverMs: 400 });
    await citySelect.selectOption("Ho Chi Minh City");
    await page.getByText(/Verified listings are ready for Ho Chi Minh City/i).waitFor();
    await hcmcOrientation.waitFor({ state: "visible", timeout: 30000 });
    await page.waitForFunction(() => {
      const select = document.querySelector('select[aria-label="Choose city"]');
      return select && !select.disabled;
    }, { timeout: 30000 });
    await pause(1800);

    // Continue from the true first-use HCMC profile and make the inputs legible.
    await click(setup.getByRole("button", { name: "Rent", exact: true }), {
      afterMs: 700,
    });
    await page.waitForFunction(() => {
      const button = [...document.querySelectorAll('button')]
        .find((item) => item.textContent?.trim() === 'Rent');
      return button && !button.disabled;
    }, { timeout: 30000 });
    await pause(1800);

    const budget = setup.locator("label").filter({ hasText: "Monthly budget" })
      .locator('input[type="number"]');
    await point(budget, { hoverMs: 200 });
    await budget.fill("1200");
    await pause(500);
    const bedrooms = setup.locator("label").filter({ hasText: "Minimum bedrooms" })
      .locator('input[type="number"]');
    await bedrooms.fill("1");
    const bathrooms = setup.locator("label").filter({ hasText: "Minimum bathrooms" })
      .locator('input[type="number"]');
    await bathrooms.fill("1");
    const schoolMinutes = setup.locator("label")
      .filter({ hasText: "International school (max min)" })
      .locator('input[type="number"]');
    await schoolMinutes.fill("25");
    await pause(1000);

    const remoteLabel = setup.locator("label").filter({ hasText: "Remote-work readiness" });
    const remoteWork = remoteLabel.locator('input[type="range"]');
    await remoteLabel.scrollIntoViewIfNeeded();
    await remoteWork.fill("0.9");
    await pause(600);
    const schoolLabel = setup.locator("label")
      .filter({ hasText: "International-school access" });
    const schoolPriority = schoolLabel.locator('input[type="range"]');
    await schoolLabel.scrollIntoViewIfNeeded();
    await schoolPriority.fill("0.85");
    await pause(1000);

    await click(setup.getByRole("button", { name: "Show my matches" }), {
      afterMs: 900,
    });
    await page.getByRole("heading", { name: "Properties matched to your profile" })
      .waitFor({ state: "visible", timeout: 90000 });
    await page.locator(".listing-card").first()
      .waitFor({ state: "visible", timeout: 90000 });
    await pause(5000);
  } else {
    await page.getByRole("heading", { name: "Properties matched to your profile" })
      .waitFor({ state: "visible", timeout: 90000 });
    await pause(4000);
  }

  // The first visible action: Fit Scores and real properties are already on screen.
  const firstProperty = page.locator(".listing-card").first();
  await point(firstProperty, { hoverMs: 900 });
  await pause(1800);

  // A real counterfactual over this profile's qualified Fit Scores selects one
  // high-impact question. The answer creates a proposal; it never mutates silently.
  const adaptive = page.locator(".adaptive-clarification");
  await adaptive.waitFor({ state: "visible", timeout: 90000 });
  await point(adaptive, { hoverMs: 900 });
  await pause(3500);
  await adaptive.locator(".adaptive-option").first()
    .waitFor({ state: "visible", timeout: 120000 });
  await click(adaptive.locator(".adaptive-option").first(), { afterMs: 1000 });
  const proposal = page.locator(".preference-prompt");
  await proposal.waitFor({ state: "visible", timeout: 60000 });
  await pause(3500);
  await click(proposal.getByRole("button", { name: /Yes, update my profile/i }), {
    afterMs: 1200,
  });
  await proposal.waitFor({ state: "hidden", timeout: 60000 });
  await page.getByText("Why your ranking changed", { exact: true })
    .waitFor({ state: "visible", timeout: 30000 });
  await pause(3500);

  // Show the map as evidence that browsing remains a real property workflow.
  const satellite = page.getByRole("button", { name: "Satellite", exact: true });
  if (await satellite.isVisible().catch(() => false)) {
    await click(satellite, { afterMs: 3200 });
    await click(page.getByRole("button", { name: "Normal", exact: true }), {
      afterMs: 1800,
    });
  }

  // Open a property and hold on the deterministic Fit Score explanation.
  const detailCard = page.locator(".listing-card").nth(2);
  await click(detailCard.getByRole("button", { name: "View property" }), {
    afterMs: 2200,
  });
  const propertyModal = page.locator(".property-modal");
  await propertyModal.waitFor({ state: "visible", timeout: 30000 });
  await pause(2500);
  await wheelInside(propertyModal, 650, 2);
  await pause(2500);
  await click(page.getByRole("button", { name: "Close property" }), {
    afterMs: 1500,
  });

  // Select three different real properties so this run cannot reuse the earlier proof brief.
  for (let index = 0; index < 3; index += 1) {
    // The locator intentionally re-resolves after each click because the
    // selected button changes its label from Compare to Selected.
    await click(
      page.locator(".listing-card").getByRole("button", { name: "Compare" }).first(),
      { afterMs: 700 },
    );
  }
  await pause(2200);

  await click(page.getByRole("button", { name: "Build Decision Brief" }), {
    afterMs: 1000,
  });
  const workflow = page.getByRole("dialog", { name: "Building your Decision Brief" })
    .or(page.locator('[aria-label="Building your Decision Brief"]'));
  await workflow.first().waitFor({ state: "visible", timeout: 30000 });
  await pause(4000);

  // Let the actual persisted SSE workflow play continuously. The UI updates each node live.
  const briefModal = page.locator(".brief-modal");
  await briefModal.waitFor({ state: "visible", timeout: 180000 });
  await briefModal.getByText("All evidence stages completed", { exact: true })
    .waitFor({ state: "visible", timeout: 30000 });
  for (const model of [
    "gemini-embedding-001",
    "gemma-4-26b-a4b-it",
    "gemma-4-31b-it",
  ]) {
    await briefModal.getByText(model, { exact: true }).first()
      .waitFor({ state: "visible", timeout: 30000 });
  }
  await pause(4500);

  // Hold on persisted model proof: embedding retrieval plus both Gemma critics.
  const modelProof = briefModal.locator(".brief-model-proof");
  await point(modelProof, { hoverMs: 1000 });
  await pause(5000);

  // Show each bonus model's product output, not merely its model identifier.
  await wheelInside(briefModal, 620, 2);
  await pause(2000);
  await wheelInside(briefModal, 700, 2);
  await pause(2500);

  // Continue into an approval-gated Decision Watch and run only the proposed checks.
  const createWatch = page.getByRole("button", { name: "Create watch plan" });
  if (await createWatch.isVisible().catch(() => false)) {
    await click(createWatch, { afterMs: 900 });
    await page.getByText(/live ADK plan/i).waitFor({ state: "visible", timeout: 90000 });
    await pause(4000);
    await click(page.getByRole("button", { name: "Approve and run" }), {
      afterMs: 900,
    });
    await page.getByText("Evidence timeline updated", { exact: true })
      .waitFor({ state: "visible", timeout: 120000 });
    await pause(4500);
  }

  // Close on the updated evidence timeline. This remains one uninterrupted
  // product session and avoids adding a second onboarding journey to the take.
  await click(page.getByRole("button", { name: "Done", exact: true }), {
    afterMs: 1800,
  });
  await page.getByRole("heading", { name: "Properties matched to your profile" })
    .waitFor({ state: "visible", timeout: 30000 });
  await pause(5000);
} finally {
  await context.close();
  if (video) rawVideoPath = await video.path();
  await browser.close();
}

if (!rawVideoPath) throw new Error("Playwright did not produce a video file.");
const finalRawPath = path.join(
  outputRoot,
  fromStart
    ? "roamstead-city-orientations-five-models-continuous-1080p.webm"
    : "roamstead-continuous-demo-1080p.webm",
);
if (path.resolve(rawVideoPath) !== path.resolve(finalRawPath)) {
  fs.copyFileSync(rawVideoPath, finalRawPath);
}
console.log(finalRawPath);
const timingPath = path.join(outputRoot, "roamstead-demo-timing.json");
fs.writeFileSync(
  timingPath,
  JSON.stringify({ narrationAudioOffsetMs, rawVideoPath: finalRawPath }, null, 2),
);
console.log(timingPath);
