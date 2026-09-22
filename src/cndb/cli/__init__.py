"""cndb 命令行入口包 — 主 CLI、用户管理、备份/恢复、种子数据.

模块划分：
- main    — 主命令行（原 runner.py，pyproject 入口 cndb = cndb.cli.main:main）
- users   — 用户管理子命令（原 cli_users.py）
- backup  — 备份命令与备份实现（原 backup.py）
- restore — 恢复命令与恢复实现（原 restore.py）
- seed    — 演示数据种子（原 seed.py）
"""
