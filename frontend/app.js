const { createInstrumentController } = typeof module !== "undefined" && module.exports
    ? require("./instruments.js") : globalThis.GiftInstruments;
const instrumentRows = new WeakMap();
let instrumentRowId = 0;

const API_BASE = "";

function parseLocalDate(value) {
    const [year, month, day] = value.split("-").map(Number);
    return new Date(year, month - 1, day);
}

function formatDateInputValue(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");
    return `${year}-${month}-${day}`;
}

function addMonths(date, months) {
    const result = new Date(date.getFullYear(), date.getMonth(), date.getDate());
    const targetMonth = result.getMonth() + months;
    result.setMonth(targetMonth);

    if (result.getMonth() !== ((targetMonth % 12) + 12) % 12) {
        result.setDate(0);
    }

    return result;
}

function getCalculationAvailabilityDate(giftDateValue) {
    const giftDate = parseLocalDate(giftDateValue);
    const displayPeriodEnd = addMonths(giftDate, 2);
    displayPeriodEnd.setDate(displayPeriodEnd.getDate() - 1);
    displayPeriodEnd.setHours(0, 0, 0, 0);

    const availableFrom = new Date(displayPeriodEnd);
    availableFrom.setDate(availableFrom.getDate() + 1);
    return availableFrom;
}

function getTodayDateValue(now = new Date()) {
    const parts = new Intl.DateTimeFormat("en-CA", {
        timeZone: "Asia/Seoul", year: "numeric", month: "2-digit", day: "2-digit",
    }).formatToParts(now);
    const value = (type) => parts.find((part) => part.type === type).value;
    return `${value("year")}-${value("month")}-${value("day")}`;
}

function getGiftDateHelp(value, assetTypes, today = getTodayDateValue()) {
    if (!value) return { text: "", warning: false };
    if (value > today) return { text: "미래 증여일은 계산할 수 없습니다.", warning: true };
    if (assetTypes.includes("stock")) {
        const available = formatDateInputValue(getCalculationAvailabilityDate(value));
        return today < available
            ? { text: `주식이 포함되어 ${available}부터 계산할 수 있습니다.`, warning: true }
            : { text: `주식 평균 산정 기간이 충족되었습니다. 계산 가능일: ${available}`, warning: false };
    }
    if (assetTypes.length && assetTypes.every((type) => type === "etf")) {
        return { text: "ETF는 증여일 전일 기준 최근 거래일 종가로 평가합니다. 해당 종가가 제공되면 계산할 수 있습니다.", warning: false };
    }
    return { text: "종목 유형을 확인하면 계산 가능일을 안내합니다.", warning: false };
}

function updateGiftDateHelp() {
    if (typeof document === "undefined") return;
    const types = Array.from(document.querySelectorAll(".stock-row"))
        .filter((row) => row.querySelector('[name="ticker"]').value.trim())
        .map((row) => instrumentRows.get(row)?.effectiveType() || null);
    const help = document.getElementById("gift-date-help");
    const message = getGiftDateHelp(document.getElementById("gift-date").value, types);
    help.textContent = message.text;
    help.className = `date-help${message.text ? (message.warning ? " warning" : "") : " hidden"}`;
}

function initStockRow(row) {
    const status = row.querySelector(".instrument-status");
    status.id = `instrument-status-${++instrumentRowId}`;
    const ticker = row.querySelector('[name="ticker"]');
    ticker.setAttribute("aria-describedby", status.id);
    row.querySelector('[name="currency"]').setAttribute("aria-describedby", status.id);
    const controller = createInstrumentController({
        tickerInput: ticker, currencyInput: row.querySelector('[name="currency"]'),
        assetInput: row.querySelector('[name="asset_type"]'),
        manualGroup: row.querySelector(".manual-selection"), status,
        retry: row.querySelector(".instrument-retry"), onChange: updateGiftDateHelp,
    });
    instrumentRows.set(row, controller);
    updateGiftDateHelp();
    return controller;
}

function addStock() {
    const row = document.getElementById("stock-row-template").content.firstElementChild.cloneNode(true);
    document.getElementById("stocks-container").appendChild(row);
    initStockRow(row);
}

function removeStock(button) {
    const container = document.getElementById("stocks-container");
    if (container.children.length > 1) {
        const row = button.closest(".stock-row");
        instrumentRows.get(row)?.destroy();
        row.remove();
        updateGiftDateHelp();
    }
}

function formatCurrency(amount) {
    return new Intl.NumberFormat("ko-KR", {
        style: "currency",
        currency: "KRW",
        maximumFractionDigits: 0,
    }).format(amount);
}

function formatDate(dateStr) {
    if (typeof dateStr !== "string") {
        return "";
    }

    const [year, month, day] = dateStr.split("-").map(Number);
    if (!year || !month || !day) {
        return dateStr;
    }

    return `${year}. ${month}. ${day}.`;
}

async function calculateGift(formData) {
    const giftDate = formData.get("gift-date");
    if (giftDate > getTodayDateValue()) throw new Error("미래 증여일은 계산할 수 없습니다.");
    const stockRows = Array.from(document.querySelectorAll(".stock-row"));
    const stocks = [];
    const selections = [];
    for (const row of stockRows) {
        const controller = instrumentRows.get(row) || initStockRow(row);
        const assetType = await controller.selection();
        const ticker = row.querySelector('[name="ticker"]').value.trim().toUpperCase();
        const qty = Number(row.querySelector('[name="qty"]').value);
        const currency = row.querySelector('[name="currency"]').value;
        if (!Number.isSafeInteger(qty) || qty <= 0) throw new Error(`${ticker}: 수량은 양의 정수로 입력해 주세요.`);
        stocks.push({ ticker, qty, currency, asset_type: assetType });
        selections.push({ state: controller.getState(), type: controller.effectiveType() });
    }
    const currentRows = Array.from(document.querySelectorAll(".stock-row"));
    if (document.getElementById("gift-date").value !== giftDate
        || currentRows.length !== stockRows.length || stockRows.some((row, index) => {
        const current = instrumentRows.get(row);
        return currentRows[index] !== row || current.getState() !== selections[index].state
            || current.effectiveType() !== selections[index].type
            || row.querySelector('[name="ticker"]').value.trim().toUpperCase() !== stocks[index].ticker
            || Number(row.querySelector('[name="qty"]').value) !== stocks[index].qty
            || row.querySelector('[name="currency"]').value !== stocks[index].currency;
    })) throw new Error("조회 중 종목 입력이 변경되었습니다. 다시 계산해 주세요.");
    const help = getGiftDateHelp(giftDate, stockRows.map((row) => instrumentRows.get(row).effectiveType()));
    if (help.warning) throw new Error(help.text);
    const response = await fetch(`${API_BASE}/api/calculate`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ gift_date: giftDate, stocks }),
    });
    if (!response.ok) {
        const error = await response.json();
        const detail = error.detail;
        const message = typeof detail === "string" ? detail : detail?.message || "계산 중 오류가 발생했습니다.";
        throw new Error(detail?.ticker && !message.includes(detail.ticker) ? `${detail.ticker}: ${message}` : message);
    }
    return response.json();
}

function escapeHtml(value) {
    return String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
}

function formatDecimal(value) {
    // Decimal 문자열을 Number로 변환하지 않아 ETF 종가와 JPY 환율의 정밀도를 유지한다.
    const match = String(value).match(/^(-?)(\d+)(?:\.(\d+))?$/);
    if (!match) return Number.isFinite(Number(value)) ? new Intl.NumberFormat("ko-KR", { minimumFractionDigits: 2, maximumFractionDigits: 20 }).format(Number(value)) : "-";
    const fraction = (match[3] || "").replace(/0+$/, "").padEnd(2, "0");
    return `${match[1]}${match[2].replace(/\B(?=(\d{3})+(?!\d))/g, ",")}.${fraction}`;
}

function renderDataTable(points, heading, valueHeading, formatter, className, limit) {
    if (!points?.length) return "";
    return `<div class="${className}-data-section"><p><strong>${escapeHtml(heading)} (${points.length}일)</strong></p>
        <div class="table-wrapper"><table class="${className}-table"><thead><tr><th>날짜</th><th>${escapeHtml(valueHeading)}</th></tr></thead>
        <tbody>${points.slice(0, limit).map((point) => `<tr><td>${escapeHtml(point.date)}</td><td>${escapeHtml(formatter(point.close))}</td></tr>`).join("")}
        ${points.length > limit ? `<tr><td colspan="2">…외 ${points.length - limit}일</td></tr>` : ""}</tbody></table></div></div>`;
}

function renderResultHtml(data) {
    const text = escapeHtml;
    let html = `<div class="gift-date"><strong>증여일:</strong> ${text(formatDate(data.gift_date))}</div>`;
    for (const stock of data.stocks) {
        const isEtf = stock.asset_type === "etf";
        const price = stock.valuation_price ?? stock.price_average;
        const formatPrice = isEtf ? formatDecimal : (value) => Number(value).toFixed(2);
        const priceDetails = isEtf
            ? `<p><strong>적용 종가:</strong> ${text(formatPrice(price))} ${text(stock.currency)}</p>
               <p><strong>가격 적용일:</strong> ${text(formatDate(stock.price_date))}</p>
               ${stock.price_date_note ? `<p class="valuation-note">${text(stock.price_date_note)}</p>` : ""}`
            : `<p><strong>평균 종가:</strong> ${text(formatPrice(price))} ${text(stock.currency)}</p>
               <p><strong>평균 산정 기간:</strong> ${text(formatDate(stock.period_start))} ~ ${text(formatDate(stock.period_end))}</p>`;
        const priceTable = renderDataTable(stock.price_data, isEtf ? "적용 종가 데이터" : "주가 데이터 (전후 2개월)", `종가 (${stock.currency})`, formatPrice, "price", 20);
        const rateTable = renderDataTable(stock.exchange_rate_data, "환율 데이터", `매매기준환율 (KRW/${stock.currency})`, formatDecimal, "rate", 10);
        html += `<div class="stock-result"><h3>${text(stock.ticker)} (${text(stock.currency)}) <span class="asset-badge">${isEtf ? "ETF" : "주식"}</span></h3>
            <p><strong>수량:</strong> ${text(stock.qty)}주</p>
            ${priceDetails}
            ${["GBp", "GBX"].includes(stock.quote_currency) ? '<p class="valuation-note">펜스 시세를 GBP로 환산한 종가입니다.</p>' : ""}
            <p><strong>환율:</strong> ${text(formatDecimal(stock.exchange_rate))} KRW/${text(stock.currency)}</p>
            <p><strong>환율 적용일:</strong> ${text(formatDate(stock.exchange_rate_date))}</p>
            <p><strong>증여금액:</strong> ${text(formatCurrency(stock.gift_amount_krw))}</p>
            ${priceTable}${rateTable}</div>`;
    }
    return html + `<div class="total-amount">총 증여금액: ${text(formatCurrency(data.total_gift_amount_krw))}</div>`;
}

function getExchangeRateLinks(data) {
    const evidence = data.exchange_rate_evidence?.length ? data.exchange_rate_evidence
        : data.stocks.map((stock) => ({ currency: stock.currency, actual_rate_date: stock.exchange_rate_date }));
    const groups = new Map();
    for (const item of evidence) {
        const key = `${item.currency}:${item.actual_rate_date}`;
        if (groups.has(key)) continue;
        const start = parseLocalDate(item.period_start || item.actual_rate_date);
        const end = parseLocalDate(item.period_end || item.actual_rate_date);
        const params = new URLSearchParams({
            StrSch_sYear: start.getFullYear(), StrSch_sMonth: String(start.getMonth() + 1).padStart(2, "0"), StrSch_sDay: String(start.getDate()).padStart(2, "0"),
            StrSch_eYear: end.getFullYear(), StrSch_eMonth: String(end.getMonth() + 1).padStart(2, "0"), StrSch_eDay: String(end.getDate()).padStart(2, "0"),
            tongwha_code: item.currency,
        });
        groups.set(key, { currency: item.currency, date: item.actual_rate_date, href: `http://www.smbs.biz/ExRate/StdExRatePop.jsp?${params}` });
    }
    return Array.from(groups.values());
}

function displayResult(data) {
    document.getElementById("result-content").innerHTML = renderResultHtml(data);
    document.getElementById("exchange-rate-links").innerHTML = getExchangeRateLinks(data).map((link) =>
        `<a class="btn-download btn-smbs" href="${escapeHtml(link.href)}" target="_blank" rel="noopener noreferrer">${escapeHtml(link.currency)} · ${escapeHtml(formatDate(link.date))} 환율 출력</a>`
    ).join("");
    document.getElementById("result").classList.remove("hidden");
}

function bindResultDownloads(data, doc = document) {
    doc.getElementById("btn-gift-pdf").onclick = () => {
        if (data.gift_pdf_file_id) { downloadFile(data.gift_pdf_file_id); previousGiftPdfFileId = null; }
    };
    doc.getElementById("btn-rate-pdf").onclick = () => {
        if (data.rate_pdf_file_id) { downloadFile(data.rate_pdf_file_id); previousRatePdfFileId = null; }
    };
}

function downloadFile(fileId) {
    window.location.href = `${API_BASE}/api/download/${fileId}`;
}

async function deletePreviousFiles(giftPdfFileId, ratePdfFileId) {
    /**이전 계산의 미다운로드 PDF 파일을 서버에서 정리한다. 실패해도 무시한다. */
    const ids = [giftPdfFileId, ratePdfFileId].filter(Boolean);
    await Promise.allSettled(
        ids.map((id) => fetch(`${API_BASE}/api/download/${id}`, { method: "DELETE" }))
    );
}

let previousGiftPdfFileId = null;
let previousRatePdfFileId = null;

async function trackUsage(eventType, source = "site", target = null) {
    try {
        // A separate event ID makes retried submissions idempotent; no user input is sent.
        const eventId = globalThis.crypto?.randomUUID?.();
        if (!eventId) return false;
        const response = await fetch(`${API_BASE}/api/events`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "same-origin",
            cache: "no-store",
            keepalive: true,
            body: JSON.stringify({ event_id: eventId, event_type: eventType, source, target }),
        });
        return response.ok;
    } catch {
        return false;
    }
}

function initUsageTracking() {
    document.addEventListener("click", (event) => {
        const link = event.target.closest?.("a[data-support-target]");
        if (link) {
            void trackUsage("support_click", link.dataset.supportSource, link.dataset.supportTarget);
        }
    });
    return trackUsage("page_view");
}

function initSupportMenu() {
    const dropdown = document.getElementById("support-dropdown");
    const toggle = document.getElementById("support-toggle");
    const menu = document.getElementById("support-menu");

    function setOpen(open) {
        toggle.setAttribute("aria-expanded", String(open));
        menu.hidden = !open;
    }

    toggle.addEventListener("click", () => setOpen(menu.hidden));

    document.addEventListener("click", (event) => {
        if (!dropdown.contains(event.target)) {
            setOpen(false);
        }
    });

    dropdown.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !menu.hidden) {
            event.preventDefault();
            setOpen(false);
            toggle.focus();
        }
    });

    dropdown.addEventListener("focusout", (event) => {
        if (!dropdown.contains(event.relatedTarget)) {
            setOpen(false);
        }
    });

    menu.addEventListener("click", (event) => {
        if (event.target.closest("a")) {
            setOpen(false);
            toggle.focus();
        }
    });
}

function feedbackSubmissionId() {
    try {
        if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
        const bytes = new Uint8Array(16);
        globalThis.crypto.getRandomValues(bytes);
        bytes[6] = (bytes[6] & 15) | 64;
        bytes[8] = (bytes[8] & 63) | 128;
        const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
        return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
    } catch {
        throw new Error("제출 번호를 만들지 못했습니다. 최신 브라우저에서 다시 시도해 주세요.");
    }
}

function readFeedback(form) {
    const field = (name) => form.elements.namedItem(name);
    const email = field("email").value.trim();
    return {
        satisfaction: field("satisfaction").value || null,
        category: field("category").value,
        message: field("message").value.trim(),
        email: email || null,
        email_consent: Boolean(email && field("email_consent").checked),
        website: field("website").value,
    };
}

function feedbackValidation(values, emailValid) {
    if (!values.satisfaction && !values.message) {
        return { field: "message", message: "만족도를 선택하거나 의견을 작성해 주세요." };
    }
    if (values.message.length > 2000) {
        return { field: "message", message: "의견은 2,000자 이내로 작성해 주세요." };
    }
    if (values.email && (!emailValid || values.email.length > 254)) {
        return { field: "email", message: "이메일 주소를 확인해 주세요." };
    }
    if (values.email && !values.email_consent) {
        return { field: "email_consent", message: "답변용 이메일 수집에 동의해 주세요." };
    }
    return null;
}

class FeedbackRequestError extends Error {
    constructor(message, code) {
        super(message);
        this.code = code;
    }
}

async function postFeedback(payload) {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
        const response = await fetch(`${API_BASE}/api/feedback`, {
            method: "POST",
            credentials: "same-origin",
            cache: "no-store",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
            signal: controller.signal,
        });
        let data = null;
        try { data = await response.json(); } catch { /* Handle empty or non-JSON errors below. */ }
        if (!response.ok) {
            const fallback = response.status === 429
                ? "요청이 많습니다. 1분 뒤 다시 보내주세요."
                : "의견을 보내지 못했습니다. 잠시 후 다시 시도해 주세요.";
            const message = typeof data?.detail?.message === "string" ? data.detail.message : fallback;
            throw new FeedbackRequestError(message, data?.detail?.code);
        }
        if (data?.id !== payload.submission_id) {
            throw new FeedbackRequestError("접수 결과를 확인하지 못했습니다. 입력 내용은 유지되니 다시 보내주세요.");
        }
        return data;
    } catch (error) {
        if (error instanceof FeedbackRequestError) throw error;
        throw new FeedbackRequestError("응답을 확인하지 못했습니다. 연결을 확인한 뒤 다시 보내주세요. 입력 내용은 유지됩니다.");
    } finally {
        clearTimeout(timeout);
    }
}

function initFeedback(root = document) {
    const $ = (id) => root.getElementById(id);
    const form = $("feedback-form");
    if (!form) return { setContext() {} };
    const field = (name) => form.elements.namedItem(name);
    const panel = $("feedback-panel");
    const fields = $("feedback-fields");
    const errorBox = $("feedback-error");
    const success = $("feedback-success");
    const support = $("feedback-support");
    const submit = $("feedback-submit");
    const email = field("email");
    const consent = field("email_consent");
    let source = "general";
    let busy = false;
    let completed = false;
    let attempt = null;

    function updateFields() {
        const hasEmail = Boolean(email.value.trim());
        $("feedback-consent").hidden = !hasEmail;
        consent.disabled = !hasEmail;
        consent.required = hasEmail;
        if (!hasEmail) consent.checked = false;
        $("feedback-count").textContent = `${field("message").value.length.toLocaleString("ko-KR")} / 2,000자`;
    }

    function open(context) {
        source = context;
        panel.open = true;
        panel.scrollIntoView({ block: "start" });
        if (completed) success.focus();
        else form.querySelector('input[name="satisfaction"]').focus({ preventScroll: true });
    }

    function showError(message, name) {
        errorBox.textContent = message;
        errorBox.hidden = false;
        if (name === "email" || name === "email_consent") $("feedback-contact").open = true;
        if (name) field(name).focus();
        else errorBox.focus();
    }

    $("feedback-open").addEventListener("click", () => open("general"));
    $("feedback-error-open").addEventListener("click", () => open("error"));
    panel.addEventListener("toggle", () => {
        $("feedback-open").setAttribute("aria-expanded", String(panel.open));
        $("feedback-error-open").setAttribute("aria-expanded", String(panel.open));
    });
    form.addEventListener("input", updateFields);
    form.addEventListener("change", updateFields);
    $("feedback-clear-rating").addEventListener("click", () => {
        form.querySelectorAll('input[name="satisfaction"]').forEach((radio) => { radio.checked = false; });
    });
    $("feedback-new").addEventListener("click", () => {
        form.reset();
        completed = false;
        attempt = null;
        form.hidden = false;
        fields.disabled = false;
        success.hidden = true;
        support.hidden = true;
        errorBox.hidden = true;
        $("feedback-contact").open = false;
        updateFields();
        open(source);
    });

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        if (busy || completed) return;
        errorBox.hidden = true;
        const values = readFeedback(form);
        const invalid = feedbackValidation(values, email.validity.valid);
        if (invalid) {
            showError(invalid.message, invalid.field);
            return;
        }
        busy = true;
        fields.disabled = true;
        form.setAttribute("aria-busy", "true");
        submit.textContent = "보내는 중...";
        try {
            const fingerprint = JSON.stringify(values);
            // Retry an unchanged request with the same ID and original entry point.
            // An edited draft is a new submission, so a previous receipt cannot mask edits.
            if (!attempt || attempt.fingerprint !== fingerprint) {
                attempt = { fingerprint, payload: { submission_id: feedbackSubmissionId(), ...values, source } };
            }
            await postFeedback(attempt.payload);
            completed = true;
            form.hidden = true;
            success.hidden = false;
            support.hidden = attempt.payload.satisfaction !== "satisfied";
            success.focus();
        } catch (error) {
            // Never log the request body or store feedback/contact details in browser storage.
            showError(error.message);
        } finally {
            busy = false;
            fields.disabled = completed;
            form.setAttribute("aria-busy", "false");
            submit.textContent = "의견 보내기";
        }
    });

    updateFields();
    return {
        setContext(context) {
            source = context;
            $("feedback-error-open").hidden = context !== "error";
            if (context === "result" && !completed) panel.open = true;
        },
    };
}

function initApp() {
    if (typeof document === "undefined") {
        return;
    }

    initSupportMenu();
    void initUsageTracking();
    const feedback = initFeedback();

    addStock();
    document.getElementById("gift-date").max = getTodayDateValue();
    document.getElementById("gift-date").addEventListener("change", updateGiftDateHelp);
    document.getElementById("gift-date").addEventListener("input", updateGiftDateHelp);
    updateGiftDateHelp();

    document.getElementById("gift-form").addEventListener("submit", async (e) => {
        e.preventDefault();

        const form = e.target;
        const submitBtn = form.querySelector(".btn-submit");
        const resultDiv = document.getElementById("result");

        // Remove existing error message
        const existingError = form.querySelector(".error");
        if (existingError) {
            existingError.remove();
        }

        submitBtn.disabled = true;
        submitBtn.textContent = "계산 중...";
        resultDiv.classList.add("hidden");
        feedback.setContext("general");

        const formData = new FormData(form);

        try {
            // 이전 계산의 미다운로드 파일 정리
            await deletePreviousFiles(previousGiftPdfFileId, previousRatePdfFileId);
            previousGiftPdfFileId = null;
            previousRatePdfFileId = null;

            const data = await calculateGift(formData);
            displayResult(data);
            feedback.setContext("result");

            previousGiftPdfFileId = data.gift_pdf_file_id;
            previousRatePdfFileId = data.rate_pdf_file_id;

            bindResultDownloads(data);
        } catch (error) {
            feedback.setContext("error");
            console.error("Error:", error);
            const errorDiv = document.createElement("div");
            errorDiv.className = "error";

            errorDiv.textContent = "오류: " + error.message;
            errorDiv.setAttribute("role", "alert");

            form.appendChild(errorDiv);
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = "계산하기";
        }
    });
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = {
        getTodayDateValue,
        getGiftDateHelp,
        updateGiftDateHelp,
        initStockRow,
        calculateGift,
        displayResult,
        renderResultHtml,
        formatDecimal,
        getExchangeRateLinks,
        bindResultDownloads,
        deletePreviousFiles,
        addMonths,
        formatDate,
        formatDateInputValue,
        getCalculationAvailabilityDate,
        parseLocalDate,
        trackUsage,
        initUsageTracking,
        feedbackSubmissionId,
        readFeedback,
        feedbackValidation,
        postFeedback,
        initFeedback,
    };
}

initApp();
