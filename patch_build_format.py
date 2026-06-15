#!/usr/bin/env python3
"""Patch build_war_report.py: add format call after war_v3 success"""
with open("/home/admin/okx_bot/build_war_report.py", "r", encoding="utf-8") as f:
    content = f.read()

# Find the run_war_v3() success path and add format call
old = '''    # 4. 运行战报
    ok = run_war_v3()
    if not ok:
        return'''

new = '''    # 4. 运行战报
    ok = run_war_v3()
    if not ok:
        return

    # 4b. 格式化（20号字 + 条件列 + 自适应列宽 + 去年份）
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
            log(f"[format] {_line}")'''

if old in content:
    content = content.replace(old, new)
    with open("/home/admin/okx_bot/build_war_report.py", "w", encoding="utf-8") as f:
        f.write(content)
    print("OK: format call inserted after war_v3")
else:
    print("FAIL: pattern not found")
