@echo off
echo ========================================================
echo Building JK_Catalog_Multi
echo ========================================================
pyinstaller -y --clean JK_Catalog_Multi.spec
if %ERRORLEVEL% neq 0 (
    echo [ERROR] PyInstaller failed for JK_Catalog_Multi.
    pause
    exit /b %ERRORLEVEL%
)

echo Compiling JK_Catalog_Multi Setup...
"C:\Program Files (x86)\Inno Setup 6\ISCC.exe" JK_Catalog_Multi_Setup.iss
if %ERRORLEVEL% neq 0 (
    echo [ERROR] ISCC failed for JK_Catalog_Multi_Setup.iss.
    pause
    exit /b %ERRORLEVEL%
)

echo ========================================================
echo BUILD COMPLETE!
echo Output installer is located in the dist\ folder.
echo ========================================================
pause
