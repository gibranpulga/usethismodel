"""Combined ASGI entry point for the Flask site and read-only MCP endpoint."""

from app import create_app
from app.mcp_server import create_http_app

flask_app = create_app()
app = create_http_app(flask_app)
