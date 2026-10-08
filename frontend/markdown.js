// Small Markdown reader for project files (plans, READMEs): headings, lists, quotes, code, tables, links.
// Built from DOM nodes with textContent only; links open just http(s) and mailto, raw HTML stays text.
// Bundled before app.js; nothing here runs at load time.
const MD_LINK=/^(https?:|mailto:)/i;
function mdNode(doc,tag,...kids){const node=doc.createElement(tag);node.append(...kids);return node}
// **bold**, *italic*, `code`, [text](url) and bare URLs; anything else is plain text.
function mdInline(doc,text){
  const out=[],re=/(`+)([^`]|[^`].*?[^`])\1|\*\*(.+?)\*\*|__(.+?)__|\*(\S(?:.*?\S)?)\*|\[([^\]]+)\]\(([^)\s]+)\)|(https?:\/\/[^\s<>()]+)/g;
  let last=0,m;
  while((m=re.exec(text))){
    if(m.index>last)out.push(text.slice(last,m.index));
    if(m[2]!==undefined)out.push(mdNode(doc,"code",m[2]));
    else if(m[3]!==undefined||m[4]!==undefined)out.push(mdNode(doc,"strong",...mdInline(doc,m[3]??m[4])));
    else if(m[5]!==undefined)out.push(mdNode(doc,"em",...mdInline(doc,m[5])));
    else out.push(mdLink(doc,m[6]??m[8],m[7]??m[8]));
    last=re.lastIndex;
  }
  if(last<text.length)out.push(text.slice(last));
  return out;
}
function mdLink(doc,label,url){
  if(!MD_LINK.test(url))return mdNode(doc,"span",label);  // Relative links point into the repository, not the panel.
  const a=mdNode(doc,"a",label);a.href=url;a.target="_blank";a.rel="noopener noreferrer";return a;
}
function mdCells(line){return line.trim().replace(/^\||\|$/g,"").split("|").map(cell=>cell.trim())}
function mdTable(doc,lines){
  const table=mdNode(doc,"table"),head=mdNode(doc,"tr",...mdCells(lines[0]).map(c=>mdNode(doc,"th",...mdInline(doc,c))));
  table.append(mdNode(doc,"thead",head));
  const body=mdNode(doc,"tbody");
  for(const line of lines.slice(2))body.append(mdNode(doc,"tr",...mdCells(line).map(c=>mdNode(doc,"td",...mdInline(doc,c)))));
  table.append(body);const wrap=mdNode(doc,"div",table);wrap.className="md-table";return wrap;
}
const MD_BREAK=/^(#{1,6}\s|```|~~~|>|\s*([-*+]|\d+[.)])\s|\s*([-*_]\s*){3,}$)/;
function renderMarkdown(text,doc=document){
  const root=doc.createElement("div"),lines=text.replace(/\r\n?/g,"\n").split("\n");
  root.className="md";
  for(let i=0;i<lines.length;){
    const line=lines[i];
    if(!line.trim()){i++;continue}
    const fence=line.match(/^\s*(```|~~~)/);
    if(fence){
      const code=[];i++;
      while(i<lines.length&&!lines[i].trim().startsWith(fence[1]))code.push(lines[i++]);
      i++;root.append(mdNode(doc,"pre",mdNode(doc,"code",code.join("\n"))));continue;
    }
    // One greedy group, trimmed afterwards: a lazy group between optional spaces backtracks for seconds
    // on a long run of spaces.
    const heading=line.match(/^(#{1,6})\s+(.*)$/);
    if(heading){root.append(mdNode(doc,"h"+heading[1].length,...mdInline(doc,heading[2].trimEnd().replace(/(^|\s)#+$/,"").trimEnd())));i++;continue}
    if(/^\s*([-*_]\s*){3,}$/.test(line)){root.append(doc.createElement("hr"));i++;continue}
    if(line.includes("|")&&/^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/.test(lines[i+1]||"")){
      const rows=[line,lines[i+1]];i+=2;
      while(i<lines.length&&lines[i].includes("|")&&lines[i].trim())rows.push(lines[i++]);
      root.append(mdTable(doc,rows));continue;
    }
    if(line.startsWith(">")){
      const quote=[];
      while(i<lines.length&&lines[i].startsWith(">"))quote.push(lines[i++].replace(/^>\s?/,""));
      root.append(mdNode(doc,"blockquote",...renderMarkdown(quote.join("\n"),doc).childNodes));continue;
    }
    const item=line.match(/^\s*([-*+]|\d+[.)])\s+(.*)$/);
    if(item){
      const list=doc.createElement(/\d/.test(item[1])?"ol":"ul");
      while(i<lines.length){
        const next=lines[i].match(/^\s*([-*+]|\d+[.)])\s+(.*)$/);
        if(next){
          const task=next[2].match(/^\[([ xX])\]\s+(.*)$/),li=mdNode(doc,"li",...mdInline(doc,task?task[2]:next[2]));
          if(task)li.prepend(task[1]===" "?"☐ ":"☑ ");
          list.append(li);i++;
        }else if(lines[i].trim()&&/^\s{2,}/.test(lines[i])&&list.lastChild){list.lastChild.append(" ",...mdInline(doc,lines[i].trim()));i++}
        else break;
      }
      root.append(list);continue;
    }
    const para=[line.trim()];i++;
    while(i<lines.length&&lines[i].trim()&&!MD_BREAK.test(lines[i]))para.push(lines[i++].trim());
    root.append(mdNode(doc,"p",...mdInline(doc,para.join(" "))));
  }
  return root;
}
function isMarkdown(path){return /\.(md|markdown|mdx)$/i.test(path)}

if(typeof module!=="undefined")module.exports={renderMarkdown,isMarkdown};
