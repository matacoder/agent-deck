const { test, expect } = require('./fixtures');

// A tone stands in for the microphone, so recording, cutting and saving run as on a phone.
async function fakeMicrophone(page) {
  await page.addInitScript(() => {
    // WebKit ignores a plain assignment to this method.
    Object.defineProperty(MediaDevices.prototype, 'getUserMedia', { configurable: true, value: async () => {
      const context = new AudioContext(), tone = context.createOscillator(), gain = context.createGain();
      const out = context.createMediaStreamDestination();
      gain.gain.value = 0.3; tone.connect(gain).connect(out); tone.start();
      return out.stream;
    } });
  });
}

async function recogniser(page, answer) {
  const pieces = [];
  await page.route('https://panel.test/api/voice_status', route => route.fulfill({ contentType: 'application/json',
    body: JSON.stringify({ voice: { ready: true, binary: true, model: true, phase: 'idle' } }) }));
  await page.route('https://panel.test/api/transcribe', route => {
    const body = route.request().postDataJSON(); pieces.push(body);
    const [status, reply] = answer(pieces.length);
    return route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(reply) });
  });
  return pieces;
}

async function dictate(page, ms) {
  await page.locator('#b_mic').click();
  await expect(page.locator('#b_mic')).toHaveAttribute('aria-pressed', 'true');
  await page.waitForTimeout(ms);
  await page.locator('#b_mic').click();
  await expect(page.locator('#b_mic')).toHaveAttribute('aria-pressed', 'false');
}

test('dictated speech is recognised and joins the draft', async ({ app }) => {
  const { page } = app;
  await fakeMicrophone(page);
  const pieces = await recogniser(page, () => [200, { ok: true, text: 'запушь в main' }]);
  await app.open();
  await page.locator('#msg').fill('Готово?');
  await dictate(page, 2500);
  await expect(page.locator('#msg')).toHaveValue('Готово? запушь в main');
  expect(pieces).toHaveLength(1);
  const wav = Buffer.from(pieces[0].audio, 'base64');
  expect(wav.subarray(0, 4).toString()).toBe('RIFF');
  expect(wav.readUInt32LE(24)).toBe(16000);
  expect(wav.length).toBeGreaterThan(44 + 32000);  // At least a second of speech.
  await expect(page.locator('#voice_state')).toBeHidden();
});

test('a recording the computer could not recognise survives a reload', async ({ app }) => {
  const { page } = app;
  await fakeMicrophone(page);
  let down = true;
  const pieces = await recogniser(page, () => down ? [503, { error: 'Remote DeckAway is unavailable' }] : [200, { ok: true, text: 'не потерялось' }]);
  await app.open();
  await dictate(page, 2000);
  await expect(page.locator('#voice_state')).toContainText('Запись сохранена');
  expect(pieces.length).toBeGreaterThan(0);
  down = false;
  await page.reload();
  await expect(page.locator('#msg')).toHaveValue('не потерялось');
  // The dictation is kept, so a draft lost with the tab can be put back.
  await page.locator('#b_mic').dispatchEvent('contextmenu');
  await expect(page.locator('#voice_texts')).toContainText('не потерялось');
});
