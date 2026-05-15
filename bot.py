import os

PORT = int(os.getenv("PORT", "5000"))

try:
    from flask import Flask

    app = Flask(__name__)

    @app.route("/")
    def index():
        return "Netflix-Tv-Bot running (Flask)"

    if __name__ == "__main__":
        app.run(host="0.0.0.0", port=PORT)

except Exception:
    # Fallback to a tiny built-in HTTP server so local checks work without installing Flask
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Netflix-Tv-Bot running (fallback)")

    if __name__ == "__main__":
        HTTPServer(("", PORT), Handler).serve_forever()
