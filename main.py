import os
import sys

project_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "facebook_share_collector")
if os.path.isdir(project_dir):
    os.chdir(project_dir)
    if project_dir not in sys.path:
        sys.path.insert(0, project_dir)

from main import main

if __name__ == "__main__":
    main()
