function instancePath(identity,path){
  if(!identity)return path;
  if(!/^[0-9a-f]{24}$/.test(identity))throw new Error('Invalid Agent Deck identifier');
  if(!path.startsWith('/api/')&&!path.startsWith('/t/'))throw new Error('Invalid instance path');
  return '/deck/'+identity+path;
}
function instanceStorage(storage,identity){
  const key=name=>identity?'deck.'+identity+'.'+name:name;
  return {getItem:name=>storage.getItem(key(name)),setItem:(name,value)=>storage.setItem(key(name),value),removeItem:name=>storage.removeItem(key(name))};
}
function populateDeckSelector(select,decks,current,localName){
  select.replaceChildren();
  for(const deck of [{id:'',name:localName},...decks]){
    const option=document.createElement('option');option.value=deck.id;option.textContent=deck.name;select.append(option);
  }
  select.value=current;
}
function panelLinkTarget(raw,{browserOrigin,panelOrigins,identity=""}){
  let url;
  try{url=new URL(raw)}catch(e){return raw}
  if(url.username||url.password||!panelOrigins.includes(url.origin))return raw;
  if(url.pathname==="/"||url.pathname==="/login")return browserOrigin+"/"+url.search+url.hash;
  if(url.pathname.startsWith("/t/"))return browserOrigin+instancePath(identity,url.pathname+url.search)+url.hash;
  return raw;
}

if(typeof module!=='undefined')module.exports={instancePath,instanceStorage,populateDeckSelector,panelLinkTarget};
