import os
import runpy


os.environ["PORT"] = "5055"
runpy.run_path("app.py", run_name="__main__")
