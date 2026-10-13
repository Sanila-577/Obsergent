"""bookshop_server.py - the same Bookshop MCP server as example 2 (no tracing).

The agent starts this file itself as a child process (stdio), so you never
have to run it by hand. In this example only the agent side is traced (MCP messages come in example 5),
so the server needs no tracing code.
"""
import json  # tools return their data as JSON text

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


# Runs only when this file is executed directly (the agent does that for us).
if __name__ == "__main__":
    # stdio = read requests from stdin, write replies to stdout, so never
    # print() to stdout in this file: it would corrupt the protocol.
    mcp.run()
