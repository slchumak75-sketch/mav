/** Pure inventory helpers. No DOM. Used by the UI and by vitest. */

export function round2(n) {
  return Math.round((Number(n) + Number.EPSILON) * 100) / 100;
}

export function expectedClosing(item) {
  return round2(item.opening + item.incoming - item.outgoing);
}

export function isBelowMin(item) {
  return Number(item.closing) < Number(item.minReserve);
}

export function isZeroStock(item) {
  return Number(item.closing) === 0;
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
 * @param {{ query?: string, warehouse?: string, group?: string, stock?: 'all'|'below'|'zero'|'ok' }} filters
 */
export function filterItems(items, filters = {}) {
  const stock = filters.stock || "all";
  return items.filter((item) => {
    if (!matchesQuery(item, filters.query)) return false;
    if (filters.warehouse && item.warehouse !== filters.warehouse) return false;
    if (filters.group && item.group !== filters.group) return false;
    if (stock === "below" && !isBelowMin(item)) return false;
    if (stock === "zero" && !isZeroStock(item)) return false;
    if (stock === "ok" && (isBelowMin(item) || isZeroStock(item))) return false;
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
    belowMin: 0,
    zeroStock: 0,
    monthTotal: 0,
  };
  for (const item of items) {
    acc.opening += Number(item.opening) || 0;
    acc.incoming += Number(item.incoming) || 0;
    acc.outgoing += Number(item.outgoing) || 0;
    acc.closing += Number(item.closing) || 0;
    acc.monthTotal += monthTotal(item);
    if (isBelowMin(item)) acc.belowMin += 1;
    if (isZeroStock(item)) acc.zeroStock += 1;
  }
  acc.opening = round2(acc.opening);
  acc.incoming = round2(acc.incoming);
  acc.outgoing = round2(acc.outgoing);
  acc.closing = round2(acc.closing);
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
    "Мин. резерв",
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
      item.minReserve,
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
