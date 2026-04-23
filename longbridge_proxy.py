#!/usr/bin/env python3
"""
Longbridge OpenAPI → HTTP proxy for the stock label generator.
Also proxies print jobs to local CUPS printer.

Run:
    python3 longbridge_proxy.py

Prerequisites:
    brew install --cask longbridge/tap/longbridge-terminal
    longbridge login

Endpoints:
    GET  /health
    GET  /quotes?symbols=TSLA.US,AAPL.US,NVDA.US
    GET  /printers                → list CUPS printers
    POST /print  (JSON body)      → print PNG to printer
         { image: "data:image/png;base64,...", printer?: "name", copies?: 1, media?: "58x40mm" }
"""
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

PORT = 8787
TIMEOUT_SEC = 20


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _normalize(sym: str) -> str:
    sym = sym.strip().upper()
    if not sym:
        return sym
    if '.' not in sym:
        sym += '.US'
    return sym


def fetch_quotes(symbols):
    """Single batch call: `longbridge quote S1 S2 ... --format json`"""
    normalized = [_normalize(s) for s in symbols if s.strip()]
    if not normalized:
        return []
    try:
        r = subprocess.run(
            ['longbridge', 'quote', *normalized, '--format', 'json'],
            capture_output=True, text=True, timeout=TIMEOUT_SEC,
        )
    except FileNotFoundError:
        return [{"symbol": s, "error": "longbridge CLI not installed"} for s in normalized]
    except subprocess.TimeoutExpired:
        return [{"symbol": s, "error": "timeout"} for s in normalized]

    if r.returncode != 0:
        err = (r.stderr or r.stdout).strip()[:300] or "CLI error"
        return [{"symbol": s, "error": err} for s in normalized]

    # CLI may print update-available notice on stderr; JSON is on stdout.
    try:
        raw = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        return [{"symbol": s, "error": f"parse error: {e}"} for s in normalized]

    if not isinstance(raw, list):
        raw = [raw]

    out = []
    for q in raw:
        if not isinstance(q, dict):
            continue
        sym = q.get('symbol', '')
        last = _num(q.get('last'))
        prev = _num(q.get('prev_close'))
        change_pct = ((last - prev) / prev * 100) if prev else 0.0
        out.append({
            "symbol": sym,
            "ticker": sym.split('.')[0] if sym else '',
            "price": round(last, 4),
            "prev_close": round(prev, 4),
            "changePct": round(change_pct, 4),
            "volume": int(_num(q.get('volume'))),
            "turnover": _num(q.get('turnover')),
            "status": q.get('status', ''),
        })
    return out


def list_printers():
    """List CUPS printer names via `lpstat -p`."""
    try:
        r = subprocess.run(['lpstat', '-p'], capture_output=True, text=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    printers = []
    for line in r.stdout.splitlines():
        if line.startswith('printer '):
            parts = line.split()
            if len(parts) >= 2:
                printers.append(parts[1])
    return printers


def get_default_printer():
    try:
        r = subprocess.run(['lpstat', '-d'], capture_output=True, text=True, timeout=5)
        # "system default destination: NAME" or "no system default destination"
        for line in r.stdout.splitlines():
            if ':' in line:
                name = line.split(':', 1)[1].strip()
                if name and name != 'no system default destination':
                    return name
    except Exception:
        pass
    return None


def print_image(image_b64, printer=None, copies=1, media=None):
    """Decode PNG from base64 and send to printer via `lpr`."""
    if image_b64.startswith('data:'):
        image_b64 = image_b64.split(',', 1)[1]
    img_bytes = base64.b64decode(image_b64)

    fd, path = tempfile.mkstemp(suffix='.png', prefix='sticker-')
    os.close(fd)
    with open(path, 'wb') as f:
        f.write(img_bytes)

    try:
        cmd = ['lpr']
        if printer:
            cmd += ['-P', printer]
        if copies and copies > 1:
            cmd += ['-#', str(int(copies))]
        if media:
            cmd += ['-o', f'media={media}']
        cmd += ['-o', 'fit-to-page']
        cmd.append(path)

        r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout).strip() or f'lpr exit {r.returncode}')
        return {"ok": True, "printer": printer or get_default_printer(), "copies": copies}
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


class Handler(BaseHTTPRequestHandler):
    def _cors(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def _send_json(self, status, payload):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self._cors()
        self.end_headers()
        self.wfile.write(json.dumps(payload, ensure_ascii=False).encode('utf-8'))

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self):
        u = urlparse(self.path)

        if u.path == '/health':
            self._send_json(200, {
                "ok": True,
                "cli": shutil.which('longbridge') is not None,
                "printer_default": get_default_printer(),
                "version": "0.2.0",
            })
            return

        if u.path == '/printers':
            self._send_json(200, {"printers": list_printers(), "default": get_default_printer()})
            return

        if u.path != '/quotes':
            self._send_json(404, {"error": "not found"})
            return

        params = parse_qs(u.query)
        symbols_str = params.get('symbols', [''])[0]
        symbols = [x for x in (s.strip() for s in symbols_str.split(',')) if x]

        if not symbols:
            self._send_json(400, {"error": "symbols param required"})
            return

        results = fetch_quotes(symbols)
        self._send_json(200, results)

    def do_POST(self):
        u = urlparse(self.path)
        if u.path != '/print':
            self._send_json(404, {"error": "not found"})
            return

        try:
            length = int(self.headers.get('Content-Length', 0))
        except (TypeError, ValueError):
            length = 0
        if length <= 0 or length > 20 * 1024 * 1024:  # 20 MB cap
            self._send_json(400, {"error": "invalid content length"})
            return

        try:
            body = json.loads(self.rfile.read(length).decode('utf-8'))
        except Exception as e:
            self._send_json(400, {"error": f"invalid JSON: {e}"})
            return

        image = body.get('image')
        if not image:
            self._send_json(400, {"error": "image (base64 PNG) required"})
            return

        try:
            result = print_image(
                image,
                printer=body.get('printer') or None,
                copies=int(body.get('copies', 1)),
                media=body.get('media') or None,
            )
            self._send_json(200, result)
        except Exception as e:
            self._send_json(500, {"error": str(e)})

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))


def main():
    has_cli = shutil.which('longbridge') is not None
    has_lpr = shutil.which('lpr') is not None

    print("=" * 50)
    print("☕  咖啡貼紙打印服務")
    print("=" * 50)
    if has_cli:
        print("✓ Longbridge CLI 已安装（/quotes 可用）")
    else:
        print("⚠  Longbridge CLI 未安装 — /quotes 不可用")
        print("   网页使用云端数据源（static）时可以忽略")
    if has_lpr:
        default_printer = get_default_printer() or '（无默认，用 lpstat -p 查看）'
        print(f"✓ lpr 就绪（默认打印机：{default_printer}）")
    else:
        print("❌ lpr 未找到 — 打印不可用（Mac 应该自带）")

    print(f"\n🚀 服务运行于 http://localhost:{PORT}")
    print(f"   保持此窗口开启，关闭即停止打印功能")
    print(f"   手动停止：Ctrl+C")
    print("=" * 50 + "\n")
    try:
        HTTPServer(('127.0.0.1', PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\n👋 已停止")


if __name__ == '__main__':
    main()
