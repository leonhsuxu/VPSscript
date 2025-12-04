#!/usr/bin/env python3
# coding: utf-8

import os
import sys
import subprocess

def main():
    input_path = os.getenv("INPUT_PATH", "flclashyaml/Tg-node.yaml")
    output_path = os.getenv("OUTPUT_PATH", "flclashyaml/1.yaml")
    max_latency = os.getenv("MAX_LATENCY", "800ms")
    try:
        min_speed_mbps = float(os.getenv("MIN_SPEED", "5"))
        min_speed = min_speed_mbps / 8  # Mbps 转 MB/s
    except Exception:
        min_speed = 0.625

    if not os.path.exists(input_path):
        print(f"输入文件不存在：{input_path}")
        sys.exit(1)

    clash_exe = "./clash_core/clash"  # 这里缺少引号，改为clash
    if not os.path.isfile(clash_exe) or not os.access(clash_exe, os.X_OK):
        print(f"找不到或无权限执行clash-speedtest: {clash_exe}")
        sys.exit(1)

    cmd = [
        clash_exe,
        "-c", input_path,
        "-output", output_path,
        "-max-latency", max_latency,
        "-min-download-speed", str(min_speed),
    ]

    print(f"执行命令: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        print(result.stdout)
        if result.returncode != 0:
            print(f"错误: {result.stderr}")
            sys.exit(1)
        print(f"测速成功，结果保存到: {output_path}")
    except Exception as e:
        print(f"异常: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
