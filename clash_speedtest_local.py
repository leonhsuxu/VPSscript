#!/usr/bin/env python3
# coding: utf-8

import os
import sys
import subprocess
import yaml

def filter_delay_greater_than_zero(yaml_path):
    # 读取 yaml 文件，过滤 proxies 延迟大于0的节点
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
        delay = None
        if isinstance(p, dict):
            delay = p.get('clash_delay')
            if delay is None:
                # 可能是别的延迟字段，或没有测速结果，保留或过滤自行判断
                continue
            if isinstance(delay, int) and delay > 0:
                filtered_proxies.append(p)
        else:
            # 如果 proxies 列表结构不是字典，跳过，或者根据实际情况处理
            pass

    data['proxies'] = filtered_proxies

    # 备份原文件
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
        "-fast"
    ]

    print(f"执行命令: {' '.join(cmd)}")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        print(result.stdout)
        if result.returncode != 0:
            print(f"错误: {result.stderr}")
            sys.exit(1)

        # 测速成功后过滤延迟大于0的节点
        filtered = filter_delay_greater_than_zero(output_path)
        if not filtered:
            print("过滤步骤失败")
            sys.exit(1)

    except Exception as e:
        print(f"测速过程发生异常: {e}")
        sys.exit(1)

    print("测速及延迟过滤全部完成。")


if __name__ == "__main__":
    main()
