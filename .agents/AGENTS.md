# Project Scope and Build Rules

1. **JK Multi Only**: All work and development on this codebase should exclusively focus on the "JK Multi" (multi-user) version of the application. Do not modify or focus on the single-user versions.
2. **PyInstaller Builds**: Always use the **one-dir** (folder) build approach (`COLLECT`) when compiling the executable with PyInstaller. Do not build single-file executables (`--onefile`), as the multi-user structure requires the folder layout for performance and proper data loading. Use `JK_Catalog_Multi.spec` for all builds.
3. **Inno Setup Builds**: After compiling with PyInstaller, always build the installer using Inno Setup Compiler. Use the `JK_Catalog_Multi_Setup.iss` script.
4. **No Automated EXE Builds**: DO NOT run PyInstaller or Inno Setup (ISCC) to create an EXE automatically (not even during `check 1`). Only build the EXE when the user explicitly requests it (e.g. "Build the EXE").

# Custom Workflow Commands
If the user types the following exact phrases, execute the corresponding workflow without requiring further confirmation:
- **"check 1"**: Immediately run `git commit` (with a small, amateur two-word message). Do NOT run PyInstaller or Inno Setup.
- **"check 2"**: Perform a deep, thorough bug-check of the codebase as if you are a senior architect with 50 years of experience.
