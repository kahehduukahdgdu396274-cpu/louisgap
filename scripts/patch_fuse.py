#!/usr/bin/env python3
"""Patch main.py: add error_strike fuse + fc() timeout hardening."""
import sys

API_PATH = "/home/admin/okx_bot/api.py"
MAIN_PATH = "/home/admin/okx_bot/main.py"

# ===== 1. api.py: GET request hardening =====
with open(API_PATH, "r") as f:
    api_src = f.read()

old_get = """        if method == "GET":
            return self._session.get(url, headers=headers, params=params, timeout=(3.05, 10)).json()"""

new_get = """        if method == "GET":
            try:
                return self._session.get(url, headers=headers, params=params, timeout=(3.05, 10)).json()
            except requests.exceptions.Timeout:
                logger.warning(f"[API] GET超时 path={path}")
                return None
            except requests.exceptions.ConnectionError as e:
                logger.error(f"[API] GET连接失败 path={path}: {e}")
                return None
            except requests.exceptions.RequestException as e:
                logger.warning(f"[API] GET异常 path={path}: {e}")
                return None"""

if old_get in api_src:
    api_src = api_src.replace(old_get, new_get, 1)
    with open(API_PATH, "w") as f:
        f.write(api_src)
    print("✓ api.py: GET hardened with timeout/connection error capture")
else:
    print("✗ api.py: old GET block not found")
    sys.exit(1)

# ===== 2. main.py: error_strike fuse in while True =====
with open(MAIN_PATH, "r") as f:
    main_src = f.read()

# Find the while True loop start
old_loop_start = """while True:
    try:
        r = fc()"""
new_loop_start = """error_strike = 0
MAX_ERROR_STRIKE = 5

while True:
    try:
        r = fc()"""

if old_loop_start in main_src:
    main_src = main_src.replace(old_loop_start, new_loop_start, 1)
    print("✓ main.py: error_strike + fuse vars added")
else:
    print("✗ main.py: while True loop start not found")
    sys.exit(1)

# Find the outer except at end of loop
old_except_end = """    except Exception as e:
        logger.error(f"异常: {e}")
        import traceback; traceback.print_exc()
    loop_count += 1
    time.sleep(POLLING_INTERVAL)"""

new_except_end = """    except Exception as e:
        error_strike += 1
        logger.error(f"异常 ({error_strike}/{MAX_ERROR_STRIKE}): {e}")
        import traceback; traceback.print_exc()
        if error_strike >= MAX_ERROR_STRIKE:
            logger.critical(
                f"连续{MAX_ERROR_STRIKE}次异常, 主动退出让systemd重启"
            )
            sys.exit(1)
        sleep_t = POLLING_INTERVAL * (2 ** (error_strike - 1))
        logger.warning(f"异常指数退避 {sleep_t}s")
        time.sleep(sleep_t)
        continue
    loop_count += 1
    error_strike = 0
    time.sleep(POLLING_INTERVAL)"""

if old_except_end in main_src:
    main_src = main_src.replace(old_except_end, new_except_end, 1)
    print("✓ main.py: fuse + exponential backoff added")
else:
    print("✗ main.py: outer except block not found")
    # Debug: show exact text around that area
    idx = main_src.find("except Exception as e:")
    if idx >= 0:
        print(f"Found at pos {idx}, showing 200 chars:")
        print(repr(main_src[idx:idx+200]))
    sys.exit(1)

with open(MAIN_PATH, "w") as f:
    f.write(main_src)

print("✓ main.py: saved")
