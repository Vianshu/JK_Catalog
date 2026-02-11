# JK Catalog — Build & Release Checklist

## Pre-Build Checks

- [ ] All `print()` statements reviewed — debug prints removed or converted to `logger.debug()`
- [ ] `config/cleaning_rules.json` is up to date with any new product name rules
- [ ] `config/catalog_config.json` has correct `header_text` for the target company
- [ ] `data/super_master.db` is the latest version
- [ ] `data/calendar_data.db` has current year's date mappings
- [ ] No `import pdb` or `breakpoint()` calls left in code
- [ ] `error.log` strategy is working (test by raising an intentional error)

## Build

```powershell
# From project root:
pyinstaller JK_Catalog.spec
```

The output EXE is at: `dist/JK_Catalog.exe`

## Bundled Files (inside EXE)

| File | Purpose | Access Function |
|------|---------|-----------------|
| `src/assets/style.qss` | UI stylesheet | `get_asset_path("style.qss")` |
| `data/super_master.db` | Product group mapping | `get_data_file_path("super_master.db")` |
| `data/calendar_data.db` | AD→BS date conversion | `get_data_file_path("calendar_data.db")` |
| `config/cleaning_rules.json` | Regex cleaning rules | Loaded by `text_utils.py` |
| `config/catalog_config.json` | Header text config | Loaded by `a4_renderer.py` |

> ⚠️ **These files are READ-ONLY at runtime** (extracted to `sys._MEIPASS` temp folder).

## Runtime Files (next to EXE)

| File | Purpose | Notes |
|------|---------|-------|
| `data/error.log` | Crash logs | Created by `main.py` global exception handler |
| `Companies/*/` | Company data folders | User-created, writable |
| `company_vault.json` | Company registry | User-created, writable |

## Post-Build Testing

- [ ] EXE launches without errors
- [ ] Company login works (path resolution correct)
- [ ] Catalog build completes (test with a small company)
- [ ] PDF export generates correctly
- [ ] `error.log` is created in `data/` folder next to EXE
- [ ] Intentional crash is logged to `error.log`
- [ ] Config files are loaded (header text matches, cleaning rules work)

## Common Issues

| Problem | Cause | Fix |
|---------|-------|-----|
| EXE crashes silently | Missing data file in spec | Add to `datas=[]` in `.spec` |
| "Module not found" | Hidden import | Add to `hiddenimports=[]` |
| Style not applied | `style.qss` not bundled | Check `datas` path |
| Crash with no log | `error.log` path issue | Check `get_writable_data_path()` |
| Huge EXE size | Unnecessary dependencies| Add to `excludes=[]` |
