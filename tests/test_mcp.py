#!/usr/bin/python3
"""The pslib MCP server, driven the way a client drives it.

stdio: the server as a child process, one JSON-RPC message per line.
http:  the server on 127.0.0.1 with a token, JSON-RPC POSTed to /mcp.

Both transports run the same calls: initialize, tools/list, every tool once
(md_to_pdf, template_list, template_info, render_template with the sample
data, pdf_preview of the result, measure_text), and the failure paths a client
must be able to tell apart (unknown tool, bad data, bad token, wrong path).
Rendered files go to a scratch out dir that is removed at the end.
"""
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER = os.path.join(HERE, "..", "mcp_server.py")
PY = sys.executable

PASS = FAIL = 0


def check(desc, ok, extra=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"OK   {desc}")
    else:
        FAIL += 1
        print(f"FAIL {desc}" + (f"\n       -> {str(extra)[:300]}" if extra else ""))


class StdioClient:
    def __init__(self, out_dir):
        self.p = subprocess.Popen([PY, SERVER, "--out-dir", out_dir],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.PIPE)
        self.n = 0

    def call(self, method, params=None):
        self.n += 1
        msg = {"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}}
        self.p.stdin.write((json.dumps(msg) + "\n").encode())
        self.p.stdin.flush()
        line = self.p.stdout.readline()
        return json.loads(line)

    def notify(self, method):
        self.p.stdin.write((json.dumps({"jsonrpc": "2.0", "method": method}) + "\n").encode())
        self.p.stdin.flush()

    def close(self):
        self.p.stdin.close()
        self.p.wait(timeout=10)
        return self.p.returncode


class HttpClient:
    def __init__(self, url, token):
        self.url, self.token, self.n = url, token, 0

    def post(self, body, token=None):
        req = urllib.request.Request(self.url, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json",
                                              "Accept": "application/json, text/event-stream",
                                              "Authorization": f"Bearer {token or self.token}"})
        with urllib.request.urlopen(req, timeout=120) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else None)

    def call(self, method, params=None):
        self.n += 1
        return self.post({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}})[1]

    def notify(self, method):
        return self.post({"jsonrpc": "2.0", "method": method})[0]


def tool(client, name, **args):
    r = client.call("tools/call", {"name": name, "arguments": args})
    return r["result"]


def pdf_blob(result):
    for c in result["content"]:
        if c["type"] == "resource":
            return base64.b64decode(c["resource"]["blob"])
    return b""


def exercise(client, label):
    r = client.call("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                   "clientInfo": {"name": "test", "version": "0"}})
    check(f"{label}: initialize answers with a protocol version and tools capability",
          r["result"]["protocolVersion"] == "2025-06-18" and "tools" in r["result"]["capabilities"], r)
    client.notify("notifications/initialized")

    r = client.call("tools/list")
    names = {t["name"] for t in r["result"]["tools"]}
    check(f"{label}: tools/list names the six tools",
          names == {"md_to_pdf", "template_list", "template_info", "render_template",
                    "pdf_preview", "measure_text"}, names)
    check(f"{label}: every tool has an inputSchema object",
          all(t["inputSchema"]["type"] == "object" for t in r["result"]["tools"]))

    res = tool(client, "md_to_pdf", markdown="# Тест\n\n## Раздел\n\nКирилица и таблица.\n\n"
                                            "| A | B |\n|---|---|\n| 1 | 2 |\n",
               output_name="t1", title="Тест")
    blob = pdf_blob(res)
    check(f"{label}: md_to_pdf returns a PDF blob", not res["isError"] and blob[:5] == b"%PDF-", res["content"][0])
    check(f"{label}: md_to_pdf text names 1 page", "1 page," in res["content"][0]["text"], res["content"][0])

    res = tool(client, "template_list")
    check(f"{label}: template_list lists report, protocol and tk_card",
          all(n in res["content"][0]["text"] for n in ("report", "protocol", "tk_card")))

    res = tool(client, "template_info", template="report")
    info = json.loads(res["content"][0]["text"])
    check(f"{label}: template_info returns schema and sample", "schema" in info and "sample" in info)

    res = tool(client, "render_template", template="report", data=info["sample"], output_name="rep")
    check(f"{label}: render_template renders the sample to a PDF",
          not res["isError"] and pdf_blob(res)[:5] == b"%PDF-", res["content"][0])

    res = tool(client, "render_template", template="protocol",
               data=json.loads(tool(client, "template_info", template="protocol")["content"][0]["text"])["sample"])
    check(f"{label}: the protocol template renders too", not res["isError"], res["content"][0])

    tk = json.loads(tool(client, "template_info", template="tk_card")["content"][0]["text"])["sample"]
    res = tool(client, "render_template", template="tk_card", data=tk, output_name="tk1001")
    check(f"{label}: the tk_card template renders",
          not res["isError"] and pdf_blob(res)[:5] == b"%PDF-", res["content"][0])
    res = tool(client, "render_template", template="tk_card",
               data={"order": {"oord_id": "x", "name": "n", "customer": "c"}, "params": []})
    check(f"{label}: tk_card rejects a non-integer oord_id",
          res["isError"] and "oord_id: expected integer" in res["content"][0]["text"], res["content"][0])

    res = tool(client, "render_template", template="report", data={"title": "x"})
    check(f"{label}: missing fields are an isError with the field names",
          res["isError"] and "author: required" in res["content"][0]["text"], res["content"][0])

    res = tool(client, "render_template", template="nope", data={})
    check(f"{label}: an unknown template is an isError", res["isError"])

    res = tool(client, "pdf_preview", file="rep", page=1, dpi=50)
    img = [c for c in res["content"] if c["type"] == "image"]
    png = base64.b64decode(img[0]["data"]) if img else b""
    check(f"{label}: pdf_preview returns a PNG", not res["isError"] and png[:8] == b"\x89PNG\r\n\x1a\n", res["content"][0])

    res = tool(client, "pdf_preview", file="../etc/passwd")
    check(f"{label}: a path with .. is refused", res["isError"])

    res = tool(client, "measure_text", text="Кирилица", font="Helvetica", size=10)
    m = json.loads(res["content"][0]["text"])
    check(f"{label}: measure_text gives a positive width", m["width_pt"] > 20, m)

    r = client.call("tools/call", {"name": "nope", "arguments": {}})
    check(f"{label}: unknown tool is a JSON-RPC error", "error" in r and r["error"]["code"] == -32602)
    r = client.call("no/such")
    check(f"{label}: unknown method is -32601", r.get("error", {}).get("code") == -32601)
    r = client.call("ping")
    check(f"{label}: ping answers", r.get("result") == {})


def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def main():
    out = tempfile.mkdtemp(prefix="pslib-mcp-test-")
    tokfile = os.path.join(out, "token")
    with open(tokfile, "w") as f:
        f.write("test-token-0123456789abcdef\n")
    http = None
    try:
        c = StdioClient(out)
        exercise(c, "stdio")
        rc = c.close()
        check("stdio: server exits 0 on stdin EOF", rc == 0, rc)

        port = free_port()
        http = subprocess.Popen([PY, SERVER, "--http", f"127.0.0.1:{port}", "--token-file", tokfile,
                                 "--out-dir", out], stderr=subprocess.PIPE)
        url = f"http://127.0.0.1:{port}/mcp"
        hc = HttpClient(url, "test-token-0123456789abcdef")
        deadline = time.time() + 5
        up = False
        while time.time() < deadline and not up:
            try:
                hc.call("ping"); up = True
            except (urllib.error.URLError, ConnectionError):
                time.sleep(0.1)
        check("http: server comes up", up)
        exercise(hc, "http")
        st = hc.notify("notifications/initialized")
        check("http: a notification is answered 202", st == 202, st)
        try:
            hc.post({"jsonrpc": "2.0", "id": 99, "method": "ping"}, token="wrong")
            check("http: a wrong token is refused", False)
        except urllib.error.HTTPError as e:
            check("http: a wrong token is refused with 401", e.code == 401, e.code)
        try:
            urllib.request.urlopen(url, timeout=5)
            check("http: GET is refused", False)
        except urllib.error.HTTPError as e:
            check("http: GET is refused with 405", e.code == 405, e.code)

        r = subprocess.run([PY, SERVER, "--http", "127.0.0.1:1", "--token-file", os.path.join(out, "none")],
                           capture_output=True, text=True)
        check("http: no token file means refuse to start", r.returncode != 0 and "token" in r.stderr, r.stderr)
    finally:
        if http is not None:
            http.terminate()
            try:
                http.wait(timeout=5)
            except subprocess.TimeoutExpired:
                http.kill()
        shutil.rmtree(out, ignore_errors=True)

    print(f"\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
