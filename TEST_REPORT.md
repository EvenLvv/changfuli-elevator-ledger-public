# 1.0 修复版测试记录

测试日期：2026-09-26 至 2026-09-27。环境：macOS、Python 3.9.6、Node 22、Chrome 153.0.8010.53。

## 自动业务测试

在项目根目录运行：

```sh
.venv/bin/python -m unittest discover -s tests -v
```

**22 个测试用例通过**，使用临时数据库和临时附件目录，不将测试数据写入物业正式台账。Windows 命令将 `.venv/bin/python` 换成 `.venv\Scripts\python.exe`。

覆盖：首次建号限制、登录、楼栋/单元/电梯、事件四类、配件价格和质保日期/更换间隔、提醒、费用、二维码、附件格式及同名保存、角色权限、审计、软删除/恢复、组合搜索、Word 和 ZIP、日期/类型筛选与空资料、金额/日期/控制字符校验、CSRF、修改冲突、演示数据保护。修复版明确由用户选择是否改变当前状态，历史补录默认保留状态。

备份不只检查返回成功：实际解压并执行 SQLite 完整性检查、对比原始附件字节、验证清除登录会话，再用新 Python 进程加载恢复的目录、登录并读取原记录。缺失附件时备份和导出会失败，且不留下伪成功 ZIP。

## 前端检查

```sh
cd frontend
npm run typecheck
npm run build
```

类型检查、生产构建通过。Vite 构建目标为 Chrome 109；这不能替代 Chrome 109 实机测试。构建提示单个 JS 包较大，暂不影响已测核心操作。

## 实际浏览器回归

`tests/browser_audit.cjs` 使用隔离测试服务器和临时 Chrome 会话。实际通过：

- 登录、新建维修并直接添加配件、质保计算、三附件上传。
- 人为令第一次附件上传返回 500，再保存后只有一条事件、三个附件，费用 260 元。
- 编辑时“已完成”正确，新增处理情况保存，组合搜索直达展开记录；将配件单价从 260 改为 300 元，自动总费用随之重算。
- 点击第二张照片预览显示对应照片；无 JavaScript 页面异常。
- 390×844 手机宽度无横向溢出，原生拍照输入存在。
- 下载真实 DOCX；工作记录页和管理员已删除资料入口存在。

浏览器版本为 **macOS Chrome 153**。测试中移除部分新 JS 方法做补充检查，**没有因此认定 Win7 Chrome/Edge 109 实测通过**。手机宽度检查也不等于真实手机拍照验收。

复跑前准备独立测试目录，不能指向正式数据。以下为 macOS/Linux 示例，需本机已有 Playwright 和 Chrome：

```sh
# 终端一：所有数据都放到临时测试目录
export ELEVATOR_DATA_DIR=/tmp/elevator-qa/data
export ELEVATOR_STORAGE_DIR=/tmp/elevator-qa/storage
export ELEVATOR_EXPORT_DIR=/tmp/elevator-qa/exports
export ELEVATOR_BACKUP_DIR=/tmp/elevator-qa/backups
export ELEVATOR_LOG_DIR=/tmp/elevator-qa/logs
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8766 --no-proxy-headers
# 终端二：生成测试上传文件，再测试；CHROME_PATH 指向本机 Chrome
.venv/bin/python tests/generate_sample.py /tmp/elevator-qa-files
AUDIT_OUTPUT=/tmp/elevator-qa-files CHROME_PATH='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' node tests/browser_audit.cjs
```

如果 Playwright 不在项目模块路径，可通过 `PLAYWRIGHT_MODULE` 指定已有模块路径。脚本只应对无真实资料的隔离服务器运行；它会建立测试管理员和演示记录。

## Word 实际文件检查

```sh
.venv/bin/python tests/generate_sample.py
```

真实调用导出接口生成 `docs/qa/audit-sample.docx`：一栋楼、两部电梯、四类工作、故障时间、配件质保、四张横竖混合图片（PNG/WEBP/JPEG）、附件目录，以及没有记录的电梯。

用 python-docx 重开成功；以文档工具所带 LibreOffice 渲染成 PDF，配置 Fontconfig 读取 macOS 系统中文字库，逐页检查 **6 页**。中文、表格、横竖图片比例、四图排版、附件目录及空电梯页面可读，无明显溢出或裁切。文件保存在 `docs/qa`。原图不会为生成 Word 而改写。

**没有在 Windows Word 或 WPS 实际打开。** 本次 LibreOffice 渲染不能替代这项验收。

## 离线包检查

```sh
.venv/bin/python scripts/verify_offline.py
```

25 个 wheel 的 ZIP 校验、Windows Python 3.12 x64 条件依赖闭包检查通过，包含 Windows 专用 colorama。前端已构建并随包交付。离线包不含 Python 安装器；安装 BAT 尚未在 Windows 执行。

## 尚未通过现场验收的项目

Win11 BAT/离线安装、防火墙和局域网；Win7 Chrome/Edge 109；Windows Word/WPS；手机实际扫码拍照；Windows 整机重启及现场备份恢复。详见 [AUDIT_REPORT.md](AUDIT_REPORT.md) 的勾选表。

以上通过结论只覆盖所列环境与样本，不能推导为“完全没有错误”。

## 端口调整复核（2026-09-27）

正式启动端口和开发代理已由 8000 改为 8765；隔离浏览器测试默认端口改为 8766，避免误用正式服务。以临时空数据库实际运行 `scripts/run.py`，确认监听 8765，首页 `/` 和 `/api/health` 均返回 HTTP 200，启动窗口地址正确。测试结束已停止服务。该检查在 macOS 执行；Windows 防火墙和云打印共存仍需部署现场确认。

## 电梯档案与界面改版复核（2026-09-27）

新增4项自动测试并全部通过：直接填写楼栋/单元及编辑归属、Excel预检查不写入/确认新增/重复跳过、错误日期或重复行整批回滚、模板文本格式/公式拦截/损坏文件/导入权限。导出重新打开核验中文列名、设备编号与电话号码前导零、公式样式文本安全保存、按楼栋筛选。

类型检查和生产构建通过。实际 Chrome 153 验证新增电梯自动建立楼栋单元、Excel 预检查及确认导入、下载真实 Excel、统一顶部搜索直达工作记录、最近8条工作动态、改版后的 Word 下载。原有附件失败重试、自动费用编辑等浏览器回归通过。

已检查电梯档案、工作记录、搜索、导出页在375、390、768、1024px宽度无横向溢出，并验证工作台账无筛选结果时最近动态仍保留。桌面和手机截图保存在 docs/qa；Word生成逻辑未改动，原六页文档验证仍保留。Windows/Win7实际设备验收边界不变。


## 2026-09-27：全界面改版与二维码修复

本轮保持原有业务流程，替换为用户确认的横向导航、蓝灰配色、建筑摄影和轻量台账样式，覆盖登录、首页、档案、详情、记录、搜索、提醒、导出、管理和弹窗。测试全部使用隔离数据目录。

### 实际通过

- `python -m unittest discover -s tests -p 'test_*.py' -v`：26 项通过，含原有22项和4项局域网二维码测试。
- `npm run typecheck`、`npm run build`：通过，目标仍为 Chrome 109。构建保留既有的大包体积提示，没有编译错误。
- `tests/browser_audit.cjs`：真实 Chrome 回归通过，包含新增电梯、Excel预检查/导入/导出、维修及配件、质保日期、图片/Word上传、上传失败重试不重复建记录、编辑、组合搜索、图片预览、Word下载、工作记录和系统管理。
- `tests/browser_design.cjs`：10 个主界面桌面截图及 390 / 320 像素无横向溢出检查通过；含手机菜单与新增电梯弹窗、登录页及二维码弹窗。
- 局域网设置通过页面保存到数据库；填写 127.0.0.1 被拒绝并保留原设置；普通工作人员无法修改地址。
- 不同网卡检测到多个候选且没有确定地址时，二维码接口返回中文提示，不生成本机地址二维码；已保存地址优先于浏览器访问地址。
- 在 `http://192.168.0.100:8766` 上用全新浏览器会话直接打开 `/elevators/4`，登录后正确显示 18栋1单元1号梯；刷新仍是同部电梯。此地址只用于本次隔离测试。
- QR PNG 真实下载、打印按钮调用、仅电梯标签的打印样式、生成 A4 PDF 通过；含电梯名称、设备编号和地址。
- 二维码实际编码参数与目标电梯路径一致，PNG 可被图像库读取；使用 macOS Vision 对下载图片实际解码得到 `http://192.168.0.100:8766/elevators/4`，与页面目标一致。缺失或已删除电梯无法生成二维码。
- 页面内摄影以构建资产本地加载，不依赖外网。修复了测试中发现的图片路径回退到 HTML、320 像素文件选择器溢出及设置加载时覆盖输入的问题。

截图见 `docs/qa/redesign/`。保留测试源文件以便复核；运行浏览器测试前先按原流程启动隔离服务并生成上传样例。`browser_design.cjs` 在 `browser_audit.cjs` 之后运行，沿用其测试管理员，只允许针对测试服务执行。

### 本轮未验证

- Windows 11 / Windows 7 实机、Chrome/Edge 109 实际浏览器。
- 物业站真实手机摄像头扫码、Wi-Fi 设备隔离、防火墙及打印机。
- Windows Word / WPS 本机打开；本轮对导出功能做既有自动回归，未重复 Office 实机验收。

Windows 更新方式及地址设置见 `INSTALL.md`。已打印旧二维码须重新生成；更改主机 IP 后同样需重新打印。

## 2026-09-30：工作档案排版与附件顺序更新

所有功能测试使用隔离数据库和附件目录，没有将测试资料写入正式台账。

- 后端全量回归28项通过，含新增2项导出和排序测试；前端类型检查、生产构建通过。构建仍有既有的大包体积提示。
- 新测试核对同日事件按发生时间排序、图号和附件号对应、图注不含微信技术文件名、A4边距与字体设置、封面不显示页码、图片尺寸和顺序、原图字节保持一致、完整附件包清单、无记录电梯及关闭照片导出。
- 排序接口核对未登录、越权、重复编号、非法编号和过期列表；排序修改产生操作日志。模拟旧数据库后连续执行初始化，排序字段自动补充，既有记录和附件保留。
- 最后补充超长中文导出文件名的实际写入检查，单独重跑新增2项测试通过。
- 真实浏览器验证已有照片上下移、刷新后顺序保留、新上传文件排序、390像素手机录入和导出布局无横向溢出、全称封面预览，以及下载真实DOCX。`tests/browser_export_format.cjs`运行通过，无页面脚本错误。
- 通过实际导出接口生成样本，涵盖两部电梯、四类工作、故障时间、配件质保、五张横竖及方形照片（含PNG/JPEG/WEBP）、附件目录和空电梯。重新打开DOCX并渲染，逐页检查全部12页：中文可读、照片比例正确、图号连续、表格和照片未溢出，修复汇总表孤行和质保日期断行。证据位于`outputs/export-format-20260930/`，不随正式更新包分发。

运行命令：

```sh
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v
.venv/bin/python -m unittest discover -s tests -p 'test_export_format.py' -v
.venv/bin/python tests/generate_sample.py outputs/export-format-20260930
# frontend目录：npm run typecheck；npm run build
# 隔离8767服务启动后：node tests/browser_export_format.cjs
```

本机排版检查使用LibreOffice和macOS中文替代字体，Word文件中的公文字体名称已单独核对。**尚未在Windows Word/WPS以及实际公文字体环境中打开和打印，本次检查不能替代现场验收。** Windows启动、Win7终端及真实局域网边界仍同上；正式审阅电脑应安装有合法使用权限的所需字体。

## 2026-10-29：工作文稿编排

本轮使用独立数据、附件、导出和日志目录，浏览器测试服务为127.0.0.1:8769，没有向正式台账写入测试记录。新增功能由Astra设计及独立审核，Sol 6.1 ultra实现。

### 通过的检查

- 后端全量36项测试通过（原28项、新增8项）。最后排版修正后，8项文稿专项测试再次全部通过。
- 新测试覆盖来源快照不可被客户端替换、标题和自然段生成、正文与照片重排、图片白名单及重复插入校验、并发保存一方成功另一方409、工作人员与管理员权限、旧下载接口不能绕过新稿权限、父级软删除及附件缺失阻止导出、无工作记录电梯、备份后在新进程恢复并重新导出。
- 实际打开DOCX检查段落顺序、连续图号、来源电梯和目录；ZIP包含移出正文的照片，所有原件与上传文件逐字节一致。微信长文件名不进入图注或照片目录展示名。
- 前端类型检查和生产构建通过，目标仍为Chrome109。文稿排版验收时页面资源为`index-Chhq68Dj.js`，后续周期按钮补丁资源见下节；无新增运行依赖。
- `tests/browser_archive_editor.cjs`完整流程通过，实际浏览器为Chrome156.0.8078.73：编辑标题/小标题/正文、段间插图、原生拖动及键盘上下移、移除撤销、保存刷新恢复、未保存离页/退出取消、退出请求失败仍保留未保存状态、409保留编辑内容、未保存预览图号与目录顺序、真实Word与ZIP下载、原台账不变。
- 手机尺寸检查包括390px编辑及图库插图、320px预览无横向溢出。这是桌面浏览器模拟尺寸，不是物理手机验收。测试还禁用了`crypto.randomUUID`及较新的数组方法，确认核心编辑流程不依赖它们。
- 原有`tests/browser_export_format.cjs`已适配新入口并实际通过：既有附件排序、刷新保留、上传队列排序、手机布局以及“直接导出原始档案”下载。另两份旧浏览器脚本已更新受影响的选择器，本轮未重复运行全套旧界面截图与审计脚本。
- 对浏览器实际下载的文稿进行渲染，发现并修复含手动换行的正文被拉大字距、范围挤断统计日期、Word目录缺少电梯位置等问题。修正后再次经真实浏览器下载、核对三行来源信息与电脑/手机预览，并逐页检查最终3页：中文可读、图注和图片同页、比例正常、正文及目录无裁切。
- Astra对最终3页和代码补审通过。其独立核验还确认实际下载Word的标题、正文、小标题、图注顺序与已保存草稿一致。
- Windows Python3.12 x64离线依赖25个wheel全部通过依赖与ZIP完整性检查。

可重跑测试为`tests/test_export_drafts.py`及`tests/browser_archive_editor.cjs`。后端测试导入应用之前，应把全部`ELEVATOR_*_DIR`设置为临时测试目录；浏览器脚本必须指定`ARCHIVE_EDITOR_TEST_URL`，仅允许本机非8765测试端口，演示图片已包含在`tests/fixtures/`。需要安装Playwright的开发环境，或以`PLAYWRIGHT_MODULE`指定已有模块路径。

界面证据位于`docs/qa/archive-editor/`。本地完整测试输出在`outputs/archive-editor-20261028/`，最终浏览器下载文件为`final/最终编排档案.docx`，逐页渲染为`render-final/`；该输出目录不随安装包分发。

### 尚未验证

Windows11/Windows7实机、Chrome/Edge109实际版本、物理手机以及目标Word/WPS字体和打印。Word视觉检查使用本机LibreOffice和中文替代字体，不能替代物业站最终电脑的试开与试打印。此次通过结论限于上述功能、环境和样本，不表示程序不存在任何错误。

### 周期快捷按钮补充核验（2026-10-29）

按页面标注将“本月／本年／全部时间”改为与电梯范围相同的单选按钮。真实浏览器交互核验通过：空日期默认选中全部时间；本月、本年切换时只有一项选中且日期正确；手动填入其他日期会清除高亮，恢复匹配日期后重新选中。在631×898视口检查无横向溢出，两组已选按钮均为背景`rgb(67,93,221)`、白字和6px圆角。Astra代码复核通过，包括一月同范围保留最后点击项；该一月场景补入已有测试脚本，本轮未重跑整套浏览器脚本。

类型检查、生产构建通过，当前资源为`index-BQ3RqIg1.js`及`index-Be-zTq4D.css`。本轮仅修改快捷选择及相应测试断言，未重复后端和Word排版测试。截图为`docs/qa/archive-editor/周期按钮选中状态.jpg`。

## 2026-10-30：Windows EXE 安装候选包

本轮增加 Windows 安装器、独立启动器和离线构建脚本，业务后端和前端页面保持原版本。目标为 Windows 10 / 11 x64；由用户在 Windows 电脑上完成人工安装验收。程序与业务数据分离，安装版数据使用 `%ProgramData%\ChangfuliElevatorLedger`，端口为 8765。

### 本轮实际通过

- `tests.test_windows_launcher` 13 项、`tests.test_windows_installer` 6 项，共 19 项测试全部通过。覆盖临时目录、路径链接与 Windows 重解析属性拒绝、重复启动、真实服务就绪、安全停止、同端口停机后立即重启、冲突端口不打开其他服务、安装维护标记、运行包白名单及 NSIS 实际编译。
- 官方 Python 3.12.10 x64 嵌入包哈希校验、25 个锁定 Windows 运行依赖及依赖闭包检查通过。目标主机无需安装 Python、Node 或联网下载依赖。
- Astra 对最终 EXE 实际解包：1,306 个程序清单文件逐一校验一致，没有清单外的业务文件；后端、启动器和前端与工作区最终版本一致。运行环境中的 47 个 PE 文件均为 AMD64；安装器为 NSIS Unicode x86 引导程序，带管理员授权声明。
- 使用安装包暂存目录中的真实应用代码，在 macOS 构建机的隔离临时目录运行：新版首页资源、首个管理员建立、登录、新建电梯、新建维修记录、生成真实 DOCX 并检查文档内容、备份、安全停止、同端口重新启动后原账号和档案可读，全部通过。没有向程序目录或正式台账写入测试业务数据。
- 补测发现 macOS 停机后立即重启的端口复用失败，已在非 Windows 分支设置 `SO_REUSEADDR`，先复现失败再验证修复。Windows 保持 `SO_EXCLUSIVEADDRUSE`；Windows 的活动连接释放与 POSIX TIME_WAIT 行为不能互相替代验收，参考 [Microsoft 官方说明](https://learn.microsoft.com/en-us/windows/win32/winsock/using-so-reuseaddr-and-so-exclusiveaddruse)。
- 维护标记采用原子创建和句柄检查，拒绝目录及重解析点，既有标记不截断写入，按已验证句柄清理。卸载只删除本产品程序文件，数据目录不在卸载删除范围内。普通用户目录预检查不等于完整防御恶意本机用户并发替换路径的安全审计。

### 最终交付文件

- 文件：`outputs/windows-installer-20261029/build/ChangfuliElevatorLedger-Setup-1.0.0-x64.exe`
- 大小：18,589,050 字节（约 18.6 MB）。
- SHA256：`de0fd2872c0c17e0b1914b0851138e31309d64e679ebedccf433720d566657db`。
- 证据：同输出目录上层的 `build.log`、`tests.log`、`staged-smoke.log` 与 `astra-review.md`；清单位于 `build/stage/BUILD-MANIFEST.json`。
- 安装与恢复说明：`docs/WINDOWS_INSTALLER.md`，安装器内同时附带其文本版本。旧源码版资料不会自动迁入安装版，应先备份，再停止系统并按说明恢复整套数据库与附件。

### 留待 Windows 人工验收

本机 VMware 已恢复到 Windows 11 ARM 的密码登录界面，未进入系统执行安装；这也不能代替目标 x64 主机测试。本包的结论为“已构建并通过所列核验，可交用户进行 Windows 实机测试”，不是已通过 Windows 正式部署验收。

应在目标电脑验证：安装与管理员授权、普通用户桌面启动、首次建账号、档案与照片录入、Word/WPS 打开导出文档、备份、停止后立即重启及整机重启、局域网终端访问，最后用测试资料验证升级和卸载保留数据。安装包未签名，Windows 可能提示未知发布者；不要关闭防病毒软件来绕过拦截，应核对来源和哈希或联系维护人员。
