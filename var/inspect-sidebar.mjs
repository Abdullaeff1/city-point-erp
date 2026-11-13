import { chromium } from "playwright";
import { writeFileSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const out = {
  htmlStructure: {},
  detailsCounts: {},
  closedLinkStyles: [],
  screenshotPath: null,
  cssHideRule: null,
  fetchOnly: null,
  error: null,
};

async function fetchCssHideRule() {
  const res = await fetch("http://localhost:3001/static/css/cp.css");
  const css = await res.text();
  const match = css.match(
    /\.cp-nav-group:not\(\[open\]\)\s*>\s*\.cp-nav-group-body\s*\{[^}]*\}/s
  );
  out.cssHideRule = match ? match[0].replace(/\s+/g, " ").trim() : "NOT FOUND";
}

async function fetchWithSession() {
  const loginRes = await fetch("http://localhost:3001/login/");
  const loginHtml = await loginRes.text();
  const setCookie = loginRes.headers.getSetCookie?.() ?? [];
  const cookieHeader = setCookie.map((c) => c.split(";")[0]).join("; ");
  const csrf =
    loginHtml.match(/name="csrfmiddlewaretoken" value="([^"]+)"/)?.[1] ?? "";
  const body = new URLSearchParams({
    csrfmiddlewaretoken: csrf,
    email: "admin@citypoint.az",
    password: "admin123",
  });
  const postRes = await fetch("http://localhost:3001/login/", {
    method: "POST",
    headers: {
      "Content-Type": "application/x-www-form-urlencoded",
      Cookie: cookieHeader,
      Referer: "http://localhost:3001/login/",
    },
    body,
    redirect: "manual",
  });
  const cookies = [...setCookie, ...(postRes.headers.getSetCookie?.() ?? [])]
    .map((c) => c.split(";")[0])
    .filter(Boolean);
  const sessionCookie = [...new Set(cookies)].join("; ");
  const erpRes = await fetch("http://localhost:3001/erp/", {
    headers: { Cookie: sessionCookie },
    redirect: "follow",
  });
  const erpHtml = await erpRes.text();
  const navMatch = erpHtml.match(/<nav class="cp-nav"[\s\S]*?<\/nav>/);
  const navHtml = navMatch ? navMatch[0] : "";
  out.fetchOnly = {
    erpStatus: erpRes.status,
    erpUrl: erpRes.url,
    hasDetailsGroup: navHtml.includes('class="cp-nav-group"'),
    hasOldNavLabel: /<div class="cp-nav-label"/.test(navHtml) || /<p class="cp-nav-label"/.test(navHtml),
    detailsOpen: (navHtml.match(/<details class="cp-nav-group" open/g) ?? []).length,
    detailsClosed: (navHtml.match(/<details class="cp-nav-group"(?![^>]*\bopen)/g) ?? []).length,
    navSnippet: navHtml.slice(0, 800),
  };
}

async function browserInspect() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();
  await page.goto("http://localhost:3001/login/", { waitUntil: "networkidle" });
  await page.fill('input[name="email"]', "admin@citypoint.az");
  await page.fill('input[name="password"]', "admin123");
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/(erp|go)/, { timeout: 15000 }).catch(() => {});
  if (!page.url().includes("/erp")) {
    await page.goto("http://localhost:3001/erp/", { waitUntil: "networkidle" });
  }
  const nav = page.locator("nav.cp-nav");
  await nav.waitFor({ timeout: 10000 });
  const navHtml = await nav.innerHTML();
  const fullNavOuter = await nav.evaluate((el) => el.outerHTML);

  out.htmlStructure = {
    hasDetailsGroup: fullNavOuter.includes('class="cp-nav-group"') || navHtml.includes("cp-nav-group"),
    hasOldCpNavLabelAsSection:
      (await page.locator("nav.cp-nav .cp-nav-label").count()) > 0,
    detailsCount: await page.locator("nav.cp-nav details.cp-nav-group").count(),
  };

  const groups = page.locator("nav.cp-nav details.cp-nav-group");
  const n = await groups.count();
  let openCount = 0;
  let closedCount = 0;
  for (let i = 0; i < n; i++) {
    const d = groups.nth(i);
    if (await d.evaluate((el) => el.hasAttribute("open"))) openCount++;
    else closedCount++;
  }
  out.detailsCounts = { open: openCount, closed: closedCount, total: n };

  for (let i = 0; i < n; i++) {
    const d = groups.nth(i);
    const isOpen = await d.evaluate((el) => el.hasAttribute("open"));
    if (isOpen) continue;
    const label = await d.locator(".cp-nav-summary-label").textContent();
    const links = d.locator(".cp-nav-group-body a");
    const linkCount = await links.count();
    for (let j = 0; j < Math.min(linkCount, 3); j++) {
      const link = links.nth(j);
      const text = (await link.textContent())?.trim();
      const styles = await link.evaluate((el) => {
        const cs = getComputedStyle(el);
        return {
          display: cs.display,
          visibility: cs.visibility,
          opacity: cs.opacity,
          height: cs.height,
        };
      });
      const bodyStyles = await d.locator(".cp-nav-group-body").evaluate((el) => {
        const cs = getComputedStyle(el);
        return { display: cs.display, visibility: cs.visibility };
      });
      out.closedLinkStyles.push({ section: label?.trim(), linkText: text, linkStyles: styles, bodyStyles });
    }
  }

  const visibleClosedLinks = [];
  for (let i = 0; i < n; i++) {
    const d = groups.nth(i);
    if (await d.evaluate((el) => el.hasAttribute("open"))) continue;
    const links = d.locator(".cp-nav-group-body a .cp-nav-text");
    const lc = await links.count();
    for (let j = 0; j < lc; j++) {
      const t = links.nth(j);
      if (await t.isVisible()) {
        visibleClosedLinks.push((await t.textContent())?.trim());
      }
    }
  }
  out.visibleClosedSectionLinks = visibleClosedLinks;

  const shot = join(__dirname, "sidebar-screenshot.png");
  await page.locator(".cp-sidebar, aside, nav.cp-nav").first().screenshot({ path: shot }).catch(async () => {
    await nav.screenshot({ path: shot });
  });
  out.screenshotPath = shot;

  const headerTexts = [];
  for (let i = 0; i < n; i++) {
    headerTexts.push(
      (await groups.nth(i).locator(".cp-nav-summary-label").textContent())?.trim()
    );
  }
  out.sectionHeaders = headerTexts;

  await browser.close();
}

await fetchCssHideRule();
await fetchWithSession();
try {
  await browserInspect();
} catch (e) {
  out.error = String(e.message || e);
}

writeFileSync(join(__dirname, "sidebar-inspect.json"), JSON.stringify(out, null, 2));
console.log(JSON.stringify(out, null, 2));
