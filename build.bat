@echo off
setlocal enabledelayedexpansion
pip install -r requirements.txt pyinstaller

if not exist lib mkdir lib

if not exist "lib\LibreHardwareMonitorLib.dll" (
  echo DLL не найдены в lib\, пробую скачать из NuGet...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "& { try { [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $ProgressPreference='SilentlyContinue'; Invoke-WebRequest 'https://www.nuget.org/api/v2/package/LibreHardwareMonitorLib/0.9.3' -OutFile lhm.zip; Expand-Archive lhm.zip -DestinationPath lhm_pkg -Force; $d=Get-ChildItem lhm_pkg -Recurse -Filter LibreHardwareMonitorLib.dll | Where-Object { $_.FullName -match 'net47' } | Select-Object -First 1; if($d){ Copy-Item $d.FullName lib\ -Force }; Invoke-WebRequest 'https://www.nuget.org/api/v2/package/HidSharp/2.1.0' -OutFile hid.zip; Expand-Archive hid.zip -DestinationPath hid_pkg -Force; $h=Get-ChildItem hid_pkg -Recurse -Filter HidSharp.dll | Where-Object { $_.FullName -match 'net3|net4' } | Select-Object -First 1; if($h){ Copy-Item $h.FullName lib\ -Force } } catch { Write-Host ('Ошибка загрузки DLL: '+$_.Exception.Message) } }"
)

set "ADDLHM="
set "ADDHID="
if exist "lib\LibreHardwareMonitorLib.dll" (
  set "ADDLHM=--add-data "lib\LibreHardwareMonitorLib.dll;.""
  echo LibreHardwareMonitorLib.dll: OK
) else (
  echo ВНИМАНИЕ: LibreHardwareMonitorLib.dll отсутствует - температуры пойдут только через WMI. Сборка продолжится.
)
if exist "lib\HidSharp.dll" set "ADDHID=--add-data "lib\HidSharp.dll;.""

pyinstaller --onefile --windowed --clean --noconfirm --name "ServiceCom_Diag" --uac-admin --add-data "logo.png;." !ADDLHM! !ADDHID! --collect-all PyQt6 --collect-all numpy --collect-all psutil --collect-all pythonnet --collect-all clr_loader main.py

echo.
echo Готово: dist\ServiceCom_Diag.exe
pause
