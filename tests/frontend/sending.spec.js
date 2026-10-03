const { test, expect, PNG } = require('./fixtures');

async function attach(page, name = 'screenshot.png') {
  await page.locator('#image_files').setInputFiles({ name, mimeType: 'image/png', buffer: PNG });
  await expect(page.locator('#attachments')).toContainText(name);
  await expect(page.locator('#b_send')).toBeEnabled();
}

test('sends multiline text once and displays confirmation', async ({ app, page }) => {
  await app.open();
  await page.locator('#msg').fill('First line\nSecond line');
  await page.locator('#b_send').click();
  await expect(page.locator('#send_state')).toContainText('Отправлено в Codex');
  expect(app.sends).toEqual([{ name: 'tmux', text: 'First line\nSecond line', attachments: [] }]);
  await expect(page.locator('#msg')).toHaveValue('');
});

test('mobile Enter creates a newline and Ctrl+Enter sends', async ({ app, page }) => {
  await app.open();
  await page.locator('#msg').fill('Hello');
  await page.locator('#msg').press('Enter');
  await expect(page.locator('#msg')).toHaveValue('Hello\n');
  expect(app.sends).toEqual([]);
  await page.locator('#msg').press('Control+Enter');
  await expect(page.locator('#send_state')).toContainText('Отправлено');
  expect(app.sends).toHaveLength(1);
});

test('image-only messages upload real bytes and clear the attachment on success', async ({ app, page }) => {
  await app.open();
  await attach(page);
  expect(app.uploads).toEqual([{ name: 'tmux', data: PNG.toString('base64'), filename: 'screenshot.png' }]);
  await page.locator('#b_send').click();
  await expect(page.locator('#send_state')).toContainText('Отправлено');
  expect(app.sends).toEqual([{ name: 'tmux', text: '', attachments: ['00000000000000000000000000000001.png'] }]);
  await expect(page.locator('#attachments')).toBeEmpty();
});

test('ZIP and text files preserve bytes, stay without image previews and survive refresh', async ({ app, page }) => {
  await app.open();
  await expect(page.locator('#image_files')).not.toHaveAttribute('accept', /.+/);
  const zip = Buffer.from([80, 75, 3, 4, 0, 255]), text = Buffer.from('Useful notes');
  await page.locator('#image_files').setInputFiles([
    { name: 'archive.zip', mimeType: 'application/zip', buffer: zip },
    { name: 'notes.txt', mimeType: 'text/plain', buffer: text },
  ]);
  await expect(page.locator('#attachments')).toContainText('notes.txt');
  await expect(page.locator('#attachments img')).toHaveCount(0);
  expect(app.uploads.map(x => [x.filename, x.data])).toEqual([['archive.zip', zip.toString('base64')], ['notes.txt', text.toString('base64')]]);
  await page.evaluate(() => refreshInterface());
  await expect(page.locator('#attachments')).toContainText('archive.zip');
  await page.locator('#b_send').click();
  await expect(page.locator('#send_state')).toContainText('Отправлено');
  expect(app.sends[0].attachments).toHaveLength(2);
  await expect(page.locator('#attachments')).toBeEmpty();
});

test('failed sends retain text and attachments so the user can retry', async ({ app, page }) => {
  await app.open();
  await attach(page);
  await page.locator('#msg').fill('Please look at this');
  app.sendError = 'Disconnected';
  await page.locator('#b_send').click();
  await expect(page.locator('#send_state')).toContainText('Не отправлено: Disconnected');
  await expect(page.locator('#msg')).toHaveValue('Please look at this');
  await expect(page.locator('#attachments')).toContainText('screenshot.png');
  app.sendError = null;
  await page.locator('#b_send').click();
  await expect(page.locator('#send_state')).toContainText('Отправлено');
  expect(app.sends).toHaveLength(2);
  expect(app.sends[0]).toEqual(app.sends[1]);
});

test('pending send blocks duplicates and keeps edits made while waiting', async ({ app, page }) => {
  await app.open();
  await page.locator('#msg').fill('Original');
  const gate = app.holdSend();
  await page.locator('#b_send').click();
  await expect(page.locator('#b_send')).toBeDisabled();
  await expect.poll(() => app.sends.length).toBe(1);
  await page.evaluate(() => send());
  expect(app.sends).toHaveLength(1);
  await page.locator('#msg').fill('New draft');
  gate.release();
  await expect(page.locator('#send_state')).toContainText('Отправлено');
  await expect(page.locator('#msg')).toHaveValue('New draft');
});

test('attachments stay with their session and survive manual refresh', async ({ app, page }) => {
  await app.open();
  await attach(page);
  await page.evaluate(() => select('other'));
  await expect(page.locator('#attachments')).toBeEmpty();
  await page.evaluate(() => refreshInterface());
  await expect(page.locator('#title b')).toHaveText('other');
  await page.evaluate(() => select('tmux'));
  await expect(page.locator('#attachments')).toContainText('screenshot.png');
  await page.getByRole('button', { name: 'Убрать screenshot.png' }).click();
  await expect(page.locator('#attachments')).toBeEmpty();
});

test('upload errors and the four-image limit are visible without sending', async ({ app, page }) => {
  await app.open();
  app.uploadError = 'Invalid image';
  await page.locator('#image_files').setInputFiles({ name: 'bad.png', mimeType: 'image/png', buffer: PNG });
  await expect(page.locator('#send_state')).toContainText('Не удалось приложить: Invalid image');
  await expect(page.locator('#attachments')).toBeEmpty();
  app.uploadError = null;
  await page.locator('#image_files').setInputFiles(Array.from({ length: 5 }, (_, i) => ({ name: `${i}.png`, mimeType: 'image/png', buffer: PNG })));
  await expect(page.locator('#toast')).toContainText('до 4 файлов');
  expect(app.uploads).toHaveLength(1);
  expect(app.sends).toEqual([]);
});

test('shell sessions hide image attachment controls', async ({ app, page }) => {
  await app.open({ active: 'shell' });
  await expect(page.locator('#b_attach')).toBeHidden();
  await page.locator('#msg').fill('pwd');
  await page.locator('#b_send').click();
  await expect(page.locator('#send_state')).toContainText('Отправлено');
  expect(app.sends[0].name).toBe('shell');
});
