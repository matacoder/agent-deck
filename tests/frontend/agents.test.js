const {AGENT_LIST,agentCommands,pickableAgents}=require('../../frontend/agents');
const {providerSources}=require('../../frontend/providers');

test('each agent is listed once and names its own commands',()=>{
  const ids=AGENT_LIST.map(a=>a.id);
  expect(new Set(ids).size).toBe(ids.length);
  expect(agentCommands('claude').map(c=>c.text)).toEqual(['/compact','/clear']);
  expect(agentCommands('codex').map(c=>c.text)).toEqual(['/compact','/new']);
  expect(agentCommands('cursor').map(c=>c.text)).toEqual(['/summarize','/clear']);
  expect(agentCommands('gemini')[0]).toEqual({label:'/compress',text:'/compress',compact:true});
  // Only the command that drops the conversation asks first.
  for(const agent of ids.filter(a=>agentCommands(a).length))expect(agentCommands(agent).map(c=>Boolean(c.confirm))).toEqual([false,true]);
  for(const agent of ['kimi','pi','shell','nobody'])expect(agentCommands(agent)).toEqual([]);
});

test('the new session dialog offers a terminal-only agent once it is installed',()=>{
  const built=['claude','codex','kimi','pi','shell'];
  expect(pickableAgents({}).map(a=>a.id)).toEqual(built);
  expect(pickableAgents(undefined).map(a=>a.id)).toEqual(built);
  expect(pickableAgents({gemini:{installed:true},qwen:{installed:false},opencode:{installed:true}}).map(a=>a.id))
    .toEqual(['claude','codex','kimi','gemini','opencode','pi','shell']);
});

test('Claude Code is offered a saved service only while it has a key',()=>{
  const list=[{id:'a1',name:'GLM',model:'glm-5.3',configured:true},{id:'b2',name:'Other',model:'m',configured:false}];
  expect(providerSources(list)).toEqual([[{kind:'provider',provider:'a1',model:'glm-5.3'},'GLM · glm-5.3']]);
  expect(providerSources([])).toEqual([]);
});
