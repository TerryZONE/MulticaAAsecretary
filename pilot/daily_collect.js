// 每日增量采集器：读 network.csv 分层轮询全网络，断点增量取新帖，分频记粉丝快照。
// 用法: NODE_PATH=... node daily_collect.js
// 输出: data/daily_YYYY-MM-DD.json（新帖按账号分组）；state.json 记断点；快照追加 snapshots.csv
// 分频策略: 帖子=全员每日一页；快照=priority≤1 每日，priority≥2 每周一。
// 首次见到某账号时只取最新 3 条作基线，避免历史帖灌爆日报。
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
    // 简易 CSV 解析（本文件无引号字段）
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
  const isMonday = new Date().getDay() === 1;
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
  const apiGet = url => page.evaluate(async u => {
    const r = await fetch(u, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
    return await r.json();
  }, url);

  await page.goto('https://m.weibo.cn/', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await sleep(4000);

  const out = { date: today, accounts: [], errors: [], snapshots: 0 };
  const snapLines = [];

  for (const acc of network) {
    const st = state[acc.uid] || {};
    const firstRun = !st.last_post_id;
    try {
      const feed = await apiGet(`https://m.weibo.cn/api/container/getIndex?type=uid&value=${acc.uid}&containerid=107603${acc.uid}`);
      const cards = ((feed && feed.data && feed.data.cards) || []).filter(c => c.card_type === 9 && c.mblog);
      let posts = cards.map(c => {
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
      let fresh;
      if (firstRun) {
        fresh = posts.filter(p => !p.is_top).slice(0, 3).map(p => ({ ...p, baseline: true }));
      } else {
        fresh = posts.filter(p => !p.is_top && BigInt(p.id) > BigInt(st.last_post_id));
      }
      // 昵称变更检测（成员改名监测）
      const curName = posts.length ? posts[0].screen_name : null;
      const renamed = curName && curName !== acc.name ? { from: acc.name, to: curName } : null;
      if (fresh.length || renamed) {
        out.accounts.push({ uid: acc.uid, name: curName || acc.name, type: acc.type, city: acc.city, priority: acc.priority, renamed, new_posts: fresh, first_run: firstRun });
      }
      state[acc.uid] = { ...st, last_post_id: maxId === '0' ? st.last_post_id : maxId, last_seen: today, name: curName || acc.name };

      // 快照分频
      if (acc.priority <= 1 || isMonday) {
        await sleep(2000);
        const info = await apiGet(`https://m.weibo.cn/api/container/getIndex?type=uid&value=${acc.uid}`);
        const ui = info && info.data && info.data.userInfo;
        if (ui) {
          const est = String(ui.followers_count).includes('万') ? Math.round(parseFloat(ui.followers_count) * 10000) : parseInt(ui.followers_count) || '';
          snapLines.push(`${today},${acc.uid},${ui.screen_name},${ui.followers_count},${est},,${ui.statuses_count || ''}`);
          out.snapshots++;
        }
      }
    } catch (e) {
      out.errors.push({ uid: acc.uid, name: acc.name, error: String(e).slice(0, 100) });
    }
    process.stderr.write(`[${network.indexOf(acc) + 1}/${network.length}] ${acc.name}\n`);
    await sleep(2500 + Math.random() * 1500);
  }

  await browser.close();
  if (snapLines.length) fs.appendFileSync(path.join(ROOT, 'snapshots.csv'), snapLines.join('\n') + '\n');
  fs.writeFileSync(statePath, JSON.stringify(state, null, 1));
  const outPath = path.join(DATA, `daily_${today}.json`);
  fs.writeFileSync(outPath, JSON.stringify(out, null, 1));
  console.log(JSON.stringify({ ok: true, date: today, accounts_with_news: out.accounts.length, snapshots: out.snapshots, errors: out.errors.length, out: outPath }));
})();
