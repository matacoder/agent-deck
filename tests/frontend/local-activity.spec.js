const { test, expect } = require('./fixtures');

test('local activity updates from prefill to streaming and retains last response', async ({ app, page }) => {
  app.lmstudio.profiles = [{id:'local',name:'RED',performance:{source:'session',model:'local-model',output_tokens:42,tokens_per_second:8.5},activity:[{phase:'waiting',model:'local-model',request_time_seconds:12,chunks:0}]}];
  await app.open({width:1280,height:900});
  const block=page.locator('.local-usage');
  await expect(block).toContainText('TTFT');
  await expect(block).toContainText('0:12');
  await expect(block.locator('.local-rate')).toHaveAttribute('title',/Последний ответ/);
  await expect(block).toContainText('8.5');
  app.lmstudio.profiles[0].activity[0]={phase:'thinking',model:'local-model',request_time_seconds:20,chunks:15};
  await expect(block).toContainText('✦');
  await expect(block).toContainText('15 Δ');
  app.lmstudio.profiles[0].activity=[];
  await expect(block).not.toHaveAttribute('aria-busy','true');
  await expect(block).toContainText('42');
});
