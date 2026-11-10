import { chromium } from "playwright";

const base = process.env.BASE_URL || "http://host.docker.internal:3001";
const out = process.env.OUT_DIR || "/out";

async function login(page, email, password) {
  await page.goto(`${base}/login/`, { waitUntil: "networkidle" });
  await page.fill('input[name="username"], input[type="email"], #id_username', email);
  await page.fill('input[name="password"], input[type="password"]', password);
  await Promise.all([
    page.waitForNavigation({ waitUntil: "networkidle", timeout: 20000 }).catch(() => {}),
    page.click('button[type="submit"], input[type="submit"]'),
  ]);
  await page.waitForTimeout(1200);
}

async function shot(page, name) {
  await page.waitForTimeout(600);
  await page.screenshot({ path: `${out}/${name}.png`, fullPage: false });
  console.log("OK", name, page.url());
}

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: "az-AZ" });
const page = await context.newPage();

await page.goto(`${base}/login/`, { waitUntil: "networkidle" });
await shot(page, "01-login");

await login(page, "admin@citypoint.az", "admin123");
await page.goto(`${base}/erp/`, { waitUntil: "networkidle" });
await shot(page, "02-erp-dashboard");

const paths = [
  ["03-spaces", "/erp/spaces/"],
  ["04-residents", "/erp/residents/"],
  ["05-tickets", "/erp/tickets/"],
  ["06-reception", "/erp/reception/"],
  ["07-crm", "/erp/crm/leads/"],
  ["08-work-orders", "/erp/work-orders/"],
  ["09-warehouse", "/erp/warehouse/"],
  ["10-procurement", "/erp/procurement/"],
  ["11-billing", "/erp/billing/"],
  ["12-accounting", "/erp/accounting/"],
  ["13-reports", "/erp/reports/"],
];
for (const [name, path] of paths) {
  await page.goto(`${base}${path}`, { waitUntil: "networkidle", timeout: 25000 });
  await shot(page, name);
}

await page.goto(`${base}/erp/spaces/`, { waitUntil: "networkidle" });
const href = await page.$$eval("a[href]", (as) => {
  const hits = as
    .map((a) => a.getAttribute("href") || "")
    .filter((h) => /\/erp\/spaces\/[^/]+\/?$/.test(h) && !h.endsWith("/new/") && !h.includes("edit"));
  return hits[0] || "";
});
if (href) {
  await page.goto(href.startsWith("http") ? href : `${base}${href}`, { waitUntil: "networkidle" });
  await shot(page, "14-space-detail");
}

await context.clearCookies();
await login(page, "security@citypoint.az", "security123");
await page.goto(`${base}/security/`, { waitUntil: "networkidle" });
await shot(page, "15-security");

await context.clearCookies();
await login(page, "office@asbc.az", "asbc123");
await page.goto(`${base}/portal/`, { waitUntil: "networkidle" });
await shot(page, "16-portal");
await page.goto(`${base}/portal/spaces/`, { waitUntil: "networkidle" }).catch(() => {});
await shot(page, "17-portal-spaces");

await browser.close();
