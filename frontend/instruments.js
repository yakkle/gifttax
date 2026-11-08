(() => {
/* 종목 행의 조회 상태를 관리한다. 입력 변경은 진행 중인 응답과 수동 선택을 무효화한다. */
function createInstrumentController({ tickerInput, currencyInput, assetInput, manualGroup, status, retry, onChange = () => {}, fetchImpl = globalThis.fetch }) {
    let state = { ticker: "", phase: "empty", info: null };
    let version = 0;
    let pending = null;
    let abort = null;
    let destroyed = false;
    const normalizedTicker = () => tickerInput.value.trim().toUpperCase();
    const supportedCurrencies = ["USD", "EUR", "JPY", "GBP"];

    function effectiveType() {
        if (state.phase === "detected") return state.info.asset_type;
        if (state.phase === "needs_selection") return assetInput.value || null;
        return null;
    }

    function render() {
        manualGroup.hidden = state.phase !== "needs_selection";
        assetInput.disabled = manualGroup.hidden;
        assetInput.required = !manualGroup.hidden;
        retry.hidden = !["needs_selection", "invalid"].includes(state.phase);
        let text = {
            empty: "티커를 입력하면 주식·ETF 유형과 시세 통화를 확인합니다.",
            idle: "입력을 마치면 종목을 확인합니다.",
            loading: "종목 정보를 확인하고 있습니다…",
            detected: `자동 판별: ${effectiveType() === "etf" ? "ETF" : "주식"}`,
            needs_selection: state.message || "유형을 확인할 수 없습니다. 주식 또는 ETF를 선택해 주세요.",
            unsupported: "해외 상장 주식과 ETF만 지원합니다. 이 상품은 계산할 수 없습니다.",
            invalid: state.message || "종목 코드를 확인해 주세요.",
        }[state.phase];
        if (state.phase === "needs_selection" && assetInput.value) {
            text = `수동 선택: ${assetInput.value === "etf" ? "ETF" : "주식"}`;
        }
        if (state.info?.currency) {
            text += ` · 시세 통화 ${state.info.currency}`;
            if (["GBp", "GBX"].includes(state.info.quote_currency)) text += " (펜스 → GBP 환산)";
            if (!supportedCurrencies.includes(state.info.currency)) {
                text += " · 현재 화면에서는 USD·EUR·JPY·GBP만 지원합니다.";
            } else if (currencyInput.value !== state.info.currency) {
                text += ` · 입력 통화를 ${state.info.currency}로 변경해 주세요.`;
            }
        }
        status.textContent = text;
        const warning = ["invalid", "unsupported", "needs_selection"].includes(state.phase)
            || (state.info?.currency && state.info.currency !== currencyInput.value);
        status.className = `instrument-status${warning ? " warning" : ""}`;
        onChange();
    }

    function edit() {
        version += 1;
        abort?.abort();
        pending = null;
        assetInput.value = "";
        state = { ticker: normalizedTicker(), phase: normalizedTicker() ? "idle" : "empty", info: null };
        render();
    }

    function lookup(force = false) {
        if (destroyed) return Promise.resolve(state);
        if (normalizedTicker() !== state.ticker) edit();
        if (!state.ticker) return Promise.resolve(state);
        if (pending) return pending;
        if (!force && state.phase !== "idle") return Promise.resolve(state);
        const requestVersion = ++version;
        const ticker = state.ticker;
        const controller = new AbortController();
        abort = controller;
        assetInput.value = "";
        state = { ticker, phase: "loading", info: null };
        render();
        const current = () => !destroyed && requestVersion === version && normalizedTicker() === ticker;
        const timer = setTimeout(() => controller.abort(), 15000);
        pending = (async () => {
            try {
                const response = await fetchImpl(`/api/instruments/${encodeURIComponent(ticker)}`, {
                    signal: controller.signal, credentials: "same-origin", cache: "no-store",
                });
                const data = await response.json().catch(() => null);
                if (!current()) return state;
                if (!response.ok && response.status === 400) {
                    state = { ticker, phase: "invalid", info: null, message: data?.detail?.message };
                } else if (!response.ok) {
                    throw new Error("lookup failed");
                } else if (data?.ticker !== ticker) {
                    throw new Error("unexpected ticker");
                } else if (data.detection_status === "unsupported") {
                    state = { ticker, phase: "unsupported", info: data };
                } else if (data.detection_status === "detected" && ["stock", "etf"].includes(data.asset_type)) {
                    state = { ticker, phase: "detected", info: data };
                } else {
                    state = { ticker, phase: "needs_selection", info: data, message: data.message };
                }
            } catch {
                if (!current()) return state;
                state = { ticker, phase: "needs_selection", info: null,
                    message: "종목 정보를 조회하지 못했습니다. 다시 확인하거나 주식·ETF를 직접 선택해 주세요." };
            } finally {
                clearTimeout(timer);
                if (current()) {
                    pending = null;
                    render();
                }
            }
            return state;
        })();
        return pending;
    }

    async function selection() {
        await lookup();
        const fail = (message, control = tickerInput) => {
            control.focus();
            throw new Error(`${normalizedTicker() || "종목"}: ${message}`);
        };
        if (destroyed || normalizedTicker() !== state.ticker || ["empty", "idle", "loading"].includes(state.phase)) {
            fail("종목 입력을 확인한 뒤 다시 계산해 주세요.");
        }
        if (state.phase === "invalid") fail(state.message || "종목 코드를 확인해 주세요.");
        if (state.phase === "unsupported") fail("해외 상장 주식과 ETF만 지원합니다.");
        if (state.info?.currency && !supportedCurrencies.includes(state.info.currency)) {
            fail("현재 화면에서는 USD·EUR·JPY·GBP만 지원합니다.", currencyInput);
        }
        if (state.info?.currency && state.info.currency !== currencyInput.value) {
            fail(`시세 통화는 ${state.info.currency}입니다. 입력 통화를 변경해 주세요.`, currencyInput);
        }
        if (state.phase === "needs_selection" && !["stock", "etf"].includes(assetInput.value)) {
            fail("주식 또는 ETF를 선택해 주세요.", assetInput);
        }
        return state.phase === "detected" ? "auto" : assetInput.value;
    }

    tickerInput.addEventListener("input", edit);
    tickerInput.addEventListener("change", () => { void lookup(); });
    tickerInput.addEventListener("blur", () => { void lookup(); });
    currencyInput.addEventListener("change", render);
    assetInput.addEventListener("change", render);
    retry.addEventListener("click", () => { void lookup(true); });
    edit();
    return {
        lookup, selection, effectiveType,
        getState: () => state,
        destroy() { destroyed = true; version += 1; abort?.abort(); },
    };
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = { createInstrumentController };
} else {
    globalThis.GiftInstruments = { createInstrumentController };
}
})();
