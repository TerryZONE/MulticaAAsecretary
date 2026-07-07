// 种子账号解析器：在 m.weibo.cn 用户搜索里核实种子昵称 → uid，并记录首次快照。
// 用法: NODE_PATH=... node resolve_seeds.js <seeds.json> <output.json>
// 精确命中：搜索结果中 screen_name 与种子名完全一致；否则记录 top3 候选供人工判断。
const { chromium } = require('playwright-core');
const path = require('path');
const os = require('os');
const fs = require('fs');

function findChromium() {
  const base = path.join(os.homedir(), 'Library/Caches/ms-playwright');
  let dir = 'chromium-1124';
  try {
    const hit = fs.readdirSync(base).find(d => d.startsWith('chromium-'));
    if (hit) dir = hit;
  } catch (e) {}
  return path.join(base, dir, 'chrome-mac/Chromium.app/Contents/MacOS/Chromium');
}

const [seedsPath, outPath] = process.argv.slice(2);
if (!seedsPath || !outPath) {
  console.log(JSON.stringify({ ok: false, error: 'usage: node resolve_seeds.js <seeds.json> <output.json>' }));
  process.exit(1);
}
const seeds = JSON.parse(fs.readFileSync(seedsPath, 'utf8')).seeds;
const sleep = ms => new Promise(r => setTimeout(r, ms));

// 从搜索结果卡片树里抽出所有用户对象（card_type 10/11 嵌套结构都处理）
function extractUsers(cards, acc = []) {
  for (const c of cards || []) {
    if (c.user) acc.push(c.user);
    if (c.card_group) extractUsers(c.card_group, acc);
  }
  return acc;
}

(async () => {
  const browser = await chromium.launch({
    executablePath: findChromium(), headless: false,
    args: ['--disable-blink-features=AutomationControlled', '--no-sandbox', '--disable-infobars', '--window-position=-3000,0'],
  });
  try { require('child_process').execSync('osascript -e \'tell application "Chromium" to set visible to false\' 2>/dev/null', { timeout: 2000 }); } catch (e) {}
  const ctx = await browser.newContext({
    userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
    locale: 'zh-CN', viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true,
  });
  await ctx.addInitScript(() => { Object.defineProperty(navigator, 'webdriver', { get: () => undefined }); });
  const page = await ctx.newPage();

  const apiGet = url => page.evaluate(async u => {
    const r = await fetch(u, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
    return await r.json();
  }, url);

  // 建立访客会话
  await page.goto('https://m.weibo.cn/', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await sleep(4000);

  const results = [];
  const snapshotDate = new Date().toISOString().slice(0, 10);

  for (const seed of seeds) {
    const rec = { ...seed, status: null, resolved_uid: seed.uid || null, snapshot: null, candidates: [] };
    try {
      if (seed.uid) {
        // 已知 uid：直接取资料做快照
        const info = await apiGet(`https://m.weibo.cn/api/container/getIndex?type=uid&value=${seed.uid}`);
        const ui = info && info.data && info.data.userInfo;
        if (ui) {
          rec.status = 'ok';
          rec.snapshot = { date: snapshotDate, screen_name: ui.screen_name, followers: ui.followers_count, statuses: ui.statuses_count, verified_reason: ui.verified_reason || '', description: ui.description || '' };
        } else rec.status = 'uid_fetch_failed';
      } else {
        const q = encodeURIComponent(seed.name);
        const res = await apiGet(`https://m.weibo.cn/api/container/getIndex?containerid=100103type%3D3%26q%3D${q}&page_type=searchall`);
        const users = extractUsers(res && res.data && res.data.cards);
        const exact = users.find(u => u.screen_name === seed.name);
        if (exact) {
          rec.status = 'resolved';
          rec.resolved_uid = String(exact.id);
          rec.snapshot = { date: snapshotDate, screen_name: exact.screen_name, followers: exact.followers_count, statuses: exact.statuses_count, verified_reason: exact.verified_reason || '', description: exact.description || '' };
        } else {
          rec.status = users.length ? 'no_exact_match' : 'not_found';
          rec.candidates = users.slice(0, 3).map(u => ({ uid: String(u.id), screen_name: u.screen_name, followers: u.followers_count, description: (u.description || '').slice(0, 60) }));
        }
      }
    } catch (e) {
      rec.status = 'error';
      rec.error = String(e).slice(0, 120);
    }
    results.push(rec);
    process.stderr.write(`[${results.length}/${seeds.length}] ${seed.name} -> ${rec.status}\n`);
    await sleep(3000 + Math.random() * 2000);
  }

  await browser.close();
  fs.writeFileSync(outPath, JSON.stringify({ ok: true, resolved_at: new Date().toISOString(), results }, null, 1));
  const tally = results.reduce((m, r) => ((m[r.status] = (m[r.status] || 0) + 1), m), {});
  console.log(JSON.stringify({ ok: true, total: results.length, tally, out: outPath }));
})();
