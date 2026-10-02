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

Work through this checklist, then keep going beyond it:

- **General logic & business rules** — wrong or inverted conditionals, off-by-one errors, incorrect calculations (especially payment amounts, totals, discounts, tax, rounding/currency precision), wrong state/workflow transitions, mismatched assumptions between what the UI shows and what the backend actually does, stale or incorrect cached values, incorrect date/time handling (timezones, fiscal periods, DST).
- **Edge cases & data validation** — empty lists/None/zero-quantity inputs, duplicate records, missing input validation before it hits the DB or a calculation, boundary values (first/last item, min/max amounts).
- **Static / syntax integrity** — compile-check modified and core files; flag syntax errors, undefined names, unreachable code, unused imports.
- **Exception handling** — bare `except:` blocks, silently swallowed exceptions, missing logging on failure paths, unclosed resources (file handles, DB connections, cursors).
- **Multi-user / concurrency integrity** — shared mutable state, race conditions, DB connection pooling misuse, transaction boundaries, file/record locking around shared data.
- **Database layer** — SQL injection risk (string-built vs. parameterized queries), missing commits/rollbacks, leaked connections, long-held locks.
- **Paths & data loading** — hardcoded local paths vs. shared/multi-user paths, path-separator issues, unsafe assumptions about permissions or drive letters.
- **UI layer** — unhandled exceptions in callbacks/event handlers, missing `None`/null checks, theme consistency (see Section 5) across payment-related screens.
- **Packaging** — hidden imports missing from the `.spec` file, data files not bundled, version-string mismatches between the app and the installer.
- **Logging** — confirm errors are actually written to `error.log` in a way that supports the client-side debugging protocol in Section 3, rather than failing silently.
- **Security** — hardcoded credentials/secrets, disabled certificate validation, unsafe deserialization.
- **Anything else** — if something reads as logically inconsistent, fragile, or surprising and it doesn't fit any category above, report it anyway under "Other."

**Output format:**
- Group findings by severity: **Critical / High / Medium / Low**.
- For each finding: file + line reference, what's wrong, why it matters, and a suggested fix.
- End with a short summary count by severity.

## 5. Theme Rules
- **Green theme for payment sheets**: in `supp_payment.py`, primary buttons and the bottom tab navigation use green (`#059669` and `#047857`) instead of blue.
- *Suggestion (not a mandate — flag only):* if these colors are scattered as literals across the file, consider centralizing them as named constants so future palette changes are a one-line edit. Only do this if the user asks.

## 6. UI & Interaction Guidelines
- **No hover tooltips / hint boxes**: Do not add `setToolTip` or hover tooltip boxes explaining what buttons or UI controls do, unless explicitly requested by the user. Keep the interface clean, fast, and free of unsolicited popup hints.