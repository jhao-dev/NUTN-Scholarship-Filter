// 提供公告資料給網頁，並每日從 GitHub 同步最新資料。
// 資料由 scraper/scrape.py（沿用 app.py 的判斷邏輯）每天產生並放在 GitHub 專案裡。
const BASE = "https://raw.githubusercontent.com/jhao-dev/NUTN-Scholarship-Filter/main/data/";
const FEEDS = {
  "/api/data": { key: "data-v3", file: "scholarships.json" },        // 南大公告
  "/api/external": { key: "external-v1", file: "external.json" },    // 外部資源
};
const STALE_MS = 36 * 3600e3;

async function pull(env, feed) {
  const r = await fetch(BASE + feed.file, { cf: { cacheTtl: 300 } });
  if (!r.ok) throw new Error(`GitHub ${r.status}`);
  const text = await r.text();
  const j = JSON.parse(text);
  if (!Array.isArray(j.items) || !j.updatedAt) throw new Error("資料格式不正確");
  await env.KV.put(feed.key, text);
  return text;
}

export default {
  async fetch(req, env, ctx) {
    const url = new URL(req.url);
    const feed = FEEDS[url.pathname];
    if (!feed) return env.ASSETS.fetch(req);
    let text = await env.KV.get(feed.key);
    if (!text) {
      try { text = await pull(env, feed); }
      catch (e) { return Response.json({ error: "目前沒有可用的公告資料：" + e.message }, { status: 503 }); }
    } else {
      // 資料超過 36 小時沒更新時，順手嘗試同步一次（失敗就沿用舊資料）
      const head = text.slice(0, 120).match(/"updatedAt":"([^"]+)"/);
      if (head && Date.now() - Date.parse(head[1]) > STALE_MS) ctx.waitUntil(pull(env, feed).catch(() => {}));
    }
    return new Response(text, {
      headers: { "Content-Type": "application/json; charset=utf-8", "Cache-Control": "public, max-age=300" },
    });
  },
  async scheduled(_evt, env, ctx) {
    for (const feed of Object.values(FEEDS)) ctx.waitUntil(pull(env, feed).catch(() => {}));
  },
};
