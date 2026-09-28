# 备份归档布局统一

## 背景与目标

- 备份归档内数据库目录原命名 `database/`，与用户数据目录 `~/.cndb/data`（DATABASE_DIR）不一致；目录模式备份直接铺在用户可见的输出目录中，命名歧义易被误解为非数据库本体。
- 统一方向：归档侧向用户目录对齐，归档内数据库目录改为 `data/`；反向改动（用户目录 `data/` → `database/`）会变动默认 DATABASE_URL 并破坏存量安装的既有数据目录，不做。
- manifest 协议版本保持 `"1"`（SUPPORTED_MANIFEST_VERSIONS 不变）：目录命名属内部布局微调，不构成协议语义变更。
- 备份文件名需自描述：默认名注明软件版本与数据库格式版本，多版本备份并存时可人工辨识（`backup-0.2.0-v1-20260928T032702Z.tar.gz`）。
- examples/backups/ 保存历史版本备份归档作为向前兼容回归基线，新版程序必须能恢复任意历史归档并在升级后的库上继续写入。

## 接口定义

### cndb.cli.restore._extracted_db_dir

- [x] 签名：`def _extracted_db_dir(extracted_dir: Path) -> Path`
- [x] 语义：依次探测 `extracted_dir/data`、`extracted_dir/database`，返回第一个存在的目录；两者均不存在时返回 `extracted_dir/data`，由调用方按「缺失文件」语义抛 RestoreError，错误路径呈现新版目录名。
- [x] 调用方：`_restore_sqlite_native`（拼 `cndb.db`）、`_restore_sqlalchemy_json`（拼 `dump.json`）。

### cndb.cli.backup.create_backup

- [x] 临时拼装目录 `db_dir` 由 `temp_root/database` 改为 `temp_root/data`；归档内路径为 `backup/data/...`，目录模式输出根下为 `data/`。
- [x] 对外函数签名（create_backup / restore_backup / inspect_backup）与参数不变。
- [x] `output=None` 时默认名经 `format_backup_filename()` 生成（归档带 `.tar.gz` 后缀，目录模式传 `ext=""`）；用户显式指定 output 时不改写文件名。

### cndb.cli.backup.format_backup_filename

- [x] 签名：`def format_backup_filename(prefix: str = "backup", ext: str = ".tar.gz") -> str`。
- [x] 语义：生成 `<prefix>-<软件版本>-v<数据库格式版本>-<UTC时间戳><ext>`；软件版本取 `cndb.__version__`，数据库格式版本取 `MANIFEST_VERSION`（备份协议/数据库格式版本，alembic revision hash 不适合入文件名）。
- [x] 调用方：CLI 默认名（`prefix="backup"`）、Web 管理台下载名（`prefix="cndb-backup"`），两处共用同一格式契约。

## 数据模型

- manifest 结构不变：`database` 键仍为 DatabaseInfo 序列化结果（描述数据库备份信息，与归档目录名解耦）。

## 算法与流程

- [x] 归档拼装流程不变：临时目录内 `data/`（cndb.db + 可选 dump.json）+ `uploads/` + `manifest.json`，打包为 `backup/` 前缀归档或复制为目录。
- [x] 恢复端数据库目录定位统一经 `_extracted_db_dir`，native 与 sqlalchemy 两条路径共用；新旧目录同时存在时优先取 `data/`。

## 异常处理

- [x] 归档缺失 `cndb.db` / `dump.json` 的 RestoreError 行为与文案不变，仅错误信息中的目录名随定位结果呈现。
- [x] `data/`、`database/` 均不存在时定位回落 `data/`，错误信息呈现新版目录名。

## 兼容性

- [x] 旧版归档（`backup/database/...`，manifest version "1"）无需任何转换即可恢复。
- [x] 兼容回退集中在 `_extracted_db_dir` 单一函数，后续格式演进仅改此一处。

## 范围外决策

- `config/` 目录不纳入备份（维持现状）：restore 覆盖旧 `.env` 可能带回过期 DATABASE_URL 导致恢复后指向错误库；`.env` 含明文密钥，入包扩大泄露面；配置可重建成本低。整机迁移需求出现时再评估 `--include-config` 可选开关。

## 历史备份向前兼容回归

- [x] `examples/backups/` 保存随仓库的历史版本备份归档（gitignore 例外 `!examples/backups/**/backup-*.tar.gz`），文件名格式与本设计「备份文件名」契约一致，版本段即归档生成时的软件版本与数据库格式版本。
- [x] `tests/test_legacy_backup_compat.py` 参数化遍历目录下全部 `backup-*.tar.gz`，新增历史归档自动纳入参数化，无需改测试；目录为空时整组 skip（wheel 安装环境）。
- [x] 每个归档验证链路：inspect_backup 读取 manifest（协议版本、软件版本、行数清单）→ restore_backup 恢复（native 自动迁移 schema 到当前 head）→ 逐表行数与 manifest 比对（旧数据零丢失）→ 升级后的库上执行完整 seed（演示数据重新生成并保存落库）。
- [x] seed 隔离：monkeypatch `cndb.core.database` 的 engine/SessionLocal 与 `settings.DATABASE_URL` 指向恢复出的临时库（seed() 函数内 import 运行时解析模块属性）；`_generate_sample_reports` 在测试中替换为空操作，避免向仓库 datasets 目录写示例报告的副作用。
