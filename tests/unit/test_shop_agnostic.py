"""S101.0 — shop stays pharma-agnostic.

Shop is a generic commerce module; it must NOT name any downstream vertical
(e.g. the pharma module). This oracle AST-greps shop's source for the ``pharma``
token. If it trips, a pharma concept leaked into shop — move it to the pharma
module instead (the pharma module depends on shop, never the reverse).
"""
import os

SHOP_SOURCE_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "shop")
)


def _python_files(root):
    for current_dir, _dirs, files in os.walk(root):
        if "__pycache__" in current_dir:
            continue
        for name in files:
            if name.endswith(".py"):
                yield os.path.join(current_dir, name)


def test_shop_source_names_no_pharma():
    offenders = []
    for path in _python_files(SHOP_SOURCE_ROOT):
        with open(path, "r", encoding="utf-8") as handle:
            if "pharma" in handle.read().lower():
                offenders.append(path)
    assert not offenders, (
        "Pharma vocabulary leaked into the shop module — keep shop agnostic: "
        f"{offenders}"
    )
