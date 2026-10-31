import logging
import sys
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.db import COMMUNITY, LOGS, ROOT


from backend.network import addresses


if __name__ == "__main__":
    if not (ROOT / "frontend" / "dist" / "index.html").exists():
        print("前端文件缺失。请先按 INSTALL.md 完成安装。")
        raise SystemExit(1)
    print("\n" + COMMUNITY + "电梯管理台账")
    print("本机访问：http://127.0.0.1:8765")
    for address in addresses():
        print(f"局域网访问：http://{address}:8765")
    print("其他电脑无法打开时，请检查 Windows 防火墙是否允许 TCP 8765 端口。")
    print("关闭此窗口会停止系统。\n")
    logging.basicConfig(filename=LOGS / "system.log", level=logging.INFO, encoding="utf-8")
    logging.info("系统启动")
    uvicorn.run("backend.main:app", host="0.0.0.0", port=8765, log_level="info", proxy_headers=False)
