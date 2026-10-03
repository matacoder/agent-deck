const { test, expect } = require('./fixtures');

for (const width of [390, 1280]) {
  test(`server metrics stay right aligned at ${width}px and refresh`, async ({ app, page }) => {
    await app.open({ width });
    const metrics = page.locator('#server_metrics');
    await expect(metrics).toHaveText('CPU 24% · RAM 3.0 / 8.0 ГиБ');
    const row = await page.locator('.composer-status').boundingBox();
    const box = await metrics.boundingBox();
    expect(Math.abs(box.x + box.width - row.x - row.width)).toBeLessThan(2);
    expect(box.x).toBeGreaterThanOrEqual(row.x);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    app.metrics.cpu_percent = 67;
    await expect(metrics).toContainText('CPU 67%', { timeout: 8000 });
    app.metricsError = true;
    await page.evaluate(() => loadMetrics());
    await expect(metrics).toHaveText('CPU — · RAM —');
    await expect(page.locator('#send_state')).toContainText('Enter');
  });
}
