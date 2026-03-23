const assert = require("node:assert/strict");
const test = require("node:test");

const {
    addMonths,
    formatDate,
    formatDateInputValue,
    getCalculationAvailabilityDate,
    parseLocalDate,
} = require("../app.js");

test("parseLocalDate preserves calendar date in local time", () => {
    const parsed = parseLocalDate("2025-11-06");

    assert.equal(parsed.getFullYear(), 2025);
    assert.equal(parsed.getMonth(), 10);
    assert.equal(parsed.getDate(), 6);
});

test("addMonths handles month-end safely", () => {
    const result = addMonths(new Date(2024, 11, 31), 2);

    assert.equal(formatDateInputValue(result), "2025-02-28");
});

test("getCalculationAvailabilityDate returns gift date plus two months", () => {
    const availableFrom = getCalculationAvailabilityDate("2025-11-06");

    assert.equal(formatDateInputValue(availableFrom), "2026-01-06");
});

test("getCalculationAvailabilityDate handles leap-year gift dates", () => {
    const availableFrom = getCalculationAvailabilityDate("2024-02-29");

    assert.equal(formatDateInputValue(availableFrom), "2024-04-29");
});

test("formatDate keeps API date string without timezone drift", () => {
    assert.equal(formatDate("2025-09-07"), "2025. 9. 7.");
    assert.equal(formatDate("2026-01-05"), "2026. 1. 5.");
});
