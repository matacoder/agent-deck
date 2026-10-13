const { test, expect } = require('./fixtures');

test('server metrics are in the sidebar footer and refresh', async ({ app, page }) => {
  await app.open({ width: 1280 });
  const metrics = page.locator('.side-foot #server_metrics');
  await expect(page.locator('#metric_cpu')).toHaveText('24%');
  await expect(page.locator('#metric_ram')).toHaveText('38%');
  await expect(metrics).toHaveAttribute('aria-label', 'CPU: 24% · RAM: 38% (3.0 / 8.0 ГиБ)');
  const foot = await page.locator('.side-foot').boundingBox();
  const box = await metrics.boundingBox();
  expect(box.x).toBeGreaterThanOrEqual(foot.x);
  expect(box.x + box.width).toBeLessThanOrEqual(foot.x + foot.width);
  app.metrics.cpu_percent = 67;
  await expect(page.locator('#metric_cpu')).toHaveText('67%', { timeout: 8000 });
  app.metricsError = true;
  await page.evaluate(() => loadMetrics());
  await expect(metrics).toHaveAttribute('aria-label', 'CPU: — · RAM: —');
});
