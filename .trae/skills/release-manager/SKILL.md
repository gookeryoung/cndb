---
name: release-manager
description: Use when a gate-green cndb change is ready to publish and deploy. Push, bump, tag and deploy only after the required human approvals.
---

# 发布与部署（release-manager）

1. **前置**：目标级别门禁全绿；ADR 交接已回填；CHANGELOG 已更新；`make adr-check` 无 error。
2. **推送**：`make push`；分支无 upstream 时先 `git push -u origin <branch>`。
3. **版本**：`make bump patch|minor|major`（写 CHANGELOG、自动打 tag）。
4. **人工卡点**：打 tag 前必须获得明确授权；未授权不 tag、不触发发布。
5. **发布**：tag → [release.yml](../../../.github/workflows/release.yml)（PyPI + 原生打包 + GitHub Release）。
6. **部署**：release 成功后 [deploy-tencent.yml](../../../.github/workflows/deploy-tencent.yml) 自动下发；失败自动回滚。
7. **验证**：`/health` 通过；异常先查 TAT 日志与 `docker logs --tail 100 cndb`。

## 铁律

- 不 force push、不直推 main/master、不打未授权 tag。
- 部署失败先确认是否已回滚，不手工重复触发。
