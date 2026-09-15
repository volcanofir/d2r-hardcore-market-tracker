(() => {
  // 來源卡片只顯示 d2jsp 原始發文時間，不顯示爬蟲擷取時間。
  sampleLinks = function(x){
    const unique=[];
    for(const s of (x.sources||[])){
      if(!s||!s.url||unique.some(u=>u.url===s.url))continue;
      unique.push(s);
    }
    if(!unique.length)return '';
    const links=unique.map((s,i)=>{
      const side=s.side==='trade'?'T4T / 成交':s.side==='ft'?'FT / BIN':s.side==='iso'?'ISO':'來源';
      const timing=sourceDateText(s);
      return `<a class="sample-link" href="${esc(s.url)}" target="_blank" rel="noopener noreferrer"><span class="sample-index">${i+1}</span><span class="sample-main"><b>${esc(s.title||'市場來源')}</b><small>${side}${s.price_fg!=null?' · '+fmt(s.price_fg)+' FG':''}</small>${timing?`<small>${timing}</small>`:''}</span><span class="sample-open">↗</span></a>`;
    }).join('');
    return `<details class="sample-links"><summary>查看來源 <span>${unique.length}</span></summary><div class="sample-list">${links}</div></details>`;
  };

  if(typeof render==='function')render();
})();
