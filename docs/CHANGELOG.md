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

### Следующие шаги (не сделано)

- UI-загрузка нового xlsx.
- Правка резерва с сохранением.
- Несколько складов, когда появятся в выгрузке.
