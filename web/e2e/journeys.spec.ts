import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";

async function noAxeViolations(page: Page) {
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"]).analyze();
  expect(results.violations.map((v) => `${v.id}: ${v.nodes.length}`)).toEqual([]);
}

test("ask a question, watch it stream, open a citation", async ({ page }) => {
  await page.goto("./");
  await expect(page.getByRole("heading", { name: "Ask your documents a question" })).toBeVisible();
  await noAxeViolations(page);
  await page.getByLabel("Your question").fill("What does a Deployment manage, and what do those objects in turn keep running?");
  await page.getByRole("button", { name: "Ask" }).click();
  const answer = page.getByRole("article", { name: /Answer to: What does a Deployment manage/ });
  await expect(answer.getByText("Deployment → ReplicaSet → Pods")).toBeVisible({ timeout: 20_000 });
  await expect(answer.getByText("relationship")).toBeVisible();
  // every claim traces to its passage in two clicks: the citation, then the passage
  await answer.getByRole("button", { name: "Open source 2" }).first().click();
  await expect(page.getByRole("article", { name: "Source 2" })).toContainText("maintain a stable set of replica Pods");
  await page.getByRole("tab", { name: "Graph" }).click();
  await page.getByRole("tab", { name: "Table" }).click();
  await expect(page.getByRole("table")).toContainText("Deployment -[MANAGES]-> ReplicaSet");
  await noAxeViolations(page);
});

test("a question the documents can't answer shows the not-found state", async ({ page }) => {
  await page.goto("./");
  await page.getByLabel("Your question").fill("What is the default replication factor for Kafka topics?");
  await page.keyboard.press("Enter");
  await expect(page.getByText("Not found in your documents.")).toBeVisible({ timeout: 15_000 });
});

test("a running answer can be stopped", async ({ page }) => {
  await page.goto("./");
  await page.getByLabel("Your question").fill("What does a Deployment manage, and what do those objects in turn keep running?");
  await page.getByRole("button", { name: "Ask" }).click();
  await page.getByRole("button", { name: "Stop" }).click();
  await expect(page.getByText("stopped")).toBeVisible();
  await expect(page.getByRole("button", { name: "Stop" })).toHaveCount(0);
});

test("upload documents to the library", async ({ page }) => {
  await page.goto("./library/");
  await expect(page.getByRole("heading", { name: "Library" })).toBeVisible();
  await expect(page.getByRole("table")).toContainText("Deployments");
  await noAxeViolations(page);
  await page.getByLabel("Choose files to upload").setInputFiles([
    { name: "runbook.md", mimeType: "text/markdown", buffer: Buffer.from("# Runbook\n\nRestart the API.") },
    { name: "virus.exe", mimeType: "application/octet-stream", buffer: Buffer.from("MZ") },
  ]);
  await expect(page.getByRole("alert").filter({ hasText: "Unsupported type" })).toBeVisible();
  await expect(page.getByText("runbook.md")).toBeVisible();
  await page.getByLabel("Search by title").fill("Secrets");
  await expect(page.getByRole("table")).toContainText("Secrets");
  await expect(page.getByRole("table")).not.toContainText("Deployments");
});

test("admin dashboard shows measured retrieval quality", async ({ page }) => {
  await page.goto("./dashboard/");
  await expect(page.getByRole("heading", { name: "Quality & cost" })).toBeVisible();
  await expect(page.getByText("Recall@10 per evaluation run")).toBeVisible();
  await noAxeViolations(page);
});

test("keyboard only: skip link and focus order", async ({ page, isMobile }) => {
  test.skip(isMobile, "keyboard journey is for desktop");
  await page.goto("./");
  await expect(page.getByRole("heading", { name: "Ask your documents a question" })).toBeVisible();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
  await page.keyboard.press("Enter");
  await page.getByLabel("Your question").focus();
  await page.keyboard.type("Which component restarts a container?");
  await page.keyboard.press("Enter");
  await expect(page.getByRole("article").first()).toBeVisible();
});

test("an off-script question in the demo says what the demo is instead of inventing an answer", async ({ page }) => {
  await page.goto("./");
  await expect(page.getByText("Live demo.")).toBeVisible();
  await page.getByLabel("Your question").fill("How do I configure a NetworkPolicy for egress traffic?");
  await page.keyboard.press("Enter");
  await expect(page.getByText(/can only replay answers recorded from the real system/)).toBeVisible({ timeout: 10_000 });
});

test("the about page explains the system and passes accessibility checks", async ({ page }) => {
  await page.goto("./about/");
  await expect(page.getByRole("heading", { name: "About CORTEX" })).toBeVisible();
  await expect(page.getByRole("table")).toContainText("Fused + cross-encoder");
  await noAxeViolations(page);
});
