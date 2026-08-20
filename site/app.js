let DATA=[],kind='rune';
const fmt=v=>v==null?'—':Number(v).toLocaleString(undefined,{maximumFractionDigits:2});
const RUNES=[['艾爾','El',11],['艾德','Eld',11],['特爾','Tir',13],['那夫','Nef',13],['愛斯','Eth',15],['伊司','Ith',15],['塔爾','Tal',17],['拉爾','Ral',19],['歐特','Ort',21],['書爾','Thul',23],['安姆','Amn',25],['索爾','Sol',27],['夏','Shael',29],['多爾','Dol',31],['海爾','Hel',0],['埃歐','Io',35],['盧姆','Lum',37],['科','Ko',39],['法爾','Fal',41],['藍姆','Lem',43],['普爾','Pul',45],['烏姆','Um',47],['馬爾','Mal',49],['伊司特','Ist',51],['古爾','Gul',53],['伐克斯','Vex',55],['歐姆','Ohm',57],['羅','Lo',59],['瑟','Sur',61],['貝','Ber',63],['喬','Jah',65],['查姆','Cham',67],['薩德','Zod',69]];

function runePos(i){const col=i%11,row=Math.floor(i/11);return `calc(var(--rune-w) * -${col}) calc(var(--rune-h) * -${row})`}

async function load(){
  try{
    const r=await fetch('../data/market.json?'+Date.now(),{cache:'no-store'});
    const d=await r.json();DATA=d.market||[];
    document.querySelector('#status').textContent=d.updated_at?'更新 '+new Date(d.updated_at).toLocaleString('zh-TW'):'等待第一次爬取';render();
  }catch(e){document.querySelector('#status').textContent='等待市場資料';render()}
}
function marketFor(en){return DATA.find(x=>x.kind==='rune'&&((x.id||'').toLowerCase()===en.toLowerCase()||(x.label||'').toLowerCase()===en.toLowerCase()))||{}}
function render(){
  const q=document.querySelector('#q').value.toLowerCase();
  if(kind==='rune'){
    const rows=RUNES.map((r,i)=>({r,i,x:marketFor(r[1])})).filter(o=>(o.r.join(' ')+' '+(o.x.label||'')).toLowerCase().includes(q));
    document.querySelector('#cards').innerHTML=rows.map(({r,i,x})=>`<article class="card"><div class="rune-icon" style="background-position:${runePos(i)}" aria-label="${r[1]} rune"></div><div class="rune-name"><h2>${r[0]} <small>${r[1]} (${i+1})</small></h2><div class="level">等級 · ${r[2]}</div></div><div class="market"><div class="fair">${fmt(x.fair_fg)} <span class="unit">FG</span></div><div class="stats"><div class="stat"><span>ISO 買價</span><b>${fmt(x.iso_fg)}</b></div><div class="stat"><span>FT / BIN</span><b>${fmt(x.ft_fg)}</b></div><div class="stat"><span>成交 / T4T</span><b>${fmt(x.trade_fg)}</b></div></div><div class="meta"><span>樣本 ${x.samples||0}</span><span>可信度 ${x.confidence||'—'}</span></div><div class="sources">${(x.sources||[]).slice(0,2).map(s=>`<a href="${s.url}" target="_blank" rel="noreferrer">${s.title}</a>`).join('')}</div></div></article>`).join('')
  }else{
    const rows=DATA.filter(x=>x.kind==='item'&&(x.label||'').toLowerCase().includes(q));
    document.querySelector('#cards').innerHTML=rows.length?rows.map(x=>`<article class="card item-card"><h2>${x.label}</h2><div class="fair">${fmt(x.fair_fg)} <span class="unit">FG</span></div><div class="meta"><span>樣本 ${x.samples||0}</span><span>可信度 ${x.confidence||'—'}</span></div></article>`).join(''):'<p>目前沒有自訂裝備資料。</p>'
  }
}
document.querySelectorAll('button[data-kind]').forEach(b=>b.onclick=()=>{kind=b.dataset.kind;document.querySelectorAll('button[data-kind]').forEach(x=>x.classList.toggle('active',x===b));render()});
document.querySelector('#q').oninput=render;load();
