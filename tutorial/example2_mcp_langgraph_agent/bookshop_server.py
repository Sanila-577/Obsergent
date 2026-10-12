"""bookshop_server.py - a small custom MCP server with two tools.

Run on its own (it waits for a client on stdin/stdout):
    python bookshop_server.py
"""
import json  # tools return their data as JSON text
import os  # to read the MCP_TRACING environment variable

from mcp.server.fastmcp import FastMCP  # high-level helper for building MCP servers

# The name clients see when they connect to this server.
mcp = FastMCP("Bookshop")

# A fake in-memory database of books: id -> details.
CATALOG = {
    "b1": {"title": "Python Crash Course", "author": "Eric Matthes", "price": 39.99, "stock": 4},
    "b2": {"title": "Fluent Python", "author": "Luciano Ramalho", "price": 59.99, "stock": 0},
    "b3": {"title": "Designing Data-Intensive Applications", "author": "Martin Kleppmann", "price": 49.99, "stock": 2},
    "b4": {"title": "AI Engineering", "author": "Chip Huyen", "price": 54.99, "stock": 7},
}


# @mcp.tool() registers the function as an MCP tool. FastMCP reads the function
# name, the type hints (-> the tool's input schema) and the docstring.
@mcp.tool()
def search_books(query: str) -> str:
    # This docstring is sent to the model: it is how the model decides WHEN to use the tool.
    """Search the catalog by words in the title or author. Returns matching books with their ids."""
    words = query.lower().split()  # "Python book" -> ["python", "book"]
    hits = [
        {"id": book_id, "title": b["title"], "author": b["author"]}
        for book_id, b in CATALOG.items()
        # Keep a book if ANY query word appears in its title or author (case-insensitive).
        if any(w in (b["title"] + " " + b["author"]).lower() for w in words)
    ]
    return json.dumps(hits)  # MCP tools here return text, so encode the list as JSON


@mcp.tool()
def get_price_and_stock(book_id: str) -> str:
    """Get the price (USD) and number of copies in stock for one book id, e.g. 'b1'."""
    book = CATALOG.get(book_id)  # None if the id doesn't exist
    if book is None:
        # Return an error message as data so the model can read it and react.
        return json.dumps({"error": f"unknown book id {book_id}"})
    return json.dumps({"id": book_id, "price_usd": book["price"], "in_stock": book["stock"]})


# Runs only when you execute this file directly (the agent starts it as a child process).
if __name__ == "__main__":
    # Tracing is on by default; set MCP_TRACING=0 to turn it off.
    if os.environ.get("MCP_TRACING", "1") != "0":
        # Imported here so the server also runs without the tracing files.
        from mcp_tracing import instrument_server
        from tracker import setup_tracing

        setup_tracing("bookshop-server")  # spans go to the same traces.db as the agent's
        instrument_server(mcp)  # one SERVER span per incoming MCP request
    # Start serving. stdio = read requests from stdin, write replies to stdout,
    # so never print() to stdout in this file: it would corrupt the protocol.
    mcp.run()
