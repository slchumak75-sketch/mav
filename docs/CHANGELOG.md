# Changelog

Формат: что сделано, зачем, что трогать следующему агенту.

## 2026-10-19 — первичная сборка ведомости

Ветка: `arena/feb459b3-mav`.

### Обнаружено

- В репозитории не было кода, только `Ведомость мав.xlsx` и заглушка README.
- xlsx = OOXML ZIP без макросов и формул.

### Добавлено

- `tools/extract_xlsx.py` — распаковка и JSON.
- `data/vedomost.json` + копия в `web/public/data/`.
- `source/xlsx/` — распакованный workbook.
- `web/` — Vite-приложение ведомости.
- `tests/test_extract.py`, `web/src/calc.test.js`.
- `.github/workflows/ci.yml` — автосборка на push/PR + GitHub Pages.
- `AGENT.md`, `README.md`, `docs/*`.

### Как воспроизвести

```
python3 tools/extract_xlsx.py
python3 -m unittest discover -s tests -v
cd web && npm ci && npm test && npm run build
```

### CI 2026-10-19

Первый push: job «Test and build» зелёный, «Deploy GitHub Pages» красный
(`Resource not accessible` / Pages не включён). Deploy переведён на
`continue-on-error: true`, чтобы автосборка не блокировалась.

## 2026-10-19 — сезонный резерв вместо мин. резерва

- UI больше не показывает и не использует столбец «Минимальный резерв».
- Добавлены колонки **Сезонный резерв** и **К закупке**.
- Формула: типичные продажи календарного месяца по K–W, сумма на горизонт
  (по умолчанию ноя–дек 2026), +10% буфер, ceil; закупка = резерв − остаток.
- Отбор «К закупке», KPI, CSV, настройки горизонта/буфера.
- Документ: `docs/SEASONAL.md`. Тесты в `web/src/calc.test.js`.

### Следующие шаги (не сделано)

- UI-загрузка нового xlsx.
- Закупка «в зиму под весну», если пользователь так решит.
- Несколько складов, когда появятся в выгрузке.
