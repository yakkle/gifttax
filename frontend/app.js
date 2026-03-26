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

function updateGiftDateHelp() {
    if (typeof document === "undefined") {
        return;
    }

    const giftDateInput = document.getElementById("gift-date");
    const help = document.getElementById("gift-date-help");
    const value = giftDateInput.value;

    if (!value) {
        help.textContent = "";
        help.className = "date-help hidden";
        return;
    }

    const availableFrom = getCalculationAvailabilityDate(value);
    const today = new Date();
    today.setHours(0, 0, 0, 0);

    if (today < availableFrom) {
        help.textContent = `이 증여일은 ${formatDateInputValue(availableFrom)}부터 계산할 수 있습니다.`;
        help.className = "date-help warning";
        return;
    }

    help.textContent = `이 증여일은 현재 계산 가능합니다. 기준 충족일: ${formatDateInputValue(availableFrom)}`;
    help.className = "date-help";
}

function addStock() {
    const container = document.getElementById("stocks-container");
    const row = document.createElement("div");
    row.className = "stock-row";
    row.innerHTML = `
        <input type="text" name="ticker" placeholder="종목코드 (예: AAPL)" required>
        <input type="number" name="qty" placeholder="수량" min="1" required>
        <div class="control-shell control-shell-select">
            <select name="currency">
                <option value="USD" selected>USD</option>
                <option value="EUR">EUR</option>
                <option value="JPY">JPY</option>
                <option value="GBP">GBP</option>
            </select>
        </div>
        <button type="button" class="btn-remove" onclick="removeStock(this)">×</button>
    `;
    container.appendChild(row);
}

function removeStock(button) {
    const container = document.getElementById("stocks-container");
    if (container.children.length > 1) {
        button.parentElement.remove();
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
    const stockRows = document.querySelectorAll(".stock-row");

    const stocks = [];
    stockRows.forEach((row) => {
        const ticker = row.querySelector('input[name="ticker"]').value.toUpperCase();
        const qty = parseInt(row.querySelector('input[name="qty"]').value);
        const currency = row.querySelector('select[name="currency"]').value;

        if (ticker && qty) {
            stocks.push({ ticker, qty, currency });
        }
    });

    const payload = {
        gift_date: giftDate,
        stocks: stocks,
    };

    const response = await fetch(`${API_BASE}/api/calculate`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
        },
        body: JSON.stringify(payload),
    });

    if (!response.ok) {
        const error = await response.json();
        const detail = error.detail;

        if (detail && typeof detail === "object") {
            throw new Error(detail.message || "계산 중 오류가 발생했습니다.");
        }

        throw new Error(detail || "계산 중 오류가 발생했습니다.");
    }

    return response.json();
}

function displayResult(data) {
    const resultDiv = document.getElementById("result");
    const contentDiv = document.getElementById("result-content");

    let html = `<div class="gift-date"><strong>증여일:</strong> ${formatDate(data.gift_date)}</div>`;

    data.stocks.forEach((stock) => {
        // Build price data table
        let priceTableHtml = "";
        if (stock.price_data && stock.price_data.length > 0) {
            const displayPrices = stock.price_data.slice(0, 20); // Show first 20
            priceTableHtml = `
                <div class="price-data-section">
                    <p><strong>주가 데이터 (${stock.price_data.length}일, 전후 2개월):</strong></p>
                    <div class="table-wrapper">
                        <table class="price-table">
                            <thead>
                                <tr>
                                    <th>날짜</th>
                                    <th>종가 (${stock.currency})</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${displayPrices.map(p => `
                                    <tr>
                                        <td>${p.date}</td>
                                        <td>${parseFloat(p.close).toFixed(2)}</td>
                                    </tr>
                                `).join("")}
                                ${stock.price_data.length > 20 ? `
                                    <tr><td colspan="2">...외 ${stock.price_data.length - 20}일</td></tr>
                                ` : ""}
                            </tbody>
                        </table>
                    </div>
                </div>
            `;
        }

        // Build exchange rate data table
        let rateTableHtml = "";
        if (stock.exchange_rate_data && stock.exchange_rate_data.length > 0) {
            const displayRates = stock.exchange_rate_data.slice(0, 10); // Show first 10
            rateTableHtml = `
                <div class="rate-data-section">
                    <p><strong>환율 데이터 (${stock.exchange_rate_data.length}일):</strong></p>
                    <div class="table-wrapper">
                        <table class="rate-table">
                            <thead>
                                <tr>
                                    <th>날짜</th>
                                    <th>매매기준환율 (KRW)</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${displayRates.map(r => `
                                    <tr>
                                        <td>${r.date}</td>
                                        <td>${parseFloat(r.close).toFixed(2)}</td>
                                    </tr>
                                `).join("")}
                                ${stock.exchange_rate_data.length > 10 ? `
                                    <tr><td colspan="2">...외 ${stock.exchange_rate_data.length - 10}일</td></tr>
                                ` : ""}
                            </tbody>
                        </table>
                    </div>
                </div>
            `;
        }

        html += `
            <div class="stock-result">
                <h3>${stock.ticker} (${stock.currency})</h3>
                <p><strong>수량:</strong> ${stock.qty}주</p>
                <p><strong>평균종가:</strong> ${parseFloat(stock.price_average).toFixed(2)} ${stock.currency}</p>
                <p><strong>기간:</strong> ${formatDate(stock.period_start)} ~ ${formatDate(stock.period_end)}</p>
                <p><strong>환율:</strong> ${stock.exchange_rate} KRW/${stock.currency}</p>
                <p><strong>증여금액:</strong> ${formatCurrency(stock.gift_amount_krw)}</p>
                ${priceTableHtml}
                ${rateTableHtml}
            </div>
        `;
    });

    html += `<div class="total-amount">총 증여금액: ${formatCurrency(data.total_gift_amount_krw)}</div>`;

    contentDiv.innerHTML = html;
    resultDiv.classList.remove("hidden");
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

function initApp() {
    if (typeof document === "undefined") {
        return;
    }

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

        const formData = new FormData(form);

        try {
            // 이전 계산의 미다운로드 파일 정리
            await deletePreviousFiles(previousGiftPdfFileId, previousRatePdfFileId);
            previousGiftPdfFileId = null;
            previousRatePdfFileId = null;

            const data = await calculateGift(formData);
            displayResult(data);

            previousGiftPdfFileId = data.gift_pdf_file_id;
            previousRatePdfFileId = data.rate_pdf_file_id;

            document.getElementById("btn-gift-pdf").onclick = () => {
                if (data.gift_pdf_file_id) {
                    downloadFile(data.gift_pdf_file_id);
                    previousGiftPdfFileId = null;
                }
            };

            document.getElementById("btn-rate-pdf").onclick = () => {
                if (data.rate_pdf_file_id) {
                    downloadFile(data.rate_pdf_file_id);
                    previousRatePdfFileId = null;
                }
            };

            // smbs.biz 링크 설정 - 실제 환율 적용일 사용
            const smbsLink = document.getElementById("btn-smbs");
            if (data.stocks && data.stocks.length > 0) {
                const currency = data.stocks[0].currency;
                const rateDateStr = data.exchange_rate_date;
                const rateDate = new Date(rateDateStr);
                const year = rateDate.getFullYear();
                const month = String(rateDate.getMonth() + 1).padStart(2, "0");
                const day = String(rateDate.getDate()).padStart(2, "0");
                const smbsUrl = `http://www.smbs.biz/ExRate/StdExRatePop.jsp?StrSch_sYear=${year}&StrSch_sMonth=${month}&StrSch_sDay=${day}&StrSch_eYear=${year}&StrSch_eMonth=${month}&StrSch_eDay=${day}&tongwha_code=${currency}`;
                smbsLink.href = smbsUrl;
                smbsLink.style.display = "inline-block";
            } else {
                smbsLink.style.display = "none";
            }
        } catch (error) {
            console.error("Error:", error);
            const errorDiv = document.createElement("div");
            errorDiv.className = "error";

            // 400 에러인 경우 (잘못된 종목 코드 등) 더 명확한 메시지
            if (error.message.includes("종목 코드를 찾을 수 없습니다")) {
                errorDiv.innerHTML = "<strong>종목 코드를 확인해 주세요.</strong><br>" + error.message;
            } else {
                errorDiv.textContent = "오류: " + error.message;
            }

            form.appendChild(errorDiv);
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = "계산하기";
        }
    });
}

if (typeof module !== "undefined" && module.exports) {
    module.exports = {
        addMonths,
        formatDate,
        formatDateInputValue,
        getCalculationAvailabilityDate,
        parseLocalDate,
    };
}

initApp();
