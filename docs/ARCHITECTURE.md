# Архитектура

## Поток данных

```
Ведомость мав.xlsx
        │
        ▼
tools/extract_xlsx.py
        │
        ├── source/xlsx/                 распакованный OOXML
        ├── data/vedomost.json           канон
        └── web/public/data/vedomost.json статика для UI
                │
                ▼
         web/src/app.js  ← fetch('./data/vedomost.json')
                │
                ▼
            web/dist                     vite build
```

Парсер не использует openpyxl: только stdlib (`zipfile`, `xml.etree`).

## Frontend

- Vite 5, vanilla JS, без фреймворка.
- Чистая логика в `web/src/calc.js` (тестируется vitest).
- UI в `web/src/app.js`: фильтры/сортировка в `localStorage`.
- `base: "./"` — относительные пути, чтобы сайт жил на GitHub Pages и в превью.

Сервер разработки слушает `0.0.0.0:5173` (`allowedHosts: true`).

## Тесты

| Набор | Где | Что проверяет |
| --- | --- | --- |
| unittest | `tests/test_extract.py` | 111 строк, баланс, JSON = extract, нет VBA |
| vitest | `web/src/calc.test.js` | фильтры, итоги, CSV, сезонный резерв / к закупке |

CI падает, если JSON в git разъехался с xlsx (`--verify`).

## Модель записи

```json
{
  "id": 1,
  "row": 8,
  "warehouse": "Склад Кореличи",
  "group": "2 краски растворители",
  "sku": "",
  "name": "…",
  "unit": "шт",
  "opening": 1,
  "incoming": 20,
  "outgoing": 17,
  "closing": 4,
  "minReserve": 3,
  "months": [1, 0, 0, 0, 0, 1, 1, 3, 1, 4, 5, 0, 2],
  "monthTotal": 18,
  "belowMin": false,
  "balanceOk": true
}
```

`belowMin` в JSON = `closing < minReserve` (факт источника, UI его не использует).
`balanceOk` = `opening + incoming - outgoing == closing`.

Расчётные поля (не в JSON, считает `web/src/calc.js`):

- `neededReserve` = ceil(сезонный спрос горизонта × 1.10)
- `toPurchase` = max(0, neededReserve − closing)

См. `docs/SEASONAL.md`.
