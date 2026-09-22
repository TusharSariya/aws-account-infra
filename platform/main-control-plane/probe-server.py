#!/usr/bin/env python3
from http.server import BaseHTTPRequestHandler, HTTPServer


class Probe(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"main-control-plane-network-probe\n")


HTTPServer(("0.0.0.0", 16443), Probe).serve_forever()
