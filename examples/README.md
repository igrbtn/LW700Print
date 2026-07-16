# Example CSVs

Import flow: open the web UI, pick the **label type** and put `{column}` placeholders
in the lines / code, upload the CSV, **Предпросмотр всех** (preview the whole run),
then **Печать всех** (mass print).

| CSV | Label type | Template (lines / code) |
|-----|-----------|--------------------------|
| `cable_flags.csv` | Флажок кабеля | line: `{marking}`  (colour column = which tape to load) |
| `servers.csv` | Текст (2 строки) | line1: `{name}`  line2: `{ip}` |
| `servers.csv` | Текст + QR | line1: `{name}`  line2: `{ip}`  code: `{url}` |
| `assets_qr.csv` | Текст + QR | line1: `{name}`  line2: `{location}`  code: `{url}` |
| `devices_multiline.csv` | Текст (3-4 строки) | `{device}` / `{model}` / `{serial}` / `{location}` |
| `patch_panel.csv` | Патч-панель | line: `{dest}`  (ports column feeds cell order) |
| `inventory_barcode.csv` | Штрихкод | code: `{code}`  line: `{name}` |

The columns are just examples - any header name works as `{that_name}` in the template.
Generate your own CSV with an LLM/agent using **CSV для наполнения** in the UI, which
exports the placeholder columns of the current label.
