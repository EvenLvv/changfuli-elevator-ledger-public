# 界面素材

界面沿用已确认的横向导航、冷白底色、蓝色重点与轻量台账设计。首页继续使用电梯厅实景配图 `frontend/src/assets/elevator-lobby.jpg`；原有示意图 `frontend/src/assets/architecture.svg` 仅作为源码历史素材保留，不用于首页配图或应用图标。

2.0 桌面版恢复使用初代白底圆角方块、深墨灰“27”字样与右侧蓝色竖线标志，以仓库中的 `scripts/windows-app.ico` 作为唯一图标源，重建多尺寸 `scripts/desktop-app-2.0.ico`（16–256px）、`scripts/desktop-app-2.0.png` 及网页图标 `frontend/src/assets/desktop-app-2.0.png`，使桌面快捷方式、窗口图标、安装程序、网页图标与页面左上角标志保持一致。字体使用系统本地字体，素材随前端构建，运行不请求外部图片服务。

早期本地版本曾使用第三方建筑摄影作视觉参考，该照片未纳入公开仓库。部署单位可用自行拍摄并有权使用的照片替换首页配图后重新构建。
