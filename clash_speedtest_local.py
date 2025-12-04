#!/usr/bin/env python3
# coding: utf-8

import os
import sys
import subprocess
import yaml

def filter_delay_greater_than_zero(yaml_path):
    if not os.path.isfile(yaml_path):
        print(f"输出文件不存在，无法过滤：{yaml_path}")
        return False

    with open(yaml_path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f)

    if not data or 'proxies' not in data:
        print("yaml 文件格式异常或无 proxies 字段")
        return False

    filtered_proxies = []
    for p in data['proxies']:
        delay = p.get('clash_delay') if isinstance(p, dict) else None
        if delay is not None and isinstance(delay, int) and delay > 0:
            filtered_proxies.append(p)

    data['proxies'] = filtered_proxies

    backup_path = yaml_path + '.backup'
    try:
        os.rename(yaml_path, backup_path)
        print(f"原文件备份为: {backup_path}")
    except Exception as e:
        print(f"备份原文件失败: {e}")
        return False

    with open(yaml_path, 'w', encoding='utf-8') as f:
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False)

    print(f"过滤完成，延迟大于0ms的节点数: {len(filtered_proxies)}，结果保存至 {yaml_path}")
    return True

def run_clash_speedtest_with_realtime_log(cmd, timeout=600):
    try:
        with subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True) as proc:
            for line in proc.stdout:
                print(line.rstrip())

            proc.wait(timeout=timeout)
            return proc.returncode
    except subprocess.TimeoutExpired:
        proc.kill()
        print("测速进程超时退出")
        return -1
    except Exception as e:
        print(f"测速异常: {e}")
        return -1

def main():
    input_path = os.getenv("INPUT_PATH", "flclashyaml/Tg-node.yaml")
    output_path = os.getenv("OUTPUT_PATH", "flclashyaml/1.yaml")
    max_latency = os.getenv("MAX_LATENCY", "800ms")

    if not os.path.exists(input_path):
        print(f"输入文件不存在：{input_path}")
        sys.exit(1)

    clash_exe = "./clash_core/clash"
    if not os.path.isfile(clash_exe) or not os.access(clash_exe, os.X_OK):
        print(f"找不到或无权限执行 clash-speedtest: {clash_exe}")
        sys.exit(1)

    cmd = [
        clash_exe,
        "-c", input_path,
        "-output", output_path,
        "-max-latency", max_latency,
        "-fast",
        "-concurrent", "8",
    ]

    print(f"执行命令: {' '.join(cmd)}")
    return_code = run_clash_speedtest_with_realtime_log(cmd, timeout=600)

    if return_code != 0:
        print(f"测速失败，返回码: {return_code}")
        sys.exit(1)

    # 测速成功后过滤延迟大于0的节点
    filtered = filter_delay_greater_than_zero(output_path)
    if not filtered:
        print("过滤步骤失败")
        sys.exit(1)

    print("测速及延迟过滤全部完成。")

if __name__ == "__main__":
    main()
