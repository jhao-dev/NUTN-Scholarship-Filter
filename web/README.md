# 網站（Cloudflare Worker）

線上版：https://nutn-scholarship-filter.aqiao0718.workers.dev

- `public/index.html`：網頁（單一檔案）
- `src/index.js`：提供 `/api/data`、`/api/external`，每天從本專案的 `data/` 同步
- `wrangler.jsonc`：部署設定

部署（需要有權限的 Cloudflare 帳號）：

```bash
cd web
npx wrangler deploy --config wrangler.jsonc
```
