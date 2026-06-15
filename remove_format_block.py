#!/usr/bin/env python3
"""Remove format_war_report.py call from build_war_report.py"""
path = "/home/admin/okx_bot/build_war_report.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old = """    # 4b. 格式化（20号字 + 条件列 + 自适应列宽 + 去年份）
    import subprocess as _sp
    _fmt = _sp.run(
        [sys.executable, os.path.join(BASE_DIR, "format_war_report.py"),
         "--in", WAR_REPORT, "--out", WAR_REPORT],
        capture_output=True, text=True, timeout=60
    )
    if _fmt.returncode != 0:
        log(f"WAR_FAIL | format_war_report.py exit={_fmt.returncode} | {_fmt.stderr[:300]}")
        return
    for _line in _fmt.stdout.strip().split("\\n"):
        if _line:
            log(f"[format] {_line}")
"""

new = ""

if old in content:
    content = content.replace(old, new)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    print("OK: format block removed")
else:
    print("FAIL: pattern not found")
    # Try to find line number
    for i, line in enumerate(content.split("\n")):
        if "format_war_report" in line:
            print(f"  Found at line {i+1}: {line[:80]}")
