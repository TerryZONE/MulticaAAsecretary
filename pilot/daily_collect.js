// 每日增量采集器 v2：逐个打开博主主页，截获页面自身的 getIndex XHR（不伪造请求）。
// 一次导航同时获得 profile（粉丝快照）与 feed（新帖），完全复用真实页面行为。
// 用法: NODE_PATH=... node daily_collect.js
// 输出: data/daily_YYYY-MM-DD.json；state.json 记断点；快照追加 snapshots.csv（全员每日）
// 首次见到某账号只取最新 3 条作基线，避免历史帖灌爆日报。
const { chromium } = require('playwright-core');
const path = require('path');
const os = require('os');
const fs = require('fs');

const ROOT = path.dirname(__filename);
const DATA = path.join(ROOT, 'data');
if (!fs.existsSync(DATA)) fs.mkdirSync(DATA);

function findChromium() {
  const base = path.join(os.homedir(), 'Library/Caches/ms-playwright');
  const hit = fs.readdirSync(base).find(d => d.startsWith('chromium-'));
  return path.join(base, hit, 'chrome-mac/Chromium.app/Contents/MacOS/Chromium');
}

function loadNetwork() {
  const lines = fs.readFileSync(path.join(ROOT, 'network.csv'), 'utf8').trim().split('\n');
  const head = lines[0].split(',');
  return lines.slice(1).map(l => {
    const v = l.split(',');
    const o = {};
    head.forEach((h, i) => (o[h] = v[i]));
    o.priority = parseInt(o.priority || '9');
    return o;
  }).filter(o => o.uid && /^\d+$/.test(o.uid));
}

const clean = s => (s || '').replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim();
const sleep = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  const today = new Date().toISOString().slice(0, 10);
  const statePath = path.join(DATA, 'state.json');
  const state = fs.existsSync(statePath) ? JSON.parse(fs.readFileSync(statePath, 'utf8')) : {};
  const network = loadNetwork();

  const browser = await chromium.launch({
    executablePath: findChromium(), headless: false,
    args: ['--disable-blink-features=AutomationControlled', '--no-sandbox', '--window-position=-3000,0'],
  });
  try { require('child_process').execSync('osascript -e \'tell application "Chromium" to set visible to false\' 2>/dev/null', { timeout: 2000 }); } catch (e) {}
  const ctx = await browser.newContext({
    userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
    locale: 'zh-CN', viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true,
  });
  await ctx.addInitScript(() => { Object.defineProperty(navigator, 'webdriver', { get: () => undefined }); });
  const page = await ctx.newPage();

  // 截获页面自身的 getIndex 响应：handler 只同步存 response 引用（在 handler 内
  // await r.json() 会与页面消费 body 争用而挂起 —— 改到主流程解析）。保留首个响应。
  let bucket = { profileResp: null, feedResp: null };
  page.on('response', r => {
    const url = r.url();
    if (!url.includes('/api/container/getIndex')) return;
    if (url.includes('containerid=100505') && !bucket.profileResp) bucket.profileResp = r;
    else if (url.includes('containerid=107603') && !bucket.feedResp) bucket.feedResp = r;
  });

  const out = { date: today, accounts: [], errors: [], snapshots: 0 };
  const snapLines = [];
  let done = 0;

  for (const acc of network) {
    const st = state[acc.uid] || {};
    const firstRun = !st.last_post_id;
    bucket = { profileResp: null, feedResp: null };
    try {
      await page.goto(`https://m.weibo.cn/u/${acc.uid}`, { waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => {});
      // 等页面自身发出 feed 请求（最多 10 秒）
      for (let w = 0; w < 20 && !bucket.feedResp; w++) await sleep(500);
      await sleep(600);
      const feed = bucket.feedResp ? await bucket.feedResp.json().catch(() => null) : null;
      const profile = bucket.profileResp ? await bucket.profileResp.json().catch(() => null) : null;

      // 快照（全员每日，来自页面自身的 profile 响应）
      const ui = profile && profile.data && profile.data.userInfo;
      if (ui) {
        const est = String(ui.followers_count).includes('万') ? Math.round(parseFloat(ui.followers_count) * 10000) : parseInt(ui.followers_count) || '';
        snapLines.push(`${today},${acc.uid},${ui.screen_name},${ui.followers_count},${est},,${ui.statuses_count || ''}`);
        out.snapshots++;
      }

      const feedOk = feed && feed.ok === 1;
      if (!feedOk) {
        out.errors.push({ uid: acc.uid, name: acc.name, error: 'feed_missing ok=' + (feed ? feed.ok : 'none') });
      } else {
        const cards = (feed.data.cards || []).filter(c => c.card_type === 9 && c.mblog);
        const posts = cards.map(c => {
          const m = c.mblog;
          return {
            id: m.id,
            is_top: !!(m.title && m.title.text && m.title.text.includes('置顶')),
            date: m.created_at,
            text: clean(m.text).slice(0, 300),
            rt: m.retweeted_status ? { user: m.retweeted_status.user ? m.retweeted_status.user.screen_name : '?', text: clean(m.retweeted_status.text).slice(0, 200) } : null,
            reposts: m.reposts_count, comments: m.comments_count, likes: m.attitudes_count, pics: (m.pics || []).length,
            screen_name: m.user ? m.user.screen_name : acc.name,
          };
        });
        const maxId = posts.reduce((mx, p) => (BigInt(p.id) > BigInt(mx || '0') ? p.id : mx), st.last_post_id || '0');
        const fresh = firstRun
          ? posts.filter(p => !p.is_top).slice(0, 3).map(p => ({ ...p, baseline: true }))
          : posts.filter(p => !p.is_top && BigInt(p.id) > BigInt(st.last_post_id));
        const curName = (ui && ui.screen_name) || (posts.length ? posts[0].screen_name : null);
        const renamed = curName && curName !== acc.name ? { from: acc.name, to: curName } : null;
        if (fresh.length || renamed) {
          out.accounts.push({ uid: acc.uid, name: curName || acc.name, type: acc.type, city: acc.city, priority: acc.priority, renamed, new_posts: fresh, first_run: firstRun });
        }
        state[acc.uid] = { ...st, last_post_id: maxId === '0' ? st.last_post_id : maxId, last_seen: today, name: curName || acc.name };
      }
    } catch (e) {
      out.errors.push({ uid: acc.uid, name: acc.name, error: String(e).slice(0, 100) });
    }
    done++;
    process.stderr.write(`[${done}/${network.length}] ${acc.name}\n`);
    await sleep(2000 + Math.random() * 2000);
  }

  await browser.close();
  if (snapLines.length) fs.appendFileSync(path.join(ROOT, 'snapshots.csv'), snapLines.join('\n') + '\n');
  fs.writeFileSync(statePath, JSON.stringify(state, null, 1));
  const outPath = path.join(DATA, `daily_${today}.json`);
  fs.writeFileSync(outPath, JSON.stringify(out, null, 1));
  console.log(JSON.stringify({ ok: true, date: today, accounts_with_news: out.accounts.length, snapshots: out.snapshots, errors: out.errors.length, out: outPath }));
})();
