# Project Scope and Build Rules — JK Multi Catalog

## 1. Project Scope
- **JK Multi only**: All work and development on this codebase should exclusively focus on the "JK Multi" (multi-user) version of the application. Do not modify or focus on single-user versions.
- If a request would require touching single-user code (e.g., a shared utility file used by both versions), pause and confirm with the user before editing it.

## 2. Build Pipeline

### 2.1 PyInstaller (One-Dir)
- Always use the **one-dir** (folder) build approach (`COLLECT`) — never `--onefile`. The multi-user structure requires the folder layout for performance and proper data loading.
- Spec file: `JK_Catalog_Multi.spec` — use for all builds.
- **Pre-build sanity check**: before invoking PyInstaller, run a quick syntax/import check (`python -m py_compile` or equivalent) on changed files. Catching a syntax error here takes seconds; catching it after a full PyInstaller pass wastes minutes.

### 2.2 Inno Setup
- After a **successful** PyInstaller build, build the installer with Inno Setup Compiler using `JK_Catalog_Multi_Setup.iss`.
- Only run this step if the PyInstaller `dist/` output folder was actually populated and the console showed no traceback. Don't compile an installer around a broken or incomplete build.

### 2.3 Automation Guardrails
- **No automated EXE builds**: never run PyInstaller or Inno Setup (ISCC) automatically after completing a task. Wait for the user to explicitly say `check` or `check 1`.
- **No automated git commits**: never run `git commit` automatically. Only commit when explicitly asked, or when triggered by `check 1`.
- **Never run the application**: never run `python main.py`, under any circumstance — not to test a fix, not to "just confirm it launches." No exceptions.

## 3. Issue Reporting Protocol (Client-Side Default)
When a bug or issue is reported without specifying where it occurred, **default to assuming it happened on the client's machine**, not the developer's local machine.
- Do **not** check local logs or the local database to try to confirm or reproduce the issue first.
- Instead, gather evidence from the client side. Ask for whichever of these are relevant:
  - The client's `error.log` (request the file or the relevant excerpt around the timestamp)
  - A targeted query against their SQL Server instance (specify table/query if known)
  - What the client was doing immediately before the issue (steps, screen, action taken)
  - A screenshot, if it's a UI/display issue
  - Approximate time the issue occurred, to correlate with logs
- Only investigate locally if the user explicitly says the issue happened on their own dev machine (e.g., "this broke locally," "on my machine").

## 4. Custom Workflow Commands

### "check 1" — Full Release Build
**Trigger:** the exact phrase `check 1`. No further confirmation needed once triggered.

Run these steps **in order**, and **stop and report immediately** if any step fails — do not proceed to the next step on a failure:

1. **Pre-flight check** — syntax/import check on changed files.
2. **Commit** — stage changes and commit with a short, plain, two-word message (no punctuation, no emoji, no detail — keep it minimal by design).
3. **PyInstaller build** — run the one-dir build via `JK_Catalog_Multi.spec`. Confirm the `dist/` output folder is populated and the console log shows no traceback before continuing.
4. **Inno Setup build** — compile `JK_Catalog_Multi_Setup.iss`. Confirm the installer `.exe` was produced in the expected output directory.
5. **Report back**: commit hash + message, build pass/fail for each stage, final installer path, and any warnings surfaced along the way.

### "check 2" — Deep Architectural Audit
**Trigger:** the exact phrase `check 2`. No further confirmation needed once triggered.

Approach this as a senior architect with decades of experience doing a thorough, skeptical review — not a surface skim. This is a **read-only audit**: identify and report issues, but do not modify code unless the user asks for fixes afterward.

**The checklist below is a floor, not a ceiling.** It names the categories most likely to bite in this codebase, but it is not the boundary of the audit. Read the actual logic of each function/screen and question whether it does what it's supposed to do — report anything that looks wrong even if it doesn't fit neatly into one of the named categories below. Don't let "I checked every item on the list" substitute for "I understood what this code is trying to do and verified it does that correctly."

Work through the **7 Universal Invariant Domains** below, then keep going beyond them:

#### Domain 1: State Synchronization & Lifecycle (Reality vs. Representation)
- **Split-brain & stale context**: When an entity (role, user, company, mapping, stock item) is altered in one dialog/thread, do all other open screens and active sessions update immediately in memory, or do they hold stale references until restart?
- **Zombie callbacks & destruction races**: Audit all `QTimer.singleShot()` and worker thread lambdas. Can the parent widget or table cell be destroyed/closed while the timer/thread is pending, causing "wrapped C/C++ object deleted" crashes?
- **Recursion storms & signal feedback loops**: In `itemChanged`, `currentIndexChanged`, or text handlers, are signals properly blocked (`blockSignals(True)`) during programmatic updates, or do they trigger uncontrolled event feedback loops and secondary saves?
- **Ghost calls & defensive swallowing**: Search for `hasattr(obj, 'method')`, `getattr(obj, 'method', None)`, and bare `except: pass`. Are these defensive guards hiding incomplete interface contracts, missing methods, or misspelled signals? Flag any missing methods as Critical.

#### Domain 2: Authorization & Permission Orthogonality (Intent vs. Enforcement)
- **Gating orthogonality**: Sub-permissions (e.g. `clear_mapping`, `export`, `print`, `reshuffle`) must NEVER be conflated or subordinated to parent edit permissions (`_can_edit` / `tab.*`) via `and`. If an admin grants permission X in User Roles, verify that NO unrelated permission Y is silently required for X to function.
- **Live session propagation**: When permissions change in Settings, does the running `UserSession` and UI sync instantly across active windows without requiring a logout or 60s background delay?
- **Two-tier gate parity**: Is every feature protected at BOTH levels:
  1. *Display-time*: UI control enabled/disabled with clear affordance.
  2. *Execution-time*: handler asserts `session.can()` before executing the DB/file action.

#### Domain 3: Visual Contrast & Dual-Engine Rendering (The Perception Domain)
- **QSS vs QPainter inversion**: Audit all custom rendering: `QHeaderView`, `QStyledItemDelegate`, `paintSection()`, `paintEvent()`. Cross-reference imperative drawing (`painter.setPen()`, `painter.setBrush()`, `it.setForeground()`) against declarative stylesheet rules in `style.qss`. Catch dark-on-dark (e.g. dark slate `#0f172a` on dark navy `#1A2035`) and light-on-light (white on light gray) text/border combinations.
- **High-DPI & dynamic geometry truncation**: Look for hardcoded pixel dimensions (`setFixedWidth`, `setRowHeight`) on labels, buttons, or headers that contain localized or dynamic text. Check whether word wrap (`TextWordWrap`) or minimum column widths prevent text clipping on smaller resolution displays or varied Windows scaling (125%/150%).
- **State contrast consistency**: Verify that `:disabled`, `:hover`, and `:selected` states maintain legible contrast ratios (minimum 4.5:1 for normal text, 3:1 for bold/headers).
- **Unified Devanagari & Latin Typography (Common Font Invariant)**: The entire application must uniformly use the bundled `'Noto Sans Devanagari'` font family (as established in `godown_list.py`) across all UI widgets, tables, dialogs, printers, and delegates. The system processes multilingual data containing Hindi/Devanagari alongside English. Audit all stylesheets, `UNIVERSAL_TABLE_STYLE`, and `QFont` declarations: flag any hardcoded overrides of `'Segoe UI'`, `'Arial'`, or system defaults that bypass or subordinate `'Noto Sans Devanagari'`, as they produce broken conjuncts, missing glyphs ("tofu" boxes), or baseline jitter on Hindi text.

#### Domain 4: Interaction Affordance & Keyboard Navigation (The Ergonomics Domain)
- **Negative affordance & initial-state deadlocks**: Inspect buttons initialized as `setEnabled(False)` or gated by selection (`has_sel`). Ensure buttons don't appear permanently broken/permission-denied when entering a screen; prefer keeping permission-backed buttons active and providing clear instructional feedback (e.g. "Select a row first") if clicked without selection.
- **Hotkey collisions & phonetic naturalness**: Audit all `&Letter` hotkey assignments across all menus for buried mid-word letters (e.g. `C&hq`, `Pa&yment`, `Bra&nch` when first letters were available) and duplicate Alt keys within the same menu.
- **Operational in-screen hotkeys**: Check all data-heavy screens for essential operational shortcuts: Search focus (`Ctrl+F` or `/`), Reset/Back (`Esc`), Refresh (`F5` or `Ctrl+R`), Export (`Ctrl+E`), Print (`Ctrl+P`), Tab switching (`Ctrl+Tab` or `Ctrl+PgUp/Dn`).
- **Event filter key swallowing**: In custom `eventFilter()` handlers on tables, delegates, and dialogs, verify that keys (Return, Tab, Esc, Alt+Key) are consumed ONLY when an active editor or popup actually requires them, and are passed up to parent shortcuts otherwise. Audit focus-out editor destruction.

#### Domain 5: Data Integrity, Aggregation & Numeric Precision (The Truth Domain)
- **View vs mutation isolation**: Verify that filtering, searching, or column sorting NEVER alters the underlying source dataset, row indices, or database record IDs.
- **Netting & multi-row aggregation**: Audit group-level vs row-level calculations (e.g. VAT vs Internal mapping groups, credit/debit balances, negative indicator netting). Ensure multi-row groups aggregate before difference calculation, not row-by-row.
- **Floating-point & currency precision**: Check that amounts are never rounded prematurely before arithmetic. Flag any currency comparison using raw `float == float` without an epsilon guard (`1e-9`).
- **Null & boundary fragility**: Test behavior with empty lists, `None`/`NULL` SQL values, zero-quantity inputs, single-row, and max-row boundaries. Ensure SQL `NULL` values never render as literal `"None"` strings in tables.

#### Domain 6: Concurrency, Database & Resource Integrity (The Stability Domain)
- **GUI thread affinity**: Verify that background threads (`QThread`, `ThreadPool`) NEVER touch GUI widgets directly. All UI updates must cross thread boundaries exclusively via `pyqtSignal`.
- **Connection & cursor lifecycles**: Check that database connections and cursors are strictly scoped: opened, executed, committed/rolled back, and closed in `try...finally` blocks. Flag leaked connections, long-held locks, and unclosed file handles (Excel exports, backups).
- **SQL injection & parameterization**: Audit all SQL statements. Flag any query built via Python f-strings or string concatenation instead of parameterized placeholders (`?`).
- **Paths & data loading**: Hardcoded local paths vs shared/multi-user paths, path-separator issues, unsafe assumptions about permissions or drive letters.

#### Domain 7: Diagnostic Integrity & Client-Side Supportability (The Observability Domain)
- **The silent failure rule**: Flag any `except:` or `except Exception:` block that does not log to `error.log` via `logger.error()`. Confirm errors are actually written in a way that supports the client-side debugging protocol in Section 3, rather than failing silently.
- **False-positive feedback**: Verify that success notifications ("Saved successfully") fire ONLY after the underlying database transaction actually committed, never before or inside an unverified try block.

#### Other Flaws
- **Static / syntax integrity**: Compile-check modified and core files; flag syntax errors, undefined names, unreachable code, unused imports.
- **Packaging**: Hidden imports missing from `.spec`, data files not bundled, version-string mismatches between app and installer.
- **Security**: Hardcoded credentials/secrets, disabled certificate validation, unsafe deserialization.
- **Anything else**: If something reads as logically inconsistent, fragile, or surprising and it doesn't fit any domain above, report it anyway under "Other."

**Output format:**
- Group findings by severity: **Critical / High / Medium / Low**.
- For each finding: file + line reference, the exact failure mechanism, why it matters, and a suggested fix.
- End with a short summary count by severity.

## 5. Theme Rules
- **Green theme for payment sheets**: in `supp_payment.py`, primary buttons and the bottom tab navigation use green (`#059669` and `#047857`) instead of blue.
- *Suggestion (not a mandate — flag only):* if these colors are scattered as literals across the file, consider centralizing them as named constants so future palette changes are a one-line edit. Only do this if the user asks.

## 6. UI & Interaction Guidelines
- **Unified Application Font**: Always use `'Noto Sans Devanagari'` (bundled in `src/assets/fonts/NotoSansDevanagari.ttf`) as the primary font family for all UI controls, tables, dialogs, reports, and delegates. Never hardcode English-only fonts like `'Segoe UI'` or `'Arial'` as primary, because they break Hindi/Devanagari text rendering.
- **No hover tooltips / hint boxes**: Do not add `setToolTip` or hover tooltip boxes explaining what buttons or UI controls do, unless explicitly requested by the user. Keep the interface clean, fast, and free of unsolicited popup hints.

## 7. Engineering Discipline & Guardrails
- **Always think before making any assumption or doing anything**: Never jump to conclusions or make unverified assumptions about business rules, existing architecture, or user intent. Always carefully review code comments, explicit requirements, and stated user context before proposing or implementing changes. Never alter intentional design constraints (such as query filters or architectural rules marked as strictly required) without explicit confirmation from the user.