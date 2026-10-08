const {diffRows}=require('../../frontend/git');

test('a unified diff becomes rows with old and new line numbers, headers dropped',()=>{
  const patch=['diff --git a/app.py b/app.py','index 1..2 100644','--- a/app.py','+++ b/app.py',
    '@@ -1,2 +1,3 @@ def main():',' a = 1','-b = 2','+b = 3','+c = 4','\\ No newline at end of file',''].join('\n');
  expect(diffRows(patch)).toEqual([
    {kind:'hunk',text:'@@ -1,2 +1,3 @@ def main():'},
    {kind:'ctx',old:1,new:1,text:'a = 1'},
    {kind:'del',old:2,new:'',text:'b = 2'},
    {kind:'add',old:'',new:2,text:'b = 3'},
    {kind:'add',old:'',new:3,text:'c = 4'}]);
});

test('source code opens by itself; tests, translations, docs and huge diffs stay folded',()=>{
  const {filesToOpen}=require('../../frontend/git');
  const file=(path,added=5)=>({path,added,removed:0});
  const open=filesToOpen([file('bot/migrations/schema_wait.py'),file('tests/unit/test_backward.py'),file('web/app.test.js'),
    file('locales/de.json'),file('README.md'),file('frontend/app.js'),file('src/huge.ts',900),file('static/vendor/lib.min.js'),file('e2e/login.spec.ts')]);
  expect([...open]).toEqual(['bot/migrations/schema_wait.py','frontend/app.js']);
  expect(filesToOpen(Array.from({length:12},(_,i)=>file('src/f'+i+'.py'))).size).toBe(8);
});

test('text that looks like markup stays text',()=>{
  const rows=diffRows('@@ -0,0 +1 @@\n+<img src=x onerror=alert(1)>');
  expect(rows[1]).toEqual({kind:'add',old:'',new:1,text:'<img src=x onerror=alert(1)>'});
});

test('authors get far-apart colours in turn and keep them',()=>{
  const store=new Map();global.localStore={getItem:k=>store.get(k)??null,setItem:(k,v)=>store.set(k,v)};
  const {authorColor,AUTHOR_COLORS}=require('../../frontend/git');
  const taken=new Map();
  expect(['Denis','Pavel','Anna'].map(n=>authorColor(n,taken))).toEqual(AUTHOR_COLORS.slice(0,3));
  expect(authorColor('Denis',taken)).toBe(AUTHOR_COLORS[0]);
  expect(JSON.parse(store.get('cc.author-colors'))).toEqual([['Denis',0],['Pavel',1],['Anna',2]]);
});
