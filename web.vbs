Set shell = CreateObject("WScript.Shell")
Set fso   = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
webDir = root & "\web"

' Пишем временный bat, чтобы не иметь проблем с кавычками
tmpBat = fso.GetSpecialFolder(2) & "\wpc_web_launch.bat"
Set f = fso.OpenTextFile(tmpBat, 2, True)
f.WriteLine "@echo off"
f.WriteLine "cd /d """ & webDir & """"
f.WriteLine ""
f.WriteLine ":: Pre-flight: проверка что python.exe в venv работает"
f.WriteLine "venv\Scripts\python.exe --version >nul 2>&1"
f.WriteLine "if errorlevel 1 ("
f.WriteLine "    echo."
f.WriteLine "    echo [ERROR] web\venv is broken: python.exe is missing or not executable."
f.WriteLine "    echo."
f.WriteLine "    echo This typically happens when the Python interpreter the venv was created"
f.WriteLine "    echo with was removed or auto-updated (e.g. Microsoft Store Python)."
f.WriteLine "    echo."
f.WriteLine "    echo To recreate:"
f.WriteLine "    echo     rmdir /s /q web\venv"
f.WriteLine "    echo     ""C:\Program Files\Python312\python.exe"" -m venv web\venv"
f.WriteLine "    echo     web\venv\Scripts\python.exe -m pip install -r web\requirements.txt"
f.WriteLine "    echo."
f.WriteLine "    pause"
f.WriteLine "    exit /b 1"
f.WriteLine ")"
f.WriteLine ""
f.WriteLine ":: Pre-flight: проверка что uvicorn установлен"
f.WriteLine "venv\Scripts\python.exe -c ""import uvicorn"" 2>nul"
f.WriteLine "if errorlevel 1 ("
f.WriteLine "    echo."
f.WriteLine "    echo [ERROR] uvicorn is not installed in web\venv."
f.WriteLine "    echo."
f.WriteLine "    echo Run:"
f.WriteLine "    echo     web\venv\Scripts\python.exe -m pip install -r web\requirements.txt"
f.WriteLine "    echo."
f.WriteLine "    pause"
f.WriteLine "    exit /b 1"
f.WriteLine ")"
f.WriteLine ""
f.WriteLine ":: Убиваем процесс на порту 8000 если висит"
f.WriteLine "for /f ""tokens=5"" %%a in ('netstat -aon ^| findstr "":8000 "" ^| findstr ""LISTENING"" 2^>nul') do taskkill /f /pid %%a >nul 2>&1"
f.WriteLine ""
f.WriteLine "venv\Scripts\python.exe -m uvicorn app:app --port 8000 --reload"
f.Close

' Открываем Windows Terminal если установлен, иначе обычный cmd
wtExe = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Microsoft\WindowsApps\wt.exe"
If fso.FileExists(wtExe) Then
    shell.Run "wt cmd /k """ & tmpBat & """", 1, False
Else
    shell.Run "cmd /k """ & tmpBat & """", 1, False
End If

' Открываем браузер через 2 секунды
WScript.Sleep 2000
shell.Run "http://localhost:8000"
