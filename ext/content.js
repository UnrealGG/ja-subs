// 页面内悬浮字幕：跟着 <video> 的位置走，全屏时自动挂进全屏元素
(() => {
  // 扩展重载后旧脚本的 runtime 已失效、监听器收不到消息，但 DOM 还留在页面上。
  // 所以每次都重装一份：先拆掉可能存在的旧壳，再挂新的。
  const stale = document.getElementById('ja-live-sub-host');
  if (stale) { try { stale.remove(); } catch (e) {} }
  window.__jaLiveSub = true;

  // 自报版本，确认页面里跑的是不是最新这份脚本
  try {
    fetch('http://127.0.0.1:8765/diag', {
      method: 'POST',
      body: 'content.js ' + chrome.runtime.getManifest().version + ' ' + location.href,
      headers: { 'Content-Type': 'text/plain' },
    }).catch(() => {});
  } catch (e) {}

  const DEFAULTS = {
    mode: 'both', size: 22, color: '#ffffff', outline: 'thin',
    pos: 'low', alpha: 0.82, fade: true, scale: false,
  };
  // 位置预设：离画面底边的距离（占视频高度百分比）
  const POS = { low: '7.5%', mid: '14%', high: '25%' };
  const OUTLINE = {
    none: 'none',
    thin: '0 0 2px #000, 1px 1px 2px #000',
    bold: '0 0 3px #000, 0 0 7px #000, 1px 1px 3px #000, -1px -1px 3px #000',
  };

  const host = document.createElement('div');
  host.id = 'ja-live-sub-host';
  host.style.cssText =
    'position:fixed;left:0;top:0;width:0;height:0;z-index:2147483647;pointer-events:none;display:none;';
  const root = host.attachShadow({ mode: 'open' });
  root.innerHTML = `
    <style>
      .wrap{position:absolute;pointer-events:none;box-sizing:border-box;
            --bottom:7.5%;--bg:.82;--zh:#fff;--ol:0 0 2px #000}
      .bar{position:absolute;left:8%;width:84%;bottom:var(--bottom);
           background:rgba(16,16,16,var(--bg));
           border-radius:8px;padding:10px 16px;box-sizing:border-box;text-align:center;
           pointer-events:none;
           font-family:"Microsoft YaHei UI","Yu Gothic UI","Hiragino Sans",sans-serif}
      .ja{color:#9fd0ff;line-height:1.35;margin-bottom:2px;word-break:break-word;
          text-shadow:var(--ol)}
      .zh{color:var(--zh);font-weight:700;line-height:1.35;word-break:break-word;
          text-shadow:var(--ol)}
      .tip{position:absolute;left:8%;bottom:var(--bottom);background:rgba(16,16,16,var(--bg));
           color:#bbb;padding:6px 12px;border-radius:6px;
           font:12px/1.4 "Microsoft YaHei UI",sans-serif}
    </style>
    <div class="wrap">
      <div class="bar"><div class="ja"></div><div class="zh"></div></div>
      <div class="tip" style="display:none"></div>
    </div>`;
  const wrap = root.querySelector('.wrap');
  const bar = root.querySelector('.bar');
  const jaEl = root.querySelector('.ja');
  const zhEl = root.querySelector('.zh');
  const tipEl = root.querySelector('.tip');

  let cfg = Object.assign({}, DEFAULTS);
  let running = false;
  let lastJa = '', lastZh = '', lastW = 0;

  const API = 'http://127.0.0.1:8765';

  // ── 字幕来源：轮询本地服务的 /subs（HTTP 比 WS/offscreen 可靠得多）──
  let pollTimer = null, since = 0, fails = 0, pollOn = false;

  function startPoller() {
    if (pollOn) return;
    pollOn = true;
    since = 0;
    fails = 0;
    (async function loop() {
      if (!pollOn) return;
      try {
        const r = await fetch(API + '/subs?since=' + since, { cache: 'no-store' });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        const d = await r.json();
        fails = 0;
        if (d.items && d.items.length) {
          for (const it of d.items) { show(it.ja, it.zh); since = it.i; }
        } else if (!lastZh) {
          running = true;
          tip('等日语语音…');
        }
      } catch (e) {
        fails++;
        if (fails === 3) tip('本地服务没连上，正在重试…');
      }
      if (pollOn) pollTimer = setTimeout(loop, 150);
    })();
  }

  function stopPoller() {
    pollOn = false;
    if (pollTimer) { clearTimeout(pollTimer); pollTimer = null; }
  }

  chrome.storage.local.get(Object.assign({ enabled: false }, DEFAULTS), (v) => {
    cfg = Object.assign({}, DEFAULTS, v);
    applyStyle();
    // 开关状态是持久化的：页面一加载就自己接上，不需要再点一次
    if (v.enabled) { running = true; host.style.display = 'block'; layout(); startPoller(); }
  });

  function applyStyle() {
    // 等比缩放：字号跟着视频宽度走（1280 宽为基准），否则固定像素
    const per = cfg.scale && lastW ? Math.min(1.6, Math.max(0.55, lastW / 1280)) : 1;
    const sz = Math.round(cfg.size * per);
    zhEl.style.fontSize = sz + 'px';
    jaEl.style.fontSize = Math.round(sz * 0.6) + 'px';
    jaEl.style.display = cfg.mode === 'zh' ? 'none' : 'block';
    zhEl.style.display = cfg.mode === 'ja' ? 'none' : 'block';
    wrap.style.setProperty('--bottom', POS[cfg.pos] || POS.low);
    wrap.style.setProperty('--bg', String(cfg.alpha));
    wrap.style.setProperty('--zh', cfg.color);
    wrap.style.setProperty('--ol', OUTLINE[cfg.outline] || OUTLINE.none);
    ensureStyle();
  }

  // Dark Reader 这类深色主题会往页面灌 !important 规则，普通声明全被压掉。
  // 内联 !important 优先级最高，再配合定时校验，主题怎么改都盖不住。
  function ensureStyle() {
    const ol = OUTLINE[cfg.outline] || OUTLINE.none;
    const bg = 'rgba(16,16,16,' + cfg.alpha + ')';
    const want = [
      [zhEl, 'color', cfg.color], [zhEl, 'text-shadow', ol],
      [jaEl, 'color', '#9fd0ff'], [jaEl, 'text-shadow', ol],
      [bar, 'background-color', bg],
      [tipEl, 'background-color', bg], [tipEl, 'color', '#bbb'],
    ];
    for (const [el, prop, val] of want) {
      if (el.style.getPropertyValue(prop) !== val ||
          el.style.getPropertyPriority(prop) !== 'important') {
        el.style.setProperty(prop, val, 'important');
      }
    }
    // Filter 型深色主题给整页套 invert，字幕跟着反色——这里反回去
    let f = '';
    try {
      f = (getComputedStyle(document.documentElement).filter || '') +
          (getComputedStyle(document.body).filter || '');
    } catch (e) {}
    const need = /invert\(/.test(f) ? 'invert(1) hue-rotate(180deg)' : 'none';
    if (host.style.filter !== need) host.style.filter = need;
  }

  // ── 找到屏幕上正在播的那个 video，把字幕条贴到它身上 ──
  function pickVideo() {
    let best = null, area = 0;
    for (const v of document.querySelectorAll('video')) {
      const r = v.getBoundingClientRect();
      const a = r.width * r.height;
      if (a > area && r.width > 200 && r.height > 120) { area = a; best = v; }
    }
    return best;
  }

  let mountedOn = null;
  function mount() {
    const fs = document.fullscreenElement;
    const target = fs || document.body;
    if (host.parentNode !== target) target.appendChild(host);
    mountedOn = target;
  }
  document.addEventListener('fullscreenchange', () => { mount(); layout(); });

  function layout() {
    const v = pickVideo();
    if (!v) { host.style.display = 'none'; return; }
    const r = v.getBoundingClientRect();
    host.style.left = r.left + 'px';
    host.style.top = r.top + 'px';
    host.style.width = r.width + 'px';
    host.style.height = r.height + 'px';
    wrap.style.width = r.width + 'px';
    wrap.style.height = r.height + 'px';
    wrap.style.left = '0px';
    wrap.style.top = '0px';
    if (cfg.scale && Math.abs(r.width - lastW) > 2) { lastW = r.width; applyStyle(); }
    else if (!lastW) lastW = r.width;
    if (running) host.style.display = 'block';
  }

  function tick() { layout(); ensureStyle(); setTimeout(tick, 250); }

  function show(ja, zh) {
    lastJa = ja || '';
    lastZh = zh || '';
    jaEl.textContent = lastJa;
    zhEl.textContent = lastZh;
    tipEl.style.display = 'none';
    bar.style.display = 'block';
    if (cfg.fade && bar.animate) {
      try { bar.animate([{ opacity: 0.35 }, { opacity: 1 }], { duration: 220, easing: 'ease-out' }); } catch (e) {}
    }
    running = true;
    host.style.display = 'block';
    layout();
  }

  function tip(text) {
    tipEl.textContent = text;
    tipEl.style.display = 'block';
    bar.style.display = 'none';
    host.style.display = 'block';
    layout();
  }

  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === 'sub') show(msg.ja, msg.zh);
    else if (msg.type === 'status') { running = true; tip(msg.text); }
    else if (msg.type === 'state') {
      running = !!msg.running;
      if (!running) { stopPoller(); host.style.display = 'none'; return; }
      lastZh = '';
      bar.style.display = 'none';
      jaEl.textContent = '';
      zhEl.textContent = '';
      host.style.display = 'block';
      layout();
      startPoller();
    }
  });

  chrome.storage.onChanged.addListener((ch) => {
    for (const k of Object.keys(DEFAULTS)) {
      if (ch[k]) cfg[k] = ch[k].newValue;
    }
    applyStyle();
  });

  mount();
  applyStyle();
  tick();
})();
