import sys

from .cli import main as cli_main
from .gui import script_main as gui_main


# A bundled Windows executable opens the GUI on a normal double click, while
# its child processes call the same executable with explicit CLI arguments.
raise SystemExit(cli_main() if len(sys.argv) > 1 else gui_main())
