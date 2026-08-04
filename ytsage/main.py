"""YTSage server entrypoint.

The project now starts the Linux/Docker-oriented web server by default. The
legacy PySide6 GUI modules remain in the source tree as migration reference,
but this entrypoint intentionally does not import Qt.
"""

from .server.app import main


if __name__ == "__main__":
    main()
