# main.py
from contextlib import asynccontextmanager

from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP

# MCP 서버: 네 알고리즘을 tool로 감싼다
mcp = FastMCP(
    "Algo Server",
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",   # /mcp 아래에 바로 노출되게 함
)

@mcp.tool()
def double(x: int) -> int:
    """x를 두 배로 만든다."""
    return x * 2


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp.session_manager.run():
        yield

app = FastAPI(lifespan=lifespan)

@app.get("/health")
def health():
    return {"ok": True}

# MCP endpoint: https://your-domain.com/mcp
app.mount("/mcp", mcp.streamable_http_app())