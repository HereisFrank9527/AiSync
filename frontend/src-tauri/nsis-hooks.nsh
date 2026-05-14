!macro NSIS_HOOK_PREINSTALL
  DetailPrint "Stopping existing AiSync processes before installing..."
  nsExec::ExecToLog 'taskkill /F /IM aisync.exe /T'
  nsExec::ExecToLog 'wmic process where "name=''python.exe'' and executablepath like ''%\\AiSync\\runtime\\python\\%''" call terminate'
  nsExec::ExecToLog 'wmic process where "name=''pythonw.exe'' and executablepath like ''%\\AiSync\\runtime\\python\\%''" call terminate'
  Sleep 1200
  DetailPrint "Removing stale AiSync install files before installing..."
  Delete /REBOOTOK "$INSTDIR\aisync.exe"
  Delete /REBOOTOK "$INSTDIR\uninstall.exe"
  RMDir /r /REBOOTOK "$INSTDIR\backend-src"
  RMDir /r /REBOOTOK "$INSTDIR\resources\backend-src"
  RMDir /r /REBOOTOK "$INSTDIR\runtime"
  RMDir /r /REBOOTOK "$INSTDIR\resources\runtime"
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  DetailPrint "Stopping existing AiSync processes before uninstalling..."
  nsExec::ExecToLog 'taskkill /F /IM aisync.exe /T'
  nsExec::ExecToLog 'wmic process where "name=''python.exe'' and executablepath like ''%\\AiSync\\runtime\\python\\%''" call terminate'
  nsExec::ExecToLog 'wmic process where "name=''pythonw.exe'' and executablepath like ''%\\AiSync\\runtime\\python\\%''" call terminate'
  Sleep 1200
!macroend
