"""Allow `python -m stock <command>` to invoke the typer app."""
from __future__ import annotations

from stock.cli import app

if __name__ == "__main__":
    app()
