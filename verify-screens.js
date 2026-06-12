// Screenshot every dashboard view for design critique (reusable design-verification script: node verify-screens.js)
const { chromium } = require('playwright');
const path = require('path');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e)));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });

  const file = 'file:///' + path.resolve(__dirname, 'dashboard-mockup.html').replace(/\\/g, '/');
  await page.goto(file);
  await page.waitForTimeout(2500); // let Plotly render

  const views = ['positions', 'journal', 'analytics', 'backtester', 'scanner', 'learn'];
  for (const v of views) {
    await page.click(`.nav a[data-view="${v}"]`);
    await page.waitForTimeout(1800);
    await page.screenshot({ path: `_screens/${v}.png`, fullPage: true });
    console.log('shot:', v);
  }

  // also capture dark theme on positions for the toggle check
  await page.click('.nav a[data-view="positions"]');
  await page.waitForTimeout(500);
  await page.click('#themetoggle');
  await page.waitForTimeout(1800);
  await page.screenshot({ path: '_screens/positions-dark.png', fullPage: true });
  console.log('shot: positions-dark');

  console.log('PAGE ERRORS:', errors.length ? errors.join('\n') : 'none');
  await browser.close();
})();
