// 浏览器 Agent 试点采集器：headed Chromium 以访客身份打开 m.weibo.cn，
// 页面内 fetch 同源 JSON API（真实浏览器指纹 + 浏览器自动完成访客 Cookie 流程）。
// 用法: node collect.js <uid> [uid...]
// 输出: JSON { ok, collected_at, accounts: [{uid, profile, posts, hot_comments}] }
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

const uids = process.argv.slice(2);
if (uids.length === 0) {
  console.log(JSON.stringify({ ok: false, error: 'usage: node collect.js <uid> [uid...]' }));
  process.exit(1);
}

const sleep = ms => new Promise(r => setTimeout(r, ms));

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

  // 页面内同源 fetch，返回解析后的 JSON
  const apiGet = url => page.evaluate(async u => {
    const r = await fetch(u, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
    return await r.json();
  }, url);

  const accounts = [];
  try {
    for (const uid of uids) {
      // 打开主页，让浏览器自然完成访客 Cookie 流程
      await page.goto(`https://m.weibo.cn/u/${uid}`, { waitUntil: 'domcontentloaded', timeout: 30000 });
      await sleep(4000);

      const acc = { uid, profile: null, posts: [], hot_comments: {} };

      const info = await apiGet(`https://m.weibo.cn/api/container/getIndex?type=uid&value=${uid}`);
      const ui = info && info.data && info.data.userInfo;
      if (ui) {
        acc.profile = {
          screen_name: ui.screen_name,
          followers_count: ui.followers_count,
          follow_count: ui.follow_count,
          statuses_count: ui.statuses_count,
          description: ui.description,
          verified_reason: ui.verified_reason || '',
        };
      }
      await sleep(2000);

      const feed = await apiGet(`https://m.weibo.cn/api/container/getIndex?type=uid&value=${uid}&containerid=107603${uid}`);
      const cards = (feed && feed.data && feed.data.cards) || [];
      for (const c of cards) {
        if (c.card_type !== 9 || !c.mblog) continue;
        const m = c.mblog;
        acc.posts.push({
          id: m.id,
          created_at: m.created_at,
          text: (m.text || '').replace(/<[^>]+>/g, '').trim(),
          is_long: !!m.isLongText,
          reposts_count: m.reposts_count,
          comments_count: m.comments_count,
          attitudes_count: m.attitudes_count,
          pics_count: (m.pics || []).length,
          is_top: !!(m.title && m.title.text && m.title.text.includes('置顶')),
        });
      }
      await sleep(2000);

      // 最新 2 条非置顶帖的热评（试点轻量：每帖只取第一页）
      const fresh = acc.posts.filter(p => !p.is_top).slice(0, 2);
      for (const p of fresh) {
        try {
          const cm = await apiGet(`https://m.weibo.cn/comments/hotflow?id=${p.id}&mid=${p.id}&max_id_type=0`);
          const list = (cm && cm.ok === 1 && cm.data && cm.data.data) || [];
          acc.hot_comments[p.id] = list.slice(0, 5).map(x => ({
            text: (x.text || '').replace(/<[^>]+>/g, '').trim(),
            like_count: x.like_count,
            author: x.user && x.user.screen_name,
          }));
        } catch (e) { acc.hot_comments[p.id] = []; }
        await sleep(2000);
      }

      accounts.push(acc);
      await sleep(3000);
    }
    console.log(JSON.stringify({ ok: true, collected_at: new Date().toISOString(), accounts }, null, 1));
  } catch (e) {
    console.log(JSON.stringify({ ok: false, error: String(e), partial: accounts }));
  } finally {
    await browser.close();
  }
})();
