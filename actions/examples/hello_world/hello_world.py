"""Example action: greets the current selection via the host bridge."""

import anchorpoint

ctx = anchorpoint.get_context()
target = ctx.path or ctx.folder or "(nothing selected)"
anchorpoint.UI().show_success("Hello World", f"Hello from {target}")
