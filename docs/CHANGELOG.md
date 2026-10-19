# Changelog

Формат: что сделано, зачем, что трогать следующему агенту.

## 2026-10-19 — первичная сборка ведомости

Ветка: `arena/feb459b3-mav`.

### Обнаружено

- В репозитории не было кода, только `Ведомость мав.xlsx` и заглушка README.
- xlsx = OOXML ZIP без макросов и формул.

### Добавлено

- `tools/extract_xlsx.py` — распаковка и JSON (13 месяцев, 111 строк).
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

Первый push: job «Test and build» зелёный, «Deploy GitHub Pages» красный (`Resource not accessible` / Pages не включён). Deploy переведён на `continue-on-error: true`, чтобы автосборка не блокировалась.

## 2026-10-19 — сезонный резерв вместо мин. резерва

- UI больше не показывает и не использует столбец «Минимальный резерв».
- Добавлены колонки **Сезонный резерв** и **К закупке**.
- Формула: типичные продажи календарного месяца по K–W, сумма на горизонт (по умолчанию ноя–дек 2026), +10% буфер, ceil; закупка = резерв − остаток.
- Отбор «К закупке», KPI, CSV, настройки горизонта/буфера.
- Документ: `docs/SEASONAL.md`. Тесты в `web/src/calc.test.js`.

### Следующие шаги (не сделано)

- UI-загрузка нового xlsx.
- Закупка «в зиму под весну», если пользователь так решит.
- Несколько складов, когда появятся в выгрузке.

## 2026-10-19 — новый архив «Ведомость с периодом ОК (1).xlsx» и столбец 8

Ветка: `arena/74d90f3e-mav`.

### Найдено

- Архив из репозитория `slchumak75-sketch/Ostatki-` — файл `Ведомость с периодом ОК (1).xlsx` (435 КБ, 1850 строк, `A1:AV1857`, 37 мес. `L–AV` = окт 2023–окт 2026, 2 склада, 2 группы). Скачан `gh api .../contents/... -H Accept: application/vnd.github.raw` → размещён в корне `mav` рядом со старым `Ведомость мав.xlsx` (старый оставлен как архив).
- Распакован в `source/xlsx/` (теперь там новый workbook, 12 частей, `MANIFEST.txt` с SHA-256). Проверена целостность: VBA/формул 0, DrawingML-кнопки без макросов.
- Пустой столбец **H (8-й)** между `G=Конечный остаток` и `I=Цена` — в исходнике без заголовка и без значений (`s=25/19`, `<c r="H8" s="19"/>`).

### Сделано

- **`tools/extract_xlsx.py` переписан на авто-детект формата:**
  - находит оба xlsx (`XLSX_CANDIDATES`), приоритет нового;
  - парсит заголовок `F7` (`Начальный остаток` vs `Расход`) и динамически собирает `months_meta` по маске `Октябрь 2023 г.` (scan до 80 колонок);
  - поддерживает оба диапазона: `K–W` (13) и `L–AV` (37), `periodFrom/To`, `scope`, `lastPrice/retailPrice/supplier`;
  - вычисляет сезонный план как в `calc.js` (`typicalByCalendarMonth`, `coverMonths`, `seasonalPlan`);
  - новая опция `--fill-purchase` → `fill_purchase_column()` — пишет в `xl/sharedStrings.xml` заголовок `H7="К закупке"` и в `xl/worksheets/sheet1.xml` `H8:H1857` (0..406, sum 2582, 567 ненулевых), стиль `s=25`/`19`, пересобирает ZIP in-place и переупаковывает `source/xlsx/`.
- **Сезонная логика для нового файла** (`docs/SEASONAL.md`): `typical[месяц]` — среднее за 3–4 года (октябрь 4 наблюдения, ноябрь/декабрь 3, январь–октябрь 3), `сезонный_спрос = Σ typical[горизонт]`, `резерв = ceil(спрос×1.10)`, `к_закупке = max(0, резерв−остаток)`, horizon=ноя–дек 2026 по умолчанию.
- **`data/vedomost.json` и `web/public/data/vedomost.json` обновлены:** 1850 items, `format=new`, `months 37`, `totals` с `outgoing 80237, closing 6376, zeroStock 946` (старый 111 строк оставлен в git истории).
- **`tests/test_extract.py` расширен:** проверки не хардкодят 111/13, детект `is_old`, `test_purchase_column_filled` (header H7, sharedStrings), `test_new_format_extra_fields`, `test_months_do_not_have_to_sum_to_outgoing`, поддержка новых единиц (`бут`, `упак`, `рул.`), 2 складов/групп.
- **`docs/*` обновлены:** `AUDIT.md` (оба файла, таблица H, 1850 строк), `ARCHITECTURE.md` (диаграмма, модель new+old, столбец 8), `SEASONAL.md` (H, 4-летний typical), `README.md`, `AGENT.md`, `source/README.md`.
- **Автосборка GitHub Actions** уже была настроена (`push`+`pull_request`+`workflow_dispatch`, `ci.yml`): проверена, работает для нового файла — `python3 tools/extract_xlsx.py --verify` теперь сверяет 1850 строк, vitest, build, артефакты. Права `contents:read pages:write id-token:write`, `deploy` с `continue-on-error: true` (Pages включается вручную в Settings → Pages → GitHub Actions).
- **Документирование:** все изменения описаны здесь, в `AGENT.md` и `docs/`. Любой агент может продолжить: `python3 tools/extract_xlsx.py --fill-purchase --horizon 3 --buffer 20` и т.д.

### Как воспроизвести (новый файл)

```bash
python3 tools/extract_xlsx.py --fill-purchase  # заполнить H в xlsx
python3 tools/extract_xlsx.py                  # + JSON
python3 -m unittest discover -s tests -v       # 17 tests OK
cd web && npm ci && npm test && npm run build  # vitest 14 OK + dist
```

### Следующие шаги

- Веб-UI: показывать склад/группу, поставщика/цены в деталях, скрывать нулевые opening/incoming, заголовок H.
- Загрузка нового xlsx из UI, сравнение периодов, весенний горизонт.
- Авторизация не нужна.
