# Windows 安装与日常使用

适用：Windows 10 / Windows 11 64 位主机。安装包内置 Python 3.12.10、Python 依赖和页面。桌面窗口使用 Microsoft Edge WebView2 Runtime。若提示缺少运行时，请安装后重新打开系统。无互联网的主机可由维护人员提前准备微软提供的 x64 Evergreen 独立安装程序。[微软 WebView2 下载页](https://developer.microsoft.com/microsoft-edge/webview2/#download-section)

## 安装与启动

1. 在准备作为物业台账主机的电脑上运行 `ChangfuliElevatorLedger-Setup-版本-x64.exe`，核对安装包来源和交付的 SHA256。按中文向导安装，并允许管理员授权。程序固定安装到 `C:\Program Files\ChangfuliElevatorLedger`，不需要选择目录。
2. 完成安装后，以普通用户身份双击桌面的“昌福里社区电梯管理系统”。服务就绪后会打开桌面窗口。打开后直接进入工作台。重复双击可切回现有窗口，也可能看到系统已运行的提示。
3. 手机扫码和其他电脑通过浏览器访问期间，请保持主机桌面窗口打开，可以最小化。停用前请通知各终端保存工作，然后关闭主机桌面窗口，或从开始菜单选择“停止电梯管理系统”。两种方式都会停止主机服务。

开始菜单同名文件夹内有“启动电梯管理系统”“停止电梯管理系统”“打开数据目录”“卸载电梯管理系统”。桌面仅放启动入口，图标为本产品的深色“27”和主蓝标志。

## 同机共享台账与局域网

这台电脑的 Windows 用户共同使用一套台账。数据根目录固定为 `%ProgramData%\ChangfuliElevatorLedger`，常见位置是 `C:\ProgramData\ChangfuliElevatorLedger`。该目录内的实际子目录由启动器管理，包含数据库、照片、附件、备份、导出资料与日志。请从开始菜单“打开数据目录”进入；不要把程序目录当成数据目录。

安装器给本机普通用户组授予此数据目录的继承“修改”权限，程序目录仍为普通用户只读/执行。更换 Windows 登录账号不会建立另一套空台账，各操作端可直接进入同一工作台。

安装器仅建立本产品的防火墙规则 `ChangfuliElevatorLedger.PrivateLAN.8765`：内置 `runtime\pythonw.exe`、入站 TCP 8765、专用网络、同一本地子网。它不开放公用网络或其他端口，也不自动把当前网络改成专用网络。手机访问前，需由主机管理员确认物业网络可信并按实际网络环境配置。网络能访问后，在系统设置中保存主机局域网地址，再测试手机扫码。

## 升级、卸载与保留数据

升级前先在系统内生成备份并复制到另一块可靠介质，通知工作人员保存页面。运行新安装包即可升级程序；安装器会要求旧实例安全退出。若停止失败、依赖自检失败或权限设置失败，安装器会明确报告未完成，不应当作已经升级成功。不要同时运行多份安装或卸载程序。

升级覆盖本产品程序文件，独立的数据目录会保留。卸载也会先停止后台，再移除程序、快捷方式和本产品防火墙规则；不会删除 `%ProgramData%\ChangfuliElevatorLedger`。卸载后的数据仍可能包含个人或业务资料，是否另行保留由资料负责人决定。

安装和卸载期间，数据根目录中的 `maintenance.flag` 会暂时阻止启动，防止停机后又被双击启动。正常结束、失败或取消时安装器会清除该标记；断电或强行结束安装器可能留下标记，此时重新运行安装器完成修复，不要在程序覆盖过程中自行删除标记。

早期源码版或便携版若把数据放在项目目录，安装包不会自行迁移，也不提供“一键迁移”承诺。先保留旧目录和完整备份，再由维护人员核对数据目录结构后迁移；不要为了看见旧记录而把程序装进旧数据目录。

## 手工恢复三步

1. 从开始菜单停止系统，确认停止成功，再选择“打开数据目录”。把现有 `data` 和 `storage` 两个文件夹整体移到另一处安全位置，留作回退；不要只移动数据库主文件，否则可能混入旧的数据库临时文件。
2. 将确认完整、同一批次的系统备份解压到临时目录，核对其中数据库、照片和附件。把备份中的 `data` 和 `storage` 文件夹放入刚打开的数据目录，保持 `data\elevator.db` 和 `storage\...` 的层级；不要只恢复数据库而漏掉附件。
3. 用桌面入口启动，直接打开工作台，抽查电梯记录、照片和已保存文稿，并生成一份 Word 验证。更换电脑后，在系统设置中设置新的局域网地址，重新生成二维码。确认恢复正确前不要删除步骤 1 的回退资料。结构不清楚时保留两份资料并请维护人员核对，不直接混合覆盖不同日期的文件。

## 维护人员：离线重建安装包

构建机需要 Python（含 pip）和 NSIS 3。以下命令在项目根目录执行；只使用指定 ZIP、现有锁定依赖和本地 wheelhouse，不会从网络下载运行依赖。

```text
python3 scripts/build_windows_installer.py --python-zip outputs/windows-installer-20261029/downloads/python-3.12.10-embed-amd64.zip --output-dir outputs/windows-installer-20261029/build --version 1.1.0
```

如果 `makensis` 不在 PATH，增加 `--makensis /opt/homebrew/bin/makensis`（macOS 示例）或 Windows 上 `makensis.exe` 的实际路径。只准备独立运行目录可增加 `--stage-only`；这用于维护验收，不是另外交付一份便携安装流程。

前置文件：已构建的 `frontend/dist`、`scripts/windows_launcher.py`、`scripts/windows-app.ico`、`requirements.lock.txt` 与完整 Windows Python 3.12 wheelhouse。官方 Python ZIP 的 SHA256 固定为 `4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3`，不匹配会拒绝构建。

构建输出包括 ASCII 文件名的安装 EXE、`.exe.sha256` 和 `stage/BUILD-MANIFEST.json`。清单记录输入和每个程序文件的哈希；内置运行目录只带后端代码、启动器、已构建前端、固定依赖与许可证，不带业务数据库、测试数据、开发虚拟环境或 node_modules。依赖许可保留在 `licenses` 及 `runtime/Lib/site-packages/*.dist-info`。

`runtime/python312._pth` 显式列出 `python312.zip`、`.`、`Lib/site-packages`、`..` 并启用 `import site`。启动、停止和自检都调用安装包自身的 Python，不读取用户安装的 Python。

发布前应在实际 Windows x64 主机验证首次安装、普通用户启动、跨用户同一套数据、带运行实例升级、安全停止失败阻断及卸载保留数据。桌面窗口请核对标题和图标，测试重复启动、文件下载、二维码打印与手机访问，再分别用关闭窗口和开始菜单停止服务，确认手机断开且主机可重新启动。记录实际测试系统与边界，Windows 11 ARM 的 x64 模拟运行需单独验收。

## 可选的首次建账

默认构建只随附程序。制作内部安装包时，在上面的构建命令追加 `--seed-ledger /绝对路径/official-ledger.xlsx`。构建脚本会把指定文件复制到 `stage/seed/official-ledger.xlsx` 并计入构建清单。请将带表格的 stage 和安装包保留在内部交付位置。升级会替换程序目录中的随包副本，请单独保存原表。

主机服务启动时，系统只在电梯表为空且尚无导入成功标记时尝试建账。依次查找环境变量 `ELEVATOR_SEED_LEDGER` 指定的绝对路径、程序目录下的 `seed/official-ledger.xlsx`、数据目录下的 `seed/official-ledger.xlsx`，采用第一个存在的文件。缺少文件时正常启动。结果见日志目录的 `seed-import-report.json`，其中列出新增、跳过、重复编号及待核对位置。失败时本次导入整体回滚，修正后可重新启动主机服务重试。成功后系统保存 `official_ledger_imported` 标记，后续补录请使用“导入档案”。
