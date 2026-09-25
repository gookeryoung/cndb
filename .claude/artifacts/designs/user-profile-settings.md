# 用户个人资料设置 Spec

> Status: ALIGNED
> Author: user
> Last updated: 2026-09-25

## Background
后端 `User` 模型（src/cndb/plugins/accounts/models.py）已含 `email`/`nickname` 字段，注册与 `/auth/me` 已支持读写展示，但缺少登录后自助更新个人资料的接口，前端也没有对应设置表单。

## In scope
- 新增更新当前用户资料的接口（昵称、邮箱）。
- 前端个人设置页新增昵称、邮箱编辑表单并接入保存。
- Pydantic schema、前端类型同步、API 测试。

## Out of scope
- 修改密码、头像上传、手机号等其他资料项。
- 邮箱验证流程（仅格式与唯一性校验）。

## Assumptions
- 更新接口挂在 accounts 插件路由下，复用 `get_current_user` 鉴权依赖。
- 邮箱需全库唯一，昵称允许为空字符串时不强制唯一。

## Solution
后端：`UserUpdateRequest`（nickname/email 可选字段，Pydantic v2 校验）+ `PUT /v1/accounts/me`，服务层做邮箱唯一性检查，路由层映射 400。前端：设置页增加表单，React Query mutation 调用后更新 `/auth/me` 缓存。

## Edge cases & risks
| Category | Notes |
|---|---|
| Boundary | 邮箱格式非法/已被占用 -> 400 带明细 |
| Failure | 更新前后字段相同 -> 幂等成功 |
| Risks | 无 |

## Acceptance criteria
- AC-1 登录用户 PUT 昵称+邮箱 -> 返回 200 且 `/auth/me` 反映新值。
- AC-2 PUT 已被他人占用的邮箱 -> 400 且提示明细。
- AC-3 未登录调用 -> 401。
- AC-4 前端设置页可编辑并保存昵称、邮箱，保存后界面展示同步更新。
