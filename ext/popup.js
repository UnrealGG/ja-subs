const $ = (id) => document.getElementById(id);
let running = false;

const DEFAULTS = {
  mode: 'both', size: 22, color: '#ffffff', outline: 'thin',
  pos: 'low', alpha: 0.82, fade: true, scale: false, mt: 'qwen3.5:latest',
};

function render() {
  const btn = $('toggle');
  btn.textContent = running ? '关闭字幕' : '开启字幕';
  btn.className = running ? 'on' : '';
}

async function loadState() {
  const { state } = await chrome.runtime.sendMessage({ type: 'get-state' }).catch(() => ({ state: {} }));
  running = !!(state && state.running);
  if (running) $('status').textContent = '已开启，字幕显示在页面上';
  render();
}

// ── 把 storage 里的值灌进控件 ──
function fill(v) {
  $('mode').value = v.mode;
  $('size').value = String(v.size);
  $('color').value = v.color;
  $('outline').value = v.outline;
  $('pos').value = v.pos;
  $('alpha').value = String(Math.round(v.alpha * 100));
  $('alphaVal').textContent = Math.round(v.alpha * 100) + '%';
  $('fade').checked = !!v.fade;
  $('scale').checked = !!v.scale;
  $('mt').value = v.mt;
}

chrome.storage.local.get(DEFAULTS, (v) => {
  fill(Object.assign({}, DEFAULTS, v));
});

// ── 控件 → storage（content.js 监听即时生效）──
$('mode').addEventListener('change', (e) => chrome.storage.local.set({ mode: e.target.value }));
$('size').addEventListener('change', (e) => chrome.storage.local.set({ size: Number(e.target.value) }));
$('color').addEventListener('change', (e) => chrome.storage.local.set({ color: e.target.value }));
$('outline').addEventListener('change', (e) => chrome.storage.local.set({ outline: e.target.value }));
$('pos').addEventListener('change', (e) => chrome.storage.local.set({ pos: e.target.value }));
$('alpha').addEventListener('input', (e) => {
  const pct = Number(e.target.value);
  $('alphaVal').textContent = pct + '%';
  chrome.storage.local.set({ alpha: pct / 100 });
});
$('fade').addEventListener('change', (e) => chrome.storage.local.set({ fade: e.target.checked }));
$('scale').addEventListener('change', (e) => chrome.storage.local.set({ scale: e.target.checked }));
$('mt').addEventListener('change', (e) => chrome.storage.local.set({ mt: e.target.value }));

$('reset').addEventListener('click', () => {
  chrome.storage.local.set(DEFAULTS, () => fill(DEFAULTS));
  $('status').textContent = '已恢复默认设置';
});

$('toggle').addEventListener('click', async () => {
  const btn = $('toggle');
  btn.disabled = true;
  $('status').textContent = running ? '正在关闭…' : '正在连接…';
  try {
    if (running) {
      await chrome.runtime.sendMessage({ type: 'stop' });
      running = false;
      $('status').textContent = '已关闭';
    } else {
      const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
      const r = await chrome.runtime.sendMessage({ type: 'start', tabId: tab && tab.id });
      if (!r || !r.ok) throw new Error((r && r.error) || '启动失败');
      running = true;
      $('status').textContent = '已开启，等第一句话…';
    }
  } catch (e) {
    $('status').textContent = '出错：' + (e.message || e);
  }
  btn.disabled = false;
  render();
});

$('diag').addEventListener('click', async () => {
  $('status').textContent = '自检中…';
  const r = await chrome.runtime.sendMessage({ type: 'diagnose' }).catch((e) => ({ ok: false, error: String(e) }));
  $('status').textContent = r && r.text ? r.text : ('诊断失败：' + (r && r.error));
});

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === 'popup-status') $('status').textContent = msg.text;
});

loadState();
