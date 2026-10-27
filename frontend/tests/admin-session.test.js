const assert = require('node:assert/strict');
const test = require('node:test');
const vm = require('node:vm');
const fs = require('node:fs');
const tick = () => new Promise((resolve) => setImmediate(resolve));

async function sessionPage() {
  const elements = new Map();
  const element = () => ({ hidden: false, value: '', textContent: '', children: [], dataset: {},
    classList: { toggle() {} }, listeners: {}, replaceChildren() { this.children = []; },
    addEventListener(type, callback) { this.listeners[type] = callback; },
  });
  const doc = { getElementById(id) {
    if (!elements.has(id)) elements.set(id, element());
    return elements.get(id);
  }, querySelectorAll: () => [] };
  const calls = [];
  const state = { shows: 0, hides: 0, timer: null, expired: false };
  const context = vm.createContext({
    document: doc, window: {}, Date,
    setTimeout: (fn) => { state.timer = fn; return 1; }, clearTimeout() {},
    GiftTaxDashboard: { createDashboard: () => ({
      show: async () => { state.shows += 1; }, hide: () => { state.hides += 1; },
    }) },
    fetch: async (path, options) => {
      calls.push({ path, options });
      const data = path.endsWith('/config') ? { mode: 'manual_jwt' }
        : path.endsWith('/session') ? { csrf_token: 'csrf-for-this-session', expires_at: Math.floor(Date.now() / 1000) + 300 }
          : {};
      if (path.endsWith('/session') && state.expired) return { status: 401, ok: false, json: async () => ({ detail: { message: '세션 만료' } }) };
      return { status: 200, ok: true, json: async () => data };
    },
  });
  vm.runInContext(fs.readFileSync(require.resolve('../admin.js'), 'utf8'), context);
  await tick();
  return { doc, state, calls, context };
}

test('관리 API 조회·변경은 동일 출처 쿠키와 캐시 금지를 사용하고 쓰기만 CSRF를 전송한다', async () => {
  const f = await sessionPage();
  assert.equal(f.state.shows, 1);
  for (const method of ['GET', 'PATCH', 'DELETE']) {
    await f.context.adminRequest('/api/admin/feedback/item', { status: 'resolved' }, method);
    const { options } = f.calls.at(-1);
    assert.equal(options.credentials, 'same-origin');
    assert.equal(options.cache, 'no-store');
    if (method === 'GET') {
      assert.equal(options.body, undefined);
      assert.equal(options.headers['X-CSRF-Token'], undefined);
    } else {
      assert.equal(options.headers['X-CSRF-Token'], 'csrf-for-this-session');
      assert.equal(options.headers['Content-Type'], 'application/json');
    }
  }
});

test('세션 만료 타이머는 비공개 화면을 지우고 재인증을 안내한다', async () => {
  const f = await sessionPage();
  const credentials = f.doc.getElementById('credentials');
  credentials.children = ['private device label'];
  assert.equal(f.doc.getElementById('session').hidden, false);
  await f.state.timer();
  assert.equal(f.state.hides, 1);
  assert.equal(f.doc.getElementById('session').hidden, true);
  assert.equal(credentials.children.length, 0);
  assert.match(f.doc.getElementById('message').textContent, /다시 로그인/);
  await f.context.adminRequest('/api/admin/feedback/item', {}, 'DELETE');
  assert.equal(f.calls.at(-1).options.headers['X-CSRF-Token'], undefined);
});

test('로그아웃은 CSRF로 세션을 폐기한 뒤 비공개 화면을 지운다', async () => {
  const f = await sessionPage();
  await f.doc.getElementById('logout-button').listeners.click();
  const logout = f.calls.find((call) => call.path.endsWith('/logout'));
  assert.equal(logout.options.method, 'POST');
  assert.equal(logout.options.headers['X-CSRF-Token'], 'csrf-for-this-session');
  assert.equal(f.state.hides, 1);
  assert.equal(f.doc.getElementById('session').hidden, true);
  assert.match(f.doc.getElementById('message').textContent, /로그아웃했습니다/);
});
