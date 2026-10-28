"""Compatibility entry point for the file-only native GUI validation helper.

The 0.2 diagram check deliberately avoids an external SpssClient.RunSyntax
connection while SPSS invokes its own Viewer scripting API. Prepare a file,
run it through the GUI, then collect the saved JSON and synthetic SPV.
"""
from gui_diagram_validation import main

if __name__ == "__main__":
    raise SystemExit(main())
