Unicode true
RequestExecutionLevel admin
ManifestDPIAware true
ManifestSupportedOS all
SetCompressor /SOLID lzma
SetDatablockOptimize on

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "x64.nsh"
!include "WinVer.nsh"

!ifndef STAGE_DIR
  !error "Pass -DSTAGE_DIR=<prepared payload directory>"
!endif
!ifndef OUT_FILE
  !error "Pass -DOUT_FILE=<installer.exe>"
!endif
!ifndef APP_VERSION
  !define APP_VERSION "1.0.0"
!endif
!ifndef PAYLOAD_KB
  !define PAYLOAD_KB 0
!endif
!define APP_ID "ChangfuliElevatorLedger"
!define APP_NAME "昌福里社区电梯管理系统"
!define MENU_NAME "昌福里社区电梯管理系统"
!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}"
!define FIREWALL_RULE "ChangfuliElevatorLedger.PrivateLAN.8765"

Name "${APP_NAME}"
OutFile "${OUT_FILE}"
InstallDir "$PROGRAMFILES64\${APP_ID}"
Icon "${__FILEDIR__}/windows-app.ico"
UninstallIcon "${__FILEDIR__}/windows-app.ico"
BrandingText "昌福里社区27区党群物业服务站"
ShowInstDetails show
ShowUninstDetails show
VIProductVersion "${APP_VERSION}.0"
VIAddVersionKey /LANG=2052 "ProductName" "${APP_NAME}"
VIAddVersionKey /LANG=2052 "ProductVersion" "${APP_VERSION}"
VIAddVersionKey /LANG=2052 "FileVersion" "${APP_VERSION}"
VIAddVersionKey /LANG=2052 "FileDescription" "电梯管理系统安装程序"
VIAddVersionKey /LANG=2052 "LegalCopyright" "昌福里社区27区党群物业服务站"

!define MUI_ABORTWARNING
!define MUI_CUSTOMFUNCTION_ABORT InstallerAbort
!define MUI_CUSTOMFUNCTION_UNABORT un.InstallerAbort
!define MUI_WELCOMEPAGE_TEXT "本程序为同一台主机安装一套电梯管理台账。$\r$\n$\r$\n安装需要管理员授权，日常使用无需管理员权限。台账数据存放在 ProgramData，升级和卸载会保留数据。$\r$\n$\r$\n请先备份已有台账，并关闭正在编辑的工作页面。"
!define MUI_FINISHPAGE_TEXT "安装已完成。$\r$\n$\r$\n请双击桌面的“昌福里社区电梯管理系统”启动。安装器不会以管理员身份打开浏览器。$\r$\n$\r$\n首次启动后按页面提示设置管理员账号。停止系统、打开数据目录和卸载入口位于开始菜单。"
!define MUI_UNCONFIRMPAGE_TEXT_TOP "卸载将停止本机系统并删除程序。ProgramData 中的台账、附件、备份及日志会保留。"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "SimpChinese"
Var MaintenanceOwned
Var MaintenanceHandle
Var InstallerMutex

Function .onInit
  SetShellVarContext all
  SetRegView 64
  StrCpy $INSTDIR "$PROGRAMFILES64\${APP_ID}"
  ${IfNot} ${AtLeastWin10}
    MessageBox MB_OK|MB_ICONSTOP "本程序需要 Windows 10 或更新版本。" /SD IDOK
    SetErrorLevel 2
    Quit
  ${EndIf}
  ${If} ${IsNativeAMD64}
    ; Native x64 Windows is the deployment target.
  ${ElseIf} ${IsNativeARM64}
    ${IfNot} ${AtLeastBuild} 22000
      MessageBox MB_OK|MB_ICONSTOP "ARM 设备需要支持 x64 模拟的 Windows 11。" /SD IDOK
      SetErrorLevel 2
      Quit
    ${EndIf}
  ${Else}
    MessageBox MB_OK|MB_ICONSTOP "本安装包需要 64 位 Windows，不能安装到 32 位系统。" /SD IDOK
    SetErrorLevel 2
    Quit
  ${EndIf}
  Call AcquireInstallerMutex
  System::Call 'shell32::SetCurrentProcessExplicitAppUserModelID(w "${APP_ID}")i.r0'
FunctionEnd

!macro InstallerMutexFunctions PREFIX
Function ${PREFIX}AcquireInstallerMutex
  System::Call 'kernel32::CreateMutexW(p 0, i 1, w "Global\${APP_ID}.Installer") p.r0 ?e'
  Pop $1
  ${If} $0 == 0
    MessageBox MB_OK|MB_ICONSTOP "无法取得安装维护锁（错误 $1），操作已取消。请关闭其他安装或卸载窗口后重试。" /SD IDOK
    SetErrorLevel 8
    Quit
  ${EndIf}
  ${If} $1 == 183
    System::Call 'kernel32::CloseHandle(p r0)'
    MessageBox MB_OK|MB_ICONSTOP "另一份本产品安装或卸载程序正在运行。请先完成并关闭该窗口，再重试。" /SD IDOK
    SetErrorLevel 8
    Quit
  ${EndIf}
  StrCpy $InstallerMutex $0
FunctionEnd

Function ${PREFIX}ReleaseInstallerMutex
  ${If} $InstallerMutex != ""
    System::Call 'kernel32::CloseHandle(p $InstallerMutex)'
    StrCpy $InstallerMutex ""
  ${EndIf}
FunctionEnd
!macroend
!insertmacro InstallerMutexFunctions ""
!insertmacro InstallerMutexFunctions "un."

Function StopCandidate
  DetailPrint "正在安全停止本机电梯管理系统…"
  nsExec::ExecToStack /TIMEOUT=60000 '"$PLUGINSDIR\payload\runtime\python.exe" "$PLUGINSDIR\payload\scripts\windows_launcher.py" --stop --quiet'
  Pop $0
  Pop $1
  ${If} $0 != "0"
    MessageBox MB_OK|MB_ICONSTOP "无法安全停止旧系统，安装未覆盖程序。请等待工作人员保存并停止系统，或重启主机后重试。$\r$\n返回码：$0$\r$\n$1" /SD IDOK
    SetErrorLevel 2
    Abort
  ${EndIf}
FunctionEnd

!macro StopInstalled PREFIX
Function ${PREFIX}StopInstalled
  IfFileExists "$INSTDIR\scripts\windows_launcher.py" stop_check_runtime
  IfFileExists "$INSTDIR\runtime\python.exe" stop_damaged stop_done
  stop_check_runtime:
    IfFileExists "$INSTDIR\runtime\python.exe" stop_run stop_damaged
  stop_run:
    DetailPrint "正在停止本机电梯管理系统…"
    nsExec::ExecToStack /TIMEOUT=60000 '"$INSTDIR\runtime\python.exe" "$INSTDIR\scripts\windows_launcher.py" --stop --quiet'
    Pop $0
    Pop $1
    StrCmp $0 "0" stop_done
    MessageBox MB_OK|MB_ICONSTOP "无法安全停止旧系统，操作已取消，程序和台账未被覆盖。$\r$\n请等待工作人员完成保存，或重启主机后重试。$\r$\n返回码：$0$\r$\n$1" /SD IDOK
    SetErrorLevel 2
    Abort
  stop_damaged:
    MessageBox MB_OK|MB_ICONSTOP "现有程序的启动器或内置运行环境不完整，无法确认旧实例已经停止。请联系维护人员修复后重试；台账数据保持不变。" /SD IDOK
    SetErrorLevel 2
    Abort
  stop_done:
FunctionEnd
!macroend
!insertmacro StopInstalled "un."

!macro DataRootGuard PREFIX
Function ${PREFIX}ValidateDataRoot
  System::Call 'kernel32::GetFileAttributesW(w "$APPDATA\${APP_ID}") i.r0 ?e'
  Pop $1
  ${If} $0 == -1
    ${If} $1 == 2
    ${OrIf} $1 == 3
      Return
    ${EndIf}
    Goto data_root_invalid
  ${EndIf}
  IntOp $1 $0 & 0x400
  ${If} $1 != 0
    Goto data_root_invalid
  ${EndIf}
  IntOp $1 $0 & 0x10
  ${If} $1 != 0
    Return
  ${EndIf}
  data_root_invalid:
    MessageBox MB_OK|MB_ICONSTOP "共享台账目录不是普通文件夹、包含重解析点或无法安全读取，维护操作已停止。请联系管理员检查 ProgramData\${APP_ID}，不要直接覆盖现有资料。" /SD IDOK
    SetErrorLevel 9
    Abort
FunctionEnd
!macroend
!insertmacro DataRootGuard ""
!insertmacro DataRootGuard "un."

!macro MaintenanceFunctions PREFIX
Function ${PREFIX}BeginMaintenance
  Call ${PREFIX}ValidateDataRoot
  CreateDirectory "$APPDATA\${APP_ID}"
  ; Create without truncation; keep the validated file open without delete sharing.
  System::Call 'kernel32::CreateFileW(w "$APPDATA\${APP_ID}\maintenance.flag", i 0x10080, i 3, p 0, i 1, i 0x02200080, p 0) p.r0 ?e'
  Pop $1
  ${If} $0 == -1
    ${If} $1 != 80
    ${AndIf} $1 != 183
      Goto maintenance_invalid
    ${EndIf}
    System::Call 'kernel32::CreateFileW(w "$APPDATA\${APP_ID}\maintenance.flag", i 0x10080, i 3, p 0, i 3, i 0x02200080, p 0) p.r0'
  ${EndIf}
  ${If} $0 == -1
    Goto maintenance_invalid
  ${EndIf}
  StrCpy $MaintenanceHandle $0
  System::Call '*(i 0, i 0) p.r1'
  System::Call 'kernel32::GetFileInformationByHandleEx(p $MaintenanceHandle, i 9, p r1, i 8) i.r0'
  System::Call '*$1(i .r2)'
  System::Free $1
  IntOp $2 $2 & 0x410
  ${If} $0 == 0
  ${OrIf} $2 != 0
    System::Call 'kernel32::CloseHandle(p $MaintenanceHandle)'
    StrCpy $MaintenanceHandle ""
    Goto maintenance_invalid
  ${EndIf}
  StrCpy $MaintenanceOwned "1"
  Return
  maintenance_invalid:
    MessageBox MB_OK|MB_ICONSTOP "无法安全锁定共享台账的维护状态，操作已停止。请检查目录权限及 maintenance.flag 是否为普通文件。" /SD IDOK
    SetErrorLevel 7
    Abort
FunctionEnd

Function ${PREFIX}EndMaintenance
  StrCpy $0 "0"
  ${If} $MaintenanceOwned == "1"
    ; Delete the same validated file, never a replacement at its path.
    System::Call '*(i 1) p.r1'
    System::Call 'kernel32::SetFileInformationByHandle(p $MaintenanceHandle, i 4, p r1, i 4) i.r2'
    System::Free $1
    ${If} $2 == 0
      DetailPrint "无法清除维护标记；请重新运行安装器修复。"
      StrCpy $0 "1"
      Return
    ${EndIf}
    System::Call 'kernel32::CloseHandle(p $MaintenanceHandle)'
    StrCpy $MaintenanceHandle ""
    StrCpy $MaintenanceOwned "0"
  ${EndIf}
FunctionEnd
!macroend
!insertmacro MaintenanceFunctions ""
!insertmacro MaintenanceFunctions "un."

Function .onInstFailed
  Call EndMaintenance
FunctionEnd
Function InstallerAbort
  Call EndMaintenance
FunctionEnd
Function .onGUIEnd
  Call EndMaintenance
  Call ReleaseInstallerMutex
FunctionEnd
Function un.onUninstFailed
  Call un.EndMaintenance
FunctionEnd
Function un.InstallerAbort
  Call un.EndMaintenance
FunctionEnd
Function un.onGUIEnd
  Call un.EndMaintenance
  Call un.ReleaseInstallerMutex
FunctionEnd

; Only program-owned paths are removed; the shared data directory is never passed to RMDir.
!macro RemoveProgramFiles
  IfFileExists "$INSTDIR\backend\*.*" 0 +2
  RMDir /r "$INSTDIR\backend"
  IfFileExists "$INSTDIR\runtime\*.*" 0 +2
  RMDir /r "$INSTDIR\runtime"
  IfFileExists "$INSTDIR\frontend\*.*" 0 +2
  RMDir /r "$INSTDIR\frontend"
  IfFileExists "$INSTDIR\scripts\*.*" 0 +2
  RMDir /r "$INSTDIR\scripts"
  IfFileExists "$INSTDIR\docs\*.*" 0 +2
  RMDir /r "$INSTDIR\docs"
  IfFileExists "$INSTDIR\licenses\*.*" 0 +2
  RMDir /r "$INSTDIR\licenses"
  IfFileExists "$INSTDIR\requirements.lock.txt" 0 +2
  Delete "$INSTDIR\requirements.lock.txt"
  IfFileExists "$INSTDIR\BUILD-MANIFEST.json" 0 +2
  Delete "$INSTDIR\BUILD-MANIFEST.json"
  IfFileExists "$INSTDIR\windows-app.ico" 0 +2
  Delete "$INSTDIR\windows-app.ico"
!macroend

Section "安装主程序" SEC_MAIN
  InitPluginsDir
  SetOutPath "$PLUGINSDIR\payload"
  File /r "${STAGE_DIR}/*"
  Call ValidateDataRoot
  DetailPrint "正在检查安装包内置 Python、依赖与页面资源…"
  nsExec::ExecToStack /TIMEOUT=60000 '"$PLUGINSDIR\payload\runtime\python.exe" "$PLUGINSDIR\payload\scripts\windows_launcher.py" --check'
  Pop $0
  Pop $1
  ${If} $0 != "0"
    MessageBox MB_OK|MB_ICONSTOP "安装包自检未通过，尚未覆盖旧程序。请重新获取完整安装包。$\r$\n返回码：$0$\r$\n$1" /SD IDOK
    SetErrorLevel 3
    Abort
  ${EndIf}

  Call BeginMaintenance
  Call StopCandidate
  ClearErrors
  !insertmacro RemoveProgramFiles
  ${If} ${Errors}
    MessageBox MB_OK|MB_ICONSTOP "旧程序文件仍被占用，安装已停止。请重启主机后重试。台账数据未被删除。" /SD IDOK
    SetErrorLevel 4
    Abort
  ${EndIf}
  SetOutPath "$INSTDIR"
  ClearErrors
  CopyFiles /SILENT "$PLUGINSDIR\payload\*" "$INSTDIR"
  ${If} ${Errors}
    MessageBox MB_OK|MB_ICONSTOP "无法写入程序目录，安装未完成。请检查磁盘空间并重新安装。台账数据未被删除。" /SD IDOK
    SetErrorLevel 4
    Abort
  ${EndIf}

  Call ValidateDataRoot
  CreateDirectory "$APPDATA\${APP_ID}"
  nsExec::ExecToStack /TIMEOUT=60000 '"$SYSDIR\icacls.exe" "$APPDATA\${APP_ID}" /grant "*S-1-5-32-545:(OI)(CI)M" /C'
  Pop $0
  Pop $1
  ${If} $0 != "0"
    MessageBox MB_OK|MB_ICONSTOP "无法设置共享台账目录的读写权限，安装未完成。$\r$\n返回码：$0$\r$\n$1" /SD IDOK
    SetErrorLevel 5
    Abort
  ${EndIf}
  nsExec::ExecToStack /TIMEOUT=60000 '"$INSTDIR\runtime\python.exe" "$INSTDIR\scripts\windows_launcher.py" --check'
  Pop $0
  Pop $1
  ${If} $0 != "0"
    MessageBox MB_OK|MB_ICONSTOP "已安装程序自检失败，不能开始使用。请重新安装或联系维护人员。台账数据会保留。$\r$\n返回码：$0$\r$\n$1" /SD IDOK
    SetErrorLevel 3
    Abort
  ${EndIf}

  ; Replace only this product's named rule; public networks and remote subnets stay closed.
  nsExec::ExecToLog '"$SYSDIR\netsh.exe" advfirewall firewall delete rule name="${FIREWALL_RULE}"'
  Pop $0
  nsExec::ExecToStack /TIMEOUT=60000 '"$SYSDIR\netsh.exe" advfirewall firewall add rule name="${FIREWALL_RULE}" dir=in action=allow protocol=TCP localport=8765 program="$INSTDIR\runtime\pythonw.exe" profile=private remoteip=localsubnet enable=yes'
  Pop $0
  Pop $1
  ${If} $0 != "0"
    MessageBox MB_OK|MB_ICONSTOP "无法配置本地子网访问规则，安装未完成。请联系主机管理员检查防火墙策略。$\r$\n返回码：$0$\r$\n$1" /SD IDOK
    SetErrorLevel 6
    Abort
  ${EndIf}

  ClearErrors
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateDirectory "$SMPROGRAMS\${MENU_NAME}"
  CreateShortcut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\runtime\pythonw.exe" '$\"$INSTDIR\scripts\windows_launcher.py$\"' "$INSTDIR\windows-app.ico"
  CreateShortcut "$SMPROGRAMS\${MENU_NAME}\启动电梯管理系统.lnk" "$INSTDIR\runtime\pythonw.exe" '$\"$INSTDIR\scripts\windows_launcher.py$\"' "$INSTDIR\windows-app.ico"
  CreateShortcut "$SMPROGRAMS\${MENU_NAME}\停止电梯管理系统.lnk" "$INSTDIR\runtime\pythonw.exe" '$\"$INSTDIR\scripts\windows_launcher.py$\" --stop' "$INSTDIR\windows-app.ico"
  CreateShortcut "$SMPROGRAMS\${MENU_NAME}\打开数据目录.lnk" "$INSTDIR\runtime\pythonw.exe" '$\"$INSTDIR\scripts\windows_launcher.py$\" --data-folder' "$INSTDIR\windows-app.ico"
  CreateShortcut "$SMPROGRAMS\${MENU_NAME}\卸载电梯管理系统.lnk" "$INSTDIR\Uninstall.exe" "" "$INSTDIR\windows-app.ico"
  WriteRegStr HKLM "${UNINSTALL_KEY}" "DisplayName" "${APP_NAME}"
  WriteRegStr HKLM "${UNINSTALL_KEY}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKLM "${UNINSTALL_KEY}" "Publisher" "昌福里社区27区党群物业服务站"
  WriteRegStr HKLM "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "${UNINSTALL_KEY}" "DisplayIcon" "$INSTDIR\windows-app.ico"
  WriteRegStr HKLM "${UNINSTALL_KEY}" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
  WriteRegStr HKLM "${UNINSTALL_KEY}" "QuietUninstallString" '$\"$INSTDIR\Uninstall.exe$\" /S'
  WriteRegStr HKLM "${UNINSTALL_KEY}" "AppUserModelID" "${APP_ID}"
  WriteRegDWORD HKLM "${UNINSTALL_KEY}" "EstimatedSize" ${PAYLOAD_KB}
  WriteRegDWORD HKLM "${UNINSTALL_KEY}" "NoModify" 1
  WriteRegDWORD HKLM "${UNINSTALL_KEY}" "NoRepair" 1
  ${If} ${Errors}
    MessageBox MB_OK|MB_ICONSTOP "无法登记程序或创建完整快捷方式，安装未完成。请检查主机权限并重新安装。台账数据会保留。" /SD IDOK
    SetErrorLevel 4
    Abort
  ${EndIf}
  Call EndMaintenance
  ${If} $0 != "0"
    MessageBox MB_OK|MB_ICONSTOP "无法清除维护标记，程序暂时不能启动。请重新运行安装器修复。" /SD IDOK
    SetErrorLevel 7
    Abort
  ${EndIf}
  SetErrorLevel 0
SectionEnd

Function un.onInit
  SetShellVarContext all
  SetRegView 64
  StrCpy $0 "$PROGRAMFILES64\${APP_ID}"
  ${If} $INSTDIR != $0
    MessageBox MB_OK|MB_ICONSTOP "卸载器位置与本产品程序目录不一致，已停止操作。请从 Windows 已安装应用中卸载。" /SD IDOK
    SetErrorLevel 2
    Quit
  ${EndIf}
  Call un.AcquireInstallerMutex
FunctionEnd

Section "Uninstall"
  Call un.BeginMaintenance
  Call un.StopInstalled
  nsExec::ExecToLog '"$SYSDIR\netsh.exe" advfirewall firewall delete rule name="${FIREWALL_RULE}"'
  Pop $0
  SetOutPath "$TEMP"
  ClearErrors
  !insertmacro RemoveProgramFiles
  Delete "$DESKTOP\${APP_NAME}.lnk"
  Delete "$SMPROGRAMS\${MENU_NAME}\启动电梯管理系统.lnk"
  Delete "$SMPROGRAMS\${MENU_NAME}\停止电梯管理系统.lnk"
  Delete "$SMPROGRAMS\${MENU_NAME}\打开数据目录.lnk"
  Delete "$SMPROGRAMS\${MENU_NAME}\卸载电梯管理系统.lnk"
  RMDir "$SMPROGRAMS\${MENU_NAME}"
  ${If} ${Errors}
    MessageBox MB_OK|MB_ICONSTOP "部分程序文件无法删除，卸载未完成。请重启主机后重试。ProgramData 台账数据仍保留。" /SD IDOK
    SetErrorLevel 4
    Abort
  ${EndIf}
  DeleteRegKey HKLM "${UNINSTALL_KEY}"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  Call un.EndMaintenance
  ${If} $0 != "0"
    MessageBox MB_OK|MB_ICONSTOP "无法清除维护标记，请重新运行安装器修复。ProgramData 台账数据仍保留。" /SD IDOK
    SetErrorLevel 7
    Abort
  ${EndIf}
  SetErrorLevel 0
SectionEnd
