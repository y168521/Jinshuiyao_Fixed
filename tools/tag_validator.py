# -*- coding: utf-8 -*-
"""经验箱标签校验 CLI（白名单 + 数量 + 格式 + 一致性）。

复用 knowledge.tag_validator.validate_experience_tags。
用法：
    py -3.14 tools/tag_validator.py [经验箱.md路径]
退出码：0=通过，1=发现问题。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    from knowledge.tag_validator import main as _main
    args = sys.argv[1:]
    return _main(args)


if __name__ == "__main__":
    sys.exit(main())
