# 全界面改版与二维码验收截图

2026-09-27，macOS Chrome 153，使用隔离测试数据库。截图中的楼栋、账号、费用等均为测试资料，未写入正式库。

- `*-desktop.png`：1500 像素桌面布局。
- `*-mobile.png`：390 像素手机布局；另检查 320 像素无页面横向溢出。
- `qr-label.png` / `qr-label.pdf`：电梯标签打印结果，仅保留电梯名称、编号和二维码。
- `scan-login-mobile.png` / `scan-detail-mobile.png`：在独立浏览器会话中通过主机局域网地址打开电梯链接，登录后留在同一电梯档案。

截图使用测试端口 8766；正式交付端口为 8765。二维码内的地址是测试主机地址，不能作为物业现场的正式二维码使用。

复核脚本：`tests/browser_audit.cjs`、`tests/browser_design.cjs`。正式实机、Wi-Fi 和打印机仍需现场测试。
