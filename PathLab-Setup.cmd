@echo off
setlocal
set "PATHLAB_PYTHON="
for /d %%D in ("%ProgramFiles%\IBM\SPSS\Statistics\*") do if exist "%%~fD\Python3\pythonw.exe" set "PATHLAB_PYTHON=%%~fD\Python3\pythonw.exe"
if not defined PATHLAB_PYTHON if exist "%ProgramFiles%\IBM\SPSS Statistics\Python3\pythonw.exe" set "PATHLAB_PYTHON=%ProgramFiles%\IBM\SPSS Statistics\Python3\pythonw.exe"
if defined PATHLAB_PYTHON (
  start "" "%PATHLAB_PYTHON%" "%~dp0setup.pyw"
) else (
  echo SPSS Python was not found in the standard installation folders.
  echo Open setup.pyw with the Python3 program supplied with your SPSS installation.
  pause
)
endlocal
