const { test, expect } = require('./fixtures');

for (const width of [320, 390, 1280]) {
  test(`server metrics stay right aligned at ${width}px and refresh`, async ({ app, page }) => {
    await app.open({ width });
    const metrics = page.locator('#server_metrics');
    await expect(page.locator('#metric_cpu')).toHaveText('24%');
    await expect(page.locator('#metric_ram')).toHaveText('38%');
    await expect(metrics).toHaveAttribute('aria-label', 'CPU: 24% · RAM: 38% (3.0 / 8.0 ГиБ)');
    const row = await page.locator('.composer-status').boundingBox();
    const box = await metrics.boundingBox();
    expect(Math.abs(box.x + box.width - row.x - row.width)).toBeLessThan(2);
    expect(box.x).toBeGreaterThanOrEqual(row.x);
    const hint = await page.locator('#send_state').boundingBox();
    expect(Math.abs(box.y - hint.y)).toBeLessThan(3);
    expect(box.x).toBeGreaterThanOrEqual(hint.x + hint.width);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    app.metrics.cpu_percent = 67;
    await expect(page.locator('#metric_cpu')).toHaveText('67%', { timeout: 8000 });
    app.metricsError = true;
    await page.evaluate(() => loadMetrics());
    await expect(metrics).toHaveAttribute('aria-label', 'CPU: — · RAM: —');
    await expect(page.locator('#send_state')).toContainText('Enter');
  });
}
