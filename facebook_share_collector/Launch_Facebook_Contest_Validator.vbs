' ============================================================================
' Facebook Contest Validator & Live Lottery Prep - Windowless Windows Engine
' Invoked automatically by "Facebook Contest Validator.exe" (or directly).
' Compatible with ALL Windows Processors: Intel x64, AMD Ryzen x64, ARM64, x86
' ============================================================================
Option Explicit

Dim fso, shell, appDir, pythonwExe, mainPy, setupBat
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

appDir = fso.GetParentFolderName(WScript.ScriptFullName)
If WScript.Arguments.Count > 0 Then
    Dim arg0
    arg0 = WScript.Arguments(0)
    If fso.FileExists(arg0) Then
        appDir = fso.GetParentFolderName(fso.GetAbsolutePathName(arg0))
    End If
End If

shell.CurrentDirectory = appDir

pythonwExe = appDir & "\.venv\Scripts\pythonw.exe"
mainPy = appDir & "\main.py"
setupBat = appDir & "\Setup_And_Launch_Windows.bat"

If fso.FileExists(pythonwExe) Then
    shell.Run Chr(34) & pythonwExe & Chr(34) & " " & Chr(34) & mainPy & Chr(34), 0, False
Else
    ' First-time run on this Windows PC: run processor-aware setup & launch
    shell.Run Chr(34) & setupBat & Chr(34), 1, False
End If
