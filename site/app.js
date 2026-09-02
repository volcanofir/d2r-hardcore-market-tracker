let DATA=[],CATALOG=[],kind='rune',runeCollapsed=true,itemCollapsed=true,openItemGroups=new Set(),openItemSubgroups=new Set();
const fmt=v=>v==null?'—':Number(v).toLocaleString(undefined,{maximumFractionDigits:2});
const esc=s=>String(s??'').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m]));
const RUNES=[['艾爾','El',11],['艾德','Eld',11],['特爾','Tir',13],['那夫','Nef',13],['愛斯','Eth',15],['伊司','Ith',15],['塔爾','Tal',17],['拉爾','Ral',19],['歐特','Ort',21],['書爾','Thul',23],['安姆','Amn',25],['索爾','Sol',27],['夏','Shael',29],['多爾','Dol',31],['海爾','Hel',0],['埃歐','Io',35],['盧姆','Lum',37],['科','Ko',39],['法爾','Fal',41],['藍姆','Lem',43],['普爾','Pul',45],['烏姆','Um',47],['馬爾','Mal',49],['伊司特','Ist',51],['古爾','Gul',53],['伐克斯','Vex',55],['歐姆','Ohm',57],['羅','Lo',59],['瑟','Sur',61],['貝','Ber',63],['喬','Jah',65],['查姆','Cham',67],['薩德','Zod',69]];
const RUNE_SPRITE='https://raw.githubusercontent.com/fabd/diablo2-runewizard/main/src/assets/images/runes-sprite.png?v=20260827-ghsprite1';
const ICON_SIZE=72,SPRITE_W=792,SPRITE_H=216;
const WEAPON_TYPES=new Set(['武器','刀劍','匕首','斧','長柄','長矛','短棒','釘鎚','重槌','權杖','法杖','法珠','魔杖','拳刃','弓','弩','標槍','投擲武器']);
function runeStyle(i){const col=i%11,row=Math.floor(i/11),x=-(col*ICON_SIZE),y=-(row*ICON_SIZE);return `width:${ICON_SIZE}px;height:${ICON_SIZE}px;background-image:url('${RUNE_SPRITE}');background-repeat:no-repeat;background-size:${SPRITE_W}px ${SPRITE_H}px;background-position:${x}px ${y}px;background-color:transparent;`}
async function load(){
  try{
    const stamp=Date.now();
    const [marketRes,catalogRes]=await Promise.all([
      fetch('../data/market.json?'+stamp,{cache:'no-store'}),
      fetch('../data/catalog.json?'+stamp,{cache:'no-store'}).catch(()=>null)
    ]);
    const d=await marketRes.json();DATA=d.market||[];
    if(catalogRes&&catalogRes.ok){const c=await catalogRes.json();CATALOG=c.items||[]}
    if(!CATALOG.length)CATALOG=DATA.filter(x=>x.kind==='item').map(x=>({id:x.id,label:x.label,category:x.category||'其他',aliases:[]}));
    document.querySelector('#status').textContent=d.updated_at?'更新 '+new Date(d.updated_at).toLocaleString('zh-TW'):'等待第一次爬取';render();
  }catch(e){document.querySelector('#status').textContent='等待市場資料';render()}
}
function marketFor(en){return DATA.find(x=>x.kind==='rune'&&((x.id||'').toLowerCase()===en.toLowerCase()||(x.label||'').toLowerCase()===en.toLowerCase()))||{}}
function itemMarket(id){return DATA.find(x=>x.kind==='item'&&x.id===id)||{}}
function updateMarketToggle(){
  const t=document.querySelector('#rune-toggle');
  const collapsed=kind==='rune'?runeCollapsed:itemCollapsed;
  const label=kind==='rune'?'符文':'裝備';
  t.hidden=false;
  t.setAttribute('aria-expanded',String(!collapsed));
  t.innerHTML=collapsed?`展開${label}行情 <span>⌄</span>`:`收起${label}行情 <span>⌃</span>`;
}
function sampleLinks(x){
  const unique=[];
  for(const s of (x.sources||[])){
    if(!s||!s.url||unique.some(u=>u.url===s.url))continue;
    unique.push(s);
  }
  if(!unique.length)return '';
  const links=unique.map((s,i)=>{
    const side=s.side==='trade'?'T4T / 成交':s.side==='ft'?'FT / BIN':s.side==='iso'?'ISO':'樣本';
    return `<a class="sample-link" href="${esc(s.url)}" target="_blank" rel="noopener noreferrer"><span class="sample-index">${i+1}</span><span class="sample-main"><b>${esc(s.title||'市場樣本')}</b><small>${side}${s.price_fg!=null?' · '+fmt(s.price_fg)+' FG':''}</small></span><span class="sample-open">↗</span></a>`;
  }).join('');
  return `<details class="sample-links"><summary>查看樣本 <span>${unique.length}</span></summary><div class="sample-list">${links}</div></details>`;
}
function slotName(raw){
  raw=(raw||'其他').replace(/^套裝/,'').trim()||'其他';
  if(raw==='護甲'||raw==='胸甲')return '衣服';
  if(raw==='鞋子'||raw==='靴子')return '靴子';
  if(WEAPON_TYPES.has(raw))return '武器';
  return raw;
}
function baseParts(item){
  const id=(item.id||'').toLowerCase();
  if(/base-(ap|ds|mp|eth-armor)/.test(id))return {parent:'衣服',subgroup:'符文之語底材'};
  if(/base-(monarch|pally)/.test(id))return {parent:'盾牌',subgroup:'符文之語底材'};
  return {parent:'武器',subgroup:'符文之語底材'};
}
function categoryParts(item){
  if(item.d2r_world_set_group)return {parent:'完整套裝',subgroup:'完整套裝'};
  if(item.d2r_world_set){
    const raw=(item.d2r_world_set.category||item.category||'其他').replace(/^套裝/,'');
    const parent=slotName(raw);
    return {parent,subgroup:`套裝${parent}`};
  }
  if(item.d2r_world){
    const raw=item.d2r_world.category||item.category||'其他';
    const parent=slotName(raw);
    if(WEAPON_TYPES.has(raw))return {parent:'武器',subgroup:raw==='武器'?'獨特武器':`獨特${raw}`};
    return {parent,subgroup:`獨特${parent}`};
  }
  const raw=(item.category||'其他').trim()||'其他';
  if(raw==='熱門符文之語鑲底')return baseParts(item);
  if(raw==='熱門護身符與暗金符咒')return {parent:'咒符',subgroup:(item.id||'').includes('torch')?'地獄火炬':'獨特咒符'};
  if(raw==='技能超大護身符')return {parent:'咒符',subgroup:'技能超大護身符'};
  if(raw==='熱門小護身符')return {parent:'咒符',subgroup:'小護身符'};
  if(raw==='熱門套裝部件')return (item.id||'').endsWith('-set')?{parent:'完整套裝',subgroup:'完整套裝'}:{parent:'套裝',subgroup:'套裝'};
  if(raw==='戒指與護身符'){
    const rings=new Set(['soj','bk-ring','raven-frost']);
    return rings.has(item.id)?{parent:'戒指',subgroup:'獨特戒指'}:{parent:'護身符',subgroup:'獨特護身符'};
  }
  if(raw.startsWith('套裝')){const parent=slotName(raw);return {parent,subgroup:`套裝${parent}`}}
  const parent=slotName(raw);
  if(WEAPON_TYPES.has(raw))return {parent:'武器',subgroup:'獨特武器'};
  return {parent,subgroup:`獨特${parent}`};
}
function itemCard(item){
  const x=itemMarket(item.id),has=x.fair_fg!=null,part=categoryParts(item);
  return `<article class="item-card"><div class="item-head"><div><div class="item-category">${part.subgroup}</div><h2>${item.label}</h2></div><span class="item-state">${has?(x.confidence||'low'):'待樣本'}</span></div><div class="fair item-fair">${has?fmt(x.fair_fg)+' <span class="unit">FG</span>':'—'}</div><div class="stats"><div class="stat"><span>ISO 買價</span><b>${fmt(x.iso_fg)}</b></div><div class="stat"><span>FT / BIN</span><b>${fmt(x.ft_fg)}</b></div><div class="stat"><span>成交 / T4T</span><b>${fmt(x.trade_fg)}</b></div></div><div class="meta"><span>樣本 ${x.samples||0}</span><span>${has?'可信度 '+(x.confidence||'low'):'等待可靠行情'}</span></div>${sampleLinks(x)}</article>`
}
function renderItems(q,cards){
  const rows=CATALOG.filter(item=>{
    const part=categoryParts(item);
    return ((item.label||'')+' '+(item.category||'')+' '+part.parent+' '+part.subgroup+' '+(item.aliases||[]).join(' ')).toLowerCase().includes(q);
  });
  if(!rows.length){cards.innerHTML='<p class="empty">找不到符合的裝備。</p>';return}
  const parents=[];
  for(const item of rows){
    const part=categoryParts(item);
    let parent=parents.find(x=>x.name===part.parent);
    if(!parent){parent={name:part.parent,groups:[]};parents.push(parent)}
    let subgroup=parent.groups.find(x=>x.name===part.subgroup);
    if(!subgroup){subgroup={name:part.subgroup,items:[]};parent.groups.push(subgroup)}
    subgroup.items.push(item);
  }
  cards.innerHTML=parents.map(parent=>{
    const total=parent.groups.reduce((n,g)=>n+g.items.length,0);
    const flat=parent.groups.length===1&&parent.groups[0].name===parent.name;
    if(flat){
      const g=parent.groups[0],open=!!q||openItemGroups.has(parent.name),key=encodeURIComponent(parent.name);
      return `<section class="item-group${open?' open':''}"><button class="item-group-title" type="button" data-group="${key}" aria-expanded="${open}"><h2>${parent.name}</h2><div class="item-group-side"><span class="item-count">${g.items.length}</span><b>${open?'⌃':'⌄'}</b></div></button><div class="item-grid${open?'':' group-collapsed'}">${open?g.items.map(itemCard).join(''):''}</div></section>`;
    }
    const parentOpen=!!q||openItemGroups.has(parent.name),parentKey=encodeURIComponent(parent.name);
    const subgroups=parent.groups.map(g=>{
      const subKey=`${parent.name}::${g.name}`,subOpen=!!q||openItemSubgroups.has(subKey),encoded=encodeURIComponent(subKey);
      return `<section style="margin:0 0 8px 12px"><button class="item-group-title" type="button" data-subgroup="${encoded}" aria-expanded="${subOpen}" style="background:#0d0f10"><h2>${g.name}</h2><div class="item-group-side"><span class="item-count">${g.items.length}</span><b>${subOpen?'⌃':'⌄'}</b></div></button><div class="item-grid${subOpen?'':' group-collapsed'}" style="${subOpen?'margin-top:9px':''}">${subOpen?g.items.map(itemCard).join(''):''}</div></section>`;
    }).join('');
    return `<section class="item-group"><button class="item-group-title" type="button" data-group="${parentKey}" aria-expanded="${parentOpen}"><h2>${parent.name}</h2><div class="item-group-side"><span class="item-count">${total}</span><b>${parentOpen?'⌃':'⌄'}</b></div></button><div class="${parentOpen?'':'group-collapsed'}" style="${parentOpen?'margin-top:9px':''}">${parentOpen?subgroups:''}</div></section>`;
  }).join('');
  cards.querySelectorAll('button[data-group]').forEach(btn=>btn.onclick=()=>{
    const name=decodeURIComponent(btn.dataset.group||'');
    if(openItemGroups.has(name))openItemGroups.delete(name);else openItemGroups.add(name);
    render();
  });
  cards.querySelectorAll('button[data-subgroup]').forEach(btn=>btn.onclick=()=>{
    const name=decodeURIComponent(btn.dataset.subgroup||'');
    if(openItemSubgroups.has(name))openItemSubgroups.delete(name);else openItemSubgroups.add(name);
    render();
  });
}
function render(){
  const q=document.querySelector('#q').value.toLowerCase().trim();
  const cards=document.querySelector('#cards');
  updateMarketToggle();
  if(kind==='rune'){
    cards.classList.remove('item-mode');
    if(runeCollapsed){cards.classList.add('collapsed');cards.innerHTML='';return}
    cards.classList.remove('collapsed');
    const rows=RUNES.map((r,i)=>({r,i,x:marketFor(r[1])})).filter(o=>(o.r.join(' ')+' '+(o.x.label||'')).toLowerCase().includes(q));
    cards.innerHTML=rows.map(({r,i,x})=>`<article class="card"><div class="rune-icon" style="${runeStyle(i)}" aria-label="${r[1]} rune"></div><div class="rune-name"><h2>${r[0]} <small>${r[1]} (${i+1})</small></h2><div class="level">等級 · ${r[2]}</div></div><div class="market"><div class="fair">${fmt(x.fair_fg)} <span class="unit">FG</span></div><div class="stats"><div class="stat"><span>ISO 買價</span><b>${fmt(x.iso_fg)}</b></div><div class="stat"><span>FT / BIN</span><b>${fmt(x.ft_fg)}</b></div><div class="stat"><span>成交 / T4T</span><b>${fmt(x.trade_fg)}</b></div></div><div class="meta"><span>樣本 ${x.samples||0}</span><span>可信度 ${x.confidence||'—'}</span></div>${sampleLinks(x)}</div></article>`).join('')
  }else{
    cards.classList.add('item-mode');
    if(itemCollapsed){cards.classList.add('collapsed');cards.innerHTML='';return}
    cards.classList.remove('collapsed');renderItems(q,cards)
  }
}
document.querySelector('#rune-toggle').onclick=()=>{if(kind==='rune')runeCollapsed=!runeCollapsed;else itemCollapsed=!itemCollapsed;render()};
document.querySelectorAll('button[data-kind]').forEach(b=>b.onclick=()=>{kind=b.dataset.kind;document.querySelectorAll('button[data-kind]').forEach(x=>x.classList.toggle('active',x===b));render()});
document.querySelector('#q').oninput=()=>{const hasQuery=document.querySelector('#q').value.trim();if(hasQuery){if(kind==='rune')runeCollapsed=false;else itemCollapsed=false}render()};
load();
