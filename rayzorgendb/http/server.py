"""
RayzorgenDB HTTP REST API
Pure stdlib, no external dependencies.
"""

import json
import re
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from rayzorgendb import RayzorgenDB
from rayzorgendb.config import DEFAULT_CONFIG


SAFE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class Handler(BaseHTTPRequestHandler):
    db = None

    def log_message(self, *args, **kwargs):
        pass

    # --------------------------------------------------------
    # Utilities
    # --------------------------------------------------------

    def _json(self, code, payload):
        try:
            body = json.dumps(payload, default=str).encode()
        except (TypeError, ValueError):
            body = b'{"error":"serialization failed"}'
            code = 500
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _body(self):
        n = int(self.headers.get("Content-Length", 0) or 0)
        if n <= 0 or n > 10_000_000:
            return {}
        try:
            raw = self.rfile.read(n).decode("utf-8")
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except (json.JSONDecodeError, UnicodeDecodeError, IOError):
            return {}

    def _qs(self):
        return parse_qs(urlparse(self.path).query)

    def _int(self, qs, key, default):
        try:
            return int(qs.get(key, [default])[0])
        except (ValueError, TypeError):
            return default

    # --------------------------------------------------------
    # GET
    # --------------------------------------------------------

    def do_GET(self):
        path = urlparse(self.path).path
        qs = self._qs()

        if path == "/health":
            return self._json(200, self.db.health())
        if path == "/stats":
            return self._json(200, self.db.stats())
        if path == "/collections":
            return self._json(200, {
                "collections": self.db.collections()
            })

        # GET /{collection}/count
        m = re.match(r"^/([A-Za-z0-9_-]+)/count$", path)
        if m:
            name = m.group(1)
            if not self.db.has_collection(name):
                return self._json(404, {"error": "not found"})
            return self._json(200, {
                "count": self.db.collection(name).count()
            })

        # GET /{collection}/search?q=X
        m = re.match(r"^/([A-Za-z0-9_-]+)/search$", path)
        if m:
            name = m.group(1)
            kw = qs.get("q", [""])[0]
            if not kw:
                return self._json(400, {"error": "q required"})
            limit = self._int(qs, "limit", 50)
            results = self.db.collection(name).search(kw, limit)
            return self._json(200, {
                "results": [r.to_dict() for r in results],
                "count": len(results),
            })

        # GET /{collection}/aggregate?field=X&op=sum
        m = re.match(r"^/([A-Za-z0-9_-]+)/aggregate$", path)
        if m:
            name = m.group(1)
            field = qs.get("field", [None])[0]
            op = qs.get("op", ["sum"])[0]
            if not field:
                return self._json(400, {"error": "field required"})
            return self._json(200, {
                "value": self.db.collection(name).aggregate(field, op)
            })

        # GET /{collection}
        m = re.match(r"^/([A-Za-z0-9_-]+)$", path)
        if m:
            name = m.group(1)
            if not self.db.has_collection(name):
                return self._json(404, {"error": "not found"})
            limit = self._int(qs, "limit", 50)
            records = self.db.collection(name).all(limit=limit)
            return self._json(200, {
                "records": [r.to_dict() for r in records],
                "count": len(records),
            })

        # GET /{collection}/{id}
        m = re.match(r"^/([A-Za-z0-9_-]+)/([A-Za-z0-9_-]+)$", path)
        if m:
            name, rid = m.groups()
            rec = self.db.collection(name).get(rid)
            if rec:
                return self._json(200, rec.to_dict())
            return self._json(404, {"error": "not found"})

        self._json(404, {"error": "route not found"})

    # --------------------------------------------------------
    # POST
    # --------------------------------------------------------

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._body()

        # POST /{collection}/_query
        m = re.match(r"^/([A-Za-z0-9_-]+)/_query$", path)
        if m:
            name = m.group(1)
            if not self.db.has_collection(name):
                return self._json(404, {"error": "not found"})
            q = self.db.collection(name).query()
            for f in body.get("filters", []):
                try:
                    q = q.where(
                        f["field"],
                        f.get("op", "eq"),
                        f.get("value"),
                    )
                except (KeyError, TypeError):
                    continue
            if body.get("order_by"):
                q = q.order_by(
                    body["order_by"],
                    body.get("desc", False),
                )
            if body.get("limit"):
                q = q.limit(int(body["limit"]))
            records = q.all()
            return self._json(200, {
                "records": [
                    r.to_dict() if hasattr(r, "to_dict") else r
                    for r in records
                ],
                "count": len(records),
            })

        # POST /{collection}/_vector
        m = re.match(r"^/([A-Za-z0-9_-]+)/_vector$", path)
        if m:
            name = m.group(1)
            vec = body.get("vector")
            if not isinstance(vec, list):
                return self._json(400, {"error": "vector required"})
            top_k = int(body.get("top_k", 5))
            results = self.db.collection(name).vector_search(vec, top_k)
            return self._json(200, {"results": results})

        # POST /{collection}/_index
        m = re.match(r"^/([A-Za-z0-9_-]+)/_index$", path)
        if m:
            name = m.group(1)
            field = body.get("field")
            if not field:
                return self._json(400, {"error": "field required"})
            self.db.collection(name).create_index(field)
            return self._json(200, {
                "indexes": self.db.collection(name).indexes()
            })

        # POST /{collection}
        m = re.match(r"^/([A-Za-z0-9_-]+)$", path)
        if m:
            name = m.group(1)
            rec = self.db.collection(name).insert(body)
            return self._json(201, rec.to_dict())

        self._json(404, {"error": "route not found"})

    # --------------------------------------------------------
    # PUT
    # --------------------------------------------------------

    def do_PUT(self):
        path = urlparse(self.path).path
        body = self._body()
        m = re.match(r"^/([A-Za-z0-9_-]+)/([A-Za-z0-9_-]+)$", path)
        if m:
            name, rid = m.groups()
            rec = self.db.collection(name).update(rid, body)
            if rec:
                return self._json(200, rec.to_dict())
            return self._json(404, {"error": "not found"})
        self._json(404, {"error": "route not found"})

    # --------------------------------------------------------
    # DELETE
    # --------------------------------------------------------

    def do_DELETE(self):
        path = urlparse(self.path).path

        # DELETE /{collection}/_index/{field}
        m = re.match(
            r"^/([A-Za-z0-9_-]+)/_index/([A-Za-z0-9_-]+)$",
            path,
        )
        if m:
            name, field = m.groups()
            ok = self.db.collection(name).drop_index(field)
            return self._json(200, {"dropped": ok})

        # DELETE /{collection}/{id}
        m = re.match(r"^/([A-Za-z0-9_-]+)/([A-Za-z0-9_-]+)$", path)
        if m:
            name, rid = m.groups()
            ok = self.db.collection(name).delete(rid)
            return self._json(200 if ok else 404, {"deleted": ok})

        # DELETE /{collection}
        m = re.match(r"^/([A-Za-z0-9_-]+)$", path)
        if m:
            ok = self.db.drop_collection(m.group(1))
            return self._json(200 if ok else 404, {"dropped": ok})

        self._json(404, {"error": "route not found"})

    # --------------------------------------------------------
    # OPTIONS (CORS)
    # --------------------------------------------------------

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header(
            "Access-Control-Allow-Methods",
            "GET, POST, PUT, DELETE, OPTIONS",
        )
        self.send_header(
            "Access-Control-Allow-Headers",
            "Content-Type",
        )
        self.end_headers()


def run_server(host=None, port=None, config=None, threaded=True):
    config = config or DEFAULT_CONFIG
    host = host or config.HTTP_HOST
    port = port or config.HTTP_PORT

    Handler.db = RayzorgenDB(config)

    if threaded:
        from socketserver import ThreadingMixIn

        class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
            daemon_threads = True

        server = ThreadedHTTPServer((host, port), Handler)
    else:
        server = HTTPServer((host, port), Handler)

    print("RayzorgenDB HTTP API: http://" + host + ":" + str(port))
    print("Try: curl http://localhost:" + str(port) + "/health")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    run_server()
