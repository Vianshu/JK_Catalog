# Table Standardization & Feature Specification

This document serves as the single source of truth for the behaviour of all tables across the application. It outlines the **Universal Features** that every table must inherit and support, as well as the **Special Features** designed for specific sheets like the Godown List and Cheque List.

---

## 1. Universal Table Features
*These features apply to all tables inheriting from `ExcelTableMixin` and using `UniversalCellDelegate`.*

### Keyboard Navigation & Editing (Excel-style)
* **Mode 1 (Overwrite):** Typing directly on a highlighted cell immediately overwrites the existing content.
* **Mode 2 (Edit - `F2`):** Pressing `F2` enters the cell without overwriting. 
  * **Cursor Placement:** The cursor lands at the very **end** of the text. 
  * **No Selection:** The text is explicitly **not** highlighted/selected to prevent accidental deletion when typing. This applies consistently across *all* tables (`supp_payment`, `cheque_list`, `godown_list`, etc.).
* **Arrow Keys:** Seamlessly navigate up, down, left, and right across the grid.
* **Default Enter Key:** By default, pressing Enter commits the cell and moves the cursor **down** to the next row (unless overridden by a special table rule).

### Smart Autocomplete (Dropdowns)
* **Fuzzy Discoverability:** The dropdown handles missing spaces and minor typos gracefully. (e.g. typing `pcvboketganga` will still populate the dropdown with `pvc bocket ganga`).
* **Strict Validation on Commit:** When the user hits Enter to manually commit a typed string, it is stripped of all spaces and punctuation. It must perfectly match a valid option (ignoring spaces/punctuation). If it is not a perfect match, the typed text is rejected, and the user is forced to pick from the dropdown. 
* **Single-Action Commit:** Selecting a value from the autocomplete dropdown via Enter or Tab instantly commits the value and moves the cursor forward in one keystroke (no "double-enter" required).

### Visuals and Data
* **Clean Editing UI:** When a cell is being edited, it features a solid white background with 0px padding, preventing the visual "inset" or "jumping" glitch commonly seen in Qt tables.
* **Date Validation:** Cells configured as dates enforce the strict `YYYY-MM-DD` format.

---

## 2. Special Table Features
*These features are explicitly configured for specific views to streamline specialized workflows.*

### Godown List (`godown_list.py`)
* **Custom Enter Navigation:**
  * Pressing Enter in **Column 2** (`प्रति कार्टुन`) jumps directly to **Column 4** (`जम्मा कार्टुन`) on the same row.
  * Pressing Enter in **Column 4** jumps directly to **Column 5** (`गोदाम`) on the same row.
* **Part No Translation:** Specific products (e.g., "super stick 100gm") are automatically translated and overridden with explicit Part Numbers (e.g., "col-1") behind the scenes.

### Cheque List (`cheque_list.py`)
* **Dynamic Column Auto-Fitting:** Columns dynamically resize themselves to perfectly fit their text contents. To prevent text from being cut off, this resizing triggers:
  * During the initial startup data load.
  * Every time the user switches back to the Cheque List tab.
  * Every time the user changes the filter (All / Cleared / Uncleared) or uses the text search.
* **GUID Identity Mapping:** Party Names and Banks are stored as hidden GUIDs. The cell visually displays the full name, ensuring stability even if the user aliases or renames a ledger in the system.
* **Initial Cleared Hide:** Uncleared cheques are shown by default; cleared cheques are initially hidden to reduce clutter.

### Supplier Payment (`supp_payment.py`)
* **Theming Rules:** Primary buttons and bottom tab navigation strictly adhere to a **Green** color scheme (e.g., `#059669`, `#047857`) to differentiate payment screens from the rest of the application.
* **Dynamic Sections:** Renders distinct visual sections for each supplier, displaying personal and company accounts dynamically.
