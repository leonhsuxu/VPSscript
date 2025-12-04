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
        min_speed = int(os.getenv("MIN_SPEED", "5"))
    except Exception:
        min_speed = 5

    if not os.path.exists(input_path):
        print(f"输入文件不存在：{input_path}")
        sys.exit(1)

    cmd = [
    "./clash_core/clash",
    "-c", input_path,
    "-output", output_path,
    "-max-latency", max_latency,
    "-min-speed", str(min_speed),
   ]
    print(f"开始测速，参数：\n 输入路径: {input_path}\n 输出路径: {output_path}\n 最大延迟: {max_latency}\n 最小速度: {min_speed}")

    try:
        result = subprocess.run(cmd, text=True, capture_output=True, timeout=300)
        print(result.stdout)
        if result.returncode != 0:
            print(f"测速失败，错误信息：\n{result.stderr}")
            sys.exit(1)
        else:
            print(f"测速成功，结果已保存至：{output_path}")
    except Exception as e:
        print(f"测速异常：{e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
