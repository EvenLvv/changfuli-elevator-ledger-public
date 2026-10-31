# GitHub 源码与自动审查

仓库保存可继续开发的完整源码；离线运行包和 Windows EXE 单独交付。首次上传前核对 `.gitignore` 与实际待提交清单，当前仓库按用户要求公开。界面使用自行绘制的示意图，素材说明见 [DESIGN_ASSETS.md](DESIGN_ASSETS.md)。

## 上传范围

保留根目录开发/使用文档与 BAT、`requirements.txt`、`requirements.lock.txt`、完整 `backend/`、`frontend/src/`（含本地照片）、前端配置及 `package-lock.json`、`scripts/`（含 NSIS 和图标）、`tests/`（含合成图片夹具）、`.github/`、`AGENTS.md` 和运行目录的空 `.gitkeep`。

不上传运行数据库及账号、照片附件、导出与备份、日志、`outputs/`、`wheelhouse/`、虚拟环境、`node_modules/`、`frontend/dist/`、生成的 QA 图片/文档、录屏、ZIP 或 EXE。`docs/qa/` 仅保留文字说明。`.gitignore` 不会清除已经提交的文件，后续提交仍需检查暂存区。

历史测试报告中的截图、Word/PDF 样例和 `outputs/` 验收证据保留在本地交付资料中，不作为 GitHub 附件上传；报告中指向这些生成物的相对链接在源码仓库中没有对应文件。

## 本地验证

前置：Python 3.12、Node.js 22/npm；首次安装依赖需要访问 Python/npm 包源。macOS/Linux 在项目根目录执行：

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt -c requirements.lock.txt
cd frontend
npm ci
npm run typecheck
npm run build
cd ..

test_root=$(mktemp -d)
export ELEVATOR_DATA_DIR="$test_root/data"
export ELEVATOR_STORAGE_DIR="$test_root/storage"
export ELEVATOR_EXPORT_DIR="$test_root/exports"
export ELEVATOR_BACKUP_DIR="$test_root/backups"
export ELEVATOR_LOG_DIR="$test_root/logs"
.venv/bin/python -m unittest discover -s tests -v
```

测试会使用临时目录并在测试内清理数据；上面导出的环境变量只作用于当前终端。在另一个终端按 [README.md](../README.md) 启动正式源码版。Windows 将虚拟环境 Python 路径换为 `.venv\Scripts\python.exe`，并在 PowerShell 用 `$env:ELEVATOR_DATA_DIR` 等变量指定独立临时目录后执行相同测试。

`.github/workflows/ci.yml` 在 pull request 和推送时运行前端类型检查/构建以及后端 unittest。它只需源码读取权限，不需要密钥、Codex API key 或模型调用。未安装 NSIS 时，现有 NSIS 编译测试会明确跳过；CI 不包含真实浏览器和 Windows 现场验收。浏览器脚本还需单独安装 Playwright/Chrome 并启动隔离服务，不属于基础依赖。

## Codex 自动审查

在 Codex 的代码审查设置中连接此 GitHub 仓库并开启自动审查；仓库的 `AGENTS.md` 提供项目审查重点。随后通过分支和 pull request 提交改动，检查 PR 上的 Codex 审查结果和 CI。原生审查由 Codex/GitHub 连接管理，仓库无需另加调用付费 API 的 Action。人工仍需确认数据迁移和正式发布边界。

## 从 GitHub 重建 Windows 安装包

克隆源码后先按上文安装依赖并构建前端。`wheelhouse/`、Python 嵌入运行库和 NSIS 不随 GitHub 源码上传，构建机另行准备：

```bash
.venv/bin/python -m pip download --dest wheelhouse --platform win_amd64 --python-version 3.12 --implementation cp --abi cp312 --only-binary=:all: -r requirements.lock.txt
.venv/bin/python scripts/verify_offline.py
```

从 Python 官方获取 `python-3.12.10-embed-amd64.zip`，安装 NSIS 3；Python ZIP 的固定 SHA256 和完整构建命令见 [WINDOWS_INSTALLER.md](WINDOWS_INSTALLER.md)。将 `--python-zip` 改为实际下载路径，`--output-dir` 指向本地 `outputs/`。安装器构建脚本验证 Python ZIP、锁定 wheel 和程序文件，不会把业务资料打包。源码/BAT 离线 ZIP 同样需要先构建 `frontend/dist/` 和准备完整 `wheelhouse/`，再运行 `scripts/package_release.py`。

能构建源码、CI 通过或生成 EXE，均不代表 Windows 现场验收通过。真实主机安装、运行中升级、普通用户/跨用户访问、卸载保留资料、防火墙和 Word/WPS 显示仍需逐项核验。
