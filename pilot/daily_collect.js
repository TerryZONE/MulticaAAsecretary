// 每日增量采集器 v3：分批轮换访客身份。
// 实测规律：微博给每个访客身份的博主页 feed 约 7-10 次配额（搜索接口不受此限）。
// 策略：每批 5 个账号用一个全新浏览器身份，批间歇 20 秒；单账号失败重试 1 次；
//       连续 2 个整批全灭则判定 IP 级风控，中止并报告。
// 用法: NODE_PATH=... node daily_collect.js
// 输出: data/daily_YYYY-MM-DD.json；state.json 断点；快照追加 snapshots.csv（全员每日）
const { chromium } = require('playwright-core');
const path = require('path');
const os = require('os');
const fs = require('fs');

const ROOT = path.dirname(__filename);
const DATA = path.join(ROOT, 'data');
if (!fs.existsSync(DATA)) fs.mkdirSync(DATA);

const BATCH = 5;          // 每个身份处理的账号数（低于单身份配额）
const BATCH_REST = 20000; // 批间歇
const clean = s => (s || '').replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim();
const sleep = ms => new Promise(r => setTimeout(r, ms));

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

async function launchFreshVisitor() {
  const browser = await chromium.launch({
    executablePath: findChromium(), headless: false,
    args: ['--disable-blink-features=AutomationControlled', '--no-sandbox', '--window-position=-3000,0'],
  });
  try { require('child_process').execSync('osascript -e \'tell application "Chromium" to set visible to false\' 2>/dev/null', { timeout: 2000 }); } catch (e) {}
  const ctx = await browser.newContext({
    userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
    locale: 'zh-CN', viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true,
  });
  const page = await ctx.newPage();
  const bucket = [];
  page.on('response', r => {
    const u = r.url();
    if (u.includes('/api/container/getIndex') && (u.includes('containerid=100505') || u.includes('containerid=107603'))) bucket.push(r);
  });
  return { browser, page, bucket };
}

// 访问一个账号主页，返回 {feed, profile}（失败返回 null 字段）
async function fetchAccount(page, bucket, uid) {
  bucket.length = 0;
  await page.goto(`https://m.weibo.cn/u/${uid}`, { waitUntil: 'domcontentloaded', timeout: 30000 }).catch(() => {});
  for (let w = 0; w < 16 && bucket.length < 2; w++) await sleep(500);
  await sleep(1000);
  let feed = null, profile = null;
  for (const r of bucket) {
    const u = r.url();
    const j = await r.json().catch(() => null);
    if (!j) continue;
    if (!feed && u.includes('containerid=107603') && j.ok === 1) feed = j;
    else if (!profile && u.includes('containerid=100505')) profile = j;
  }
  return { feed, profile };
}

(async () => {
  const now = new Date();
  const today = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
  const statePath = path.join(DATA, 'state.json');
  const state = fs.existsSync(statePath) ? JSON.parse(fs.readFileSync(statePath, 'utf8')) : {};
  const network = loadNetwork();

  const out = { date: today, accounts: [], errors: [], snapshots: 0 };
  const snapLines = [];
  let batchDeadStreak = 0;

  for (let b = 0; b < network.length; b += BATCH) {
    const batch = network.slice(b, b + BATCH);
    let vis = null, batchHits = 0;
    try {
      vis = await launchFreshVisitor();
      await sleep(1500);
      for (const acc of batch) {
        const st = state[acc.uid] || {};
        const firstRun = !st.last_post_id;
        try {
          let { feed, profile } = await fetchAccount(vis.page, vis.bucket, acc.uid);
          if (!feed) {
            await sleep(4000);
            ({ feed, profile } = await fetchAccount(vis.page, vis.bucket, acc.uid));
          }
          const ui = profile && profile.data && profile.data.userInfo;
          if (ui) {
            const est = String(ui.followers_count).includes('万') ? Math.round(parseFloat(ui.followers_count) * 10000) : parseInt(ui.followers_count) || '';
            snapLines.push(`${today},${acc.uid},${ui.screen_name},${ui.followers_count},${est},,${ui.statuses_count || ''}`);
            out.snapshots++;
          }
          if (!feed) {
            out.errors.push({ uid: acc.uid, name: acc.name, error: 'feed_missing' });
          } else {
            batchHits++;
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
                raw: m, // 完整 mblog，入库存档（采集求全，加工靠后）
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
        process.stderr.write(`[${Math.min(b + batch.indexOf(acc) + 1, network.length)}/${network.length}] ${acc.name}\n`);
        await sleep(3000 + Math.random() * 2000);
      }
    } catch (e) {
      out.errors.push({ batch: b / BATCH, error: 'batch_launch: ' + String(e).slice(0, 100) });
    } finally {
      if (vis) await vis.browser.close().catch(() => {});
    }
    batchDeadStreak = batchHits === 0 ? batchDeadStreak + 1 : 0;
    if (batchDeadStreak >= 2) {
      out.aborted = `连续 ${batchDeadStreak} 个整批全灭，疑似 IP 级风控，中止（进度 ${Math.min(b + BATCH, network.length)}/${network.length}）`;
      process.stderr.write('ABORT: ' + out.aborted + '\n');
      break;
    }
    if (b + BATCH < network.length) await sleep(BATCH_REST);
  }

  if (snapLines.length) fs.appendFileSync(path.join(ROOT, 'snapshots.csv'), snapLines.join('\n') + '\n');
  fs.writeFileSync(statePath, JSON.stringify(state, null, 1));
  const outPath = path.join(DATA, `daily_${today}.json`);
  fs.writeFileSync(outPath, JSON.stringify(out, null, 1));
  console.log(JSON.stringify({ ok: true, date: today, accounts_with_news: out.accounts.length, snapshots: out.snapshots, errors: out.errors.length, aborted: out.aborted || null, out: outPath }));
})();
