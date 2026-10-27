const assert = require('node:assert/strict');
const test = require('node:test');
const { createDashboard, dateRange, query, metrics } = require('../admin-dashboard.js');

function page() {
  const ids = new Map();
  const doc = { getElementById: (id) => ids.get(id), focused: null };
  doc.createElement = (tagName) => {
    const listeners = new Map();
    const el = {
      tagName, children: [], dataset: {}, hidden: false, disabled: false, value: '', _text: '',
      classList: { toggle() {} },
      set textContent(value) { this._text = String(value); this.children = []; },
      get textContent() { return this._text + this.children.map((child) => child.textContent).join(''); },
      set innerHTML(_) { assert.fail('Untrusted HTML must never be parsed'); },
      append(...children) { this.children.push(...children); },
      replaceChildren(...children) { this._text = ''; this.children = children; },
      setAttribute(key, value) { this[key] = value; },
      addEventListener(type, callback) { listeners.set(type, callback); },
      async fire(type) { await listeners.get(type)?.({ preventDefault() {} }); await tick(); },
      focus() { doc.focused = this; }, select() { this.selected = true; },
      querySelectorAll(selector) {
        const tags = selector.split(',');
        return this.children.flatMap((child) => [
          ...(tags.includes(child.tagName) ? [child] : []), ...child.querySelectorAll(selector),
        ]);
      },
    };
    return el;
  };
  for (const id of ['dashboard', 'usage-form', 'usage-days', 'usage-totals', 'usage-daily', 'usage-head',
    'usage-details', 'usage-message', 'feedback-filters', 'filter-start', 'filter-end', 'filter-category',
    'filter-satisfaction', 'filter-status', 'feedback-message', 'feedback-list', 'feedback-page',
    'feedback-prev', 'feedback-next']) {
    ids.set(id, doc.createElement(id.includes('filter-') || id === 'usage-days' ? 'select' : 'div'));
  }
  doc.getElementById('usage-form').append(doc.getElementById('usage-days'), doc.createElement('button'));
  for (const id of ['filter-start', 'filter-end', 'filter-category', 'filter-satisfaction', 'filter-status']) {
    doc.getElementById('feedback-filters').append(doc.getElementById(id));
  }
  doc.getElementById('feedback-filters').append(doc.createElement('button'));
  return doc;
}
const tick = () => new Promise((resolve) => setImmediate(resolve));
const NOW = new Date('2026-10-27T03:00:00Z');
function feedback(changes = {}) {
  return { id: 'id-1', category: 'review', satisfaction: 'satisfied', message: '<img src=x onerror=alert(1)>',
    source: 'result', status: 'new', created_at: NOW.toISOString(), email: null, email_expires_at: null, ...changes };
}
function usage() {
  const counts = Object.fromEntries(Object.keys(metrics).map((key) => [key, 0]));
  return { period_start: '2026-09-28', period_end: '2026-10-27', period_days: 30, totals: counts,
    daily: [{ day: '2026-10-27', ...counts }] };
}
function fixture(t, options = {}) {
  const doc = page();
  const calls = [];
  let unauthorized = 0;
  const state = { items: [feedback()], total: 1, confirmed: true, ...options };
  const request = async (url, body, method, opts) => {
    calls.push({ url, body, method, opts });
    if (state.request) return state.request(url, body, method);
    if (url.startsWith('/api/admin/usage')) return usage();
    if (method !== 'GET') return {};
    return { items: state.items, total: state.total, page: 1, page_size: 50 };
  };
  const controller = createDashboard(doc, { request, now: () => NOW,
    onUnauthorized: () => { unauthorized += 1; }, confirm: () => state.confirmed,
    clipboard: options.clipboard ?? {},
  });
  t.after(() => controller.hide());
  return { doc, el: (id) => doc.getElementById(id), calls, state, controller, unauthorized: () => unauthorized };
}

test('한국 시간 자정과 월·연도 경계에서 최근 30일을 계산한다', () => {
  assert.deepEqual(dateRange(new Date('2026-12-31T15:00:00Z')), { start: '2026-12-03', end: '2027-01-01' });
  assert.deepEqual(dateRange(new Date('2026-10-26T14:59:59Z')), { start: '2026-09-27', end: '2026-10-26' });
  assert.equal(query({ category: 'problem', status: '', start_date: '2026-10-01' }, 2), '/api/admin/feedback?page=2&category=problem&start_date=2026-10-01');
});

test('기본 30일·0 통계·일별 표를 표시하고 사용자 입력은 텍스트로 렌더링한다', async (t) => {
  const f = fixture(t);
  await f.controller.show();
  assert.equal(f.el('dashboard').hidden, false);
  assert.match(f.calls[0].url, /days=30/);
  assert.match(f.calls[1].url, /start_date=2026-09-28&end_date=2026-10-27/);
  assert.equal(f.el('usage-totals').children.length, 9);
  assert.equal(f.el('usage-totals').children[0].children[1].textContent, '0');
  assert.equal(f.el('usage-daily').children.length, 1);
  assert.match(f.el('feedback-list').textContent, /<img src=x onerror=alert\(1\)>/);
  assert.equal(f.el('feedback-next').disabled, true);
  assert.equal(f.el('feedback-list')['aria-busy'], 'false');
});

test('필터 적용과 페이지 이동은 적용된 조건을 유지하고 새 조회는 첫 페이지로 이동한다', async (t) => {
  const f = fixture(t, { total: 51 });
  await f.controller.show();
  f.el('filter-category').value = 'problem';
  f.el('filter-status').value = 'in_progress';
  await f.el('feedback-filters').fire('submit');
  assert.match(f.calls.at(-1).url, /category=problem&status=in_progress/);
  f.el('filter-category').value = 'suggestion'; // Draft changes do not affect pagination.
  await f.el('feedback-next').fire('click');
  assert.match(f.calls.at(-1).url, /page=2/);
  assert.match(f.calls.at(-1).url, /category=problem/);
  assert.equal(f.el('feedback-next').disabled, true);
  await f.el('feedback-filters').fire('submit');
  assert.match(f.calls.at(-1).url, /page=1/);
  assert.match(f.calls.at(-1).url, /category=suggestion/);
});

test('잘못된 날짜는 요청하지 않고 빈 결과와 오류를 안내한다', async (t) => {
  const f = fixture(t, { items: [], total: 0 });
  await f.controller.show();
  assert.match(f.el('feedback-message').textContent, /조건에 맞는 의견이 없습니다/);
  const count = f.calls.length;
  f.el('filter-start').value = '2026-10-28';
  await f.el('feedback-filters').fire('submit');
  assert.equal(f.calls.length, count);
  assert.match(f.el('feedback-message').textContent, /시작일/);
  f.el('filter-start').value = '';
  f.state.request = async () => { throw Object.assign(new Error('저장소를 사용할 수 없습니다.'), { status: 503 }); };
  await f.el('feedback-filters').fire('submit');
  assert.match(f.el('feedback-message').textContent, /저장소/);
  assert.equal(f.el('feedback-next').disabled, true);
});

test('변경한 상태만 저장하고 실패하면 재시도할 수 있다', async (t) => {
  const f = fixture(t);
  await f.controller.show();
  const select = f.el('feedback-list').querySelectorAll('select')[0];
  const save = f.el('feedback-list').querySelectorAll('button')[0];
  assert.equal(save.disabled, true);
  select.value = 'resolved';
  await select.fire('change');
  assert.equal(save.disabled, false);
  f.state.request = async (url, body, method) => {
    if (method === 'PATCH') throw Object.assign(new Error('저장 실패'), { status: 503 });
    return { items: [feedback({ status: 'resolved' })], total: 1 };
  };
  await save.fire('click');
  assert.deepEqual(f.calls.at(-1).body, { status: 'resolved' });
  assert.match(f.el('feedback-message').textContent, /저장 실패/);
  assert.equal(save.disabled, false);
  f.state.request = null;
  await save.fire('click');
  assert.match(f.el('feedback-message').textContent, /저장했습니다/);
});

test('삭제 취소는 요청하지 않고 마지막 페이지 삭제 후 앞 페이지로 이동한다', async (t) => {
  const f = fixture(t, { total: 51 });
  await f.controller.show();
  await f.el('feedback-next').fire('click');
  f.state.confirmed = false;
  const remove = f.el('feedback-list').querySelectorAll('button').at(-1);
  const count = f.calls.length;
  await remove.fire('click');
  assert.equal(f.calls.length, count);
  f.state.confirmed = true;
  f.state.total = 50;
  await remove.fire('click');
  assert.equal(f.calls[count].method, 'DELETE');
  assert.deepEqual(f.calls[count].body, {});
  assert.match(f.calls.at(-1).url, /page=1/);
  assert.match(f.el('feedback-message').textContent, /이메일을 삭제했습니다/);
});

test('이메일 복사와 권한 거부 시 직접 복사를 지원하고 만료 이메일은 표시하지 않는다', async (t) => {
  const copied = [];
  const f = fixture(t, { items: [feedback({ email: 'reply@example.com', email_expires_at: '2027-01-01T00:00:00Z' })],
    clipboard: { writeText: async (value) => { copied.push(value); } } });
  await f.controller.show();
  await f.el('feedback-list').querySelectorAll('button')[0].fire('click');
  assert.deepEqual(copied, ['reply@example.com']);
  assert.match(f.el('feedback-list').textContent, /복사했습니다/);
  f.controller.hide();
  const denied = fixture(t, { items: f.state.items, clipboard: { writeText: async () => { throw new Error('denied'); } } });
  await denied.controller.show();
  await denied.el('feedback-list').querySelectorAll('button')[0].fire('click');
  assert.equal(denied.doc.focused.value, 'reply@example.com');
  assert.equal(denied.doc.focused.selected, true);
  assert.match(denied.el('feedback-list').textContent, /직접 복사/);
  denied.state.items = [feedback({ email: 'expired@example.com', email_expires_at: NOW.toISOString() })];
  await denied.el('feedback-filters').fire('submit');
  assert.equal(denied.el('feedback-list').querySelectorAll('input').length, 0);
});

test('화면을 닫은 후 늦게 도착한 응답은 개인정보를 다시 표시하지 않는다', async (t) => {
  let finish;
  const f = fixture(t, { request: async (url) => {
    if (url.startsWith('/api/admin/usage')) return usage();
    return new Promise((resolve) => { finish = resolve; });
  } });
  const pending = f.controller.show();
  assert.equal(f.el('feedback-list')['aria-busy'], 'true');
  f.controller.hide();
  assert.equal(f.calls[1].opts.signal.aborted, true);
  finish({ items: [feedback()], total: 1 });
  await pending;
  assert.equal(f.el('dashboard').hidden, true);
  assert.equal(f.el('feedback-list').children.length, 0);
  assert.equal(f.el('usage-totals').children.length, 0);
});

test('401 응답은 모든 비공개 데이터를 지우고 로그인 화면으로 넘긴다', async (t) => {
  const f = fixture(t);
  await f.controller.show();
  f.state.request = async () => { throw Object.assign(new Error('세션 만료'), { status: 401 }); };
  await f.el('feedback-filters').fire('submit');
  assert.equal(f.unauthorized(), 1);
  assert.equal(f.el('dashboard').hidden, true);
  assert.equal(f.el('feedback-list').children.length, 0);
  assert.equal(f.el('usage-totals').children.length, 0);
});
