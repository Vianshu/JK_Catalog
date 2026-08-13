# Project Scope and Build Rules

1. **JK Multi Only**: All work and development on this codebase should exclusively focus on the "JK Multi" (multi-user) version of the application. Do not modify or focus on the single-user versions.
2. **PyInstaller Builds**: Always use the **one-dir** (folder) build approach (`COLLECT`) when compiling the executable with PyInstaller. Do not build single-file executables (`--onefile`), as the multi-user structure requires the folder layout for performance and proper data loading. Use `JK_Catalog_Multi.spec` for all builds.
3. **Inno Setup Builds**: After compiling with PyInstaller, always build the installer using Inno Setup Compiler. Use the `JK_Catalog_Multi_Setup.iss` script.
4. **No Automated EXE Builds**: DO NOT run PyInstaller or Inno Setup (ISCC) to create an EXE automatically (not even during `check 1`). Only build the EXE when the user explicitly requests it (e.g. "Build the EXE").
5. **No Automated Git Commits**: DO NOT run `git commit` automatically after completing tasks. Only commit when explicitly asked by the user, or when triggered by the `check 1` command.

# Issue Reporting Assumptions
- **Default to Client**: When the user reports a bug or issue without specifying where it occurred, always assume it happened on the **client's machine** (not the developer's local machine). Do not check local logs or local databases to confirm — instead, guide the user on how to gather evidence from the client side (e.g., ask for the client's `error.log`, query their SQL Server, or ask what the client was doing before the issue occurred).

# Custom Workflow Commands
If the user types the following exact phrases, execute the corresponding workflow without requiring further confirmation:
- **"check 1"**: Immediately run `git commit` (with a small, amateur two-word message), then trigger the PyInstaller one-dir build, and finally compile the Inno Setup (`.iss`) script.
- **"check 2"**: Perform a deep, thorough bug-check of the codebase as if you are a senior architect with 50 years of experience.
