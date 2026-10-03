const { test, expect } = require('./fixtures');

for (const width of [320, 390]) {
  test(`Codex questions can be answered by touch at ${width}px`, async ({ app, page }) => {
    await app.open({ width });
    await page.locator('#msg').focus();
    for (const [name, key] of [['Предыдущий вопрос', 'S-Left'], ['Следующий вопрос', 'S-Right'], ['Вариант ниже', 'Down'], ['Вариант выше', 'Up'], ['Подтвердить выбор', 'Enter']]) {
      const button = page.getByRole('button', { name, exact: true });
      await expect(button).toBeVisible();
      const box = await button.boundingBox();
      expect(box.x).toBeGreaterThanOrEqual(0);
      expect(box.x + box.width).toBeLessThanOrEqual(width);
      await button.click();
      await expect.poll(() => app.sends.at(-1)?.key).toBe(key);
    }
    const first = await page.getByRole('button', { name: 'Предыдущий вопрос', exact: true }).boundingBox();
    const enter = await page.getByRole('button', { name: 'Подтвердить выбор', exact: true }).boundingBox();
    expect(first.y).toBe(enter.y);
    await page.getByRole('button', { name: 'Другие клавиши' }).click();
    await expect(page.getByRole('button', { name: '⇧Tab', exact: true })).toBeVisible();
    await expect(page.locator('#b_wrap')).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  });
}
