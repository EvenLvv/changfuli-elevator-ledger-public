# 项目协作约定

先说明假设、影响范围和可验证的完成标准，再做最小改动。保持直接、准确；区分已验证事实、推断和未测试边界，不把自动测试通过写成现场验收通过。

- 技术栈：Vue 3 / TypeScript / Vite 前端，FastAPI / SQLite 后端。沿用已有结构与依赖。
- `data/`、`storage/`、`exports/`、`backups/`、`logs/` 是本地业务资料，禁止提交、清空或用于自动测试。`outputs/`、`wheelhouse/` 和安装包不进入源码仓库。
- 后端测试使用 `tests/support.py::isolated_app()`；运行测试前还应将五个 `ELEVATOR_*_DIR` 指向临时目录，防止导入模块碰到默认目录。浏览器回归只对独立数据目录和非 8765 的回环端口执行。
- 前端修改运行 `npm ci`、`npm run typecheck`、`npm run build`；后端修改运行 `python -m unittest discover -s tests -v`。依赖准备和隔离命令见 `docs/GITHUB.md`。
- 保留 `frontend/src/assets/architecture.svg`、`tests/fixtures/archive-photo.png` 和锁文件；不要用全局图片忽略规则误删源码资产。照片权利边界见 `docs/DESIGN_ASSETS.md`。
- Windows UAC、真实安装/升级/卸载、共享数据权限、局域网及 Word/WPS 显示必须另做现场验收；macOS/Linux 检查不能替代。

## Review guidelines

优先指出能解释触发条件和实际影响的问题，避免只提风格偏好或与本次变更无关的重构。

- 检查升级、恢复、删除和备份是否会丢失数据库、附件或已保存文稿；保留事务、校验、失败回退和并发修改保护。
- 检查登录、首次建号、角色权限、附件路径、导出下载和安装器路径边界；不得把测试账号密码作为生产默认值。
- 检查前后端字段、金额/日期、排序、导入导出和已有记录兼容性；修复根因并保留有意义的回归验证。
- 检查提交中是否混入业务数据、账号、密钥、现场附件、日志、安装包或生成文件；前端本地设计素材和合成测试夹具应保留。
- 报告明确文件位置、复现前提与后果。没有证据时标明不确定，不声称未执行的平台或设备已通过。
