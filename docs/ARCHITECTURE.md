# Архитектура

## Поток данных

```
Ведомость с периодом ОК (1).xlsx  (1850 строк, A1:AV1857, L–AV = 37 мес)
Ведомость мав.xlsx                (111 строк,  A1:W119,   K–W  = 13 мес) — архив
        │ оба — OOXML ZIP без VBA/формул, найдёт tools/extract_xlsx.py (приоритет нового)
        ▼
tools/extract_xlsx.py  [--fill-purchase]
        │
        ├── source/xlsx/                 распакованный OOXML (MANIFEST.txt + SHA-256)
        ├── data/vedomost.json           канон (и meta.months 37 шт для нового файла)
        └── web/public/data/vedomost.json статика для UI
                │
                ▼
         web/src/app.js  ← fetch('./data/vedomost.json') + withSeasonalPlan()
                │
                ▼
            web/dist                     vite build (base: "./")
```

Парсер не использует openpyxl: только stdlib (`zipfile`, `xml.etree`). Авто-детект формата по заголовку `F7` («Начальный остаток» = old, «Расход» = new) и по числу месячных колонок.

## Сезонная закупка и столбец 8

- `tools/extract_xlsx.py --fill-purchase` считает для каждой позиции `toPurchase` по сезонной логике (`docs/SEASONAL.md`) и записывает в **столбец H (8-й)** — заголовок `H7 = "К закупке"` (sharedStrings) и числа `H8:H1857`.
- JSON не хранит расчётные поля; фронт считает их заново (`web/src/calc.js`), но Excel-столбец H теперь согласован с фронтом (тест `test_purchase_column_filled`).

## Frontend

- Vite 5, vanilla JS, без фреймворка.
- Чистая логика в `web/src/calc.js` (`seasonalPlan`, `typicalByCalendarMonth`, `withSeasonalPlan`, `filterItems`, `totals`, `toCsv`) — тестируется vitest.
- UI в `web/src/app.js`: фильтры/сортировка в `localStorage` (`mav-vedomost-settings-v2`), горизонт/буфер, показывать месяцы, компактная таблица.
- `base: "./"` — относительные пути, чтобы сайт жил на GitHub Pages и в превью.
- Поддержка обеих схем: старые записи имеют `opening/incoming/minReserve`, новые — `lastPrice/retailPrice/supplier`. Отсутствующие поля показываются как «—» или 0.

Сервер разработки слушает `0.0.0.0:5173` (`allowedHosts: true`). Превью: `0.0.0.0:4173`.

## Тесты

| Набор | Где | Что проверяет |
| --- | --- | --- |
| unittest | `tests/test_extract.py` | детект формата, 1850 vs 111 строк, баланс (old), месяцы 37/13, JSON = extract, нет VBA, H-столбец заполнен (new), цены/поставщик (new) |
| vitest | `web/src/calc.test.js` | фильтры, итоги, CSV, сезонный резерв / к закупке, typical averaging 2 октября |

CI падает, если JSON в git разъехался с xlsx (`--verify`).

## Модель записи (новый формат)

```json
{
  "id": 1,
  "row": 8,
  "warehouse": "Склад Кореличи",
  "group": "2 краски растворители",
  "sku": "",
  "name": "Аммиак водный 0,5л Адмирал",
  "unit": "шт",
  "opening": 0,
  "incoming": 0,
  "outgoing": 8,
  "closing": 3,
  "minReserve": 0,
  "lastPrice": 2.37,
  "retailPrice": 3.55,
  "supplier": "ООО \"БелАдмиралСтрой\"",
  "months": [0, 0, 0, ... 37 шт],
  "monthTotal": 8,
  "belowMin": false,
  "balanceOk": true
}
```

`belowMin` = `closing < minReserve` (для new всегда false, UI не использует).  
`balanceOk` = `opening+incoming-outgoing==closing` для old, для new всегда true.  
Расчётные поля (не в JSON, считает `web/src/calc.js` и `extract_xlsx.py --fill-purchase`):

- `neededReserve` = ceil(сезонный спрос горизонта × (1+буфер))
- `toPurchase` = max(0, neededReserve − closing) — пишется в H

См. `docs/SEASONAL.md`.

## Модель записи (старый формат, архив)

```json
{
  "opening": 1, "incoming": 20, "outgoing": 17, "closing": 4, "minReserve": 3,
  "months": [1,0,0,0,0,1,1,3,1,4,5,0,2]
}
```

Хранится для совместимости.
