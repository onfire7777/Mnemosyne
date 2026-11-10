"""Pure expression experiments: no attributes, imports, files or network calls.

The child process interprets an allowlisted AST rather than evaluating Python.
Input/output limits, an operation budget and a process timeout bound experiments.
"""

from __future__ import annotations

import ast
import json
import operator
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

def _contains_sequence(sequence, steps):
    if not isinstance(sequence, list) or not isinstance(steps, list) or not steps:
        return False
    if len(sequence) > 256 or len(steps) > 64:
        raise ValueError("sequence exceeds limit")
    iterator = iter(sequence)
    return all(any(value == step for value in iterator) for step in steps)


_CALLS = {"contains_sequence": _contains_sequence, "sorted": sorted, "len": len, "sum": sum, "min": min, "max": max,
          "abs": abs, "round": round, "str": str, "int": int, "float": float,
          "bool": bool, "list": list, "tuple": tuple, "all": all, "any": any}
_BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod}
_COMPARE = {ast.Eq: operator.eq, ast.NotEq: operator.ne, ast.Lt: operator.lt,
            ast.LtE: operator.le, ast.Gt: operator.gt, ast.GtE: operator.ge,
            ast.In: lambda a, b: a in b, ast.NotIn: lambda a, b: a not in b}


def _evaluate(expression, value):
    if not isinstance(expression, str) or len(expression) > 4096:
        raise ValueError("expression exceeds limit")
    root = ast.parse(expression, mode="eval")
    budget = [1000]
    def visit(node):
        budget[0] -= 1
        if budget[0] < 0:
            raise ValueError("operation limit")
        if isinstance(node, ast.Constant) and type(node.value) in {str, int, float, bool, type(None)}:
            result = node.value
        elif isinstance(node, ast.Name) and node.id == "value":
            result = value
        elif isinstance(node, (ast.List, ast.Tuple)):
            result = [visit(item) for item in node.elts]
        elif isinstance(node, ast.Dict):
            result = {visit(key): visit(item) for key, item in zip(node.keys, node.values, strict=True)}
        elif isinstance(node, ast.Subscript):
            result = visit(node.value)[visit(node.slice)]
        elif isinstance(node, ast.Slice):
            return slice(visit(node.lower) if node.lower else None, visit(node.upper) if node.upper else None,
                         visit(node.step) if node.step else None)
        elif isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Mult) and not (type(left) in {float, int} and type(right) in {float, int}):
                raise ValueError("sequence multiplication is not permitted")
            if isinstance(node.op, ast.Mod) and not (type(left) in {float, int} and type(right) in {float, int}):
                raise ValueError("string formatting is not permitted")
            result = _BINARY[type(node.op)](left, right)
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd, ast.Not)):
            result = {ast.USub: operator.neg, ast.UAdd: operator.pos, ast.Not: operator.not_}[type(node.op)](visit(node.operand))
        elif isinstance(node, ast.Compare) and all(type(op) in _COMPARE for op in node.ops):
            values = [visit(node.left), *[visit(item) for item in node.comparators]]
            result = all(_COMPARE[type(op)](values[i], values[i + 1]) for i, op in enumerate(node.ops))
        elif isinstance(node, ast.IfExp):
            result = visit(node.body if visit(node.test) else node.orelse)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in _CALLS and not node.keywords:
            result = _CALLS[node.func.id](*[visit(item) for item in node.args])
        else:
            raise ValueError("operation is not permitted")
        if len(json.dumps(result, allow_nan=False)) > 65536:
            raise ValueError("result exceeds limit")
        if type(result) is int and abs(result) > 10 ** 100:
            raise ValueError("number exceeds limit")
        return result
    return visit(root.body)


def run_experiment(check):
    if (not isinstance(check, dict) or check.get("kind") not in {"python_expression", "observed_trace_replay"}
            or check.get("version") != 1):
        return {"status": "inconclusive", "reason": "unsupported_sandbox_check"}
    cases = check.get("cases")
    if not isinstance(cases, list) or not 1 <= len(cases) <= 32:
        return {"status": "inconclusive", "reason": "invalid_sandbox_cases"}
    payload = json.dumps({"expression": check.get("expression"), "cases": cases}, allow_nan=False)
    if len(payload) > 65536:
        return {"status": "inconclusive", "reason": "sandbox_input_limit"}
    with TemporaryDirectory(prefix="mnemosyne-review-") as cwd:
        try:
            process = subprocess.run([sys.executable, "-I", "-S", str(Path(__file__).resolve())],
                                     input=payload, text=True, capture_output=True, cwd=cwd,
                                     env={"PATH": os.defpath, "PYTHONHASHSEED": "0"}, timeout=2, check=False)
        except subprocess.TimeoutExpired:
            return {"status": "inconclusive", "reason": "sandbox_timeout"}
    if process.returncode or len(process.stdout) > 131072:
        return {"status": "inconclusive", "reason": "sandbox_process_failed"}
    return json.loads(process.stdout)


def _main():
    try:
        request = json.loads(sys.stdin.read(65537))
        results = []
        for case in request["cases"]:
            actual = _evaluate(request["expression"], case["input"])
            results.append({"actual": actual, "expected": case["expected"],
                            "passed": actual == case["expected"]})
        passed = sum(item["passed"] for item in results)
        result = {"status": "passed" if passed == len(results) else "failed",
                  "passed": passed, "failed": len(results) - passed, "results": results}
    except Exception as exc:
        result = {"status": "inconclusive", "reason": "sandbox_operation_refused", "error_type": type(exc).__name__}
    sys.stdout.write(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    _main()
