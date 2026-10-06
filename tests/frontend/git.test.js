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

test('text that looks like markup stays text',()=>{
  const rows=diffRows('@@ -0,0 +1 @@\n+<img src=x onerror=alert(1)>');
  expect(rows[1]).toEqual({kind:'add',old:'',new:1,text:'<img src=x onerror=alert(1)>'});
});
