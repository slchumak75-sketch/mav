import { describe, expect, it } from "vitest";
import {
  coverMonths,
  expectedClosing,
  filterItems,
  fmt,
  needsPurchase,
  seasonalPlan,
  sortItems,
  toCsv,
  totals,
  typicalByCalendarMonth,
  withSeasonalPlan,
} from "./calc.js";

const MONTHS = [
  "2025-10",
  "2025-11",
  "2025-12",
  "2026-01",
  "2026-02",
  "2026-03",
  "2026-04",
  "2026-05",
  "2026-06",
  "2026-07",
  "2026-08",
  "2026-09",
  "2026-10",
].map((key) => ({ key, label: key }));

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
    minReserve: 100,
    months: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
  },
];

const planOpts = { asOf: "2026-10-19", horizonMonths: 2, bufferPercent: 10 };

describe("expectedClosing", () => {
  it("matches opening + in - out", () => {
    expect(expectedClosing(sample[0])).toBe(0);
    expect(expectedClosing(sample[1])).toBe(15);
    expect(expectedClosing(sample[2])).toBe(3);
  });
});

describe("coverMonths", () => {
  it("starts after the as-of month", () => {
    const cover = coverMonths("2026-10-19", 2);
    expect(cover.map((c) => `${c.year}-${c.month}`)).toEqual(["2026-11", "2026-12"]);
  });

  it("wraps the year", () => {
    const cover = coverMonths("2026-11-01", 3);
    expect(cover.map((c) => `${c.year}-${c.month}`)).toEqual([
      "2026-12",
      "2027-1",
      "2027-2",
    ]);
  });
});

describe("typicalByCalendarMonth", () => {
  it("averages two Octobers", () => {
    const typical = typicalByCalendarMonth(sample[1], MONTHS);
    expect(typical[10]).toBe(2.5);
    expect(typical[11]).toBe(1);
    expect(typical[12]).toBe(0);
    expect(typical[4]).toBe(27);
  });
});

describe("seasonalPlan", () => {
  it("covers Nov+Dec and ignores minReserve", () => {
    const dead = seasonalPlan(sample[2], MONTHS, planOpts);
    expect(dead.seasonalDemand).toBe(0);
    expect(dead.neededReserve).toBe(0);
    expect(dead.toPurchase).toBe(0);
    expect(dead.minReserveIgnored).toBe(100);

    const enamel = seasonalPlan(sample[1], MONTHS, planOpts);
    // Nov 1 + Dec 0 = 1; 10% buffer → 1.1 → ceil 2; closing 15 → buy 0
    expect(enamel.seasonalDemand).toBe(1);
    expect(enamel.neededReserve).toBe(2);
    expect(enamel.toPurchase).toBe(0);

    const brava = seasonalPlan(sample[0], MONTHS, planOpts);
    // Nov 0 + Dec 1 = 1; buffer 1.1 → 2; closing 0 → buy 2
    expect(brava.seasonalDemand).toBe(1);
    expect(brava.neededReserve).toBe(2);
    expect(brava.toPurchase).toBe(2);
  });

  it("does not use minReserve even when stock is below it", () => {
    const item = {
      ...sample[2],
      closing: 1,
      minReserve: 50,
      months: sample[2].months,
    };
    const plan = seasonalPlan(item, MONTHS, planOpts);
    expect(plan.toPurchase).toBe(0);
  });

  it("orders stock when closing is below seasonal reserve", () => {
    const item = {
      ...sample[1],
      closing: 0,
    };
    const plan = seasonalPlan(item, MONTHS, { ...planOpts, bufferPercent: 0 });
    expect(plan.neededReserve).toBe(1);
    expect(plan.toPurchase).toBe(1);
  });
});

describe("filterItems", () => {
  const planned = withSeasonalPlan(sample, MONTHS, planOpts);

  it("filters by query across name and sku", () => {
    expect(filterItems(planned, { query: "094977" })).toHaveLength(1);
    expect(filterItems(planned, { query: "эмаль" })).toHaveLength(1);
    expect(filterItems(planned, { query: "грунт" })).toHaveLength(1);
  });

  it("filters by warehouse and purchase need", () => {
    expect(filterItems(planned, { warehouse: "Склад Кореличи" })).toHaveLength(2);
    expect(filterItems(planned, { stock: "buy" }).map((i) => i.id)).toEqual([1]);
    expect(filterItems(planned, { stock: "below" }).map((i) => i.id)).toEqual([1]);
    expect(filterItems(planned, { stock: "zero" })).toHaveLength(1);
    expect(filterItems(planned, { stock: "ok" }).map((i) => i.id)).toEqual([2, 3]);
  });
});

describe("totals", () => {
  it("sums purchase columns and ignores minReserve", () => {
    const planned = withSeasonalPlan(sample, MONTHS, planOpts);
    const t = totals(planned);
    expect(t.items).toBe(3);
    expect(t.opening).toBe(12);
    expect(t.incoming).toBe(127);
    expect(t.outgoing).toBe(121);
    expect(t.closing).toBe(18);
    expect(t.buyCount).toBe(1);
    expect(t.toPurchase).toBe(2);
    expect(t.neededReserve).toBe(4);
    expect(t.zeroStock).toBe(1);
  });
});

describe("needsPurchase", () => {
  it("is true only when toPurchase > 0", () => {
    const planned = withSeasonalPlan(sample, MONTHS, planOpts);
    expect(needsPurchase(planned[0])).toBe(true);
    expect(needsPurchase(planned[1])).toBe(false);
    expect(needsPurchase(planned[2])).toBe(false);
  });
});

describe("sortItems", () => {
  it("sorts by closing desc", () => {
    const sorted = sortItems(sample, "closing", "desc");
    expect(sorted.map((i) => i.id)).toEqual([2, 3, 1]);
  });
});

describe("toCsv / fmt", () => {
  it("emits seasonal columns instead of min reserve", () => {
    const planned = withSeasonalPlan(sample.slice(0, 1), MONTHS, planOpts);
    const csv = toCsv(planned, [{ key: "2025-10", label: "Октябрь 2025 г." }]);
    expect(csv.startsWith("\uFEFF")).toBe(true);
    expect(csv).toContain("Номенклатура");
    expect(csv).toContain("094977");
    expect(csv).toContain("Сезонный резерв");
    expect(csv).toContain("К закупке");
    expect(csv).not.toContain("Мин. резерв");
  });

  it("formats ru numbers", () => {
    expect(fmt(15)).toBe("15");
    expect(fmt(15.5)).toBe("15,50");
  });
});
