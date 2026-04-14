Set shell = CreateObject("WScript.Shell")
Set fso   = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
webDir = root & "\web"

' Пишем временный bat, чтобы не иметь проблем с кавычками
tmpBat = fso.GetSpecialFolder(2) & "\wpc_web_launch.bat"
Set f = fso.OpenTextFile(tmpBat, 2, True)
f.WriteLine "@echo off"
f.WriteLine "cd /d """ & webDir & """"
f.WriteLine "call venv\Scripts\activate"
f.WriteLine "python -m uvicorn app:app --port 8000 --reload"
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
