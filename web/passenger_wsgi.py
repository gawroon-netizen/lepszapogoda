"""Passenger entry point on mydevil (SPEC §7.4). Linked as ~/domains/lepszapogoda.pl/public_python/passenger_wsgi.py.

mydevil sets a site's Python only when the site is created, so this file switches to the project virtualenv itself
(the standard Passenger pattern): when started by another interpreter it re-executes the loader with the venv's
python. sys.prefix is compared, not the executable path: the venv's python is a symlink to the system one.
"""

import os
import sys

BASE = os.path.join(os.path.expanduser("~"), "domains", "lepszapogoda.pl")
VENV = os.path.join(BASE, "venv")
VENV_PYTHON = os.path.join(VENV, "bin", "python")

if os.path.exists(VENV_PYTHON) and os.path.realpath(sys.prefix) != os.path.realpath(VENV):
    os.execl(VENV_PYTHON, VENV_PYTHON, *sys.argv)

sys.path.insert(0, os.path.join(BASE, "app"))

from web.app import create_app  # noqa: E402

application = create_app()
