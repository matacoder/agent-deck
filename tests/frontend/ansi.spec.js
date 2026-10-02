const { test, expect } = require('./fixtures');

test('screen renders terminal colors, emphasis, resets and safe clickable links', async ({ app, page }) => {
  app.sessions[0].preview_ansi = '\x1b[31;1mRed bold\x1b[0m Plain\n\x1b[38;5;196mIndexed\x1b[0m\n\x1b[38;2;12;34;56mRGB\x1b[0m\nhttps://example.com/help';
  await app.open();
  const red = page.locator('#pre span').filter({ hasText: /^Red bold$/ });
  await expect(red).toHaveCSS('font-weight', '700');
  await expect(page.locator('#pre span').filter({ hasText: /^Indexed$/ })).toHaveCSS('color', 'rgb(255, 0, 0)');
  await expect(page.locator('#pre span').filter({ hasText: /^RGB$/ })).toHaveCSS('color', 'rgb(12, 34, 56)');
  await expect(page.locator('#pre')).toContainText('Plain');
  const link = page.locator('#pre a');
  await expect(link).toHaveAttribute('href', 'https://example.com/help');
  await expect(link).toHaveAttribute('rel', 'noopener');
  expect(await page.locator('#pre').textContent()).not.toContain('\x1b');
});

test('terminal output containing HTML is rendered as text without executing it', async ({ app, page }) => {
  app.sessions[0].preview_ansi = '\x1b[32m<img src=x onerror="window.injected=true">\x1b[0m\n<script>window.injected=true</script>';
  await app.open();
  await expect(page.locator('#pre')).toContainText('<img src=x');
  await expect(page.locator('#pre img, #pre script')).toHaveCount(0);
  expect(await page.evaluate(() => window.injected)).toBeUndefined();
});

test('terminal separators stay compact and long lines can switch wrapping', async ({ app, page }) => {
  app.sessions[0].preview_ansi = '\x1b[90m' + '─'.repeat(100) + '\x1b[0m\n' + 'long-output-'.repeat(80);
  await app.open();
  await expect(page.locator('#pre .hr')).toHaveCount(1);
  expect((await page.locator('#pre .hr').boundingBox()).height).toBe(1);
  await page.locator('#b_wrap').click();
  await expect(page.locator('#pre')).toHaveClass(/no-wrap/);
  expect(await page.locator('#pre').evaluate(el => el.scrollWidth > el.clientWidth)).toBe(true);
  await page.locator('#b_wrap').click();
  await expect(page.locator('#pre')).not.toHaveClass(/no-wrap/);
});
