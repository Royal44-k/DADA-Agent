import playwright from "file:///C:/Users/lenovo/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/index.js";
import { pathToFileURL } from "node:url";

const { chromium } = playwright;

const executablePath = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const reports = [
  {
    key: "deepseek",
    file: "D:\\Codex-chat\\deepseek-harness-core-design-analysis.html",
    expectedTitle: "DeepSeek Harness",
    expectedSections: 13,
    probe: "#llm-tools",
    back: ".backtop",
    nav: ".nav a",
  },
  {
    key: "pi",
    file: "D:\\Codex-chat\\pi-agent-core-design-analysis.html",
    expectedTitle: "Pi Agent",
    expectedSections: 14,
    probe: "#tools",
    back: ".back",
    nav: ".topnav a",
  },
];

const browser = await chromium.launch({ headless: true, executablePath });
const failures = [];
const results = [];

for (const report of reports) {
  for (const viewport of [
    { name: "desktop", width: 1440, height: 1000 },
    { name: "mobile", width: 390, height: 844 },
  ]) {
    const context = await browser.newContext({ viewport, reducedMotion: "reduce" });
    const page = await context.newPage();
    const consoleErrors = [];
    page.on("console", (message) => {
      if (message.type() === "error") consoleErrors.push(message.text());
    });
    page.on("pageerror", (error) => consoleErrors.push(error.message));
    await page.goto(pathToFileURL(report.file).href, { waitUntil: "load" });
    await page.waitForTimeout(120);

    const state = await page.evaluate(({ expectedTitle, expectedSections, navSelector }) => {
      const anchors = [...document.querySelectorAll(`${navSelector}[href^="#"]`)];
      const missingTargets = anchors
        .map((a) => a.getAttribute("href"))
        .filter((href) => !href || !document.querySelector(href));
      const wideElements = [...document.querySelectorAll("body *")]
        .filter((el) => {
          const style = getComputedStyle(el);
          const rect = el.getBoundingClientRect();
          return style.position !== "fixed" && rect.right > innerWidth + 2 && style.overflowX !== "auto";
        })
        .slice(0, 8)
        .map((el) => ({ tag: el.tagName, className: el.className, right: Math.round(el.getBoundingClientRect().right) }));
      return {
        title: document.title,
        titleOk: document.title.includes(expectedTitle),
        sectionCount: document.querySelectorAll("main section").length,
        sectionCountOk: document.querySelectorAll("main section").length === expectedSections,
        h1: document.querySelector("h1")?.textContent?.trim(),
        missingTargets,
        pageOverflow: document.documentElement.scrollWidth > innerWidth + 2,
        scrollWidth: document.documentElement.scrollWidth,
        innerWidth,
        wideElements,
      };
    }, { expectedTitle: report.expectedTitle, expectedSections: report.expectedSections, navSelector: report.nav });

    await page.screenshot({ path: `D:\\Codex-chat\\${report.key}-report-${viewport.name}-hero.png` });
    await page.locator(report.probe).scrollIntoViewIfNeeded();
    await page.waitForTimeout(100);
    await page.screenshot({ path: `D:\\Codex-chat\\${report.key}-report-${viewport.name}-probe.png` });

    const navActive = await page.locator(`${report.nav}.active`).count();
    await page.evaluate(() => scrollTo(0, document.documentElement.scrollHeight));
    await page.waitForTimeout(80);
    const backVisible = await page.locator(report.back).evaluate((el) => getComputedStyle(el).display !== "none");
    await page.locator(report.back).click();
    await page.waitForTimeout(450);
    const backWorked = (await page.evaluate(() => scrollY)) < 20;

    await page.emulateMedia({ media: "print" });
    const printState = await page.evaluate(({ nav, back }) => ({
      navDisplay: getComputedStyle(document.querySelector(nav)).display,
      backDisplay: getComputedStyle(document.querySelector(back)).display,
    }), { nav: report.nav.includes(".topnav") ? ".topnav-wrap" : ".nav", back: report.back });

    const result = { report: report.key, viewport: viewport.name, ...state, consoleErrors, navActive, backVisible, backWorked, printState };
    results.push(result);
    if (!state.titleOk) failures.push(`${report.key}/${viewport.name}: title`);
    if (!state.sectionCountOk) failures.push(`${report.key}/${viewport.name}: section count ${state.sectionCount}`);
    if (state.missingTargets.length) failures.push(`${report.key}/${viewport.name}: missing anchors ${state.missingTargets.join(",")}`);
    if (state.pageOverflow) failures.push(`${report.key}/${viewport.name}: page overflow ${state.scrollWidth}/${state.innerWidth}`);
    if (consoleErrors.length) failures.push(`${report.key}/${viewport.name}: console ${consoleErrors.join(" | ")}`);
    if (navActive !== 1) failures.push(`${report.key}/${viewport.name}: active nav count ${navActive}`);
    if (!backVisible || !backWorked) failures.push(`${report.key}/${viewport.name}: back-to-top`);
    if (printState.navDisplay !== "none" || printState.backDisplay !== "none") failures.push(`${report.key}/${viewport.name}: print controls visible`);
    await context.close();
  }
}

await browser.close();
console.log(JSON.stringify({ ok: failures.length === 0, failures, results }, null, 2));
if (failures.length) process.exitCode = 1;
