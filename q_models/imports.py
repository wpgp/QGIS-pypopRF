import os
import sys

def setup_pypoprf_path():
    plugin_dir = os.path.dirname(os.path.dirname(__file__))
    pypoprf_dir = os.path.join(plugin_dir, 'pypoprf', 'src')
    if pypoprf_dir not in sys.path:
        sys.path.append(pypoprf_dir)