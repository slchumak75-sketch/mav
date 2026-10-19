import { describe, expect, it } from "vitest";
import {
  expectedClosing,
  filterItems,
  fmt,
  isBelowMin,
  monthlySeries,
  sortItems,
  toCsv,
  totals,
} from "./calc.js";

const sample = [
  {
    id: 1,
    warehouse: "Склад Кореличи",
    group: "2 краски растворители",
    sku: "094977",
    name: "Краска ВД-АК-1035у белый Брава",
    unit: "шт",
    opening: 1,
    incoming: 0,
    outgoing: 1,
    closing: 0,
    minReserve: 1,
    months: [0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
  },
  {
    id: 2,
    warehouse: "Склад Кореличи",
    group: "2 краски растворители",
    sku: "",
    name: "Эмаль ПФ-115 белая 0,9л (0,85кг)",
    unit: "шт",
    opening: 9,
    incoming: 126,
    outgoing: 120,
    closing: 15,
    minReserve: 6,
    months: [1, 1, 0, 0, 1, 10, 27, 14, 15, 19, 20, 21, 4],
  },
  {
    id: 3,
    warehouse: "Другой склад",
    group: "прочее",
    sku: "X",
    name: "Грунтовка тест",
    unit: "банка",
    opening: 2,
    incoming: 1,
    outgoing: 0,
    closing: 3,
    minReserve: 4,
    months: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
  },
];

describe("expectedClosing", () => {
  it("matches opening + in - out", () => {
    expect(expectedClosing(sample[0])).toBe(0);
    expect(expectedClosing(sample[1])).toBe(15);
    expect(expectedClosing(sample[2])).toBe(3);
  });
});

describe("isBelowMin", () => {
  it("flags rows under reserve", () => {
    expect(isBelowMin(sample[0])).toBe(true);
    expect(isBelowMin(sample[1])).toBe(false);
    expect(isBelowMin(sample[2])).toBe(true);
  });
});

describe("filterItems", () => {
  it("filters by query across name and sku", () => {
    expect(filterItems(sample, { query: "094977" })).toHaveLength(1);
    expect(filterItems(sample, { query: "эмаль" })).toHaveLength(1);
    expect(filterItems(sample, { query: "грунт" })).toHaveLength(1);
  });

  it("filters by warehouse and stock", () => {
    expect(filterItems(sample, { warehouse: "Склад Кореличи" })).toHaveLength(2);
    expect(filterItems(sample, { stock: "below" })).toHaveLength(2);
    expect(filterItems(sample, { stock: "zero" })).toHaveLength(1);
    expect(filterItems(sample, { stock: "ok" })).toHaveLength(1);
  });
});

describe("totals", () => {
  it("sums numeric columns", () => {
    const t = totals(sample);
    expect(t.items).toBe(3);
    expect(t.opening).toBe(12);
    expect(t.incoming).toBe(127);
    expect(t.outgoing).toBe(121);
    expect(t.closing).toBe(18);
    expect(t.belowMin).toBe(2);
    expect(t.zeroStock).toBe(1);
  });
});

describe("sortItems", () => {
  it("sorts by closing desc", () => {
    const sorted = sortItems(sample, "closing", "desc");
    expect(sorted.map((i) => i.id)).toEqual([2, 3, 1]);
  });
});

describe("monthlySeries", () => {
  it("aggregates a month column", () => {
    const months = [{ key: "2025-10", label: "Октябрь 2025 г." }];
    const series = monthlySeries(sample, months);
    expect(series[0].value).toBe(1);
  });
});

describe("toCsv / fmt", () => {
  it("emits a BOM and quoted names", () => {
    const csv = toCsv(sample.slice(0, 1), [{ key: "2025-10", label: "Октябрь 2025 г." }]);
    expect(csv.startsWith("\uFEFF")).toBe(true);
    expect(csv).toContain("Номенклатура");
    expect(csv).toContain("094977");
  });

  it("formats ru numbers", () => {
    expect(fmt(15)).toBe("15");
    expect(fmt(15.5)).toBe("15,50");
  });
});
