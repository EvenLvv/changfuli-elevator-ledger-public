# Windows 安装与日常使用（2.0.2）

适用：Windows 10 / Windows 11 64 位主机。安装包内置 Python 3.12.10、Python 依赖和已构建页面，默认作为空台账桌面软件交付，不随包预置正式业务台账表格。桌面窗口使用 Microsoft Edge WebView2 Runtime。若提示缺少运行时，请安装后重新打开系统，程序不会回退系统浏览器。无互联网的主机可由维护人员提前准备微软提供的 x64 Evergreen 独立安装程序。[微软 WebView2 下载页](https://developer.microsoft.com/microsoft-edge/webview2/#download-section)

## 安装与启动

1. 在准备作为物业台账主机的电脑上运行 `ChangfuliElevatorDesktop-Setup-2.0.2-x64.exe`，核对安装包来源和交付的 SHA256。按中文向导安装并允许管理员授权。向导支持自由选择程序安装目录（默认 `C:\Program Files\ChangfuliElevatorDesktop`）；程序目录必须为本机磁盘上的普通文件夹，不可选磁盘根目录、系统目录、旧版 1.x 目录或数据目录。
2. 安装完成后，请以日常使用的普通用户身份双击桌面“昌福里社区电梯管理系统 2.0”。服务就绪后会打开标题为“昌福里社区电梯管理系统 2.0.2”的桌面窗口，无需登录即可直接进入工作台。重复双击会切回已运行的 2.0 桌面窗口，不会连接或唤醒旧版 1.x 实例。
3. 手机扫码和其他电脑通过浏览器访问期间，请保持主机桌面窗口打开，可以最小化。停用前请通知各终端保存工作，然后关闭主机桌面窗口，或从开始菜单“昌福里社区电梯管理系统 2.0”选择“停止电梯管理系统 2.0”。两种方式都会安全停止主机 2.0 服务。

开始菜单“昌福里社区电梯管理系统 2.0”文件夹内提供“启动电梯管理系统 2.0”“停止电梯管理系统 2.0”“打开数据目录 2.0”“卸载电梯管理系统 2.0”，名称独立于 1.x，不会覆盖旧版快捷方式。图标采用与初代 `scripts/windows-app.ico` 一致的白底深色“27”与蓝色竖线标志（`desktop-app-2.0.ico` / `desktop-app-2.0.png`）。

## 程序与数据分离及局域网访问

程序文件仅存放在安装时所选的程序目录（`INSTDIR`）。台账数据库、现场照片、导出文稿、备份、日志、运行状态锁（`desktop-instance-v2.lock` / `desktop-instance-v2.json`）及 WebView2 用户数据目录（`WebView2\`）均保存在当前登录用户的本地数据目录 `%LOCALAPPDATA%\ChangfuliElevatorDesktop`（常见位置如 `C:\Users\当前用户名\AppData\Local\ChangfuliElevatorDesktop`），绝不写入程序目录。

安装过程以管理员权限运行，安装阶段不会在提权管理员的 `LocalAppData` 下提前建立业务数据库；数据根目录在日常用户启动应用时按当前交互账户解析创建。请从开始菜单“打开数据目录 2.0”（调用 `windows_launcher.py --data-folder`）直接打开当前用户正在使用的数据根目录。

2.0 默认使用 TCP `8766` 端口（避免与遗留 1.x 的 `8765` 端口冲突）。安装器仅建立本产品的防火墙规则 `ChangfuliElevatorDesktop.PrivateLAN.8766`：指向所选安装目录下的 `runtime\pythonw.exe`、入站 TCP 8766、专用网络、同一本地子网。它不开放公用网络或其他端口，也不改动旧版规则。手机访问前，需由主机管理员确认物业网络可信并设为专用网络，随后在网页“系统设置 → 局域网访问与二维码”保存 `http://主机IPv4:8766` 并测试手机扫码。

## 1.x 旧版资料自动安全复制与升级卸载

启动 2.0 且当前用户 `%LOCALAPPDATA%\ChangfuliElevatorDesktop\data\elevator.db` 尚不存在或电梯表为空时，启动器会依次检查 `%PROGRAMDATA%\ChangfuliElevatorLedger`、`%LOCALAPPDATA%\ChangfuliElevatorLedger` 与 `%APPDATA%\ChangfuliElevatorLedger`（优先采用含在册电梯的旧版数据库），将旧版目录中的 `data`、`storage`、`exports`、`backups` 安全复制到 2.0 用户数据目录，并在 2.0 数据根目录写入 `migration-from-v1.json` 迁移记录：

- 仅执行只读复制，**不移动、不删除**任何 1.x 旧版目录中的文件。
- 若 2.0 用户数据目录中已经存在包含电梯的 `data\elevator.db`，则绝不会再次复制或覆盖现有 2.0 数据库，旧目录保持原样。
- 若复制后的 1.x 数据库电梯表为空且实际存在初始建账表格，后续仍会继续执行初始台账导入；无初始表格时保持正常空工作台状态。
- 若旧版曾保存 `:8765` 的二维码地址，请在 2.0“系统设置 → 局域网访问与二维码”中更新为 `:8766` 后再重印二维码。

升级 2.0 时，向导会从 2.0 专属注册表项自动带出上次选择的安装目录（也可重新指定），先安全停止本机 2.0 实例再更新程序文件，保留 `%LOCALAPPDATA%\ChangfuliElevatorDesktop` 中的全部业务资料。卸载 2.0 只移除当前 2.0 程序目录、2.0 快捷方式和 8766 防火墙规则，**不会删除用户本地数据目录，也不会删除 1.x 程序目录或 `ProgramData\ChangfuliElevatorLedger`**。

安装和卸载期间，程序目录中的句柄锁文件 `maintenance.flag` 会暂时阻止启动，正常结束、失败或取消时自动清除；若异常断电残留该标记，重新运行安装器即可恢复。

## 手工恢复三步

1. 关闭 2.0 桌面窗口（或从开始菜单选择“停止电梯管理系统 2.0”），确认停止成功后选择“打开数据目录 2.0”。把现有 `data` 和 `storage` 两个文件夹整体移到另一处安全位置留作回退；不要只移动数据库主文件，以免混入旧的 `-wal` / `-shm` 临时文件。
2. 将确认完整、同一批次的系统备份解压到临时目录，核对其中数据库、照片和附件。把备份中的 `data` 和 `storage` 文件夹放入刚打开的数据目录，保持 `data\elevator.db` 和 `storage\...` 的层级；不要只恢复数据库而漏掉附件。
3. 双击桌面“昌福里社区电梯管理系统 2.0”启动，抽查电梯记录、照片和已保存文稿，并生成一份 Word 验证。更换电脑后，在系统设置中保存新的 `:8766` 局域网地址并重新生成二维码。确认恢复无误前不要删除步骤 1 的回退资料。

## 维护人员：离线重建安装包

构建机需要 Python（含 pip）和 NSIS 3。以下命令在项目根目录执行；只使用指定 ZIP、现有锁定依赖和本地 wheelhouse，不会从网络下载运行依赖。

```text
.venv/bin/python scripts/build_windows_installer.py --python-zip outputs/windows-installer-20261029/downloads/python-3.12.10-embed-amd64.zip --output-dir outputs/windows-installer --version 2.0.2
```

如果 `makensis` 不在 PATH，增加 `--makensis /path/to/makensis`。只准备独立运行目录可增加 `--stage-only`。

前置文件：已构建的 `frontend/dist`、`scripts/windows_launcher.py`、`scripts/desktop-app-2.0.ico`、`scripts/desktop-app-2.0.png`、`requirements.lock.txt` 与完整 Windows Python 3.12 wheelhouse。官方 Python ZIP 的 SHA256 固定为 `4acbed6dd1c744b0376e3b1cf57ce906f9dc9e95e68824584c8099a63025a3c3`，不匹配会拒绝构建。

构建输出为 `ChangfuliElevatorDesktop-Setup-2.0.2-x64.exe`、`.exe.sha256` 和 `stage/BUILD-MANIFEST.json`。内置运行目录只包含后端代码、启动器、已构建前端、2.0 图标、固定依赖与许可证，不包含业务数据库、预置台账表格、测试数据、虚拟环境或 `node_modules`。

发布前应在实际 Windows x64 主机完成现场验收：自定义目录安装、普通用户启动（确认窗口标题含 2.0.2 且免登录）、`%LOCALAPPDATA%\ChangfuliElevatorDesktop` 数据分离、1.x 旧数据安全复制保留原目录、与 1.x 共存互不干扰、局域网 8766 访问与扫码、关闭窗口停服，以及卸载保留数据与旧版目录。Windows 11 ARM 的 x64 模拟运行需单独验收。

## 可选的首次建账

默认构建只随附空程序，不传递 `--seed-ledger`，也不向安装包拷贝任何 `.xlsx` 台账；未放置初始表格时首页和“电梯档案”作为普通空工作台运行，不提示警告横幅。若特定场景显式传递 `--seed-ledger /绝对路径/official-ledger.xlsx` 或在本地配置 `ELEVATOR_SEED_LEDGER` / `seed/official-ledger.xlsx`，带表格的构建物不得提交至源码仓库。

安装版启动器仅在检测到实际存在的初始表格文件时设置 `ELEVATOR_SEED_LEDGER`。主机服务启动时，仅当初始表格文件存在且数据库电梯表为空时尝试自动建账；当至少存在一部电梯或不存在初始表格时自动跳过。存在初始表格时，导入结果写入日志目录的 `seed-import-report.json`，成功后写入 `official_ledger_imported` 标记并在首页和“电梯档案”页展示导入数量，失败时整批回滚且提示查看报告，重新启动即可重试。
