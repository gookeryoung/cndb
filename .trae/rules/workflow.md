---
alwaysApply: true
description: "开发流程"
---

# 开发流程

## 沟通与语言

- 所有回复、注释、提交说明**必须**使用中文；标识符使用英文；不用 emoji。
- 阶段切换一句话；子任务完成一两句总结；收尾直接输出总结，不询问"是否继续"。

## 迭代循环

每次需求默认驱动1到3轮迭代，迭代间不询问。每轮走完6步，**禁止**跳步：

1. **收集**：回顾 `.trae/docs/` 遗留；查 CI/CD 失败；扫描 `.trae/req/` 新需求；按领域调用 SKILL。
2. **计划**：研究既有模式；用任务清单工具拆子任务；优先复用现有抽象；三处相似才提取。
3. **实现**：遵守语言 SKILL 与既有风格；优先编辑现有文件；公共 API 须有完整类型签名与中文 docstring；不写未被要求的功能。
4. **测试**：公共 API 配套测试，覆盖功能/性能/边界；失败定位根因，不放宽断言；依赖/环境问题先 2 轮自救。
5. **文档**：同步更新文档注释/README；有价值决策追加到 memory；不主动新建 `*.md`。
6. **验证**：逐条对照验收标准；给出变更清单。

未达标准回「收集」；多阶段项目初始确认目标是**整个项目**，阶段完成即自动进入下一阶段「收集」（跨阶段需外部资源时暂停），"整个项目目标达成"不是暂停条件，仅全部交付后才收尾。

## make check 全局门禁

`make check`（lint/typecheck/cov）以下时机**必须**本地通过：每轮实现完成后、收尾复核时、每次 `git commit` 前。收尾总结须注明"已本地通过 `make check`"。

## 暂停条件

仅以下情况中断找用户：歧义无法自决；高风险/不可逆操作（删除非临时文件、重命名公共模块、`force-push`、工作区未提交时的 `reset --hard`、`git clean -f/-fd/-fx`、改 CI/git config、引入新依赖、改工具链配置（.pre-commit-config.yaml/ruff.toml/pytest.ini/.coveragerc/pyrefly.toml/.bumpversion.toml/uv.toml）、改规则文件（`.trae/rules/`、`.trae-cn/rules/`、`.trae-cn/user_rules/`）、卸载降级依赖；普通 commit/push 除外，自动执行）；不可恢复失败（根因不在本仓库/需外部权限/两轮无法定位）；显著超出初始范围；用户主动询问。

可直接自决：测试/lint/类型错误修复、代码风格、文件编辑、运行校验、重命名局部变量、`git clean -fX`、`git stash`/`stash pop`、`git revert`、创建/切换分支、工作区干净时的 `reset --hard`。

## 产物约束

- **需求记录**：`.trae/req/req-NN-<主题>.md`，`[x]`/`[]` 勾选；已完成移至 `.trae/req/done/`。
- **迭代记录**：`.trae/docs/iter-NN-<主题>.md`，含需求清单/迭代目标/改动文件/关键决策/测试结果/遗留事项/下一轮计划；保留最新 5 条；歧义时采用默认决策须标注"待用户复核"。
- **文档规范**：中文；严禁 AI 式文档（不用 `iter`/`TODO iterate`）；README 精简，详细内容拆 `docs/`；CHANGELOG 遵循 Keep a Changelog；不主动创建文档文件。
- **规则变更**：修改规则文件必须先询问用户，获授权后变动，记录为 `rule-NN-<主题>.md` 并同步 `project_memory.md`。

## SKILL 触发

- 开发前按需调用对应 SKILL；新 SKILL 与既有约定冲突时优先按既有约定整合，无法自决才问用户。
- **Python**：开发前**必须**先调用 `python-standards`；其余按领域调用 `python-*` 系列 SKILL。
- **fspack 打包**：用 `python-fspack-release`（与 `python-packaging` 互斥）。
- **GUI 项目**：**必须**调用 `python-gui-pyside`。
- **FastAPI Web 项目**：先调用 `python-standards`，再读取 `02-webdev.md`。

## 工具使用

- 独立操作并行调用；长命令后台运行；文件操作用专用工具（Read/Edit/Write/Glob/Grep），不用 `cat`/`sed`/`grep`/`find`。
- **只调用真实存在于当前会话工具列表中的工具**，禁止猜测或伪造；找不到就明说"我没有 X 工具"并找替代方案；命令执行工具不能触发系统级动作；同一工具连续 3 次失败立即停止并求助。

## 收尾

全部交付后执行：输出总结（交付物/关键决策/遗留事项）→ 复核 make check 全绿 → `git add` + `git commit`（遵循 Git 提交规范）+ `make push` → 更新 memory；验收未满足则回「收集」。
