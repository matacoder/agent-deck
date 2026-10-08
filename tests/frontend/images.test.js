const {imageMatches,joinImageLines}=require('../../frontend/images');
const runs=text=>[{text,style:{}}];
const plain=line=>line.map(r=>r.text).join('');

test('finds absolute, home and relative screenshot paths but leaves web links alone',()=>{
 const text='Касса (/private/tmp/a/cashier_viewport.png) · shots/home.PNG, ~/Desktop/r.jpeg https://example.com/x.png';
 const url=text.indexOf('https');
 expect(imageMatches(text,[[url,text.length]]).map(m=>m.path)).toEqual(['/private/tmp/a/cashier_viewport.png','shots/home.PNG','~/Desktop/r.jpeg']);
 expect(imageMatches('report.pdf notes.png.bak archive.png-old')).toEqual([]);
});

test('glues a path the agent wrapped across lines, as in Codex output',()=>{
 const lines=[runs('  Касса (/private/tmp/padel-w1-cashier-'),runs('preview/cashier_viewport.png) · Отдельный экран'),runs('next line')];
 const joined=joinImageLines(lines);
 expect(joined.map(plain)).toEqual(['  Касса (/private/tmp/padel-w1-cashier-preview/cashier_viewport.png) · Отдельный экран','next line']);
 expect(imageMatches(plain(joined[0])).map(m=>m.path)).toEqual(['/private/tmp/padel-w1-cashier-preview/cashier_viewport.png']);
});

test('does not glue ordinary lines',()=>{
 const lines=[runs('see /tmp/done.png'),runs('next.png is separate'),runs('path /usr/lib/'),runs('and more text')];
 expect(joinImageLines(lines).map(plain)).toEqual(['see /tmp/done.png','next.png is separate','path /usr/lib/','and more text']);
});

test('an image that failed to load is not retried on every redraw for a while',()=>{
  const {imageMissing,missingImages}=require('../../frontend/images');
  global.selectedDeck='';
  missingImages.set('\ns\nshot.png',1000);
  expect(imageMissing('s','shot.png',1000+30*1000)).toBe(true);
  expect(imageMissing('other','shot.png',1000+30*1000)).toBe(false);
  global.selectedDeck='a'.repeat(24);
  expect(imageMissing('s','shot.png',1000+30*1000)).toBe(false);  // Another computer's session of the same name.
  global.selectedDeck='';
  expect(imageMissing('s','shot.png',1000+2*60*1000)).toBe(false);  // Tried again after a minute.
});
