#!/usr/bin/python3
"""mcp_server.py -- pslib as an MCP server (Model Context Protocol).

One process, two transports:

  stdio   `python3 mcp_server.py`               -- a child of one Claude Code
                                                    session, newline-delimited
                                                    JSON-RPC on stdin/stdout
  http    `python3 mcp_server.py --http HOST:PORT` -- one shared server,
                                                    Streamable HTTP: JSON-RPC
                                                    POSTed to /mcp, bearer token

Register in Claude Code:
  claude mcp add pslib -- /usr/bin/python3 /path/to/mcp_server.py
  claude mcp add --transport http pslib http://192.0.2.10:7462/mcp \
      --header "Authorization: Bearer <token>"

Every tool is stateless: the call renders, the PDF (or PNG) comes back in the
response as inline content and is also written under --out-dir, so a client on
another machine gets the bytes without a shared filesystem. Templates live in
templates.py (the registry is code, not files): a client names a template and
sends the data, nothing else.

Only the standard library plus pslib/md2ps (and jinja2 for templates).
"""
import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pslib import PSDoc                      # noqa: E402
from md2ps import md_to_pdf, MdConfig        # noqa: E402
import templates                             # noqa: E402

SERVER_NAME = "pslib"
SERVER_VERSION = "0.1"
PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

OUT_DIR = os.path.join(os.path.expanduser("~"), "pslib-out")
GS = "/usr/bin/gs"

INSTRUCTIONS = (
    "pslib renders print-ready PDF (A4, CP1251 cyrillic) from markdown or from a "
    "named template plus data. Call template_list first when the document has a "
    "known shape; md_to_pdf for free-form text. Every PDF comes back inline "
    "(resource blob) and is written on the server under its out dir. Use "
    "pdf_preview to look at a page before trusting the layout."
)


# ── output files ────────────────────────────────────────────────────────────

class ToolError(Exception):
    """A user-facing tool failure -- becomes isError=true, never a crash."""


def safe_out_path(name, ext):
    """A file name (no directories) under OUT_DIR with the wanted extension."""
    name = (name or "").strip()
    if not name:
        name = "document"
    if "/" in name or name.startswith(".") or ".." in name:
        raise ToolError("output_name must be a plain file name, no directories")
    if not name.lower().endswith(ext):
        name += ext
    os.makedirs(OUT_DIR, exist_ok=True)
    return os.path.join(OUT_DIR, name)


def read_b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def pdf_pages(path):
    """Page count via gs (pdftops-free, works on every host gs is on)."""
    r = subprocess.run(
        [GS, "-q", "-dNODISPLAY", "-dNOSAFER", "-c",
         f"({path}) (r) file runpdfbegin pdfpagecount = quit"],
        capture_output=True)
    try:
        return int(r.stdout.decode().strip().splitlines()[-1])
    except (ValueError, IndexError):
        return 0


def pdf_result(path, extra_text=""):
    ps = path[:-4] + ".ps"                  # PSDoc's intermediate, not a deliverable
    if os.path.exists(ps):
        os.unlink(ps)
    pages = pdf_pages(path)
    text = f"{os.path.basename(path)}: {pages} page{'s' if pages != 1 else ''}, " \
           f"{os.path.getsize(path)} bytes, saved as {path}"
    if extra_text:
        text += "\n" + extra_text
    return {
        "content": [
            {"type": "text", "text": text},
            {"type": "resource", "resource": {
                "uri": "file://" + path,
                "mimeType": "application/pdf",
                "blob": read_b64(path),
            }},
        ],
        "isError": False,
    }


# ── tools ───────────────────────────────────────────────────────────────────

def tool_md_to_pdf(args):
    md = args.get("markdown")
    if not isinstance(md, str) or not md.strip():
        raise ToolError("markdown must be a non-empty string")
    out = safe_out_path(args.get("output_name"), ".pdf")
    cfg = MdConfig(**{k: v for k, v in (args.get("config") or {}).items()
                      if hasattr(MdConfig(), k)})
    overlays = args.get("overlays")          # None -> footer + QR defaults
    if overlays is not None and not isinstance(overlays, list):
        raise ToolError("overlays must be a list of {type: watermark|footer|qr, ...}")
    title = args.get("title") or "Document"
    md_to_pdf(md, out, cfg=cfg, overlays=overlays, title=title)
    return pdf_result(out)


def tool_render_template(args):
    name = args.get("template")
    data = args.get("data")
    if not isinstance(data, dict):
        raise ToolError("data must be an object")
    tpl = templates.get(name)
    if tpl is None:
        raise ToolError(f"unknown template {name!r}; call template_list")
    problems = templates.validate(tpl, data)
    if problems:
        raise ToolError("data does not fit the template schema:\n  " + "\n  ".join(problems))
    out = safe_out_path(args.get("output_name") or name, ".pdf")
    if tpl.render_pdf is not None:          # a PSDoc-drawn template
        tpl.render_pdf(data, out)
    else:                                   # markdown through jinja2 + md2ps
        md = templates.render(tpl, data)
        cfg = MdConfig(**tpl.config)
        md_to_pdf(md, out, cfg=cfg, overlays=tpl.overlays,
                  title=data.get("title") or tpl.description)
    return pdf_result(out, f"template {tpl.name} v{tpl.version}")


def tool_template_list(args):
    rows = [f"- {t.name} (v{t.version}): {t.description}" for t in templates.all()]
    return {"content": [{"type": "text", "text": "\n".join(rows) or "(no templates)"}],
            "isError": False}


def tool_template_info(args):
    tpl = templates.get(args.get("template"))
    if tpl is None:
        raise ToolError(f"unknown template {args.get('template')!r}; call template_list")
    info = {"name": tpl.name, "version": tpl.version, "description": tpl.description,
            "schema": tpl.schema, "sample": tpl.sample}
    return {"content": [{"type": "text", "text": json.dumps(info, ensure_ascii=False, indent=2)}],
            "isError": False}


def tool_pdf_preview(args):
    name = args.get("file")
    if not isinstance(name, str) or not name:
        raise ToolError("file is the name of a PDF under the out dir")
    pdf = safe_out_path(name, ".pdf")
    if not os.path.exists(pdf):
        raise ToolError(f"no such file under the out dir: {os.path.basename(pdf)}")
    page = int(args.get("page") or 1)
    dpi = int(args.get("dpi") or 72)
    if page < 1 or dpi < 36 or dpi > 200:
        raise ToolError("page >= 1, 36 <= dpi <= 200")
    fd, png = tempfile.mkstemp(prefix="pslib-preview-", suffix=".png")
    os.close(fd)
    try:
        r = subprocess.run(
            [GS, "-q", "-dBATCH", "-dNOPAUSE", "-sDEVICE=png16m", f"-r{dpi}",
             f"-dFirstPage={page}", f"-dLastPage={page}", f"-sOutputFile={png}", pdf],
            capture_output=True)
        if r.returncode != 0 or os.path.getsize(png) == 0:
            raise ToolError("gs could not render that page: "
                            + r.stderr.decode("utf-8", "replace")[-400:])
        data = read_b64(png)
    finally:
        os.unlink(png)
    return {"content": [
        {"type": "text", "text": f"{os.path.basename(pdf)} page {page} at {dpi} dpi"},
        {"type": "image", "data": data, "mimeType": "image/png"},
    ], "isError": False}


def tool_measure_text(args):
    font = args.get("font") or "Helvetica"
    size = float(args.get("size") or 10)
    text = args.get("text")
    if not isinstance(text, str):
        raise ToolError("text must be a string")
    fd, ps = tempfile.mkstemp(prefix="pslib-measure-", suffix=".ps")
    os.close(fd)
    try:
        doc = PSDoc(ps)
        doc.font(font, size)
        width = doc.string_width(text)
    finally:
        os.unlink(ps)
    return {"content": [{"type": "text",
                         "text": json.dumps({"font": font, "size": size, "width_pt": round(width, 2),
                                             "width_mm": round(width * 0.3528, 2)})}],
            "isError": False}


TOOLS = [
    {
        "name": "md_to_pdf",
        "description": "Render markdown (title, ##/###/#### headings, paragraphs, bullets, "
                       "numbered lists, code blocks, pipe tables) to an A4 PDF with cyrillic "
                       "support. Default overlays: footer with timestamp and page numbers, "
                       "per-page QR with an RSC code. Returns the PDF inline.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "markdown": {"type": "string", "description": "the document text"},
                "output_name": {"type": "string", "description": "file name under the out dir, .pdf added"},
                "title": {"type": "string"},
                "config": {"type": "object", "description": "MdConfig overrides, e.g. body_size, margin_left"},
                "overlays": {"type": "array", "description": "[] for none; items {type: watermark|footer|qr, ...}",
                             "items": {"type": "object"}},
            },
            "required": ["markdown"],
        },
        "handler": tool_md_to_pdf,
    },
    {
        "name": "template_list",
        "description": "The document templates this server holds, one line each.",
        "inputSchema": {"type": "object", "properties": {}},
        "handler": tool_template_list,
    },
    {
        "name": "template_info",
        "description": "A template's data schema and a sample data object.",
        "inputSchema": {"type": "object",
                        "properties": {"template": {"type": "string"}},
                        "required": ["template"]},
        "handler": tool_template_info,
    },
    {
        "name": "render_template",
        "description": "Render a named template with the given data to a PDF. The data is "
                       "validated against the template schema first; a missing or mistyped "
                       "field is an error, never a half-empty document.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "template": {"type": "string"},
                "data": {"type": "object"},
                "output_name": {"type": "string"},
            },
            "required": ["template", "data"],
        },
        "handler": tool_render_template,
    },
    {
        "name": "pdf_preview",
        "description": "One page of a PDF under the out dir as a PNG, to check the layout by eye.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "description": "PDF name under the out dir"},
                "page": {"type": "integer", "minimum": 1},
                "dpi": {"type": "integer", "minimum": 36, "maximum": 200},
            },
            "required": ["file"],
        },
        "handler": tool_pdf_preview,
    },
    {
        "name": "measure_text",
        "description": "Width of a string in a font at a size (points and mm), from the "
                       "same metrics pslib uses -- for sizing table columns before rendering.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "font": {"type": "string", "description": "Helvetica, Helvetica-Bold, Times-Roman, Courier, ..."},
                "size": {"type": "number"},
            },
            "required": ["text"],
        },
        "handler": tool_measure_text,
    },
]
TOOL_BY_NAME = {t["name"]: t for t in TOOLS}


# ── JSON-RPC ────────────────────────────────────────────────────────────────

def rpc_error(rid, code, message):
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def rpc_result(rid, result):
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def handle(msg):
    """One JSON-RPC message in, one response out (None for notifications)."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return rpc_error(None, -32600, "invalid request")
    method = msg.get("method")
    rid = msg.get("id")
    params = msg.get("params") or {}
    if method is None:                      # a response to something we never sent
        return None
    if rid is None:                         # notification
        return None

    if method == "initialize":
        asked = params.get("protocolVersion")
        version = asked if asked in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0]
        return rpc_result(rid, {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "instructions": INSTRUCTIONS,
        })
    if method == "ping":
        return rpc_result(rid, {})
    if method == "tools/list":
        return rpc_result(rid, {"tools": [
            {k: v for k, v in t.items() if k != "handler"} for t in TOOLS]})
    if method == "tools/call":
        name = params.get("name")
        tool = TOOL_BY_NAME.get(name)
        if tool is None:
            return rpc_error(rid, -32602, f"unknown tool {name!r}")
        args = params.get("arguments") or {}
        try:
            return rpc_result(rid, tool["handler"](args))
        except ToolError as e:
            return rpc_result(rid, {"content": [{"type": "text", "text": str(e)}], "isError": True})
        except Exception as e:              # a bug or gs failure: report, keep serving
            return rpc_result(rid, {"content": [{"type": "text",
                                                 "text": f"{type(e).__name__}: {e}"}],
                                    "isError": True})
    if method in ("resources/list", "resources/templates/list"):
        return rpc_result(rid, {"resources": [], "resourceTemplates": []})
    if method == "prompts/list":
        return rpc_result(rid, {"prompts": []})
    return rpc_error(rid, -32601, f"method not found: {method}")


# ── stdio transport ─────────────────────────────────────────────────────────

def serve_stdio():
    out = sys.stdout.buffer
    for line in sys.stdin.buffer:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply = rpc_error(None, -32700, "parse error")
        else:
            reply = handle(msg)
        if reply is not None:
            out.write(json.dumps(reply, ensure_ascii=False).encode("utf-8") + b"\n")
            out.flush()


# ── HTTP transport (Streamable HTTP, JSON responses) ───────────────────────

class Handler(BaseHTTPRequestHandler):
    token = None
    lock = threading.Lock()

    def log_message(self, fmt, *args):     # one line per request on stderr
        sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def _authed(self):
        auth = self.headers.get("Authorization", "")
        return auth == f"Bearer {self.token}"

    def do_GET(self):                       # no server-initiated stream here
        self.send_response(405)
        self.send_header("Allow", "POST")
        self.end_headers()

    def do_POST(self):
        if self.path.rstrip("/") != "/mcp":
            self.send_response(404); self.end_headers(); return
        if not self._authed():
            self.send_response(401)
            self.send_header("WWW-Authenticate", "Bearer")
            self.end_headers()
            return
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        try:
            msg = json.loads(body)
        except ValueError:
            reply = rpc_error(None, -32700, "parse error")
        else:
            if isinstance(msg, list):       # batch
                with self.lock:
                    replies = [r for r in (handle(m) for m in msg) if r is not None]
                reply = replies or None
            else:
                with self.lock:
                    reply = handle(msg)
        if reply is None:                   # notification or client response
            self.send_response(202)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        data = json.dumps(reply, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def serve_http(bind, token):
    host, _, port = bind.rpartition(":")
    Handler.token = token
    srv = ThreadingHTTPServer((host or "127.0.0.1", int(port)), Handler)
    sys.stderr.write(f"pslib mcp: http on {host or '127.0.0.1'}:{port}, out dir {OUT_DIR}\n")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


def main():
    global OUT_DIR
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--http", metavar="HOST:PORT",
                    help="serve Streamable HTTP on HOST:PORT instead of stdio")
    ap.add_argument("--token-file", default=os.path.expanduser("~/.pslib-mcp-token"),
                    help="bearer token for --http (default ~/.pslib-mcp-token)")
    ap.add_argument("--out-dir", default=OUT_DIR, help="where rendered files are written")
    a = ap.parse_args()
    OUT_DIR = a.out_dir
    if a.http:
        try:
            with open(a.token_file) as f:
                token = f.read().strip()
        except OSError:
            sys.exit(f"pslib mcp: --http needs a token in {a.token_file} (refusing to serve open)")
        if len(token) < 16:
            sys.exit("pslib mcp: the token is shorter than 16 characters -- refusing")
        serve_http(a.http, token)
    else:
        serve_stdio()


if __name__ == "__main__":
    main()
