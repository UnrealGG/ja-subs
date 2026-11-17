// service worker：拉起本地服务 → 往页面注入字幕脚本 → 记住开关状态
// 采集与识别都在本地 Python 服务里（抓系统回环），页面只负责把 /subs 的字幕画出来。
// 这样不再需要 tabCapture / offscreen 文档——那一层是之前反复出问题的根源。
let state = { tabId: null, running: false };
const API = 'http://127.0.0.1:8765';
const BUILD = chrome.runtime.getManifest().version;

function recordStatus(text, tabId) {
  const t = tabId || state.tabId;
  if (t) chrome.tabs.sendMessage(t, { type: 'status', text }).catch(() => {});
  chrome.runtime.sendMessage({ type: 'popup-status', text }).catch(() => {});
}

// 后台往服务端黑匣子写一行，卡在哪一步一目了然
function diag(text) {
  try {
    fetch(API + '/diag', {
      method: 'POST',
      body: 'bg ' + text,
      headers: { 'Content-Type': 'text/plain' },
    }).catch(() => {});
  } catch (e) {}
}

// 通过 native messaging 拉起本地服务（没装也继续走，页面侧会自己重试）
function ensureServer() {
  return new Promise((resolve) => {
    let settled = false;
    const done = (r) => { if (!settled) { settled = true; resolve(r); } };
    let port;
    try {
      port = chrome.runtime.connectNative('com.jasubs.launcher');
    } catch (e) {
      return done({ ok: false, error: String(e) });
    }
    port.onMessage.addListener((m) => {
      done(m || { ok: true });
      try { port.disconnect(); } catch (e) {}
    });
    port.onDisconnect.addListener(() => {
      const err = chrome.runtime.lastError && chrome.runtime.lastError.message;
      done({ ok: false, error: err || '本地启动器未安装' });
    });
    try { port.postMessage({ cmd: 'ensure' }); } catch (e) { done({ ok: false, error: String(e) }); }
    setTimeout(() => done({ ok: false, error: '启动器无响应' }), 4000);
  });
}

// 自检：把每个环节的真实状态抓出来，省得靠猜
async function diagnose() {
  const out = [];
  out.push('版本: ' + BUILD);
  out.push('nativeMessaging: ' +
    (typeof chrome.runtime.connectNative === 'function' ? 'OK' : '缺失 → 扩展没重新加载'));
  const r = await ensureServer();
  out.push('启动器: ' + JSON.stringify(r));
  try {
    const res = await fetch(API + '/subs?since=0', { cache: 'no-store' });
    const txt = await res.text();
    out.push('本地服务: HTTP ' + res.status + ' ' + txt.slice(0, 90));
  } catch (e) {
    out.push('本地服务: 连不上 (' + e.message + ')');
  }
  return out.join('\n');
}

async function start(tabId) {
  diag('start tabId=' + tabId);
  if (!tabId) {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    tabId = tab && tab.id;
  }
  if (!tabId) throw new Error('找不到当前标签页');
  if (state.running) { try { await stop(); } catch (e) {} }

  const srv = await ensureServer();
  if (!srv.ok) recordStatus('自动启动不可用：' + srv.error, tabId);

  // 先落盘开关状态：content.js 一加载就会自己开始轮询，不依赖后续消息
  await chrome.storage.local.set({ enabled: true });
  state = { tabId, running: true };
  await chrome.storage.session.set(state);
  try {
    await chrome.scripting.executeScript({ target: { tabId }, files: ['content.js'] });
  } catch (e) {
    recordStatus('注入字幕脚本失败：' + (e.message || e), tabId);
  }
  await chrome.tabs.sendMessage(tabId, { type: 'state', running: true }).catch(() => {});
  return state;
}

async function stop() {
  const t = state.tabId;
  // 让本地服务退出，显存/内存立刻释放（下次开启会重新拉起并加载模型）
  try { await fetch(API + '/quit', { cache: 'no-store' }); } catch (e) {}
  await chrome.storage.local.set({ enabled: false });
  state = { tabId: null, running: false };
  await chrome.storage.session.set(state);
  if (t) await chrome.tabs.sendMessage(t, { type: 'state', running: false }).catch(() => {});
  return state;
}

chrome.runtime.onInstalled.addListener(() => chrome.storage.session.set(state));
chrome.runtime.onStartup.addListener(() => chrome.storage.session.set(state));

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    try {
      if (msg.type === 'start') {
        sendResponse({ ok: true, state: await start(msg.tabId) });
      } else if (msg.type === 'stop') {
        sendResponse({ ok: true, state: await stop() });
      } else if (msg.type === 'get-state') {
        sendResponse({ ok: true, state });
      } else if (msg.type === 'diagnose') {
        sendResponse({ ok: true, text: await diagnose() });
      } else if (msg.type === 'status') {
        if (state.tabId) chrome.tabs.sendMessage(state.tabId, { type: 'status', text: msg.text }).catch(() => {});
        chrome.runtime.sendMessage({ type: 'popup-status', text: msg.text }).catch(() => {});
        sendResponse({ ok: true });
      } else {
        sendResponse({ ok: false, error: 'unknown message ' + msg.type });
      }
    } catch (e) {
      const err = String(e && e.message ? e.message : e);
      if (state.tabId) chrome.tabs.sendMessage(state.tabId, { type: 'status', text: err }).catch(() => {});
      sendResponse({ ok: false, error: err });
    }
  })();
  return true; // 异步回包
});
