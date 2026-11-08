const assert = require("node:assert/strict");
const test = require("node:test");
const { createInstrumentController } = require("../instruments.js");
const { getTodayDateValue, getGiftDateHelp, formatDecimal, renderResultHtml, getExchangeRateLinks, initStockRow, calculateGift, displayResult, bindResultDownloads, deletePreviousFiles } = require("../app.js");

function element(value = "") {
    const events = new Map();
    return {
        value, hidden: false, disabled: false, required: false, textContent: "", innerHTML: "",
        addEventListener(type, fn) { events.set(type, fn); },
        fire(type) { events.get(type)?.(); },
        setAttribute(name, value) { this[name] = value; },
        focus() { this.focused = true; },
        classList: { remove() {}, add() {} },
    };
}
const detection = (ticker = "QQQ", asset_type = "etf", currency = "USD") => ({ ticker, asset_type, currency, detection_status: "detected" });
const response = (data, status = 200) => ({ ok: status === 200, status, json: async () => data });
const deferred = () => {
    let resolve;
    const promise = new Promise((done) => { resolve = done; });
    return { promise, resolve };
};
function controls(fetchImpl, ticker = "QQQ") {
    const fields = {
        tickerInput: element(ticker), currencyInput: element("USD"), assetInput: element(),
        manualGroup: element(), status: element(), retry: element(), fetchImpl,
    };
    return { ...fields, controller: createInstrumentController(fields) };
}

test("자동 판별 유형과 통화를 표시하고 수동 선택란을 숨긴다", async () => {
    const c = controls(async (url, options) => {
        assert.equal(url, "/api/instruments/QQQ");
        assert.ok(options.signal instanceof AbortSignal);
        assert.equal(options.credentials, "same-origin");
        return response(detection());
    }, " qqq ");
    assert.equal(await c.controller.selection(), "auto");
    assert.equal(c.controller.effectiveType(), "etf");
    assert.match(c.status.textContent, /자동 판별: ETF · 시세 통화 USD/);
    assert.equal(c.manualGroup.hidden, true);
    assert.equal(c.assetInput.disabled, true);
});

test("누락된 유형과 조회 실패에만 수동 선택을 허용한다", async () => {
    for (const fetch of [async () => response({ ticker: "QQQ", detection_status: "needs_selection", currency: "USD" }),
        async () => { throw new Error("offline"); }, async () => response(null, 503)]) {
        const c = controls(fetch);
        await assert.rejects(c.controller.selection(), /주식 또는 ETF/);
        assert.equal(c.manualGroup.hidden, false);
        assert.equal(c.assetInput.required, true);
        c.assetInput.value = "etf";
        c.assetInput.fire("change");
        assert.equal(await c.controller.selection(), "etf");
        assert.match(c.status.textContent, /수동 선택: ETF/);
    }
});

test("미지원 상품과 잘못된 티커는 수동 선택으로 우회할 수 없다", async () => {
    for (const [data, status, message] of [
        [{ ticker: "QQQ", detection_status: "unsupported" }, 200, /주식과 ETF만/],
        [{ detail: { message: "종목 코드를 찾을 수 없습니다" } }, 400, /종목 코드/],
    ]) {
        const c = controls(async () => response(data, status));
        await c.controller.lookup();
        c.assetInput.value = "etf";
        assert.equal(c.manualGroup.hidden, true);
        await assert.rejects(c.controller.selection(), message);
    }
});

test("잘못된 티커 오류의 본문이 JSON이 아니어도 수동 선택을 허용하지 않는다", async () => {
    const c = controls(async () => ({ ok: false, status: 400, json: async () => { throw new Error("bad JSON"); } }));
    await assert.rejects(c.controller.selection(), /종목 코드/);
    assert.equal(c.manualGroup.hidden, true);
});

test("티커를 변경하면 판별과 수동 선택을 즉시 초기화한다", async () => {
    const c = controls(async () => response({ ticker: "QQQ", detection_status: "needs_selection" }));
    await c.controller.lookup();
    c.assetInput.value = "etf";
    c.tickerInput.value = "AAPL";
    c.tickerInput.fire("input");
    assert.equal(c.assetInput.value, "");
    assert.equal(c.controller.getState().phase, "idle");
    assert.equal(c.controller.effectiveType(), null);
    assert.equal(c.manualGroup.hidden, true);
});

test("이전 티커의 늦은 응답과 이전 요청의 실패는 새 상태를 덮어쓰지 않는다", async () => {
    for (const old of [response(detection()), response({ ticker: "QQQ", detection_status: "needs_selection" }), response(null, 503)]) {
        const first = deferred();
        const c = controls((url) => url.endsWith("QQQ") ? first.promise : Promise.resolve(response(detection("AAPL", "stock"))));
        const pending = c.controller.lookup();
        c.tickerInput.value = "AAPL";
        c.tickerInput.fire("input");
        await c.controller.lookup();
        first.resolve(old);
        await pending;
        assert.equal(c.controller.getState().ticker, "AAPL");
        assert.equal(c.controller.effectiveType(), "stock");
        assert.equal(c.manualGroup.hidden, true);
    }
});

test("A→B→A로 되돌아와도 첫 A의 늦은 응답을 무시한다", async () => {
    const first = deferred();
    let count = 0;
    const c = controls(async () => ++count === 1 ? first.promise : response(detection()));
    const pending = c.controller.lookup();
    c.tickerInput.value = "AAPL";
    c.tickerInput.fire("input");
    c.tickerInput.value = "QQQ";
    c.tickerInput.fire("input");
    await c.controller.lookup();
    first.resolve(response({ ticker: "QQQ", detection_status: "unsupported" }));
    await pending;
    assert.equal(c.controller.getState().phase, "detected");
});

test("동일 티커의 blur·change·계산 대기는 한 요청을 공유한다", async () => {
    const request = deferred();
    let count = 0;
    const c = controls(() => { count++; return request.promise; });
    c.tickerInput.fire("blur");
    c.tickerInput.fire("change");
    const selected = c.controller.selection();
    assert.equal(count, 1);
    request.resolve(response(detection()));
    assert.equal(await selected, "auto");
});

test("GBP 펜스 시세와 통화 불일치를 안내하고 수정 전에는 계산을 막는다", async () => {
    const c = controls(async () => response({ ...detection("ISF.L", "etf", "GBP"), quote_currency: "GBp" }), "ISF.L");
    await assert.rejects(c.controller.selection(), /GBP.*입력 통화/);
    assert.match(c.status.textContent, /펜스 → GBP 환산/);
    assert.match(c.status.textContent, /GBP로 변경/);
    c.currencyInput.value = "GBP";
    c.currencyInput.fire("change");
    assert.equal(await c.controller.selection(), "auto");
    assert.doesNotMatch(c.status.textContent, /변경해/);
});

test("화면에서 지원하지 않는 통화는 계산 전에 안내한다", async () => {
    const c = controls(async () => response(detection("QQQ", "etf", "CHF")));
    await assert.rejects(c.controller.selection(), /USD·EUR·JPY·GBP/);
});

test("재조회가 성공하면 이전 수동 선택을 지우고 자동 판별로 전환한다", async () => {
    let count = 0;
    const c = controls(async () => response(++count === 1 ? { ticker: "QQQ", detection_status: "needs_selection" } : detection()));
    await c.controller.lookup();
    c.assetInput.value = "stock";
    await c.controller.lookup(true);
    assert.equal(c.assetInput.value, "");
    assert.equal(await c.controller.selection(), "auto");
});

test("조회 시간 초과는 수동 선택을 허용하고 제거한 행의 응답은 무시한다", async (t) => {
    let expire;
    t.mock.method(globalThis, "setTimeout", (callback) => { expire = callback; return 1; });
    t.mock.method(globalThis, "clearTimeout", () => {});
    const c = controls((url, { signal }) => new Promise((resolve, reject) => {
        signal.addEventListener("abort", () => reject(new Error("timeout")));
    }));
    const request = c.controller.lookup();
    expire();
    await request;
    assert.equal(c.controller.getState().phase, "needs_selection");
    const pending = deferred();
    const removed = controls(() => pending.promise);
    const late = removed.controller.lookup();
    removed.controller.destroy();
    pending.resolve(response(detection()));
    await late;
    assert.equal(removed.controller.effectiveType(), null);
});

test("상품 유형에 맞춰 날짜 도움말을 표시하고 미래 증여일은 거절한다", () => {
    const today = "2025-11-10";
    assert.doesNotMatch(getGiftDateHelp(today, ["etf"], today).text, /2개월|2026/);
    assert.equal(getGiftDateHelp(today, ["etf"], today).warning, false);
    assert.match(getGiftDateHelp(today, ["etf", "stock"], today).text, /2026-01-10/);
    assert.equal(getGiftDateHelp(today, ["stock"], today).warning, true);
    assert.match(getGiftDateHelp(today, [null], today).text, /종목 유형/);
    assert.match(getGiftDateHelp("2025-11-11", ["etf"], today).text, /미래/);
    assert.equal(getGiftDateHelp("2025-09-10", ["stock"], today).warning, false);
    assert.equal(getTodayDateValue(new Date("2025-11-09T15:00:00Z")), today);
});

const stock = (overrides = {}) => ({ ticker: "QQQ", asset_type: "etf", qty: 10, currency: "USD", valuation_price: "200.12345", price_average: "200.12345", price_date: "2025-11-07", price_date_note: "전일 종가가 없어 이전 최근 거래일 적용", period_start: "2025-11-07", period_end: "2025-11-07", price_data: [{ date: "2025-11-07", close: "200.12345" }], exchange_rate: "9.3943", exchange_rate_date: "2025-11-06", exchange_rate_data: [{ date: "2025-11-06", close: "9.3943" }], gift_amount_krw: "2601605", ...overrides });
const result = (stocks = [stock()]) => ({ gift_date: "2025-11-10", stocks, total_gift_amount_krw: "2601605" });

test("ETF 종가·적용일과 주식 평균·기간을 구분하고 정밀도를 유지한다", () => {
    const etf = renderResultHtml(result());
    assert.match(etf, /적용 종가:.*200\.12345/);
    assert.match(etf, /가격 적용일:.*2025\. 11\. 7\./);
    assert.match(etf, /환율 적용일:.*2025\. 11\. 6\./);
    assert.match(etf, /이전 최근 거래일/);
    assert.match(etf, /9\.3943 KRW\/USD/);
    assert.doesNotMatch(etf, /평균 종가|평균 산정 기간|전후 2개월/);
    const equity = renderResultHtml(result([stock({ asset_type: "stock", valuation_price: "150.00", period_start: "2025-09-07", period_end: "2026-01-05", price_date: null })]));
    assert.match(equity, /평균 종가:.*150\.00/);
    assert.match(equity, /평균 산정 기간:.*2025\. 9\. 7\. ~ 2026\. 1\. 5\./);
    assert.doesNotMatch(equity, /가격 적용일/);
    assert.equal(formatDecimal("123456789.123450000001"), "123,456,789.123450000001");
    assert.equal(formatDecimal("200"), "200.00");
});

test("결과의 티커·주석은 HTML로 실행하지 않고 텍스트로 표시한다", () => {
    const html = renderResultHtml(result([stock({ ticker: '<img src=x onerror="alert(1)">', price_date_note: "<script>bad()</script>" })]));
    assert.doesNotMatch(html, /<img|<script>/);
    assert.match(html, /&lt;img/);
});

test("모든 통화·적용일별 원문 링크를 중복 없이 제공하고 증빙 기간을 사용한다", () => {
    const data = result();
    data.exchange_rate_evidence = [
        { currency: "USD", actual_rate_date: "2025-11-07", period_start: "2025-11-06", period_end: "2025-11-08" },
        { currency: "USD", actual_rate_date: "2025-11-07" },
        { currency: "JPY", actual_rate_date: "2025-11-06", period_start: "2025-11-05", period_end: "2025-11-07" },
        { currency: "USD", actual_rate_date: "2025-11-06" },
    ];
    const links = getExchangeRateLinks(data);
    assert.equal(links.length, 3);
    assert.deepEqual(links.map((item) => [item.currency, item.date]), [["USD", "2025-11-07"], ["JPY", "2025-11-06"], ["USD", "2025-11-06"]]);
    const params = new URL(links[1].href).searchParams;
    assert.equal(params.get("tongwha_code"), "JPY");
    assert.equal(params.get("StrSch_sDay"), "05");
    assert.equal(params.get("StrSch_eDay"), "07");
    assert.equal(getExchangeRateLinks(result([stock(), stock({ currency: "EUR" }), stock()])).length, 2);
});

function page(t, tickers = ["QQQ"]) {
    const ids = Object.fromEntries(["gift-date", "gift-date-help", "result", "result-content", "exchange-rate-links", "btn-gift-pdf", "btn-rate-pdf"].map((id) => [id, element()]));
    ids["gift-date"].value = "2025-11-10";
    const rows = tickers.map((ticker) => {
        const fields = { ticker: element(ticker), qty: element("10"), currency: element("USD"), asset_type: element() };
        const info = { ".manual-selection": element(), ".instrument-status": element(), ".instrument-retry": element() };
        return { fields, querySelector(selector) { return selector.startsWith("[name=") ? fields[selector.match(/"(\w+)"/)[1]] : info[selector]; } };
    });
    const doc = { getElementById: (id) => ids[id], querySelectorAll: () => rows };
    globalThis.document = doc;
    t.after(() => { delete globalThis.document; });
    const controllers = rows.map(initStockRow);
    return { doc, ids, rows, controllers, formData: { get: () => ids["gift-date"].value } };
}

test("계산 요청에서 서버 자동 판별과 수동 선택 값을 구분해 전송한다", async (t) => {
    const calls = [];
    t.mock.method(globalThis, "fetch", async (url, options) => {
        if (url.endsWith("QQQ")) return response(detection());
        if (url.endsWith("UNKNOWN")) return response({ ticker: "UNKNOWN", detection_status: "needs_selection" });
        calls.push(JSON.parse(options.body));
        return response(result());
    });
    const p = page(t, ["QQQ", "UNKNOWN"]);
    await p.controllers[1].lookup();
    p.rows[1].fields.asset_type.value = "etf";
    await calculateGift(p.formData);
    assert.deepEqual(calls[0].stocks, [
        { ticker: "QQQ", qty: 10, currency: "USD", asset_type: "auto" },
        { ticker: "UNKNOWN", qty: 10, currency: "USD", asset_type: "etf" },
    ]);
});

test("통화 불일치와 최근 혼합 요청은 계산 API를 호출하기 전에 막는다", async (t) => {
    const calls = [];
    t.mock.method(globalThis, "fetch", async (url) => {
        calls.push(url);
        return response(url.endsWith("AAPL") ? detection("AAPL", "stock") : detection("QQQ", "etf", "EUR"));
    });
    const p = page(t, ["QQQ"]);
    await assert.rejects(calculateGift(p.formData), /시세 통화는 EUR/);
    assert.equal(calls.some((url) => url.endsWith("calculate")), false);
    p.rows[0].fields.ticker.value = "AAPL";
    p.rows[0].fields.ticker.fire("input");
    p.ids["gift-date"].value = getTodayDateValue();
    await assert.rejects(calculateGift(p.formData), /주식이 포함/);
    assert.equal(calls.some((url) => url.endsWith("calculate")), false);
});

test("두 PDF 다운로드 버튼과 이전 파일 삭제 흐름을 유지한다", async (t) => {
    const p = page(t);
    const data = { ...result(), gift_pdf_file_id: "gift-id", rate_pdf_file_id: "rate-id" };
    displayResult(data);
    assert.match(p.ids["result-content"].innerHTML, /ETF/);
    assert.match(p.ids["exchange-rate-links"].innerHTML, /USD.*2025\. 11\. 6\./);
    globalThis.window = { location: {} };
    t.after(() => { delete globalThis.window; });
    bindResultDownloads(data, p.doc);
    p.ids["btn-gift-pdf"].onclick();
    assert.equal(window.location.href, "/api/download/gift-id");
    p.ids["btn-rate-pdf"].onclick();
    assert.equal(window.location.href, "/api/download/rate-id");
    const calls = [];
    t.mock.method(globalThis, "fetch", async (url, options) => { calls.push([url, options.method]); throw new Error("offline"); });
    await deletePreviousFiles("gift-id", "rate-id");
    assert.deepEqual(calls, [["/api/download/gift-id", "DELETE"], ["/api/download/rate-id", "DELETE"]]);
});

test("다른 행을 조회하는 동안 이미 확인한 티커가 바뀌면 이전 입력으로 계산하지 않는다", async (t) => {
    const second = deferred();
    const started = deferred();
    let posted = false;
    t.mock.method(globalThis, "fetch", async (url) => {
        if (url.endsWith("QQQ")) return response(detection());
        if (url.endsWith("AAPL")) { started.resolve(); return second.promise; }
        posted = true;
        return response(result());
    });
    const p = page(t, ["QQQ", "AAPL"]);
    const calculation = calculateGift(p.formData);
    await started.promise;
    p.rows[0].fields.ticker.value = "ISF.L";
    p.rows[0].fields.ticker.fire("input");
    second.resolve(response(detection("AAPL", "stock")));
    await assert.rejects(calculation, /입력이 변경/);
    assert.equal(posted, false);
});

test("미래 증여일은 종목 조회와 계산 요청을 보내지 않는다", async (t) => {
    t.mock.method(globalThis, "fetch", () => assert.fail("future request sent"));
    const p = page(t);
    p.ids["gift-date"].value = "2099-12-31";
    await assert.rejects(calculateGift(p.formData), /미래 증여일/);
});

test("서버의 종목별 오류에 티커를 포함해 안내한다", async (t) => {
    t.mock.method(globalThis, "fetch", async (url) => url.endsWith("QQQ") ? response(detection())
        : response({ detail: { code: "PRICE_DATA_UNAVAILABLE", ticker: "QQQ", message: "종가 데이터가 없습니다." } }, 422));
    const p = page(t);
    await assert.rejects(calculateGift(p.formData), /QQQ: 종가 데이터/);
});

test("브라우저의 동일 전역 범위에서 두 스크립트를 순서대로 로드할 수 있다", () => {
    const vm = require("node:vm");
    const fs = require("node:fs");
    const path = require("node:path");
    const context = vm.createContext({});
    for (const name of ["instruments.js", "app.js"]) {
        vm.runInContext(fs.readFileSync(path.join(__dirname, "..", name), "utf8"), context);
    }
    assert.equal(typeof context.GiftInstruments.createInstrumentController, "function");
});
