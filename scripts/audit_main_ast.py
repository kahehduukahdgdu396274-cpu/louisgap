#!/usr/bin/env python3
"""审计main.py主要逻辑"""
import ast, sys

with open(sys.argv[1]) as f:
    tree = ast.parse(f.read())

# 收集所有try/except信息
issues = []
for node in ast.walk(tree):
    if isinstance(node, ast.Try):
        for h in node.handlers:
            if h.type is None or (isinstance(h.type, ast.Name) and h.type.id == 'Exception'):
                issues.append((node.lineno, f"except {ast.dump(h.type) if h.type else 'bare'}"))

print(f"总行数: {tree.body[-1].end_lineno if hasattr(tree.body[-1],'end_lineno') else '?'}")
print(f"try/except块: {len(set(i[0] for i in issues))}")
for lno, msg in sorted(issues):
    print(f"  行{lno}: {msg}")

# 检查关键函数
funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
print(f"\n函数列表 ({len(funcs)}):")
for fn in funcs:
    print(f"  {fn.name}(行{fn.lineno})")
