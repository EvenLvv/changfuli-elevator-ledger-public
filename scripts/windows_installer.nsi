Unicode true
RequestExecutionLevel admin
ManifestDPIAware true
ManifestSupportedOS all
SetCompressor /SOLID lzma
SetDatablockOptimize on

!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"
!include "x64.nsh"
!include "WinVer.nsh"

!ifndef STAGE_DIR
  !error "Pass -DSTAGE_DIR=<prepared payload directory>"
!endif
!ifndef OUT_FILE
  !error "Pass -DOUT_FILE=<installer.exe>"
!endif
!ifndef APP_VERSION
  !define APP_VERSION "2.0.3"
!endif
!ifndef PAYLOAD_KB
  !define PAYLOAD_KB 0
!endif
!define APP_ID "ChangfuliElevatorDesktop"
!define LEGACY_APP_ID "ChangfuliElevatorLedger"
!define APP_NAME "昌福里社区电梯管理系统"
!define MENU_NAME "昌福里社区电梯管理系统"
!define ICON_FILE "desktop-app-2.0.ico"
!define PNG_ICON_FILE "desktop-app-2.0.png"
!define UNINSTALL_KEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_ID}"
!define FIREWALL_RULE "ChangfuliElevatorDesktop.PrivateLAN.8766"

Name "${APP_NAME}"
OutFile "${OUT_FILE}"
InstallDir "$PROGRAMFILES64\${APP_ID}"
InstallDirRegKey HKLM "${UNINSTALL_KEY}" "InstallLocation"
Icon "${ICON_FILE}"
UninstallIcon "${ICON_FILE}"
BrandingText "昌福里社区27区党群物业服务站 · ${APP_VERSION}"
ShowInstDetails show
ShowUninstDetails show
VIProductVersion "${APP_VERSION}.0"
VIAddVersionKey /LANG=2052 "ProductName" "${APP_NAME}"
VIAddVersionKey /LANG=2052 "ProductVersion" "${APP_VERSION}"
VIAddVersionKey /LANG=2052 "FileVersion" "${APP_VERSION}"
VIAddVersionKey /LANG=2052 "FileDescription" "${APP_NAME}安装程序"
VIAddVersionKey /LANG=2052 "LegalCopyright" "昌福里社区27区党群物业服务站"

!define MUI_ABORTWARNING
!define MUI_CUSTOMFUNCTION_ABORT InstallerAbort
!define MUI_CUSTOMFUNCTION_UNABORT un.InstallerAbort
!define MUI_WELCOMEPAGE_TEXT "本向导将在本机安装“${APP_NAME}”（独立桌面版，保留 1.x 旧版程序和数据）。$\r$\n$\r$\n下一步可自行选择程序安装目录。台账数据库、现场照片、导出文稿、备份及 WebView2 缓存统一保存在当前登录用户的本地数据目录（%LOCALAPPDATA%\${APP_ID}），与程序目录分离，升级和卸载均保留业务资料。$\r$\n$\r$\n安装需要管理员授权，日常使用无需管理员权限。"
!define MUI_DIRECTORYPAGE_TEXT_TOP "请选择“${APP_NAME}”的程序安装文件夹。程序文件仅写入下方所选目录；台账数据库与附件资料会在用户启动应用时保存在 %LOCALAPPDATA%\${APP_ID}，不会写入程序目录。"
!define MUI_FINISHPAGE_TEXT "“${APP_NAME}”已安装完成。$\r$\n$\r$\n请以日常使用的普通用户身份双击桌面“${APP_NAME}”，打开桌面窗口后即可直接进入免登录工作台。若本机存有 1.x 旧版台账，首次启动会在当前用户数据目录安全复制旧台账，且不改动旧版目录。$\r$\n$\r$\n关闭主机桌面窗口会停止服务（端口 8766）；局域网访问期间请保持窗口打开。打开数据目录、停止系统与卸载入口位于开始菜单“${MENU_NAME}”。"
!define MUI_UNCONFIRMPAGE_TEXT_TOP "卸载将停止本机正在运行的服务，并仅移除当前安装目录中的程序文件、快捷方式及 8766 防火墙规则。用户数据目录（%LOCALAPPDATA%\${APP_ID}）中的台账、附件、备份以及旧版 1.x 目录均会完整保留。"

!insertmacro MUI_PAGE_WELCOME
!define MUI_PAGE_CUSTOMFUNCTION_LEAVE ValidateInstallDirPage
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "SimpChinese"

Var MaintenanceOwned
Var MaintenanceHandle
Var InstallerMutex

Function HasCmdLineDirOverride
  StrCpy $1 0
  StrLen $2 $CMDLINE
  loop_cmdline:
    IntCmp $1 $2 no_override 0 no_override
    StrCpy $3 $CMDLINE 3 $1
    ${If} $3 == "/D="
      Push "1"
      Return
    ${EndIf}
    IntOp $1 $1 + 1
    Goto loop_cmdline
  no_override:
    Push "0"
FunctionEnd

Function .onInit
  SetShellVarContext all
  SetRegView 64
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
  Call HasCmdLineDirOverride
  Pop $1
  ${If} $1 == "0"
    ReadRegStr $0 HKLM "${UNINSTALL_KEY}" "InstallLocation"
    ${If} $0 != ""
      StrCpy $INSTDIR $0
    ${EndIf}
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
    MessageBox MB_OK|MB_ICONSTOP "另一份本产品的安装或卸载程序正在运行。请先完成并关闭该窗口，再重试。" /SD IDOK
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

!macro InstDirGuard PREFIX
Function ${PREFIX}CheckInstDirSafe
  ; Returns "ok" on top of stack, or a Chinese error reason.
  StrLen $0 "$INSTDIR"
  ${If} $0 <= 3
    Push "安装目录不能为磁盘根目录或空路径，请选择独立的程序文件夹。"
    Return
  ${EndIf}
  StrCpy $1 "$INSTDIR" 2 1
  ${If} $1 != ":\"
    Push "请选择本机磁盘上的普通文件夹作为安装目录（例如 C:\Program Files\${APP_ID} 或 D:\${APP_ID}）。"
    Return
  ${EndIf}
  ${If} "$INSTDIR" == "$WINDIR"
  ${OrIf} "$INSTDIR" == "$SYSDIR"
  ${OrIf} "$INSTDIR" == "$PROGRAMFILES64"
  ${OrIf} "$INSTDIR" == "$PROGRAMFILES32"
  ${OrIf} "$INSTDIR" == "$APPDATA"
  ${OrIf} "$INSTDIR" == "$LOCALAPPDATA"
    Push "不能直接安装到系统根目录或公共应用数据根目录，请选择独立的子文件夹。"
    Return
  ${EndIf}
  ${If} "$INSTDIR" == "$PROGRAMFILES64\${LEGACY_APP_ID}"
  ${OrIf} "$INSTDIR" == "$APPDATA\${LEGACY_APP_ID}"
    Push "不能覆盖 1.x 旧版目录（${LEGACY_APP_ID}），请选择独立的安装文件夹。"
    Return
  ${EndIf}
  ${If} "$INSTDIR" == "$APPDATA\${APP_ID}"
  ${OrIf} "$INSTDIR" == "$LOCALAPPDATA\${APP_ID}"
    Push "程序安装目录不能与用户数据目录重合，请选择其他程序文件夹。"
    Return
  ${EndIf}
  System::Call 'kernel32::GetFileAttributesW(w "$INSTDIR") i.r0 ?e'
  Pop $1
  ${If} $0 == -1
    ${If} $1 == 2
    ${OrIf} $1 == 3
      Push "ok"
      Return
    ${EndIf}
    Push "所选安装目录无法安全读取，请检查路径与磁盘状态后重试。"
    Return
  ${EndIf}
  IntOp $1 $0 & 0x400
  ${If} $1 != 0
    Push "所选安装目录包含符号链接或重解析点，出于安全保护已拒绝写入。"
    Return
  ${EndIf}
  IntOp $1 $0 & 0x10
  ${If} $1 == 0
    Push "所选安装路径是文件而非文件夹，请重新选择普通文件夹。"
    Return
  ${EndIf}
  System::Call 'shlwapi::PathIsDirectoryEmptyW(w "$INSTDIR") i.r0'
  ${If} $0 != 0
    Push "ok"
    Return
  ${EndIf}
  ; 1.x also ships Uninstall.exe, a manifest and a launcher. Require the
  ; registered 2.x location and its desktop icon before removing program files.
  ReadRegStr $0 HKLM "${UNINSTALL_KEY}" "InstallLocation"
  ${If} $0 == "$INSTDIR"
  ${AndIf} ${FileExists} "$INSTDIR\${ICON_FILE}"
  ${AndIf} ${FileExists} "$INSTDIR\Uninstall.exe"
    Push "ok"
    Return
  ${EndIf}
  Push "无法确认所选文件夹是本产品的 2.x 安装目录。请选择空的专用文件夹，或选择原有的 2.x 安装目录进行升级。"
FunctionEnd

Function ${PREFIX}ValidateInstDir
  Call ${PREFIX}CheckInstDirSafe
  Pop $0
  ${If} $0 != "ok"
    MessageBox MB_OK|MB_ICONSTOP "$0" /SD IDOK
    SetErrorLevel 9
    Abort
  ${EndIf}
FunctionEnd
!macroend
!insertmacro InstDirGuard ""
!insertmacro InstDirGuard "un."

Function ValidateInstallDirPage
  Call CheckInstDirSafe
  Pop $0
  ${If} $0 != "ok"
    MessageBox MB_OK|MB_ICONEXCLAMATION "$0" /SD IDOK
    Abort
  ${EndIf}
FunctionEnd

Function StopCandidate
  DetailPrint "正在安全停止本机电梯管理系统…"
  nsExec::ExecToStack /TIMEOUT=60000 '"$PLUGINSDIR\payload\runtime\python.exe" "$PLUGINSDIR\payload\scripts\windows_launcher.py" --stop --all-users --quiet'
  Pop $0
  Pop $1
  ${If} $0 != "0"
    MessageBox MB_OK|MB_ICONSTOP "无法安全停止正在运行的实例，安装未覆盖程序。请等待工作人员保存并关闭桌面窗口，或重启主机后重试。$\r$\n返回码：$0$\r$\n$1" /SD IDOK
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
    nsExec::ExecToStack /TIMEOUT=60000 '"$INSTDIR\runtime\python.exe" "$INSTDIR\scripts\windows_launcher.py" --stop --all-users --quiet'
    Pop $0
    Pop $1
    StrCmp $0 "0" stop_done
    MessageBox MB_OK|MB_ICONSTOP "无法安全停止正在运行的实例，操作已取消，程序和用户台账未被改动。$\r$\n请先关闭桌面窗口后重试。$\r$\n返回码：$0$\r$\n$1" /SD IDOK
    SetErrorLevel 2
    Abort
  stop_damaged:
    MessageBox MB_OK|MB_ICONSTOP "现有程序的启动器或内置运行环境不完整，无法确认实例已经停止。请联系维护人员修复后重试；用户数据目录保持不变。" /SD IDOK
    SetErrorLevel 2
    Abort
  stop_done:
FunctionEnd
!macroend
!insertmacro StopInstalled "un."

!macro MaintenanceFunctions PREFIX
Function ${PREFIX}BeginMaintenance
  Call ${PREFIX}ValidateInstDir
  ClearErrors
  CreateDirectory "$INSTDIR"
  ${If} ${Errors}
    MessageBox MB_OK|MB_ICONSTOP "无法创建或写入所选程序目录，请检查文件夹权限或更换安装路径。" /SD IDOK
    SetErrorLevel 4
    Abort
  ${EndIf}
  Call ${PREFIX}ValidateInstDir
  ; Create without truncation; keep the validated file open without delete sharing.
  System::Call 'kernel32::CreateFileW(w "$INSTDIR\maintenance.flag", i 0x10080, i 3, p 0, i 1, i 0x02200080, p 0) p.r0 ?e'
  Pop $1
  ${If} $0 == -1
    ${If} $1 != 80
    ${AndIf} $1 != 183
      Goto maintenance_invalid
    ${EndIf}
    System::Call 'kernel32::CreateFileW(w "$INSTDIR\maintenance.flag", i 0x10080, i 3, p 0, i 3, i 0x02200080, p 0) p.r0'
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
    MessageBox MB_OK|MB_ICONSTOP "无法安全锁定程序目录的维护状态，请检查所选安装目录是否可写，以及 maintenance.flag 是否为普通文件。" /SD IDOK
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

; Only 2.0 program-owned paths in INSTDIR are removed; per-user data and 1.x directories are never touched.
!macro RemoveProgramFiles
  IfFileExists "$INSTDIR\seed\official-ledger.xlsx" 0 +2
  Delete "$INSTDIR\seed\official-ledger.xlsx"
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
  IfFileExists "$INSTDIR\${ICON_FILE}" 0 +2
  Delete "$INSTDIR\${ICON_FILE}"
  IfFileExists "$INSTDIR\${PNG_ICON_FILE}" 0 +2
  Delete "$INSTDIR\${PNG_ICON_FILE}"
!macroend

!macro RemoveShortcuts SUFFIX
  IfFileExists "$DESKTOP\${APP_NAME}${SUFFIX}.lnk" 0 +2
  Delete "$DESKTOP\${APP_NAME}${SUFFIX}.lnk"
  IfFileExists "$SMPROGRAMS\${MENU_NAME}${SUFFIX}\启动电梯管理系统${SUFFIX}.lnk" 0 +2
  Delete "$SMPROGRAMS\${MENU_NAME}${SUFFIX}\启动电梯管理系统${SUFFIX}.lnk"
  IfFileExists "$SMPROGRAMS\${MENU_NAME}${SUFFIX}\停止电梯管理系统${SUFFIX}.lnk" 0 +2
  Delete "$SMPROGRAMS\${MENU_NAME}${SUFFIX}\停止电梯管理系统${SUFFIX}.lnk"
  IfFileExists "$SMPROGRAMS\${MENU_NAME}${SUFFIX}\打开数据目录${SUFFIX}.lnk" 0 +2
  Delete "$SMPROGRAMS\${MENU_NAME}${SUFFIX}\打开数据目录${SUFFIX}.lnk"
  IfFileExists "$SMPROGRAMS\${MENU_NAME}${SUFFIX}\卸载电梯管理系统${SUFFIX}.lnk" 0 +2
  Delete "$SMPROGRAMS\${MENU_NAME}${SUFFIX}\卸载电梯管理系统${SUFFIX}.lnk"
  ${IfNot} ${Errors}
    ${DirState} "$SMPROGRAMS\${MENU_NAME}${SUFFIX}" $0
    ClearErrors
    ${If} $0 == 0
      RMDir "$SMPROGRAMS\${MENU_NAME}${SUFFIX}"
    ${EndIf}
  ${EndIf}
!macroend

Section "安装主程序" SEC_MAIN
  Call ValidateInstDir
  InitPluginsDir
  SetOutPath "$PLUGINSDIR\payload"
  File /r "${STAGE_DIR}/*"
  DetailPrint "正在检查安装包内置 Python、依赖与页面资源…"
  nsExec::ExecToStack /TIMEOUT=60000 '"$PLUGINSDIR\payload\runtime\python.exe" "$PLUGINSDIR\payload\scripts\windows_launcher.py" --check --quiet'
  Pop $0
  Pop $1
  ${If} $0 != "0"
    MessageBox MB_OK|MB_ICONSTOP "安装包自检未通过，尚未写入程序目录。请重新获取完整安装包。$\r$\n返回码：$0$\r$\n$1" /SD IDOK
    SetErrorLevel 3
    Abort
  ${EndIf}

  Call BeginMaintenance
  Call StopCandidate
  ClearErrors
  !insertmacro RemoveProgramFiles
  ${If} ${Errors}
    MessageBox MB_OK|MB_ICONSTOP "目标目录中的程序文件仍被占用，安装已停止。请关闭窗口或重启主机后重试。用户台账数据未被删除。" /SD IDOK
    SetErrorLevel 4
    Abort
  ${EndIf}
  SetOutPath "$INSTDIR"
  ClearErrors
  CopyFiles /SILENT "$PLUGINSDIR\payload\*" "$INSTDIR"
  ${If} ${Errors}
    MessageBox MB_OK|MB_ICONSTOP "无法写入所选程序目录，安装未完成。请检查磁盘空间与目录权限后重试。用户台账数据未被删除。" /SD IDOK
    SetErrorLevel 4
    Abort
  ${EndIf}

  nsExec::ExecToStack /TIMEOUT=60000 '"$INSTDIR\runtime\python.exe" "$INSTDIR\scripts\windows_launcher.py" --check --quiet'
  Pop $0
  Pop $1
  ${If} $0 != "0"
    MessageBox MB_OK|MB_ICONSTOP "已安装程序自检失败，不能开始使用。请重新安装或联系维护人员。用户台账数据会保留。$\r$\n返回码：$0$\r$\n$1" /SD IDOK
    SetErrorLevel 3
    Abort
  ${EndIf}

  ; Replace only this 2.0 product's named rule on TCP 8766; public networks and 1.x rules stay untouched.
  nsExec::ExecToLog '"$SYSDIR\netsh.exe" advfirewall firewall delete rule name="${FIREWALL_RULE}"'
  Pop $0
  nsExec::ExecToStack /TIMEOUT=60000 '"$SYSDIR\netsh.exe" advfirewall firewall add rule name="${FIREWALL_RULE}" dir=in action=allow protocol=TCP localport=8766 program="$INSTDIR\runtime\pythonw.exe" profile=private remoteip=localsubnet enable=yes'
  Pop $0
  Pop $1
  ${If} $0 != "0"
    MessageBox MB_OK|MB_ICONSTOP "无法配置本地子网访问规则（TCP 8766），安装未完成。请联系主机管理员检查防火墙策略。$\r$\n返回码：$0$\r$\n$1" /SD IDOK
    SetErrorLevel 6
    Abort
  ${EndIf}

  ClearErrors
  !insertmacro RemoveShortcuts " 2.0"
  !insertmacro RemoveShortcuts ""
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateDirectory "$SMPROGRAMS\${MENU_NAME}"
  CreateShortcut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\runtime\pythonw.exe" '$\"$INSTDIR\scripts\windows_launcher.py$\"' "$INSTDIR\${ICON_FILE}"
  CreateShortcut "$SMPROGRAMS\${MENU_NAME}\启动电梯管理系统.lnk" "$INSTDIR\runtime\pythonw.exe" '$\"$INSTDIR\scripts\windows_launcher.py$\"' "$INSTDIR\${ICON_FILE}"
  CreateShortcut "$SMPROGRAMS\${MENU_NAME}\停止电梯管理系统.lnk" "$INSTDIR\runtime\pythonw.exe" '$\"$INSTDIR\scripts\windows_launcher.py$\" --stop' "$INSTDIR\${ICON_FILE}"
  CreateShortcut "$SMPROGRAMS\${MENU_NAME}\打开数据目录.lnk" "$INSTDIR\runtime\pythonw.exe" '$\"$INSTDIR\scripts\windows_launcher.py$\" --data-folder' "$INSTDIR\${ICON_FILE}"
  CreateShortcut "$SMPROGRAMS\${MENU_NAME}\卸载电梯管理系统.lnk" "$INSTDIR\Uninstall.exe" "" "$INSTDIR\${ICON_FILE}"
  WriteRegStr HKLM "${UNINSTALL_KEY}" "DisplayName" "${APP_NAME}"
  WriteRegStr HKLM "${UNINSTALL_KEY}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKLM "${UNINSTALL_KEY}" "Publisher" "昌福里社区27区党群物业服务站"
  WriteRegStr HKLM "${UNINSTALL_KEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "${UNINSTALL_KEY}" "DisplayIcon" "$INSTDIR\${ICON_FILE}"
  WriteRegStr HKLM "${UNINSTALL_KEY}" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
  WriteRegStr HKLM "${UNINSTALL_KEY}" "QuietUninstallString" '$\"$INSTDIR\Uninstall.exe$\" /S'
  WriteRegStr HKLM "${UNINSTALL_KEY}" "AppUserModelID" "${APP_ID}"
  WriteRegDWORD HKLM "${UNINSTALL_KEY}" "EstimatedSize" ${PAYLOAD_KB}
  WriteRegDWORD HKLM "${UNINSTALL_KEY}" "NoModify" 1
  WriteRegDWORD HKLM "${UNINSTALL_KEY}" "NoRepair" 1
  ${If} ${Errors}
    MessageBox MB_OK|MB_ICONSTOP "无法登记程序或创建完整快捷方式，安装未完成。请检查主机权限并重新安装。用户台账数据会保留。" /SD IDOK
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
  ReadRegStr $0 HKLM "${UNINSTALL_KEY}" "InstallLocation"
  ${If} $0 == ""
  ${OrIf} "$INSTDIR" != "$0"
    MessageBox MB_OK|MB_ICONSTOP "卸载器位置与已登记的程序安装目录不一致，已停止操作。请从 Windows“已安装的应用”中卸载“${APP_NAME}”。" /SD IDOK
    SetErrorLevel 2
    Quit
  ${EndIf}
  ${If} "$INSTDIR" == "$PROGRAMFILES64\${LEGACY_APP_ID}"
  ${OrIf} "$INSTDIR" == "$APPDATA\${LEGACY_APP_ID}"
    MessageBox MB_OK|MB_ICONSTOP "检测到旧版 1.x 目录路径，卸载器不会改动旧版文件，操作已停止。" /SD IDOK
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
  !insertmacro RemoveShortcuts " 2.0"
  !insertmacro RemoveShortcuts ""
  ${If} ${Errors}
    MessageBox MB_OK|MB_ICONSTOP "部分程序文件无法删除，卸载未完成。请重启主机后重试。用户本地数据目录中的台账资料仍保留。" /SD IDOK
    SetErrorLevel 4
    Abort
  ${EndIf}
  DeleteRegKey HKLM "${UNINSTALL_KEY}"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR\seed"
  Call un.EndMaintenance
  ${If} $0 != "0"
    MessageBox MB_OK|MB_ICONSTOP "无法清除维护标记，请重新运行安装器修复。用户本地数据目录中的台账资料仍保留。" /SD IDOK
    SetErrorLevel 7
    Abort
  ${EndIf}
  RMDir "$INSTDIR"
  SetErrorLevel 0
SectionEnd
