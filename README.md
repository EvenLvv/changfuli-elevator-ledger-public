# 昌福里社区电梯管理系统

供物业站在一台 Windows 10 / 11 主机上运行，其他电脑或手机通过同一局域网的浏览器访问。记录一梯一档、维保故障维修和配件更换，集中保存照片附件，并导出 Word 工作档案或完整 ZIP 包。

## Windows 安装版（版本 2.0.3）

安装 `ChangfuliElevatorDesktop-Setup-2.0.3-x64.exe` 时可自行选择程序安装目录（保留 1.x 旧版程序和数据）。安装完成后，双击桌面“昌福里社区电梯管理系统”即可打开主机桌面窗口（窗口标题显示 `昌福里社区电梯管理系统`），无需登录直接进入空工作台，在“电梯档案”中新增或批量导入资料即可开始使用。安装包内置 Python 和页面，默认不预置业务台账表格；桌面窗口需要 Microsoft Edge WebView2 Runtime。其他电脑或手机访问台账期间，请保持主机桌面窗口打开；关闭桌面窗口会安全停止主机服务。

安装、自定义目录、1.x 旧数据自动复制、停止、升级和换电脑步骤见 [Windows 安装版使用说明](docs/WINDOWS_INSTALLER.md)。安装版将业务数据库、附件、导出、备份、日志与 WebView2 缓存保存在当前登录用户的 `%LOCALAPPDATA%\ChangfuliElevatorDesktop`，与程序目录完全分离；当本版尚无数据库或电梯表为空时，会依次在 `%PROGRAMDATA%\ChangfuliElevatorLedger`、`%LOCALAPPDATA%\ChangfuliElevatorLedger` 和 `%APPDATA%\ChangfuliElevatorLedger` 查找旧版台账并只读安全复制（保留原目录不删除）。卸载程序保留业务资料。下文 BAT 和开发命令仅适用于源码版。

## 技术栈

- 前端：Vue 3、TypeScript、Vite、Element Plus。正式运行时由后端提供已构建的静态文件，不需要持续运行 Node。
- 后端：Python、FastAPI。
- 数据：SQLite，由后端统一访问；照片和附件保存在主机文件夹。
- 文档：python-docx；二维码：qrcode；Excel：openpyxl，基础档案支持模板导入和按范围导出，工作附件保留原文件。

## 启动

源码版先按 [INSTALL.md](INSTALL.md) 安装，然后在 Windows 主机双击 `启动电梯管理系统.bat`。浏览器打开 `http://127.0.0.1:8766`。主机和同网设备均直接进入工作台，可编辑同一套台账。仅向可信的物业站内网开放服务。

软件默认以空台账交付；若显式配置了可选的初始表格文件，空台账启动时可自动一次建账，失败会回滚并可在修正后重试。详情见 [首次建账说明](docs/WINDOWS_INSTALLER.md#可选的首次建账)。

“工作记录”按上海日期倒序展示工作与系统操作，可从日历选日期，再按电梯或类型筛选。

开发环境：

```bash
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt -c requirements.lock.txt
cd frontend && npm ci && npm run build
cd .. && .venv/Scripts/python scripts/run.py
```

macOS/Linux 第一步使用 `python3 -m venv .venv`，并把 `.venv/Scripts/python` 换成 `.venv/bin/python`。Windows 正式交付使用 Python 3.12 64位版本；`wheelhouse` 中的 Windows 依赖不能用于 macOS。开发时也可在 `frontend` 运行 `npm run dev`，API 代理到本机 8766 端口。

## 数据位置

以下为数据根目录内的相对路径。EXE 安装版位于 `%LOCALAPPDATA%\ChangfuliElevatorDesktop`，可从开始菜单“昌福里社区电梯管理系统 → 打开数据目录”进入；源码版默认在项目目录内。

| 目录 | 内容 |
| --- | --- |
| `data/elevator.db` | 电梯、工作记录、文稿、设置和操作日志 |
| `storage/photos/` | 原始现场照片，不改写水印 |
| `storage/attachments/` | Word、PDF、Excel 等原始附件 |
| `exports/` | 已生成的 Word、ZIP |
| `backups/` | 最近 30 份系统备份 |
| `logs/system.log` | 启动和错误日志 |

不要通过网络共享 `data/elevator.db` 给其他电脑直接打开；所有终端只访问网页。

## 局域网访问

安装版在网页“系统设置 → 局域网访问与二维码”查看主机地址；源码版启动窗口也会列出 `http://本机IP:8766`。也可在 Windows 命令提示符输入 `ipconfig`，查找正在使用网卡的 IPv4 地址。其他终端须连接同一局域网，再在浏览器输入这个地址。若打不开，检查主机 Windows 防火墙是否允许 TCP 8766 的局域网入站访问。

Win7 终端只需 Chrome 109 或 Edge 109 浏览器，不安装 Python、Node 或数据库。浏览器不可使用过旧的 IE。Win7 的真实设备验收尚需在部署现场完成。

二维码统一使用在“系统设置 → 局域网访问与二维码”保存的主机地址（例如 `http://192.168.1.20:8766`）。系统不会生成指向 `127.0.0.1` 或 `localhost` 的二维码；多网卡时需选择手机能访问的那一个。进入电梯档案，点“查看、下载与打印”可下载二维码或打印带电梯名称的标签。手机连接同一网络，扫码直接进入对应电梯。

## 备份与演示数据

在“系统设置 → 立即备份并下载”生成包含数据库及所有附件的 ZIP，并把下载文件另存到另一块磁盘。具体恢复步骤见 [BACKUP_AND_RESTORE.md](BACKUP_AND_RESTORE.md)。

可运行 `.venv\Scripts\python.exe scripts\demo_data.py` 生成“演示18栋”测试资料；用相同命令加 `--remove` 移除。演示电梯若已有新工作记录，删除会被阻止。

日常操作见 [USER_GUIDE.md](USER_GUIDE.md)。测试情况见 [TEST_REPORT.md](TEST_REPORT.md)，交付边界和现场验收表见 [AUDIT_REPORT.md](AUDIT_REPORT.md)。本版已完成本机回归，尚需 Windows 现场验收后再正式投入使用。

## 2026-09-30 工作档案更新

单位名称统一为昌福里社区27区党群物业服务站。工作档案按电梯和事件发生时间编排，照片使用“图记录号-照片号”，不再把上传文件名写在图注中；可在新增或编辑记录时调整附件顺序。封面、正文、页码和照片页面采用正式归档版式，完整附件包保留原始文件并提供对应清单。升级及查阅电脑字体要求见 [INSTALL.md](INSTALL.md) 最后一节。

## 2026-10-29 可编排工作文稿

“工作档案导出”可以先从所选电梯和时间段生成编排稿，再修改标题、小标题、正文及图片说明，使用段间插入、拖动或上下移动调整内容。图片从本稿来源工作记录中选择，图号根据最终顺序自动生成。草稿保存在主机数据库，各终端共享草稿，并发保存时检查版本；文稿编辑不修改原始台账。预览与 Word 使用相同的内容顺序，ZIP 保留来源资料的全部原件。固定版式的原始档案导出继续保留。

升级前先在系统设置中备份并另存。关闭原服务窗口，更新程序及 `frontend/dist/`，保留原有 `data/` 和 `storage/`，再启动系统；数据库会自动增加草稿表。重新打开页面后，“工作档案导出”应出现“生成编排稿”入口。详细操作见 [USER_GUIDE.md](USER_GUIDE.md)。
