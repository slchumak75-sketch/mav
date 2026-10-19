/** Pure inventory helpers. No DOM. Used by the UI and by vitest. */

export const DEFAULT_AS_OF = "2026-10-19";
export const DEFAULT_HORIZON_MONTHS = 2;
export const DEFAULT_BUFFER_PERCENT = 10;

const MONTH_NAMES_RU = {
  1: "январь",
  2: "февраль",
  3: "март",
  4: "апрель",
  5: "май",
  6: "июнь",
  7: "июль",
  8: "август",
  9: "сентябрь",
  10: "октябрь",
  11: "ноябрь",
  12: "декабрь",
};

export function round2(n) {
  return Math.round((Number(n) + Number.EPSILON) * 100) / 100;
}

export function expectedClosing(item) {
  return round2(item.opening + item.incoming - item.outgoing);
}

export function isZeroStock(item) {
  return Number(item.closing) === 0;
}

export function needsPurchase(item) {
  return Number(item.toPurchase) > 0;
}

export function monthTotal(item) {
  return round2((item.months || []).reduce((s, n) => s + Number(n || 0), 0));
}

export function normalizeQuery(q) {
  return String(q || "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

export function matchesQuery(item, q) {
  const needle = normalizeQuery(q);
  if (!needle) return true;
  const hay = [item.name, item.sku, item.warehouse, item.group, item.unit]
    .map((v) => String(v || "").toLowerCase())
    .join(" ");
  return hay.includes(needle);
}

/**
 * @param {object[]} items
 * @param {{ query?: string, warehouse?: string, group?: string, stock?: 'all'|'buy'|'zero'|'ok' }} filters
 */
export function filterItems(items, filters = {}) {
  const stock = filters.stock === "below" ? "buy" : filters.stock || "all";
  return items.filter((item) => {
    if (!matchesQuery(item, filters.query)) return false;
    if (filters.warehouse && item.warehouse !== filters.warehouse) return false;
    if (filters.group && item.group !== filters.group) return false;
    if (stock === "buy" && !needsPurchase(item)) return false;
    if (stock === "zero" && !isZeroStock(item)) return false;
    if (stock === "ok" && (needsPurchase(item) || isZeroStock(item))) return false;
    return true;
  });
}

export function uniqueSorted(items, key) {
  return [...new Set(items.map((i) => i[key]).filter(Boolean))].sort((a, b) =>
    String(a).localeCompare(String(b), "ru"),
  );
}

export function sortItems(items, sortKey, dir = "asc") {
  const mul = dir === "desc" ? -1 : 1;
  const copy = items.slice();
  copy.sort((a, b) => {
    const va = a[sortKey];
    const vb = b[sortKey];
    if (typeof va === "number" && typeof vb === "number") {
      return (va - vb) * mul;
    }
    return String(va ?? "").localeCompare(String(vb ?? ""), "ru") * mul;
  });
  return copy;
}

export function totals(items) {
  const acc = {
    items: items.length,
    opening: 0,
    incoming: 0,
    outgoing: 0,
    closing: 0,
    neededReserve: 0,
    toPurchase: 0,
    buyCount: 0,
    zeroStock: 0,
    monthTotal: 0,
  };
  for (const item of items) {
    acc.opening += Number(item.opening) || 0;
    acc.incoming += Number(item.incoming) || 0;
    acc.outgoing += Number(item.outgoing) || 0;
    acc.closing += Number(item.closing) || 0;
    acc.neededReserve += Number(item.neededReserve) || 0;
    acc.toPurchase += Number(item.toPurchase) || 0;
    acc.monthTotal += monthTotal(item);
    if (needsPurchase(item)) acc.buyCount += 1;
    if (isZeroStock(item)) acc.zeroStock += 1;
  }
  acc.opening = round2(acc.opening);
  acc.incoming = round2(acc.incoming);
  acc.outgoing = round2(acc.outgoing);
  acc.closing = round2(acc.closing);
  acc.neededReserve = round2(acc.neededReserve);
  acc.toPurchase = round2(acc.toPurchase);
  acc.monthTotal = round2(acc.monthTotal);
  return acc;
}

export function monthlySeries(items, months) {
  return (months || []).map((m, idx) => ({
    key: m.key,
    label: m.label,
    value: round2(items.reduce((s, item) => s + Number(item.months?.[idx] || 0), 0)),
  }));
}

export function parseYearMonth(key) {
  const [year, month] = String(key)
    .split("-")
    .map((v) => Number(v));
  return { year, month };
}

export function monthNameRu(month, year) {
  const name = MONTH_NAMES_RU[month] || String(month);
  return year ? `${name} ${year}` : name;
}

/**
 * Next `horizon` full calendar months after the as-of month.
 * Date of report 2026-10-19 → Oct is treated as closed; horizon 2 = Nov, Dec.
 */
export function coverMonths(asOf = DEFAULT_AS_OF, horizon = DEFAULT_HORIZON_MONTHS) {
  const d = new Date(`${asOf}T00:00:00Z`);
  if (Number.isNaN(d.getTime())) {
    throw new Error(`Bad asOf date: ${asOf}`);
  }
  let year = d.getUTCFullYear();
  let month = d.getUTCMonth() + 1;
  const n = Math.max(0, Number(horizon) || 0);
  const list = [];
  for (let i = 0; i < n; i += 1) {
    month += 1;
    if (month > 12) {
      month = 1;
      year += 1;
    }
    list.push({
      month,
      year,
      weight: 1,
      label: monthNameRu(month, year),
    });
  }
  return list;
}

/**
 * Typical sales of a calendar month. October has two observations
 * (2025 and 2026) — they are averaged. Other months have one year.
 * Source minReserve is never used.
 */
export function typicalByCalendarMonth(item, monthsMeta) {
  const buckets = new Map();
  (monthsMeta || []).forEach((meta, idx) => {
    const { month } = parseYearMonth(meta.key);
    if (!month) return;
    if (!buckets.has(month)) buckets.set(month, []);
    buckets.get(month).push(Number(item.months?.[idx] || 0));
  });
  const typical = {};
  for (let m = 1; m <= 12; m += 1) {
    const arr = buckets.get(m) || [];
    typical[m] = arr.length ? arr.reduce((s, v) => s + v, 0) / arr.length : 0;
  }
  return typical;
}

/**
 * Seasonal stock target and purchase qty.
 *
 * neededReserve = ceil( sum(typical[next months]) * (1 + buffer%) )
 * toPurchase    = max(0, neededReserve - closing)
 *
 * minReserve from the xlsx is ignored on purpose.
 */
export function seasonalPlan(item, monthsMeta, options = {}) {
  const asOf = options.asOf || DEFAULT_AS_OF;
  const horizonMonths = Number(options.horizonMonths ?? DEFAULT_HORIZON_MONTHS);
  const bufferPercent = Number(options.bufferPercent ?? DEFAULT_BUFFER_PERCENT);
  const typical = typicalByCalendarMonth(item, monthsMeta);
  const cover = coverMonths(asOf, horizonMonths);
  const seasonalDemand = cover.reduce(
    (s, c) => s + (typical[c.month] || 0) * c.weight,
    0,
  );
  const buffered = seasonalDemand * (1 + bufferPercent / 100);
  const neededReserve = buffered < 1e-9 ? 0 : Math.ceil(buffered - 1e-9);
  const closing = Number(item.closing) || 0;
  const toPurchase = round2(Math.max(0, neededReserve - closing));
  return {
    typical,
    cover: cover.map((c) => ({
      ...c,
      typical: round2(typical[c.month] || 0),
    })),
    seasonalDemand: round2(seasonalDemand),
    bufferPercent,
    horizonMonths,
    asOf,
    neededReserve,
    toPurchase,
    minReserveIgnored: Number(item.minReserve) || 0,
  };
}

export function withSeasonalPlan(items, monthsMeta, options = {}) {
  return (items || []).map((item) => {
    const plan = seasonalPlan(item, monthsMeta, options);
    return {
      ...item,
      neededReserve: plan.neededReserve,
      toPurchase: plan.toPurchase,
      seasonalDemand: plan.seasonalDemand,
      cover: plan.cover,
      bufferPercent: plan.bufferPercent,
      horizonMonths: plan.horizonMonths,
      asOf: plan.asOf,
    };
  });
}

export function toCsv(items, months) {
  const monthHeaders = (months || []).map((m) => m.label);
  const headers = [
    "Склад",
    "Группа",
    "Артикул",
    "Номенклатура",
    "Ед.",
    "Начальный остаток",
    "Приход",
    "Расход",
    "Конечный остаток",
    "Сезонный резерв",
    "К закупке",
    ...monthHeaders,
  ];
  const lines = [headers.join(";")];
  for (const item of items) {
    const row = [
      item.warehouse,
      item.group,
      item.sku,
      item.name,
      item.unit,
      item.opening,
      item.incoming,
      item.outgoing,
      item.closing,
      item.neededReserve,
      item.toPurchase,
      ...(item.months || []),
    ].map(csvCell);
    lines.push(row.join(";"));
  }
  return "\uFEFF" + lines.join("\n");
}

function csvCell(value) {
  const s = String(value ?? "");
  if (/[;"\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

export function fmt(n) {
  const v = Number(n);
  if (!Number.isFinite(v)) return "—";
  return v.toLocaleString("ru-RU", {
    minimumFractionDigits: v % 1 === 0 ? 0 : 2,
    maximumFractionDigits: 2,
  });
}

export function coverLabel(cover) {
  if (!cover?.length) return "—";
  return cover.map((c) => c.label).join(", ");
}
