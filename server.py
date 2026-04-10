from fastmcp import FastMCP

mcp = FastMCP("my-first-mcp")

@mcp.tool()
def hello(name: str) -> str:
    return f"Hello, {name}!"

@mcp.tool()
def add(a: float, b: float) -> float:
    return a + b

if __name__ == "__main__":
    # mcp.run(transport="stdio")
    mcp.run(transport="http", port=8000)
