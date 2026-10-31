# 昌福里社区27区党群物业服务站电梯管理台账 1.0

供物业站在一台 Windows 10 / 11 主机上运行，其他电脑或手机通过同一局域网的浏览器访问。记录一梯一档、维保故障维修和配件更换，集中保存照片附件，并导出 Word 工作档案或完整 ZIP 包。

## Windows 安装版

普通用户使用 EXE 安装包，安装后双击桌面“昌福里社区电梯管理系统”。运行环境与页面已内置，无需另装 Python、Node 或数据库，安装及使用无需联网。首次打开网页时自行设置管理员账号与密码，没有固定默认密码。

安装、停止、升级和换电脑步骤见 [Windows 安装版使用说明](docs/WINDOWS_INSTALLER.md)。安装版把资料保存在 `C:\ProgramData\ChangfuliElevatorLedger`（以系统 ProgramData 实际位置为准），与程序目录分开；卸载程序保留资料。下文 BAT 和开发命令仅适用于源码版。

## 技术栈

- 前端：Vue 3、TypeScript、Vite、Element Plus。正式运行时由后端提供已构建的静态文件，不需要持续运行 Node。
- 后端：Python、FastAPI。
- 数据：SQLite，由后端统一访问；照片和附件保存在主机文件夹。
- 文档：python-docx；二维码：qrcode；Excel：openpyxl，基础档案支持模板导入和按范围导出，工作附件保留原文件。

## 启动

源码版先按 [INSTALL.md](INSTALL.md) 安装，然后在 Windows 主机双击 `启动电梯管理系统.bat`。浏览器打开 `http://127.0.0.1:8765`。首次进入先设置管理员账号与密码；**系统没有固定默认账号或密码**。

开发环境：

```bash
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt -c requirements.lock.txt
cd frontend && npm ci && npm run build
cd .. && .venv/Scripts/python scripts/run.py
```

macOS/Linux 第一步使用 `python3 -m venv .venv`，并把 `.venv/Scripts/python` 换成 `.venv/bin/python`。Windows 正式交付使用 Python 3.12 64位版本；`wheelhouse` 中的 Windows 依赖不能用于 macOS。开发时也可在 `frontend` 运行 `npm run dev`，API 代理到本机 8765 端口。

## 数据位置

以下为数据根目录内的相对路径。EXE 安装版可从开始菜单“昌福里社区电梯管理系统 → 打开数据目录”进入；源码版默认在项目目录内。

| 目录 | 内容 |
| --- | --- |
| `data/elevator.db` | 电梯、记录、用户及日志索引 |
| `storage/photos/` | 原始现场照片，不改写水印 |
| `storage/attachments/` | Word、PDF、Excel 等原始附件 |
| `exports/` | 已生成的 Word、ZIP |
| `backups/` | 最近 30 份系统备份 |
| `logs/system.log` | 启动和错误日志 |

不要通过网络共享 `data/elevator.db` 给其他电脑直接打开；所有终端只访问网页。

## 局域网访问

安装版在网页“系统管理 → 局域网访问与二维码”查看主机地址；源码版启动窗口也会列出 `http://本机IP:8765`。也可在 Windows 命令提示符输入 `ipconfig`，查找正在使用网卡的 IPv4 地址。其他终端须连接同一局域网，再在浏览器输入这个地址。若打不开，检查主机 Windows 防火墙是否允许 TCP 8765 的局域网入站访问。

Win7 终端只需 Chrome 109 或 Edge 109 浏览器，不安装 Python、Node 或数据库。浏览器不可使用过旧的 IE。Win7 的真实设备验收尚需在部署现场完成。

二维码统一使用管理员在“系统管理 → 局域网访问与二维码”保存的主机地址（例如 `http://192.168.1.20:8765`）。系统不会生成指向 `127.0.0.1` 或 `localhost` 的二维码；多网卡时需选择手机能访问的那一个。进入电梯档案，点“查看、下载与打印”可下载二维码或打印带电梯名称的标签。手机连接同一网络，扫码登录后直接进入对应电梯。

## 备份与演示数据

管理员在“系统管理 → 立即备份并下载”生成包含数据库及所有附件的 ZIP，并把下载文件另存到另一块磁盘。具体恢复步骤见 [BACKUP_AND_RESTORE.md](BACKUP_AND_RESTORE.md)。

首次建立管理员后，可运行 `.venv\Scripts\python.exe scripts\demo_data.py` 生成“演示18栋”测试资料；用相同命令加 `--remove` 移除。演示电梯若已有新工作记录，删除会被阻止。

普通工作人员操作见 [USER_GUIDE.md](USER_GUIDE.md)。测试情况见 [TEST_REPORT.md](TEST_REPORT.md)，交付边界和现场验收表见 [AUDIT_REPORT.md](AUDIT_REPORT.md)。本版已完成本机回归，尚需 Windows 现场验收后再正式投入使用。

## 2026-09-30 工作档案更新

单位名称统一为昌福里社区27区党群物业服务站。工作档案按电梯和事件发生时间编排，照片使用“图记录号-照片号”，不再把上传文件名写在图注中；可在新增或编辑记录时调整附件顺序。封面、正文、页码和照片页面采用正式归档版式，完整附件包保留原始文件并提供对应清单。升级及查阅电脑字体要求见 [INSTALL.md](INSTALL.md) 最后一节。

## 2026-10-29 可编排工作文稿

“档案导出”可以先从所选电梯和时间段生成编排稿，再修改标题、小标题、正文及图片说明，使用段间插入、拖动或上下移动调整内容。图片从本稿来源工作记录中选择，图号根据最终顺序自动生成。草稿保存在主机数据库，具有权限检查和并发修改保护；文稿编辑不修改原始台账。预览与 Word 使用相同的内容顺序，ZIP 保留来源资料的全部原件。固定版式的原始档案导出继续保留。

升级前先在系统管理中备份并另存。关闭原服务窗口，更新程序及 `frontend/dist/`，保留原有 `data/` 和 `storage/`，再启动系统；数据库会自动增加草稿表。重新打开页面后，“档案导出”应出现“生成编排稿”入口。详细操作见 [USER_GUIDE.md](USER_GUIDE.md)。
