import json, requests
from pathlib import Path

urls = [
  "https://forums.d2jsp.org/forum.php?c=2&f=123",
  "https://r.jina.ai/http://forums.d2jsp.org/forum.php?c=2&f=123",
  "https://r.jina.ai/https://forums.d2jsp.org/forum.php?c=2&f=123",
]
headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
out=[]
for u in urls:
    row={"url":u}
    try:
        r=requests.get(u,headers=headers,timeout=35,allow_redirects=True)
        row.update({"status":r.status_code,"final_url":r.url,"content_type":r.headers.get("content-type"),"bytes":len(r.text),"has_topic_php":"topic.php" in r.text,"sample":r.text[:2500]})
    except Exception as e:
        row["error"]=repr(e)
    out.append(row)
Path("data").mkdir(exist_ok=True)
Path("data/diagnostic.json").write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps([{k:v for k,v in x.items() if k!='sample'} for x in out],ensure_ascii=False,indent=2))
