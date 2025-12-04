#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import os
import sys

def run_clash_speedtest_local(input_yaml_path, output_yaml_path, max_latency='800ms', min_speed=5):
    """
    使用 clash-speedtest 命令行工具对本地 YAML 配置文件测速并输出过滤结果

    参数:
        input_yaml_path (str): 输入的 Clash YAML 配置文件路径
        output_yaml_path (str): 输出的测速后配置文件路径
        max_latency (str): 节点最大允许延迟，如 '800ms'
        min_speed (int): 节点最小速度 Mbps

    返回:
        bool: 测速是否成功
    """

    if not os.path.isfile(input_yaml_path):
        print(f"错误：输入文件不存在: {input_yaml_path}")
        return False

    cmd = [
        'clash-speedtest',
        '-c', input_yaml_path,
        '-output', output_yaml_path,
        '-max-latency', max_latency,
        '-min-speed', str(min_speed)
    ]

    try:
        print(f"开始测速，输入文件: {input_yaml_path}\n输出文件: {output_yaml_path}")
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='utf-8', timeout=300)
        if result.returncode == 0:
            print(f"测速完成，结果已保存到: {output_yaml_path}")
            print(result.stdout)
            return True
        else:
            print(f"测速失败，错误信息:\n{result.stderr}")
            return False
    except FileNotFoundError:
        print("错误: 未找到 clash-speedtest 可执行文件，请确认已安装并配置环境变量。")
        return False
    except subprocess.TimeoutExpired:
        print("错误: 测速进程超时退出。")
        return False
    except Exception as e:
        print(f"异常错误: {e}")
        return False

def main():
    input_path = 'flclashyaml/Tg-node.yaml'
    output_path = os.path.join(os.path.dirname(input_path), '1.yaml')
    success = run_clash_speedtest_local(input_path, output_path)
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()
