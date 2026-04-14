Set shell = CreateObject("WScript.Shell")
Set fso   = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
webDir = root & "\web"
cmd = "call venv\Scripts\activate && python -m uvicorn app:app --port 8000 --reload"

' Открываем Windows Terminal если установлен, иначе обычный cmd
wtExe = shell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Microsoft\WindowsApps\wt.exe"
If fso.FileExists(wtExe) Then
    shell.Run "wt -d """ & webDir & """ cmd /k """ & cmd & """", 0, False
Else
    shell.Run "cmd /k ""cd /d """ & webDir & """ && " & cmd & """", 1, False
End If

' Открываем браузер через 2 секунды
WScript.Sleep 2000
shell.Run "http://localhost:8000"
