"""Team coding standard (Oct 1 meeting): no function longer than 20 lines.

The docstring does not count. Checks the API, the worker, the evaluation tool and the shared code.
Run: python -m unittest tests.code_standards_test   (from backend/)
"""
import ast
import os
import unittest
from pathlib import Path

MAX_LINES = 20
BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
# Works from a checkout (all three folders) and inside the backend container (app + /srv/shared).
CANDIDATES = [BACKEND / "app", ROOT / "worker" / "worker", ROOT / "worker" / "evaluation", Path(os.getenv("SHARED_DIR", ROOT / "shared"))]
SOURCES = [folder for folder in CANDIDATES if folder.is_dir()]


def _body_lines(node: ast.AST) -> int:
    body = list(node.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(getattr(body[0], "value", None), ast.Constant):
        body = body[1:]
    return body[-1].end_lineno - body[0].lineno + 1 if body else 0


def long_functions() -> list[str]:
    found = []
    for folder in SOURCES:
        for path in sorted(folder.rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _body_lines(node) > MAX_LINES:
                    found.append(f"{path.relative_to(folder.parent)}:{node.lineno} {node.name} ({_body_lines(node)} lines)")
    return found


class CodeStandardsTests(unittest.TestCase):
    def test_no_function_longer_than_20_lines(self):
        self.assertEqual(long_functions(), [], "Split these functions into smaller helpers")


if __name__ == "__main__":
    unittest.main()
