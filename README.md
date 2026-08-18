# D2R Hardcore Ladder Market Tracker

自動追蹤 d2jsp **D2:R RotW Hardcore Ladder Trading (f=123)** 的公開市場資訊。

## 功能
- El → Zod 共 33 種符文
- ISO 買價 / FT、BIN 賣價 / T4T 成交訊號
- FG 合理價格、樣本數、可信度
- 每筆資料可回查 d2jsp 原始文章
- 保留 7 日價格歷史
- 自訂裝備監控，支援 roll-aware aliases（預設 Griffon's 20/15、CTA）

## 自動更新
`.github/workflows/update-market.yml` 每 3 小時執行一次，也支援 GitHub Actions 的 **Run workflow** 手動執行。

爬蟲會更新：
- `data/market.json`
- `data/history.json`

## 網站
靜態前端位於 `site/`，可部署至 Netlify。部署時將 Publish directory 指向 repository 根目錄（網站入口為 `/site/`），或後續將站點檔案搬至根目錄。

## 資料來源與注意事項
資料來源為公開 d2jsp forum f=123。價格由公開文章中的 ISO / FT / BIN / T4T 等訊號統計，屬市場參考，不代表保證成交價格。
