// 成员号发现器：从团体官号的帖子（含转发与@提及）里抽取候选成员账号，
// 按「昵称含团名关键词」过滤，再经用户搜索核实 uid 与粉丝数。
// 用法: node members_discover.js <groups.json> <output.json>
// groups.json: [{uid, name, keywords:[匹配成员昵称的关键词]}]
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

const [groupsPath, outPath] = process.argv.slice(2);
const groups = JSON.parse(fs.readFileSync(groupsPath, 'utf8'));
const sleep = ms => new Promise(r => setTimeout(r, ms));

function extractUsersFromSearch(cards, acc = []) {
  for (const c of cards || []) {
    if (c.user) acc.push(c.user);
    if (c.card_group) extractUsersFromSearch(c.card_group, acc);
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

  await page.goto('https://m.weibo.cn/', { waitUntil: 'domcontentloaded', timeout: 30000 });
  await sleep(4000);

  const results = [];
  for (const g of groups) {
    const rec = { group: g.name, uid: g.uid, candidates: {}, members: [], unresolved: [] };
    try {
      // 抓官号最近 2 页帖子（含置顶），从 @提及 与 转发原作者 里收集昵称
      let sinceId = '';
      for (let p = 0; p < 2; p++) {
        const feed = await apiGet(`https://m.weibo.cn/api/container/getIndex?type=uid&value=${g.uid}&containerid=107603${g.uid}${sinceId ? '&since_id=' + sinceId : ''}`);
        const cards = (feed && feed.data && feed.data.cards) || [];
        for (const c of cards) {
          if (c.card_type !== 9 || !c.mblog) continue;
          const m = c.mblog;
          const texts = [m.text || ''];
          if (m.retweeted_status) {
            texts.push(m.retweeted_status.text || '');
            const ru = m.retweeted_status.user;
            if (ru && ru.screen_name) rec.candidates[ru.screen_name] = (rec.candidates[ru.screen_name] || 0) + 1;
          }
          for (const t of texts) {
            for (const mt of t.matchAll(/\/n\/([^'"]+)['"]/g)) {
              rec.candidates[decodeURIComponent(mt[1])] = (rec.candidates[decodeURIComponent(mt[1])] || 0) + 1;
            }
          }
        }
        sinceId = (feed && feed.data && feed.data.cardlistInfo && feed.data.cardlistInfo.since_id) || '';
        if (!sinceId) break;
        await sleep(3000);
      }

      // 过滤：昵称含团名关键词，排除官号自身；按出现次数排序取前 10 个去核实
      const names = Object.entries(rec.candidates)
        .filter(([n]) => n !== g.name && g.keywords.some(k => n.toLowerCase().includes(k.toLowerCase())))
        .sort((a, b) => b[1] - a[1]).slice(0, 10).map(([n]) => n);

      for (const name of names) {
        await sleep(3000 + Math.random() * 1500);
        try {
          const res = await apiGet(`https://m.weibo.cn/api/container/getIndex?containerid=100103type%3D3%26q%3D${encodeURIComponent(name)}&page_type=searchall`);
          const exact = extractUsersFromSearch(res && res.data && res.data.cards).find(u => u.screen_name === name);
          if (exact) rec.members.push({ name, uid: String(exact.id), followers: exact.followers_count, mentions: rec.candidates[name], description: (exact.description || '').slice(0, 50) });
          else rec.unresolved.push(name);
        } catch (e) { rec.unresolved.push(name); }
      }
    } catch (e) { rec.error = String(e).slice(0, 120); }
    delete rec.candidates;
    results.push(rec);
    process.stderr.write(`[${results.length}/${groups.length}] ${g.name}: ${rec.members.length} 成员核实, ${rec.unresolved.length} 未解析\n`);
    await sleep(4000);
  }

  await browser.close();
  fs.writeFileSync(outPath, JSON.stringify({ ok: true, at: new Date().toISOString(), results }, null, 1));
  console.log(JSON.stringify({ ok: true, groups: results.length, members: results.reduce((s, r) => s + r.members.length, 0) }));
})();
