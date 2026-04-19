#!/usr/bin/env python
"""Run shop populate_db inside the running Flask app context."""
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

from vbwd.app import create_app

app = create_app()
with app.app_context():
    from plugins.shop.populate_db import populate
    populate(app)
    print("Shop populate complete.")
