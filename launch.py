import multiprocessing
import os
from pathlib import Path
import traceback

if __name__ == "__main__":
    multiprocessing.freeze_support()
    try:
        from even_r1.ui import main
        main()
    except Exception:
        path = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "EvenR1Remote"
        path.mkdir(parents=True, exist_ok=True)
        (path / "startup-error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
