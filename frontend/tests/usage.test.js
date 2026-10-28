const assert = require("node:assert/strict");
const test = require("node:test");
const { trackUsage, initUsageTracking } = require("../app.js");

test("usage sends only allowlisted event fields with an independent UUID", async (t) => {
    const calls = [];
    t.mock.method(globalThis, "fetch", async (...args) => {
        calls.push(args);
        return { ok: true };
    });
    assert.equal(await trackUsage("page_view"), true);
    assert.equal(await trackUsage("support_click", "header", "fairy"), true);
    const [url, options] = calls[0];
    assert.equal(url, "/api/events");
    assert.equal(options.keepalive, true);
    assert.equal(options.credentials, "same-origin");
    assert.equal(options.cache, "no-store");
    assert.deepEqual(Object.keys(JSON.parse(options.body)).sort(), ["event_id", "event_type", "source", "target"]);
    assert.match(JSON.parse(options.body).event_id, /^[a-f0-9-]{36}$/);
    assert.notEqual(JSON.parse(options.body).event_id, JSON.parse(calls[1][1].body).event_id);
    assert.deepEqual({ ...JSON.parse(calls[1][1].body), event_id: null }, {
        event_id: null, event_type: "support_click", source: "header", target: "fairy",
    });
});

test("network and HTTP errors do not escape to the page", async (t) => {
    const fetch = t.mock.method(globalThis, "fetch", async () => { throw new Error("offline"); });
    assert.equal(await trackUsage("page_view"), false);
    fetch.mock.mockImplementation(async () => ({ ok: false }));
    assert.equal(await trackUsage("page_view"), false);
    t.mock.method(globalThis.crypto, "randomUUID", () => { throw new Error("unsupported"); });
    assert.equal(await trackUsage("page_view"), false);
});

test("support clicks preserve normal navigation while sending the entry point", async (t) => {
    const calls = [];
    t.mock.method(globalThis, "fetch", async (url, options) => {
        calls.push(JSON.parse(options.body));
        return { ok: true };
    });
    let clicked;
    globalThis.document = { addEventListener: (kind, listener) => {
        assert.equal(kind, "click");
        clicked = listener;
    } };
    t.after(() => { delete globalThis.document; });
    await initUsageTracking();
    const link = { dataset: { supportSource: "feedback", supportTarget: "github" } };
    clicked({ target: { closest: () => link }, preventDefault: () => assert.fail("navigation blocked") });
    clicked({ target: { closest: () => null } });
    assert.equal(calls.length, 2);
    assert.equal(calls[0].event_type, "page_view");
    assert.deepEqual({ ...calls[1], event_id: null }, {
        event_id: null, event_type: "support_click", source: "feedback", target: "github",
    });
});
