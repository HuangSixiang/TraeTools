#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
计量代理（echo-proxy）：验证 Trae BYOK 出站请求是否带缓存参数。

用法：
  py tools/echo-proxy/echo_proxy.py [port]   # 默认 8788

在 Trae「自定义模型 / 自定义请求地址」填写 http://127.0.0.1:8788（v1）
后发一条消息，本代理会把 Trae 发来的原始请求（headers + body）落盘到
tools/echo-proxy/capture/ 目录，并返回一个 mock 响应让客户端不报错。
重点观察：
  - /v1/messages（Claude 系）：messages 各 block 是否带 cache_control
  - /v1/chat/completions（OpenAI 系）：前缀是否稳定（system/messages 结构）
"""

import datetime
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CAPTURE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "capture")

ENDPOINTS = {"/v1/chat/completions": "openai", "/v1/messages": "anthropic", "/v1/messages/raw": "anthropic-raw"}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # 静默访问日志
        pass

    def _capture(self, endpoint):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        os.makedirs(CAPTURE_DIR, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        name = "%s_%s.json" % (ts, ENDPOINTS.get(endpoint, "other"))
        payload = {
            "time": datetime.datetime.now().isoformat(),
            "endpoint": endpoint,
            "method": self.command,
            "headers": {k: v for k, v in self.headers.items()},
            "body": json.loads(raw.decode("utf-8", errors="replace")) if raw else None,
        }
        with open(os.path.join(CAPTURE_DIR, name), "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        return payload

    def _is_stream(self, payload):
        return bool(payload and payload.get("body") and payload["body"].get("stream"))

    def _send_json(self, obj, status=200):
        data = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_sse(self, lines):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        for line in lines:
            self.wfile.write(("data: %s\n\n" % json.dumps(line)).encode("utf-8"))
            self.wfile.flush()
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def do_POST(self):
        if self.path not in ENDPOINTS:
            self._send_json({"error": {"message": "unknown endpoint %s" % self.path}}, 404)
            return
        payload = self._capture(self.path)
        kind = ENDPOINTS[self.path]
        model = (payload.get("body") or {}).get("model", "echo")
        if kind.startswith("anthropic"):
            if self._is_stream(payload):
                self._send_sse([{
                    "type": "message_start", "message": {
                        "id": "msg_echo", "type": "message", "role": "assistant", "model": model,
                        "content": [], "stop_reason": None,
                        "usage": {"input_tokens": 1, "output_tokens": 1,
                                  "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
                    },
                }, {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
                   {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta",
                                                                         "text": "echo-proxy: 已记录本次请求，请查看 capture 目录"}},
                   {"type": "content_block_stop", "index": 0},
                   {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                    "usage": {"output_tokens": 2}}])
            else:
                self._send_json({
                    "id": "msg_echo", "type": "message", "role": "assistant", "model": model,
                    "content": [{"type": "text",
                                 "text": "echo-proxy: 已记录本次请求，请查看 capture 目录"}],
                    "stop_reason": "end_turn", "stop_sequence": None,
                    "usage": {"input_tokens": 1, "output_tokens": 1,
                              "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0},
                })
        else:
            if self._is_stream(payload):
                self._send_sse([{
                    "id": "chatcmpl-echo", "object": "chat.completion.chunk", "created": 1, "model": model,
                    "choices": [{"index": 0, "delta": {"role": "assistant",
                                                       "content": "echo-proxy: 已记录本次请求，请查看 capture 目录"},
                                 "finish_reason": None}],
                }, {
                    "id": "chatcmpl-echo", "object": "chat.completion.chunk", "created": 1, "model": model,
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2,
                              "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 1},
                }])
            else:
                self._send_json({
                    "id": "chatcmpl-echo", "object": "chat.completion", "created": 1, "model": model,
                    "choices": [{"index": 0,
                                 "message": {"role": "assistant",
                                             "content": "echo-proxy: 已记录本次请求，请查看 capture 目录"},
                                 "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2,
                              "prompt_cache_hit_tokens": 0, "prompt_cache_miss_tokens": 1},
                })

    def do_GET(self):
        self._send_json({"service": "echo-proxy", "ok": True, "capture_dir": CAPTURE_DIR})


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8788
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print("echo-proxy listening on http://127.0.0.1:%d  (capture -> %s)" % (port, CAPTURE_DIR))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()