#!/usr/bin/env python3
"""Patch api.py: add 51169 early exit to place_order retry loop."""
import re

API_PATH = "/home/admin/okx_bot/api.py"

with open(API_PATH, "r") as f:
    content = f.read()

old_block = """                    if is_close:
                        logger.critical(f"平仓code=1 第{attempt}/{max_retries}次不死不休重试! | {cl_ord_id}")
                        time.sleep(1)
                    else:
                        time.sleep(delay)
                        delay *= 2.5"""

new_block = """                    if is_close:
                        # 51169=方向无持仓，重试无意义，提前退出
                        if s_code == "51169":
                            logger.warning(
                                f"51169提前退出 | {cl_ord_id} | OKX无此方向持仓，终止重试"
                            )
                            return res
                        logger.critical(f"平仓code=1 第{attempt}/{max_retries}次不死不休重试! | {cl_ord_id}")
                        time.sleep(1)
                    else:
                        time.sleep(delay)
                        delay *= 2.5"""

if old_block in content:
    content = content.replace(old_block, new_block, 1)
    with open(API_PATH, "w") as f:
        f.write(content)
    print("✓ patched: 51169 early exit added")
else:
    print("✗ old block not found — checking for near match")
    # fuzzy fallback
    idx = content.find("logger.critical(f\"平仓code=1")
    if idx >= 0:
        # find the enclosing indented block
        before = content[:idx]
        last_elif = before.rfind("elif code")
        if last_elif >= 0:
            block_start = last_elif
            block_end = content.find("\n                    else:", idx)
            if block_end == -1:
                block_end = len(content)
            else:
                block_end = content.find("\n", block_end + 1)
                block_end = content.find("\n", block_end + 1)
            print(f"block from {block_start} to {block_end}:")
            print(repr(content[block_start:block_end]))
    else:
        print("no '平仓code=1' found in file")
