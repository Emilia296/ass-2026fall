"""A few functional HTTP requests through real nginx; no stress/load generation."""

import json, os, subprocess, tempfile, threading, time
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import httpx

binary = os.environ.get("NGINX_BINARY", "/home/dev/electra-nginx/extracted/usr/sbin/nginx")
source = (Path(__file__).parents[2] / "deploy/nginx.conf").read_text()
seen = []


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        data = json.dumps({"upstream": self.server.server_port}).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length", 0)))
        seen.append(self.server.server_port)
        self.send_response(503)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


with tempfile.TemporaryDirectory(prefix="electra-gateway-") as tmp:
    config = (
        source.replace("worker_processes auto", "worker_processes 1")
        .replace("api-secondary:8080", "127.0.0.1:18082")
        .replace("api:8080", "127.0.0.1:18081")
        .replace("listen 8080", "listen 127.0.0.1:18080")
        .replace("/tmp/electra-nginx.pid", tmp + "/nginx.pid")
        .replace("/dev/stderr", tmp + "/error.log")
        .replace("/dev/stdout", tmp + "/access.log")
    )
    config = config.replace(
        "http {",
        "http {\n"
        + "\n".join(
            f"{kind}_temp_path {tmp}/{kind};"
            for kind in ("client_body", "proxy", "fastcgi", "uwsgi", "scgi")
        ),
    )
    path = Path(tmp) / "nginx.conf"
    path.write_text(config)
    subprocess.run([binary, "-t", "-p", tmp, "-c", str(path)], check=True)
    servers = [ThreadingHTTPServer(("127.0.0.1", port), Handler) for port in (18081, 18082)]
    for s in servers:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    process = subprocess.Popen([binary, "-p", tmp, "-c", str(path), "-g", "daemon off;"])
    try:
        with httpx.Client(timeout=3) as c:
            for attempt in range(30):
                try:
                    c.get("http://127.0.0.1:18080/health").raise_for_status()
                    break
                except httpx.TransportError:
                    time.sleep(0.1)
            replies = [c.get("http://127.0.0.1:18080/health").json()["upstream"] for _ in range(4)]
            assert set(replies) == {18081, 18082}, replies
            assert (
                c.post("http://127.0.0.1:18080/post-error", json={"test": True}).status_code == 503
            )
            assert len(seen) == 1, "Gateway replayed a sent POST"
            servers[0].shutdown()
            servers[0].server_close()
            assert c.get("http://127.0.0.1:18080/health").json()["upstream"] == 18082
        print("nginx syntax, two-upstream routing, failover, and POST non-replay checks passed.")
    finally:
        process.terminate()
        process.wait(timeout=5)
        for s in servers:
            s.shutdown()
            s.server_close()
