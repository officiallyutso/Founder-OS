' Launch the Founder OS service with NO visible console window.
' Used by the Task Scheduler "FounderOS" task (trigger: at log on).
Dim shell, fso, here
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = here
' 0 = hidden window, False = don't wait for it to finish
shell.Run "cmd /c """ & here & "\founder_os_service.bat""", 0, False
