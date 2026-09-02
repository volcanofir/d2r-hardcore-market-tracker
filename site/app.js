let DATA=[],CATALOG=[],kind='rune',runeCollapsed=true;
const fmt=v=>v==null?'—':Number(v).toLocaleString(undefined,{maximumFractionDigits:2});
const RUNES=[['艾爾','El',11],['艾德','Eld',11],['特爾','Tir',13],['那夫','Nef',13],['愛斯','Eth',15],['伊司','Ith',15],['塔爾','Tal',17],['拉爾','Ral',19],['歐特','Ort',21],['書爾','Thul',23],['安姆','Amn',25],['索爾','Sol',27],['夏','Shael',29],['多爾','Dol',31],['海爾','Hel',0],['埃歐','Io',35],['盧姆','Lum',37],['科','Ko',39],['法爾','Fal',41],['藍姆','Lem',43],['普爾','Pul',45],['烏姆','Um',47],['馬爾','Mal',49],['伊司特','Ist',51],['古爾','Gul',53],['伐克斯','Vex',55],['歐姆','Ohm',57],['羅','Lo',59],['瑟','Sur',61],['貝','Ber',63],['喬','Jah',65],['查姆','Cham',67],['薩德','Zod',69]];
const RUNE_SPRITE='https://raw.githubusercontent.com/fabd/diablo2-runewizard/main/src/assets/images/runes-sprite.png?v=20260827-ghsprite1';
const ICON_SIZE=72,SPRITE_W=792,SPRITE_H=216;
function runeStyle(i){const col=i%11,row=Math.floor(i/11),x=-(col*ICON_SIZE),y=-(row*ICON_SIZE);return `width:${ICON_SIZE}px;height:${ICON_SIZE}px;background-image:url('${RUNE_SPRITE}');background-repeat:no-repeat;background-size:${SPRITE_W}px ${SPRITE_H}px;background-position:${x}px ${y}px;background-color:transparent;`}
async function load(){
  try{
    const stamp=Date.now();
    const [marketRes,catalogRes]=await Promise.all([
      fetch('../data/market.json?'+stamp,{cache:'no-store'}),
      fetch('../data/watchlist.json?'+stamp,{cache:'no-store'}).catch(()=>null)
    ]);
    const d=await marketRes.json();DATA=d.market||[];
    if(catalogRes&&catalogRes.ok){const c=await catalogRes.json();CATALOG=c.items||[]}
    if(!CATALOG.length)CATALOG=DATA.filter(x=>x.kind==='item').map(x=>({id:x.id,label:x.label,category:x.category||'其他',aliases:[]}));
    document.querySelector('#status').textContent=d.updated_at?'更新 '+new Date(d.updated_at).toLocaleString('zh-TW'):'等待第一次爬取';render();
  }catch(e){document.querySelector('#status').textContent='等待市場資料';render()}
}
function marketFor(en){return DATA.find(x=>x.kind==='rune'&&((x.id||'').toLowerCase()===en.toLowerCase()||(x.label||'').toLowerCase()===en.toLowerCase()))||{}}
function itemMarket(id){return DATA.find(x=>x.kind==='item'&&x.id===id)||{}}
function updateRuneToggle(){
  const t=document.querySelector('#rune-toggle');
  if(kind!=='rune'){t.hidden=true;return}
  t.hidden=false;
  t.setAttribute('aria-expanded',String(!runeCollapsed));
  t.innerHTML=runeCollapsed?'展開符文行情 <span>⌄</span>':'收起符文行情 <span>⌃</span>';
}
function itemCard(item){
  const x=itemMarket(item.id),has=x.fair_fg!=null;
  return `<article class="item-card"><div class="item-head"><div><div class="item-category">${item.category||'其他'}</div><h2>${item.label}</h2></div><span class="item-state">${has?(x.confidence||'low'):'待樣本'}</span></div><div class="fair item-fair">${has?fmt(x.fair_fg)+' <span class="unit">FG</span>':'—'}</div><div class="stats"><div class="stat"><span>ISO 買價</span><b>${fmt(x.iso_fg)}</b></div><div class="stat"><span>FT / BIN</span><b>${fmt(x.ft_fg)}</b></div><div class="stat"><span>成交 / T4T</span><b>${fmt(x.trade_fg)}</b></div></div><div class="meta"><span>樣本 ${x.samples||0}</span><span>${has?'可信度 '+(x.confidence||'low'):'等待可靠行情'}</span></div></article>`
}
function renderItems(q,cards){
  const rows=CATALOG.filter(item=>((item.label||'')+' '+(item.category||'')+' '+(item.aliases||[]).join(' ')).toLowerCase().includes(q));
  if(!rows.length){cards.innerHTML='<p class="empty">找不到符合的裝備。</p>';return}
  const groups=[];
  for(const item of rows){let g=groups.find(x=>x.name===(item.category||'其他'));if(!g){g={name:item.category||'其他',items:[]};groups.push(g)}g.items.push(item)}
  cards.innerHTML=groups.map(g=>`<section class="item-group"><div class="item-group-title"><h2>${g.name}</h2><span>${g.items.length}</span></div><div class="item-grid">${g.items.map(itemCard).join('')}</div></section>`).join('');
}
function render(){
  const q=document.querySelector('#q').value.toLowerCase().trim();
  const cards=document.querySelector('#cards');
  updateRuneToggle();
  if(kind==='rune'){
    cards.classList.remove('item-mode');
    if(runeCollapsed){cards.classList.add('collapsed');cards.innerHTML='';return}
    cards.classList.remove('collapsed');
    const rows=RUNES.map((r,i)=>({r,i,x:marketFor(r[1])})).filter(o=>(o.r.join(' ')+' '+(o.x.label||'')).toLowerCase().includes(q));
    cards.innerHTML=rows.map(({r,i,x})=>`<article class="card"><div class="rune-icon" style="${runeStyle(i)}" aria-label="${r[1]} rune"></div><div class="rune-name"><h2>${r[0]} <small>${r[1]} (${i+1})</small></h2><div class="level">等級 · ${r[2]}</div></div><div class="market"><div class="fair">${fmt(x.fair_fg)} <span class="unit">FG</span></div><div class="stats"><div class="stat"><span>ISO 買價</span><b>${fmt(x.iso_fg)}</b></div><div class="stat"><span>FT / BIN</span><b>${fmt(x.ft_fg)}</b></div><div class="stat"><span>成交 / T4T</span><b>${fmt(x.trade_fg)}</b></div></div><div class="meta"><span>樣本 ${x.samples||0}</span><span>可信度 ${x.confidence||'—'}</span></div></div></article>`).join('')
  }else{
    cards.classList.remove('collapsed');cards.classList.add('item-mode');renderItems(q,cards)
  }
}
document.querySelector('#rune-toggle').onclick=()=>{runeCollapsed=!runeCollapsed;render()};
document.querySelectorAll('button[data-kind]').forEach(b=>b.onclick=()=>{kind=b.dataset.kind;document.querySelectorAll('button[data-kind]').forEach(x=>x.classList.toggle('active',x===b));render()});
document.querySelector('#q').oninput=()=>{if(kind==='rune'&&runeCollapsed&&document.querySelector('#q').value.trim())runeCollapsed=false;render()};
load();
