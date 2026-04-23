#!/bin/bash
# 雙擊此檔案即可啟動咖啡貼紙打印服務
# 窗口保持打開，關閉即停止打印功能
cd "$(dirname "$0")"
exec python3 longbridge_proxy.py
