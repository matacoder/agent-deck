const {downsample,cutPoint,hasSpeech,encodeWav,joinDictation,voicePieceKey,bytesToBase64,VOICE_RATE}=require('../../frontend/voice-audio');

const tone=(seconds,level=0.5)=>Float32Array.from({length:seconds*VOICE_RATE},(_,i)=>level*Math.sin(i/5));

test('the recording is written as the 16 kHz mono 16-bit WAV the recogniser accepts',()=>{
  const bytes=encodeWav(Float32Array.from([0,1,-1,2])),view=new DataView(bytes.buffer);
  expect(String.fromCharCode(...bytes.slice(0,4))+String.fromCharCode(...bytes.slice(8,16))).toBe('RIFFWAVEfmt ');
  expect([view.getUint16(20,true),view.getUint16(22,true),view.getUint32(24,true),view.getUint16(34,true)]).toEqual([1,1,16000,16]);
  expect(view.getUint32(40,true)).toBe(8);
  // Out-of-range samples are clipped, never wrapped into the opposite sign.
  expect([1,2,3].map(i=>view.getInt16(44+i*2,true))).toEqual([32767,-32768,32767]);
});

test('a 48 kHz microphone becomes 16 kHz by averaging',()=>{
  const out=downsample(Float32Array.from([3,3,3,6,6,6]),48000);
  expect(Array.from(out)).toEqual([3,6]);
  expect(downsample(new Float32Array(44100),44100).length).toBe(16000);
});

test('a piece is cut at the pause, not in the middle of a word',()=>{
  const samples=tone(18);
  samples.fill(0,13*VOICE_RATE,13*VOICE_RATE+VOICE_RATE/5);  // A fifth of a second of silence after 13 s.
  const cut=cutPoint(samples);
  expect(cut).toBeGreaterThanOrEqual(13*VOICE_RATE);
  expect(cut).toBeLessThanOrEqual(13*VOICE_RATE+VOICE_RATE/5);
  // Without a pause the piece still ends by the longest length.
  expect(cutPoint(tone(25))).toBeLessThanOrEqual(18*VOICE_RATE);
});

test('silence is never sent, since whisper would invent words for it',()=>{
  expect(hasSpeech(new Float32Array(VOICE_RATE*5))).toBe(false);
  expect(hasSpeech(tone(5,0.001))).toBe(false);
  expect(hasSpeech(tone(1))).toBe(true);
});

test('dictated text joins the draft with one space',()=>{
  expect(joinDictation('','Hello')).toBe('Hello');
  expect(joinDictation('Fix it','now')).toBe('Fix it now');
  expect(joinDictation('Fix it\n','now')).toBe('Fix it\nnow');
  expect(joinDictation('Fix it','')).toBe('Fix it');
});

test('pieces sort in the order they were spoken',()=>{
  const keys=[voicePieceKey('1760000000000',10),voicePieceKey('1760000000000',9),voicePieceKey('1760000000000',100)];
  expect([...keys].sort()).toEqual([keys[1],keys[0],keys[2]]);
});

test('large recordings are encoded to base64 without overflowing the call stack',()=>{
  const bytes=new Uint8Array(600000).map((_,i)=>i%256);
  expect(Buffer.from(bytesToBase64(bytes),'base64').equals(Buffer.from(bytes))).toBe(true);
});
