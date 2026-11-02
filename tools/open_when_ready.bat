@echo off
chcp 65001 >nul
rem Waits until the SUSTechPOINTS server listens on port 8081, then opens the browser.
rem Started by run.bat in a separate minimized window; plain `exit` closes that window when done.
rem Arg 1 = seconds to wait (default 180). SUSTECH_NO_BROWSER=1 = do not open the browser (for tests).
set "LIMIT=%~1"
if "%LIMIT%"=="" set "LIMIT=180"
set "PING=%SystemRoot%\System32\ping.exe"
for /l %%i in (1,1,%LIMIT%) do (
    netstat -ano 2>nul | findstr /r /c:":8081 .*LISTENING" >nul && goto :ready
    "%PING%" -n 2 127.0.0.1 >nul
)
echo Server did not start within %LIMIT% s.
exit 1
:ready
if "%SUSTECH_NO_BROWSER%"=="1" (echo ready & exit 0)
start "" http://127.0.0.1:8081
exit 0
