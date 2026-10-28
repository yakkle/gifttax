const assert = require("node:assert/strict");
const test = require("node:test");
const { feedbackSubmissionId, readFeedback, feedbackValidation, postFeedback, initFeedback } = require("../app.js");

// Small DOM boundary double; browser checks cover the actual markup and native controls.
function feedbackPage() {
    const ids = new Map();
    function element(id = "") {
        const listeners = new Map();
        const el = {
            value: "", checked: false, hidden: false, disabled: false, validity: { valid: true },
            addEventListener(type, fn) { listeners.set(type, fn); },
            async fire(type) { await listeners.get(type)?.({ preventDefault() {} }); },
            focus() { page.focused = el; },
            scrollIntoView() { page.scrolled = el; },
            setAttribute(name, value) { el[name] = value; },
        };
        if (id) ids.set(id, el);
        return el;
    }
    const page = { getElementById: (id) => ids.get(id), ids };
    for (const id of ["feedback-form", "feedback-panel", "feedback-fields", "feedback-error", "feedback-success", "feedback-support", "feedback-submit", "feedback-consent", "feedback-count", "feedback-open", "feedback-error-open", "feedback-clear-rating", "feedback-new", "feedback-contact"]) element(id);
    const controls = Object.fromEntries(["category", "message", "email", "email_consent", "website"].map((name) => [name, element()]));
    const radios = ["satisfied", "neutral", "dissatisfied"].map((value) => Object.assign(element(), { value }));
    controls.satisfaction = { get value() { return radios.find((radio) => radio.checked)?.value || ""; } };
    const form = ids.get("feedback-form");
    form.elements = { namedItem: (name) => controls[name] };
    form.querySelector = () => radios[0];
    form.querySelectorAll = () => radios;
    form.reset = () => {
        for (const control of Object.values(controls)) {
            if (control === controls.satisfaction) continue;
            control.value = "";
            control.checked = false;
        }
        controls.category.value = "review";
        radios.forEach((radio) => { radio.checked = false; });
    };
    form.reset();
    Object.assign(page, { controls, radios, form, submit: () => form.fire("submit"), el: (id) => ids.get(`feedback-${id}`) });
    page.el("success").hidden = true;
    page.el("support").hidden = true;
    page.el("error").hidden = true;
    page.controller = initFeedback(page);
    return page;
}

function receipt(payload) {
    return { ok: true, json: async () => ({ id: payload.submission_id }) };
}

function mockReceipts(t, calls) {
    return t.mock.method(globalThis, "fetch", async (url, options) => {
        const payload = JSON.parse(options.body);
        calls.push(payload);
        return receipt(payload);
    });
}

test("만족도만 또는 의견만 제출할 수 있고 빈 의견과 긴 의견은 막는다", () => {
    const page = feedbackPage();
    assert.equal(feedbackValidation(readFeedback(page.form), true).field, "message");
    page.controls.message.value = "  \n  ";
    assert.equal(feedbackValidation(readFeedback(page.form), true).field, "message");
    page.radios[0].checked = true;
    assert.equal(feedbackValidation(readFeedback(page.form), true), null);
    page.radios[0].checked = false;
    page.controls.message.value = "기간 안내가 더 자세하면 좋겠어요";
    assert.equal(feedbackValidation(readFeedback(page.form), true), null);
    page.controls.message.value = "가".repeat(2001);
    assert.equal(feedbackValidation(readFeedback(page.form), true).field, "message");
});

test("이메일 형식과 동의를 확인하고 허용한 필드만 전송한다", () => {
    const page = feedbackPage();
    page.controls.message.value = "  개선 의견  ";
    page.controls.email.value = " reply@example.com ";
    page.controls.gift_value = { value: "1234567" };
    assert.equal(feedbackValidation(readFeedback(page.form), false).field, "email");
    assert.equal(feedbackValidation(readFeedback(page.form), true).field, "email_consent");
    page.controls.email_consent.checked = true;
    assert.deepEqual(readFeedback(page.form), {
        satisfaction: null, category: "review", message: "개선 의견", email: "reply@example.com", email_consent: true, website: "",
    });
    assert.equal(feedbackValidation(readFeedback(page.form), true), null);
    page.controls.email.value = " ";
    assert.equal(readFeedback(page.form).email_consent, false);
});

test("UUID는 매번 다르며 randomUUID가 없으면 안전한 난수로 만든다", (t) => {
    assert.notEqual(feedbackSubmissionId(), feedbackSubmissionId());
    const descriptor = Object.getOwnPropertyDescriptor(globalThis.crypto, "randomUUID");
    Object.defineProperty(globalThis.crypto, "randomUUID", { configurable: true, value: undefined });
    t.after(() => {
        if (descriptor) Object.defineProperty(globalThis.crypto, "randomUUID", descriptor);
        else delete globalThis.crypto.randomUUID;
    });
    assert.match(feedbackSubmissionId(), /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/);
    t.mock.method(globalThis.crypto, "getRandomValues", () => { throw new Error("unavailable"); });
    assert.throws(feedbackSubmissionId, /제출 번호/);
});

test("후기 요청은 같은 출처와 캐시 금지를 적용하고 접수 ID를 확인한다", async (t) => {
    const payload = { submission_id: feedbackSubmissionId(), message: "의견" };
    t.mock.method(globalThis, "fetch", async (url, options) => {
        assert.equal(url, "/api/feedback");
        assert.equal(options.method, "POST");
        assert.equal(options.credentials, "same-origin");
        assert.equal(options.cache, "no-store");
        assert.deepEqual(JSON.parse(options.body), payload);
        assert.ok(options.signal instanceof AbortSignal);
        return receipt(payload);
    });
    assert.equal((await postFeedback(payload)).id, payload.submission_id);
});

test("요청 오류와 불명확한 접수 결과를 한국어로 안내한다", async (t) => {
    const mocked = t.mock.method(globalThis, "fetch", async () => ({ ok: false, json: async () => ({ detail: { code: "EMPTY_FEEDBACK", message: "의견을 입력해 주세요." } }) }));
    await assert.rejects(postFeedback({ submission_id: "id" }), { code: "EMPTY_FEEDBACK", message: "의견을 입력해 주세요." });
    mocked.mock.mockImplementation(async () => ({ ok: false, status: 429, json: async () => { throw new Error("not json"); } }));
    await assert.rejects(postFeedback({}), /1분 뒤/);
    mocked.mock.mockImplementation(async () => ({ ok: false, status: 503, json: async () => null }));
    await assert.rejects(postFeedback({}), /잠시 후/);
    mocked.mock.mockImplementation(async () => ({ ok: true, json: async () => ({ id: "wrong-id" }) }));
    await assert.rejects(postFeedback({ submission_id: "id" }), /접수 결과/);
    mocked.mock.mockImplementation(async () => { throw new Error("offline"); });
    await assert.rejects(postFeedback({}), /입력 내용은 유지/);
});

test("응답 대기가 길어지면 요청을 취소하고 다시 보낼 수 있게 한다", async (t) => {
    let expire;
    let cleared = false;
    t.mock.method(globalThis, "setTimeout", (fn, delay) => {
        assert.equal(delay, 15000);
        expire = fn;
        return 123;
    });
    t.mock.method(globalThis, "clearTimeout", (id) => { cleared = id === 123; });
    t.mock.method(globalThis, "fetch", async (url, { signal }) => new Promise((resolve, reject) => {
        signal.addEventListener("abort", () => reject(new Error("aborted")));
    }));
    const request = postFeedback({});
    expire();
    await assert.rejects(request, /다시 보내주세요/);
    assert.equal(cleared, true);
});

test("검증 실패 시 요청하지 않고 문제 입력으로 초점을 옮긴다", async (t) => {
    t.mock.method(globalThis, "fetch", () => assert.fail("invalid submission sent"));
    const page = feedbackPage();
    await page.submit();
    assert.equal(page.focused, page.controls.message);
    assert.equal(page.el("error").hidden, false);
    page.controls.message.value = "답변 부탁드려요";
    page.controls.email.value = "reply@example.com";
    await page.submit();
    assert.equal(page.focused, page.controls.email_consent);
    assert.equal(page.el("contact").open, true);
});

test("전송 중 중복 제출을 막고 만족한 후기 접수 후 후원을 안내한다", async (t) => {
    const calls = [];
    let finish;
    t.mock.method(globalThis, "fetch", (url, options) => {
        const payload = JSON.parse(options.body);
        calls.push(payload);
        return new Promise((resolve) => { finish = () => resolve(receipt(payload)); });
    });
    const page = feedbackPage();
    page.radios[0].checked = true;
    const pending = page.submit();
    assert.equal(page.el("fields").disabled, true);
    assert.equal(page.form["aria-busy"], "true");
    assert.equal(page.el("support").hidden, true);
    await page.submit();
    assert.equal(calls.length, 1);
    finish();
    await pending;
    assert.equal(page.form.hidden, true);
    assert.equal(page.el("success").hidden, false);
    assert.equal(page.el("support").hidden, false);
    assert.equal(page.focused, page.el("success"));
    await page.submit();
    assert.equal(calls.length, 1);
    await page.el("new").fire("click");
    assert.equal(page.form.hidden, false);
    assert.equal(page.el("fields").disabled, false);
    assert.equal(page.controls.satisfaction.value, "");
    assert.equal(page.el("support").hidden, true);
});

test("실패 후 입력을 유지하고 같은 내용 재시도에는 ID와 최초 출처를 재사용한다", async (t) => {
    const calls = [];
    const mocked = t.mock.method(globalThis, "fetch", async (url, options) => {
        calls.push(JSON.parse(options.body));
        throw new Error("lost receipt");
    });
    const page = feedbackPage();
    page.controller.setContext("error");
    page.controls.message.value = "계산 중 오류가 났어요";
    await page.submit();
    assert.equal(page.el("fields").disabled, false);
    assert.equal(page.controls.message.value, "계산 중 오류가 났어요");
    assert.equal(page.el("error").hidden, false);
    assert.equal(page.el("support").hidden, true);
    page.controller.setContext("result");
    mocked.mock.mockImplementation(async (url, options) => {
        const payload = JSON.parse(options.body);
        calls.push(payload);
        return receipt(payload);
    });
    await page.submit();
    assert.deepEqual(calls[0], calls[1]);
    assert.equal(calls[1].source, "error");
    assert.equal(page.el("support").hidden, true);
});

test("실패한 내용을 수정하면 새 ID를 사용하고 중립·불만에는 후원을 표시하지 않는다", async (t) => {
    const calls = [];
    const mocked = t.mock.method(globalThis, "fetch", async (url, options) => {
        calls.push(JSON.parse(options.body));
        throw new Error("lost receipt");
    });
    const page = feedbackPage();
    page.radios[0].checked = true;
    await page.submit();
    page.radios[0].checked = false;
    page.radios[2].checked = true;
    mocked.mock.mockImplementation(async (url, options) => {
        const payload = JSON.parse(options.body);
        calls.push(payload);
        return receipt(payload);
    });
    await page.submit();
    assert.notEqual(calls[0].submission_id, calls[1].submission_id);
    assert.equal(page.el("support").hidden, true);
    await page.el("new").fire("click");
    page.radios[1].checked = true;
    await page.submit();
    assert.equal(page.el("support").hidden, true);
});

test("이메일 입력 시 동의 항목이 나타나고 이메일을 지우면 동의도 해제한다", async () => {
    const page = feedbackPage();
    assert.equal(page.el("consent").hidden, true);
    assert.equal(page.controls.email_consent.disabled, true);
    page.controls.email.value = "reply@example.com";
    await page.form.fire("input");
    assert.equal(page.el("consent").hidden, false);
    assert.equal(page.controls.email_consent.required, true);
    page.controls.email_consent.checked = true;
    page.controls.email.value = "";
    await page.form.fire("input");
    assert.equal(page.controls.email_consent.checked, false);
    assert.equal(page.controls.email_consent.disabled, true);
});

test("상단 진입은 일반 의견, 오류 진입은 오류 의견, 계산 완료는 결과 의견으로 기록한다", async (t) => {
    const calls = [];
    mockReceipts(t, calls);
    const page = feedbackPage();
    page.controller.setContext("error");
    assert.equal(page.el("error-open").hidden, false);
    await page.el("error-open").fire("click");
    assert.equal(page.el("panel").open, true);
    assert.equal(page.focused, page.radios[0]);
    page.radios[0].checked = true;
    await page.submit();
    await page.el("new").fire("click");
    await page.el("open").fire("click");
    page.radios[0].checked = true;
    await page.submit();
    await page.el("new").fire("click");
    page.controller.setContext("result");
    assert.equal(page.el("error-open").hidden, true);
    page.radios[0].checked = true;
    await page.submit();
    assert.deepEqual(calls.map((call) => call.source), ["error", "general", "result"]);
    await page.el("panel").fire("toggle");
    assert.equal(page.el("open")["aria-expanded"], "true");
});
