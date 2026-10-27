'use strict';

const GiftTaxDashboard = (() => {
  const metrics = {
    page_views: '페이지 조회', visitors: '이용자 (추정)',
    calculation_successes: '계산 성공', calculation_failures: '계산 실패',
    calculation_users: '계산 이용자 (추정)', gift_pdf_downloads: '증여 PDF 다운로드',
    rate_pdf_downloads: '환율 PDF 다운로드', feedback_submissions: '의견 접수',
    support_clicks: '후원 링크 클릭',
  };
  const categories = { review: '후기', problem: '문제 신고', suggestion: '기능 제안' };
  const ratings = { satisfied: '만족', neutral: '보통', dissatisfied: '불만족' };
  const statuses = { new: '신규', in_progress: '처리 중', resolved: '완료' };
  const sources = { general: '일반 화면', result: '계산 결과', error: '오류 화면' };

  function dateRange(now = new Date()) {
    const parts = new Intl.DateTimeFormat('en-US', {
      timeZone: 'Asia/Seoul', year: 'numeric', month: '2-digit', day: '2-digit',
    }).formatToParts(now);
    const part = (type) => parts.find((item) => item.type === type).value;
    const end = `${part('year')}-${part('month')}-${part('day')}`;
    const start = new Date(`${end}T00:00:00Z`);
    start.setUTCDate(start.getUTCDate() - 29);
    return { start: start.toISOString().slice(0, 10), end };
  }

  function query(filters, page) {
    const params = new URLSearchParams({ page: String(page) });
    for (const [key, value] of Object.entries(filters)) if (value) params.set(key, value);
    return `/api/admin/feedback?${params}`;
  }

  function createDashboard(doc, { request, onUnauthorized, confirm = (text) => window.confirm(text),
    clipboard = globalThis.navigator?.clipboard, now = () => new Date() }) {
    const $ = (id) => doc.getElementById(id);
    const node = (tag, text, className) => {
      const el = doc.createElement(tag);
      if (text !== undefined) el.textContent = text;
      if (className) el.className = className;
      return el;
    };
    let active = false;
    let usageVersion = 0;
    let listVersion = 0;
    let page = 1;
    let total = 0;
    let applied = {};
    let loading = false;
    let abort = new AbortController();
    const contactTimers = new Set();
    const clearContacts = () => {
      for (const timer of contactTimers) clearTimeout(timer);
      contactTimers.clear();
    };
    const status = (id, text, error = false) => {
      $(id).textContent = text;
      $(id).classList.toggle('error', error);
    };
    const failure = (error, id) => {
      if (error.status === 401) {
        hide();
        onUnauthorized();
      } else if (error.name !== 'AbortError') {
        status(id, error.status ? error.message : '서버에 연결할 수 없습니다. 잠시 후 다시 조회해 주세요.', true);
      }
    };
    const lock = (value) => {
      loading = value;
      $('feedback-list').setAttribute('aria-busy', String(value));
      $('feedback-filters').querySelectorAll('input,select,button').forEach((el) => { el.disabled = value; });
      $('feedback-list').querySelectorAll('select,button').forEach((el) => { el.disabled = value || el.dataset.locked === 'true'; });
      $('feedback-prev').disabled = value || page <= 1;
      $('feedback-next').disabled = value || page * 50 >= total;
    };
    const readFilters = () => ({
      start_date: $('filter-start').value, end_date: $('filter-end').value,
      category: $('filter-category').value, satisfaction: $('filter-satisfaction').value,
      status: $('filter-status').value,
    });

    async function loadUsage() {
      const version = ++usageVersion;
      $('usage-totals').replaceChildren();
      $('usage-daily').replaceChildren();
      $('usage-details').hidden = true;
      $('usage-form').querySelectorAll('select,button').forEach((el) => { el.disabled = true; });
      status('usage-message', '이용 통계를 불러오는 중입니다.');
      try {
        const data = await request(`/api/admin/usage?days=${$('usage-days').value}`, null, 'GET', { signal: abort.signal });
        if (!active || version !== usageVersion) return;
        status('usage-message', `${data.period_start} ~ ${data.period_end} · 한국 시간 · ${data.period_days}일`);
        for (const [key, label] of Object.entries(metrics)) {
          const item = node('div');
          item.append(node('dt', label), node('dd', data.totals[key].toLocaleString('ko-KR')));
          $('usage-totals').append(item);
        }
        const heading = node('tr');
        const dateHeading = node('th', '날짜');
        dateHeading.scope = 'col';
        heading.append(dateHeading);
        for (const label of Object.values(metrics)) {
          const th = node('th', label);
          th.scope = 'col';
          heading.append(th);
        }
        $('usage-head').replaceChildren(heading);
        for (const day of data.daily) {
          const tr = node('tr');
          const th = node('th', day.day);
          th.scope = 'row';
          tr.append(th);
          for (const key of Object.keys(metrics)) tr.append(node('td', day[key].toLocaleString('ko-KR')));
          $('usage-daily').append(tr);
        }
        $('usage-details').hidden = false;
      } catch (error) {
        if (active && version === usageVersion) failure(error, 'usage-message');
      } finally {
        if (active && version === usageVersion) $('usage-form').querySelectorAll('select,button').forEach((el) => { el.disabled = false; });
      }
    }

    function card(item) {
      const article = node('article', undefined, 'feedback-card');
      const heading = node('h3', `${categories[item.category]} · ${ratings[item.satisfaction] || '만족도 미선택'}`);
      const stamp = new Date(item.created_at).toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' });
      article.append(heading, node('p', `${stamp} (한국 시간) · ${sources[item.source]}`, 'hint'));
      article.append(node('p', item.message || '만족도만 남긴 의견입니다.', 'feedback-body'));
      const emailRow = node('div', undefined, 'email-row');
      if (item.email && new Date(item.email_expires_at) > now()) {
        const input = node('input');
        input.type = 'text';
        input.readOnly = true;
        input.value = item.email;
        input.setAttribute('aria-label', '답변 받을 이메일');
        const copy = node('button', '이메일 복사', 'secondary');
        copy.type = 'button';
        const note = node('span', '', 'hint');
        note.setAttribute('role', 'status');
        const expire = () => {
          input.value = '';
          copy.disabled = true;
          copy.dataset.locked = 'true';
          note.textContent = '이메일 보관 기간이 만료되었습니다.';
        };
        const remaining = new Date(item.email_expires_at) - now();
        if (remaining <= 2147483647) contactTimers.add(setTimeout(expire, remaining));
        copy.addEventListener('click', async () => {
          if (new Date(item.email_expires_at) <= now()) { expire(); return; }
          const version = listVersion;
          try {
            if (!clipboard?.writeText) throw new Error('clipboard unavailable');
            await clipboard.writeText(input.value);
            if (active && version === listVersion) note.textContent = '이메일을 복사했습니다.';
          } catch {
            if (!active || version !== listVersion) return;
            input.focus();
            input.select();
            note.textContent = '선택한 이메일을 직접 복사해 주세요.';
          }
        });
        emailRow.append(input, copy, note);
      } else emailRow.append(node('span', '이메일 없음 또는 보관 기간 만료', 'hint'));
      article.append(emailRow);
      const controls = node('div', undefined, 'card-controls');
      const label = node('label', '처리 상태');
      const select = node('select');
      select.setAttribute('aria-label', `${categories[item.category]} 처리 상태`);
      for (const [value, text] of Object.entries(statuses)) {
        const option = node('option', text);
        option.value = value;
        select.append(option);
      }
      select.value = item.status;
      label.append(select);
      const save = node('button', '상태 저장');
      save.type = 'button';
      save.disabled = true;
      save.dataset.locked = 'true';
      select.addEventListener('change', () => {
        save.dataset.locked = String(select.value === item.status);
        save.disabled = loading || select.value === item.status;
      });
      save.addEventListener('click', () => mutate(item, 'PATCH', { status: select.value }));
      const remove = node('button', '의견 삭제', 'danger');
      remove.type = 'button';
      remove.addEventListener('click', () => {
        if (confirm('이 의견을 삭제할까요? 함께 보관한 이메일도 삭제되며 복구할 수 없습니다.')) mutate(item, 'DELETE', {});
      });
      controls.append(label, save, remove);
      article.append(controls);
      return article;
    }

    async function loadList(nextPage = 1, notice = '') {
      if (!active) return;
      const version = ++listVersion;
      page = nextPage;
      clearContacts();
      $('feedback-list').replaceChildren();
      $('feedback-page').textContent = '';
      lock(true);
      status('feedback-message', '의견을 불러오는 중입니다.');
      try {
        const data = await request(query(applied, page), null, 'GET', { signal: abort.signal });
        if (!active || version !== listVersion) return;
        total = data.total;
        const lastPage = Math.max(1, Math.ceil(total / 50));
        if (page > lastPage) return await loadList(lastPage, notice);
        $('feedback-list').replaceChildren(...data.items.map(card));
        $('feedback-page').textContent = `${page} / ${lastPage} 페이지 · 총 ${total.toLocaleString('ko-KR')}개`;
        status('feedback-message', notice || (total ? '최신 의견부터 표시합니다.' : '조건에 맞는 의견이 없습니다.'));
      } catch (error) {
        // A failed page must not leave navigation enabled using an old total.
        if (active && version === listVersion) {
          total = 0;
          failure(error, 'feedback-message');
        }
      } finally {
        if (active && version === listVersion) lock(false);
      }
    }

    async function mutate(item, method, body) {
      if (!active || loading) return;
      const version = listVersion;
      lock(true);
      status('feedback-message', method === 'DELETE' ? '삭제 중입니다.' : '저장 중입니다.');
      try {
        await request(`/api/admin/feedback/${encodeURIComponent(item.id)}`, body, method, { signal: abort.signal });
        if (!active || version !== listVersion) return;
        await loadList(page, method === 'DELETE' ? '의견과 이메일을 삭제했습니다.' : '처리 상태를 저장했습니다.');
      } catch (error) {
        if (active && version === listVersion) failure(error, 'feedback-message');
      } finally {
        if (active && version === listVersion) lock(false);
      }
    }

    function hide() {
      active = false;
      ++usageVersion;
      ++listVersion;
      abort.abort();
      clearContacts();
      $('dashboard').hidden = true;
      for (const id of ['feedback-list', 'usage-totals', 'usage-head', 'usage-daily']) $(id).replaceChildren();
      for (const id of ['feedback-message', 'feedback-page', 'usage-message']) $(id).textContent = '';
      $('usage-details').hidden = true;
    }
    async function show() {
      hide();
      active = true;
      abort = new AbortController();
      const range = dateRange(now());
      $('filter-start').value = range.start;
      $('filter-end').value = range.end;
      $('filter-start').max = range.end;
      $('filter-end').max = range.end;
      for (const id of ['filter-category', 'filter-satisfaction', 'filter-status']) $(id).value = '';
      $('usage-days').value = '30';
      applied = readFilters();
      $('dashboard').hidden = false;
      await Promise.all([loadUsage(), loadList()]);
    }
    $('usage-form').addEventListener('submit', (event) => { event.preventDefault(); if (active) loadUsage(); });
    $('feedback-filters').addEventListener('submit', (event) => {
      event.preventDefault();
      if (!active || loading) return;
      if ($('filter-start').value && $('filter-end').value && $('filter-start').value > $('filter-end').value) {
        status('feedback-message', '시작일은 종료일보다 늦을 수 없습니다.', true);
        return;
      }
      applied = readFilters();
      loadList();
    });
    $('feedback-prev').addEventListener('click', () => { if (active && !loading && page > 1) loadList(page - 1); });
    $('feedback-next').addEventListener('click', () => { if (active && !loading && page * 50 < total) loadList(page + 1); });
    return { show, hide };
  }
  return { createDashboard, dateRange, query, metrics };
})();

if (typeof module !== 'undefined') module.exports = GiftTaxDashboard;
