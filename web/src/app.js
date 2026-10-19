import {
  filterItems,
  fmt,
  isBelowMin,
  isZeroStock,
  monthlySeries,
  sortItems,
  toCsv,
  totals,
  uniqueSorted,
} from "./calc.js";

const SETTINGS_KEY = "mav-vedomost-settings-v1";

const DEFAULT_SETTINGS = {
  query: "",
  warehouse: "",
  group: "",
  stock: "all",
  sortKey: "name",
  sortDir: "asc",
  showMonths: true,
  dense: false,
};

function loadSettings() {
  try {
    const raw = localStorage.getItem(SETTINGS_KEY);
    if (!raw) return { ...DEFAULT_SETTINGS };
    return { ...DEFAULT_SETTINGS, ...JSON.parse(raw) };
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

function saveSettings(settings) {
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
}

function statusOf(item) {
  if (isZeroStock(item)) return "zero";
  if (isBelowMin(item)) return "low";
  return "ok";
}

function statusLabel(status) {
  if (status === "zero") return "нет";
  if (status === "low") return "ниже мин.";
  return "норма";
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

async function loadData() {
  const res = await fetch("./data/vedomost.json", { cache: "no-store" });
  if (!res.ok) {
    throw new Error(`HTTP ${res.status} loading ./data/vedomost.json`);
  }
  return res.json();
}

function download(filename, text, type) {
  const blob = new Blob([text], { type });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

export async function mount(root) {
  const data = await loadData();
  const state = {
    data,
    settings: loadSettings(),
    settingsOpen: false,
    selectedId: null,
    refreshedAt: new Date(),
  };

  function visibleItems() {
    const filtered = filterItems(data.items, state.settings);
    return sortItems(filtered, state.settings.sortKey, state.settings.sortDir);
  }

  function setSetting(patch) {
    state.settings = { ...state.settings, ...patch };
    saveSettings(state.settings);
    render();
  }

  function refresh() {
    state.refreshedAt = new Date();
    render();
  }

  root.addEventListener("click", (ev) => {
    if (ev.target.matches("[data-overlay]")) {
      state.settingsOpen = false;
      render();
      return;
    }
    const btn = ev.target.closest("[data-action]");
    if (!btn) return;
    const action = btn.dataset.action;
    if (action === "refresh") refresh();
    if (action === "settings") {
      state.settingsOpen = !state.settingsOpen;
      render();
    }
    if (action === "close-settings") {
      state.settingsOpen = false;
      render();
    }
    if (action === "export") {
      const items = visibleItems();
      download(
        "vedomost-mav.csv",
        toCsv(items, data.meta.months),
        "text/csv;charset=utf-8",
      );
    }
    if (action === "print") window.print();
    if (action === "sort") {
      const key = btn.dataset.key;
      const dir =
        state.settings.sortKey === key && state.settings.sortDir === "asc"
          ? "desc"
          : "asc";
      setSetting({ sortKey: key, sortDir: dir });
    }
    if (action === "select") {
      const id = Number(btn.dataset.id);
      state.selectedId = state.selectedId === id ? null : id;
      render();
    }
  });

  root.addEventListener("input", (ev) => {
    const el = ev.target;
    if (el.name === "query") setSetting({ query: el.value });
  });

  root.addEventListener("change", (ev) => {
    const el = ev.target;
    if (el.name === "warehouse") setSetting({ warehouse: el.value });
    if (el.name === "group") setSetting({ group: el.value });
    if (el.name === "stock") setSetting({ stock: el.value });
    if (el.name === "showMonths") setSetting({ showMonths: el.checked });
    if (el.name === "dense") setSetting({ dense: el.checked });
  });

  root.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && state.settingsOpen) {
      state.settingsOpen = false;
      render();
    }
  });

  function render() {
    const active = document.activeElement;
    const restore =
      active && root.contains(active) && active.name
        ? {
            name: active.name,
            start: active.selectionStart,
            end: active.selectionEnd,
          }
        : null;

    const items = visibleItems();
    const t = totals(items);
    const series = monthlySeries(items, data.meta.months);
    const maxMonth = Math.max(1, ...series.map((s) => s.value));
    const warehouses = uniqueSorted(data.items, "warehouse");
    const groups = uniqueSorted(data.items, "group");
    const selected = data.items.find((i) => i.id === state.selectedId);
    const s = state.settings;
    const showMonths = s.showMonths;

    root.innerHTML = `
      <div class="sheet ${s.dense ? "is-dense" : ""}">
        <header class="mast">
          <div class="mast__mark">
            <span class="mast__sigil">МАВ</span>
            <div>
              <p class="mast__kicker">Складской учёт</p>
              <h1>${escapeHtml(data.meta.title)}</h1>
            </div>
          </div>
          <div class="mast__meta">
            <p class="period">${escapeHtml(data.meta.periodLabel)}</p>
            <p class="scope">${escapeHtml(data.meta.scope)}</p>
          </div>
          <div class="mast__actions">
            <button type="button" class="btn" data-action="refresh">Обновить</button>
            <button type="button" class="btn" data-action="settings">Настройка</button>
            <button type="button" class="btn btn--ghost" data-action="export">CSV</button>
            <button type="button" class="btn btn--ghost" data-action="print">Печать</button>
          </div>
        </header>

        <section class="kpis" aria-label="Итоги">
          ${kpi("Позиций", t.items, `${data.meta.itemCount} в источнике`)}
          ${kpi("Конечный остаток", fmt(t.closing), `начало ${fmt(t.opening)}`)}
          ${kpi("Приход", fmt(t.incoming), `расход ${fmt(t.outgoing)}`)}
          ${kpi("Ниже резерва", t.belowMin, t.belowMin ? "требует закупки" : "резерв закрыт", t.belowMin ? "warn" : "ok")}
          ${kpi("Нулевой остаток", t.zeroStock, "нет на складе", t.zeroStock ? "muted" : "ok")}
        </section>

        <section class="toolbar">
          <label class="search">
            <span>Поиск</span>
            <input type="search" name="query" placeholder="Номенклатура, артикул…" value="${escapeHtml(s.query)}" />
          </label>
          <label>
            <span>Склад</span>
            <select name="warehouse">
              <option value="">Все склады</option>
              ${warehouses.map((w) => `<option value="${escapeHtml(w)}" ${w === s.warehouse ? "selected" : ""}>${escapeHtml(w)}</option>`).join("")}
            </select>
          </label>
          <label>
            <span>Группа</span>
            <select name="group">
              <option value="">Все группы</option>
              ${groups.map((g) => `<option value="${escapeHtml(g)}" ${g === s.group ? "selected" : ""}>${escapeHtml(g)}</option>`).join("")}
            </select>
          </label>
          <label>
            <span>Остаток</span>
            <select name="stock">
              <option value="all" ${s.stock === "all" ? "selected" : ""}>Все</option>
              <option value="below" ${s.stock === "below" ? "selected" : ""}>Ниже минимума</option>
              <option value="zero" ${s.stock === "zero" ? "selected" : ""}>Нулевые</option>
              <option value="ok" ${s.stock === "ok" ? "selected" : ""}>В норме</option>
            </select>
          </label>
          <p class="shown">показано ${items.length} из ${data.items.length}</p>
        </section>

        <section class="chart" aria-label="Расход по месяцам">
          <h2>Помесячное движение (колонки источника K–W)</h2>
          <ol>
            ${series
              .map(
                (m) => `
              <li>
                <span class="chart__bar" style="height:${Math.round((m.value / maxMonth) * 100)}%"></span>
                <span class="chart__val">${fmt(m.value)}</span>
                <span class="chart__lbl">${escapeHtml(shortMonth(m.label))}</span>
              </li>`,
              )
              .join("")}
          </ol>
        </section>

        <div class="table-wrap">
          <table class="grid">
            <thead>
              <tr>
                ${th("name", "Номенклатура", s)}
                ${th("sku", "Артикул", s)}
                ${th("unit", "Ед.", s)}
                ${th("opening", "Нач.", s)}
                ${th("incoming", "Приход", s)}
                ${th("outgoing", "Расход", s)}
                ${th("closing", "Кон.", s)}
                ${th("minReserve", "Мин.", s)}
                <th>Статус</th>
                ${
                  showMonths
                    ? data.meta.months
                        .map((m, idx) => `<th title="${escapeHtml(m.label)}">${escapeHtml(shortMonth(m.label))}</th>`)
                        .join("")
                    : ""
                }
              </tr>
            </thead>
            <tbody>
              ${
                items.length
                  ? items.map((item) => rowHtml(item, data.meta.months, showMonths, state.selectedId)).join("")
                  : `<tr><td colspan="${showMonths ? 9 + data.meta.months.length : 9}" class="empty">Ничего не найдено</td></tr>`
              }
            </tbody>
            <tfoot>
              <tr>
                <td>Итого (${t.items})</td>
                <td></td>
                <td></td>
                <td>${fmt(t.opening)}</td>
                <td>${fmt(t.incoming)}</td>
                <td>${fmt(t.outgoing)}</td>
                <td>${fmt(t.closing)}</td>
                <td></td>
                <td></td>
                ${showMonths ? series.map((m) => `<td>${fmt(m.value)}</td>`).join("") : ""}
              </tr>
            </tfoot>
          </table>
        </div>

        ${selected ? detailHtml(selected, data.meta.months) : ""}

        <footer class="colophon">
          <p>Источник: ${escapeHtml(data.meta.sourceFile)} · лист ${escapeHtml(data.meta.sheet)} · SHA-256 ${escapeHtml(data.meta.sourceSha256.slice(0, 12))}…</p>
          <p>Обновлено в интерфейсе: ${state.refreshedAt.toLocaleString("ru-RU")} · VBA: ${data.meta.hasVba ? "да" : "нет"} · формулы: ${data.meta.hasFormulas ? "да" : "нет"}</p>
        </footer>
      </div>

      ${state.settingsOpen ? settingsHtml(s) : ""}
    `;

    if (restore?.name) {
      const el = root.querySelector(`[name="${restore.name}"]`);
      if (el) {
        el.focus();
        if (typeof restore.start === "number") {
          try {
            el.setSelectionRange(restore.start, restore.end);
          } catch {
            /* not a text field */
          }
        }
      }
    }
  }

  render();
  return { refresh, getState: () => state };
}

function shortMonth(label) {
  const map = {
    Октябрь: "окт",
    Ноябрь: "ноя",
    Декабрь: "дек",
    Январь: "янв",
    Февраль: "фев",
    Март: "мар",
    Апрель: "апр",
    Май: "май",
    Июнь: "июн",
    Июль: "июл",
    Август: "авг",
    Сентябрь: "сен",
  };
  const year = label.match(/\d{4}/)?.[0]?.slice(2) ?? "";
  for (const [full, short] of Object.entries(map)) {
    if (label.startsWith(full)) return `${short}’${year}`;
  }
  return label;
}

function kpi(label, value, hint, tone = "") {
  return `<article class="kpi ${tone ? `kpi--${tone}` : ""}">
    <p class="kpi__label">${escapeHtml(label)}</p>
    <p class="kpi__value">${escapeHtml(value)}</p>
    <p class="kpi__hint">${escapeHtml(hint)}</p>
  </article>`;
}

function th(key, label, settings) {
  const active = settings.sortKey === key;
  const arrow = active ? (settings.sortDir === "asc" ? "↑" : "↓") : "";
  return `<th><button type="button" data-action="sort" data-key="${key}" class="${active ? "is-active" : ""}">${escapeHtml(label)} ${arrow}</button></th>`;
}

function rowHtml(item, months, showMonths, selectedId) {
  const status = statusOf(item);
  return `<tr class="row row--${status} ${item.id === selectedId ? "is-selected" : ""}" data-action="select" data-id="${item.id}">
    <td class="name">
      <strong>${escapeHtml(item.name)}</strong>
      <small>${escapeHtml(item.warehouse)} · ${escapeHtml(item.group)}</small>
    </td>
    <td class="mono">${escapeHtml(item.sku || "—")}</td>
    <td>${escapeHtml(item.unit)}</td>
    <td class="num">${fmt(item.opening)}</td>
    <td class="num">${fmt(item.incoming)}</td>
    <td class="num">${fmt(item.outgoing)}</td>
    <td class="num num--close">${fmt(item.closing)}</td>
    <td class="num">${fmt(item.minReserve)}</td>
    <td><span class="tag tag--${status}">${statusLabel(status)}</span></td>
    ${
      showMonths
        ? (item.months || [])
            .map((n, i) => `<td class="num ${n ? "" : "is-zero"}" title="${escapeHtml(months[i]?.label || "")}">${n ? fmt(n) : "·"}</td>`)
            .join("")
        : ""
    }
  </tr>`;
}

function detailHtml(item, months) {
  const status = statusOf(item);
  return `<aside class="detail">
    <h2>${escapeHtml(item.name)}</h2>
    <dl>
      <div><dt>Склад</dt><dd>${escapeHtml(item.warehouse)}</dd></div>
      <div><dt>Группа</dt><dd>${escapeHtml(item.group)}</dd></div>
      <div><dt>Артикул</dt><dd>${escapeHtml(item.sku || "—")}</dd></div>
      <div><dt>Ед.</dt><dd>${escapeHtml(item.unit)}</dd></div>
      <div><dt>Начальный</dt><dd>${fmt(item.opening)}</dd></div>
      <div><dt>Приход</dt><dd>${fmt(item.incoming)}</dd></div>
      <div><dt>Расход</dt><dd>${fmt(item.outgoing)}</dd></div>
      <div><dt>Конечный</dt><dd>${fmt(item.closing)}</dd></div>
      <div><dt>Мин. резерв</dt><dd>${fmt(item.minReserve)}</dd></div>
      <div><dt>Статус</dt><dd>${statusLabel(status)}</dd></div>
      <div><dt>Баланс</dt><dd>${item.balanceOk ? "сходится" : "ошибка"}</dd></div>
    </dl>
    <p class="detail__note">Помесячные значения — как в исходном xlsx, сумма месяцев не обязана равняться расходу.</p>
    <ul class="detail__months">
      ${months
        .map(
          (m, i) =>
            `<li><span>${escapeHtml(m.label)}</span><strong>${fmt(item.months[i] || 0)}</strong></li>`,
        )
        .join("")}
    </ul>
  </aside>`;
}

function settingsHtml(s) {
  return `<div class="overlay" data-overlay>
    <form class="panel">
      <header>
        <h2>Настройка</h2>
        <button type="button" class="btn btn--ghost" data-action="close-settings">Закрыть</button>
      </header>
      <label class="check">
        <input type="checkbox" name="showMonths" ${s.showMonths ? "checked" : ""} />
        Показывать помесячные колонки
      </label>
      <label class="check">
        <input type="checkbox" name="dense" ${s.dense ? "checked" : ""} />
        Компактная таблица
      </label>
      <p>Фильтры и сортировка пишутся в localStorage браузера (${SETTINGS_KEY}).</p>
    </form>
  </div>`;
}
