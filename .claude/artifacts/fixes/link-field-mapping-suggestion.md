# Bug: 引入字段时 link 字段未按语义生成映射建议（部门负责人 vs 关联部门）

> Status: FIXED
> Mode: (default)
> Severity: functional
> Author: 用户
> Last updated: 2026-09-23

## Symptom

从【部门表】引入"部门"、"部门负责人"字段到【员工表】时，"部门负责人"（link→员工表）没有得到与"关联部门"（link→部门表）相关的映射结果，只落到 0.03 分的无关弱匹配（姓名），面板上看不到有意义的映射建议。

## Expected

映射建议遵循 link 语义（用户确认）：
- link ↔ 非 link 不互相推荐（`部门`(text) 不再靠名字包含拿到 `关联部门`(link) 的 will_map）；
- link ↔ link 指向同一目标表 → 语义加分并推荐；指向不同目标表 → 不推荐；
- 无兼容候选时明确落到"无候选/新字段"，不产生无意义的低分占用。

## Reproduction

- 单元级：构造 src=[部门(text), 部门负责人(link→999)]，dst=[姓名(text), 关联部门(link→888)] 调 `suggest_field_mapping`，旧代码返回 部门→关联部门(0.88, will_map=True)、部门负责人→姓名(0.03)。
- 测试位置：`tests/test_field_mapping.py::TestLinkSemanticMapping`（3 用例）
- 复现稳定性：3/3 reliably fails（stash 修复后 3 failed）。

## Hypotheses & diagnosis

| # | Hypothesis | Verdict | Evidence |
|---|---|---|---|
| H1 | 贪心分配把 `关联部门` 分给得分更高的 `部门`，`部门负责人` 无候选可落 | 部分成立（症状放大器） | 复现输出显示 部门→关联部门 0.88 被占用 |
| H2（root cause） | `_name_similarity`/`_type_compat` 完全不感知 link 语义：text→link 靠名字包含即可过阈值；link↔link 的 target_table_id 异同不参与打分 | confirmed | 复现脚本输出 reason="包含匹配 (相似度 0.85)"，得分 0.88/1.03；link 字段的 config.target_table_id 未被读取 |

反向追溯：bad value（0.88 will_map / 0.03 弱匹配）首次产生在 `suggest_mapping` 的打分循环 → 在该层引入 `_pair_score` 门控，而非在前端映射面板打补丁。

## Root cause

`suggest_mapping` 的评分只有"名字相似度 + 类型组加分"，link 字段的 `config.target_table_id` 语义完全缺失。导致两条错误路径：① text 源字段可凭名字包含匹配到 link 目标字段（语义倒挂）；② link 源字段与指向不同表的 link 目标字段之间没有任何排斥信号，最终落到无关字段的极低分"弱匹配"上，用户看到的建议毫无意义。

## Fix

- 改动文件：`src/cndb/plugins/tables/services/importing/field_mapping.py`
- 新增 `_pair_score(sf, df, name_score, reason, type_bonus)`：返回 `(score, reason)` 或 `None`（不兼容，剔除候选）。规则：link↔非 link → None；link↔link 且 target_table_id 相同 → `+0.3` 并追加理由"link 指向同一目标表"；不同 → None；任一侧缺 target_table_id（历史数据）→ 退回原打分。
- `suggest_mapping` 打分循环调用 `_pair_score`，`None` 的配对不进入 `scored`。

## Verification

- V-1: `uv run pytest tests/test_field_mapping.py::TestLinkSemanticMapping -q` → 3 passed ✓
- V-2: `git stash push -- <修复文件>` 后重跑 → 3 failed（RED，证明测试真抓 bug），`stash pop` 后恢复 GREEN ✓
- V-3: `tests/test_field_mapping.py` + `tests/test_fields_import.py` → 114 passed；全仓 `make check` 全绿（后端 2223 passed、前端 837 passed）✓

## Regression test

- 路径：`tests/test_field_mapping.py::TestLinkSemanticMapping`
- 名称：`test_link_vs_non_link_not_recommended` / `test_same_target_link_boosted` / `test_diff_target_link_not_recommended`

## Pattern analysis

| 搜索方式 | 命中数 | 是否本次同类隐患 |
|---|---|---|
| `grep "_name_similarity"` | 仅 field_mapping.py 内部 | 否 |
| `grep "target_table_id"` 打分相关 | 仅本次新增 | 否 |

无其他调用点复用该评分逻辑；`auto_match_fields`（同名保守策略）不涉及。

## Open questions / Follow-ups

- 贪心分配仍无"次优回退"（一个源字段的top候选被占后不回看第二候选）；本次场景不依赖它，留作后续增强。
- `tests/test_cov_records_edge.py` 存量未格式化（此前被 ruff 缓存掩盖），本次已顺手 `ruff format` 通过门禁，未改逻辑。
