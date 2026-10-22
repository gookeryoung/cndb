# Changelog

遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [未发布]

### 修复
- **推荐提示词（每日新闻 / 美食推荐）开箱即失败：长 JSON 被默认 `max_tokens` 截断 + 模型无实时数据就返回空数组**（ADR 0019 P3）：用户按内置预设建任务，美食报「模型返回内容不是合法 JSON: Unterminated string…」（1024 token 在长 JSON 中途截断），新闻直接拿空结果。修复：① 默认 `max_tokens` 1024 → **4096**（上限 32768 不变，连通测试仍用小请求）；② `_parse_response` 新增截断识别（`Unterminated string`、或 `Expecting ...` 且错误位置贴近内容末尾），报错改为「模型输出可能被截断：请提高 max_tokens（当前默认 4096）或精简提示词输出（本次返回 N 字符）」，普通非法 JSON 文案不变；③ 内置 `DEFAULT_SYSTEM_PROMPT` 真实性约束改为：综述 / 摘要 / 推荐类任务基于已掌握公开知识尽力输出、**不因无法联网返回空数组**，无法核实的实时事实在 `summary` / `source` 标注「综合整理」、`url` 用空串、禁止编造可核实的精确统计数字；④ 「每日新闻摘要」预设改为基于已掌握近期公开信息汇总、允许标注「综合整理」，「美食推荐做法」预设改为四类各 2 道共 8 道并限制食材 / 步骤长度，避免输出过长再次截断。测试：`tests/test_datasource_llm_provider.py` 补默认 token / 截断提示 / 普通非法 JSON 回归 / 系统提示词约束，前端 `llmPromptPresets.test.ts` 锁住两组文案
- **CI E2E shard 1 红灯：新增的「切换登录背景」按钮污染登录按钮选择器**：ADR 0016 的 `AuthBackgroundSwitcher` 把 `aria-label` 写成「切换登录背景，当前 …，下一组 …」，其中“登录”二字让 dev 模式回归用例里宽泛的 `getByRole("button", { name: /登\s*录/ })` 同时命中提交按钮与切换器，Playwright strict mode violation，CI 的 `Run dev-mode E2E` 步骤两条（含 retry）全挂（run 39599862621，其余 3 个 shard 与常规 e2e 均绿）。修复：登录 / 注册按钮定位统一改为首尾锚定 `/^登\s*录$/`、`/^注\s*册$/`（dev 回归、`smoke/login`、`smoke/register`、`auth.setup`），与单元测试口径一致；语义等价且后续任何「登录背景」类按钮不会再污染选择器
- **工作区搜索在未打开视图 / 不在表页时搜不到数据表内容**（ADR 0015 P0）：两个范围缺陷叠加 —— ① 不在表上下文（工作区页 / 文档页）时后端只扫**前 8 张表**（`MAX_TABLES_SCAN`），第 9 张及以后的数据表内容永远不进入结果，且与关键词无关；② 范围选择器写着「工作区」，后端仍把 `table_id` / `view_id` 收敛到当前表与激活视图，其他表、当前视图外的行都搜不到。修复：删除 8 张表截断，工作区范围（`scope=all`）覆盖全部可读表且**不按视图收敛**（当前表仅排序优先）；只有「数据表」范围（`scope=tables`）才收敛当前表 + 激活视图；前端只在 `scope=tables` 时下发 `view_id`，面板范围回显同步。测试：`tests/test_workspace_search.py` 增 6 例（第 10 张表仍命中 / `all` 忽略 `view_id` 与视图外行 / `tables` 仍按视图收敛 / 缓存命中 / 单行与批量写失效），前端 `GlobalSearch.test.tsx` 拆为「工作区范围不回显视图」与「数据表范围按视图收敛」两例
- **数据分析页布局错乱：`cn-an-*` 类名在样式表里从未定义**：上一轮把面板改成 `AnalyticsBox` + `cn-an-*` 命名后只改了 TSX，`index.css` 里没有任何对应规则，页头、方盒、网格、字段 chips、公式行全部退化为无样式堆叠（标题与描述挤成一团、控件散乱、配置区与结果区上下摞满一屏）。修复：在 `index.css` 补齐整套样式，全部走设计标尺变量（间距 / 字号 / 圆角不写字面量）：页头图标 + 标题 + 单行元信息、方盒（1px 描边 + 浅底标题条 + 1px 分隔线、无投影）、两列 / 三列字段网格、字段与函数 chips、公式行、汇总指标行、空态；窄屏（<768px）页头控件整行、双栏改单列、三列网格改单列
- **Windows 开发机 `make test` 固定 7 例假红（部署脚本回归）**：`tests/test_deploy_scripts.py` 假定 POSIX bash，本机 `shutil.which("bash")` 命中 MSYS / Gow 包装器 —— 它既不认 `F:\...` 反斜杠路径，在 Python `subprocess` 下连 `--version` 都返回 1 且无输出，7 例（3 条语法检查 + 4 条假 docker 桩）必然失败。脚本本身是 POSIX sh，用 WSL bash `-n` 逐一验证三个脚本均通过，CI（Linux）覆盖完整。修复：该文件在 Windows 上整体跳过（`skipif(os.name == "nt")`），Linux / CI 口径不变
- **CI 红灯：工作区列表改版 + 迁移 head 推进后 e2e 与迁移测试失效**：① 工作区列表由卡片改为 GitHub 风格行列表后，`smoke/grid`、`smoke/onboarding`、`perf/grid-lcp` 仍在按 `.ant-card` 点卡进工作区，五例全部超时 → 统一改为按 `[data-testid^="workspace-row-"]` 的行主体点击进入；② K 线视图默认落「按股票代码升序的首只有序列标的」，示例扩为 10 只 A 股后首只已不是 `sh600519`，用例硬编码断言失效 → 改为股票代码正则断言（只校验「落在一个真实标的上」，不再绑定具体代码）；③ 分析模板「另存为副本」在深链 `?template=` 的模板列表尚未载入时就可点击，默认名落到「未命名分析」（e2e 偶发失败）→ 页面在模板加载中禁用「另存为 / 重命名」，e2e 等模板名回填后再操作；④ 协作者 / 站内通知下线迁移 `2c3d4e5f6a70` 未同步测试口径 → `HEAD_REVISION` 更新为 `2c3d4e5f6a70`，`_DROPPED_TABLES` 补 `documents_permission` / `accounts_notification`（历史备份恢复到 head 后这两张表应被删除）；⑤ 「恢复历史备份 + 全量 seed」的集成用例在示例扩到约 3.4 万行后本地已逼近 30s 默认超时（CI runner 上必然超时）→ 该用例单独放宽到 180s，其余用例仍守 30s
- **套用领域分析模板必报「字段名可能与目标表不一致」**（ADR 0006 M5）：领域模板按 provider 默认输出命名（`close` / `trade_date` / `symbol`），而同步任务一旦配了 `field_mapping` 改过名，模板原样提交就会被后端 `normalize_config` 以「公式引用了不存在的字段」400 拒绝；前端 `catch` 又把真实原因吞掉，只剩一句误导性的猜测文案。修复：新增 `pages/datasource/domainTemplate.ts`，套用前按任务映射（源名 → 目标名、`null` = 丢弃）翻译公式字段引用、`partition_by / order_by`、图表 `x / y / series`、汇总 `group_by / metrics / sort_by`；字段被映射丢弃时剔除该公式，并连带剔除引用它的图表与汇总指标，跳过的部件以 warning 回报；建模板失败时直接展示后端校验文案，不再猜测原因。测试：`domainTemplate.test.ts` 5 例（无映射原样 / 改名全量翻译 / 丢弃字段降级 / 公式剔除连带图表 / 无公式模板）+ 页面 2 例（提交体用目标字段名 / 透传后端 400 文案）
- **文档预览里的目录 / 文内锚点点了没反应**：查看模式的 `a` 组件对 `#` 链接原样透传，浏览器按 id 找不到目标（标题 id 带 `doc-h-` 前缀），在 SPA 里还会把 hash 写进 URL 而正文不动；`[[#小节]]` 之前更被直接降级成纯文本。修复：新增 `components/Document/docAnchor.ts` 统一解析锚点（先 id 精确匹配，再按标题文本生成 id，最后按同文本标题兜底，`#一概述` 可命中 `## 一、概述`），预览里 `[小节](#小节)` 与 `[[#小节]]`（含 `|别名`）均 `preventDefault` 后原地滚动到标题；锚点未命中静默忽略
- **文档「实时预览」里表格 / 列表 / 待办原样显示 Markdown 源码**：实时预览（CodeMirror）的装饰只覆盖标题、强调、行内代码、链接、图片、引用、分隔线与代码块，GFM 的 `Table` / `ListMark` / `Task` 节点没有对应装饰，于是 `| a | b |`、`| --- |` 分隔行、`- 条目`、`- [ ] 待办` 全部以源码形态出现，与查看模式的渲染结果不一致。补齐三类装饰：① **表格** —— 光标不在表格内时整块替换为真表格（表头底色、按 `:--` / `--:` / `:-:` 对齐、单元格内的粗体 / 斜体 / 行内代码 / 删除线按渲染态显示），点击表格把光标落进首行切回源码编辑（与 Obsidian 一致）；分隔行不合法、或表格嵌在引用 / 列表里时保留源码不做替换。② **无序列表** —— `-` / `*` / `+` 换成圆点并按缩进层级切换 `•` / `◦` / `▪`；有序列表保留序号只做配色。③ **待办** —— `[ ]` / `[x]` 换成复选框，点击直接写回标记（`[ ]` ↔ `[x]`），不动同行其它字符。实现上装饰从 `ViewPlugin` 迁到 `StateField`（CodeMirror 不允许插件下发块级装饰，表格整块替换属块装饰），并把词法高亮改为单次重建总量 300 KB 预算，避免「每次按键装饰整篇」（原实现只装饰可视区）后大文档卡顿。新增 `components/Document/mdTable.ts`（表格源码解析）与 17 例单测
- **专用 provider 的 `parse` 从未被执行 —— 腾讯 / 东财 / RSS 的嵌套响应被通用数组探测压成「1 行/请求」**（ADR 0013 P0）：抓取管线只调 `fetch_json(plan.config)` 拿已解析数组，各 provider 覆写的 `parse` 成了死代码，`tencent_kline` 的 `{data:{symbol:{qfqday:[…]}}}` 被 `_extract_array` 的候选键探测命中后每请求只出 1 行（长历史抓取必然失真，此前示例任务实跑就是这个结果）。修复：`http_json` 增加 `uses_custom_parse` 类属性，置 True 的 provider 在 `build_requests` 时把 `response_handler` 设为绑定自身 `parse` 的 callable，复用 `api_fetch` 的重试 / SSRF / 编码能力只替换解析段；`tencent_kline` / `sina_kline` / `eastmoney_kline` / `eastmoney_symbols` / `rss_atom` 全部置位。顺带修两个腾讯口径问题：`volume` 在 `parse` 阶段由「手」×100 换算为「股」（新浪本来就是股，同表口径一致才可比），默认 URL 从 `web.ifzq.gtimg.cn` 改为 `proxy.finance.qq.com/ifzqgtimg/...`（前者对脚本流量返回 WAF 501 挑战页，实测后者同一接口不拦）。测试：`test_datasource_sina.py` 增「handler 注入 / 通用 provider 不注入」，`test_datasource_providers.py` 锁住手→股换算
- **`make bump` 必然失败：ruff hook 重写 `uv.lock` 导致 bump 提交被中止**：bump 先改 `pyproject.toml` 版本再 `git commit`，提交时 pre-commit 里的 `uv run ruff` 发现版本变了会自动重锁并把 `uv.lock` 改脏（`name = "cndb"` 的版本 + lock `revision`），pre-commit 判定「hook 修改了文件」→ 提交非零退出 → bump-my-version 回滚，版本永远升不上去。修复：① hook 改为 `uv run --frozen --no-sync ruff …`，只复用已同步的 `.venv`，不做 lock / sync 副作用（`make lint` 等本地门禁仍用 `uv run`，环境照常自动同步）；② `.bumpversion.toml` 增加 `uv.lock` 条目，bump 时一并更新 lock 里 editable 包的版本，避免提交后 lock 与 `pyproject.toml` 不一致、下次 `uv run` 再把工作区改脏
- **数据源同步被目标站限流时只报「请求失败」，短退避还会反复冲刷封禁窗口**（ADR 0011 运维加固）：`api_fetch` 原先把「对端建连后一个字节都不回就断开」当普通瞬时失败处理 —— 2 次重试只退避 0.5s / 1s，东方财富按出口 IP 限流时（`RemoteProtocolError: Server disconnected without sending a response`，用浏览器 / curl / 多个 CDN IP / 带官方 `ut` 参数均复现，行情页自身 K 线也拉不到）几乎必然耗尽重试，且越试封得越久；错误信息只剩笼统的 `请求失败: …`，看不出是外部限流而不是 URL / 字段映射写错。修复：新增限流类判定（`RemoteProtocolError` / `ReadError` / 文案命中 `connection reset`·WinError 10054 的 `ConnectError`），命中后退避改为 **2s / 8s**（`THROTTLE_BACKOFF_SECONDS` × 4^尝试次数），耗尽后报「目标站可能正在限流本机出口 IP：<原始异常>」；普通瞬时失败与 POST 不重试的语义不变。示例 `datasource.json` 的 5 个东财 K 线任务 `rate_limit_ms` 500 → **2000** 并错峰到 17:30 / 17:45 / 18:00 / 18:15 / 18:30（原为 17:30–17:50 背靠背，7 标的下 25 分钟内 35 次请求）。测试：`test_api_fetch.py` 补长退避 / 退避后重试成功 / 重置文案判定 / 短退避不回归 5 例，`test_seed_datasource.py` 锁住「K 线任务必须错峰且间隔 ≥ 1500ms」
- **编辑数据表的关联字段时「关联目标表」与「引用字段」为空**：字段编辑表单用了 `<Form preserve={false}>`（字段组件卸载即丢弃其值），而 React 开发态的 StrictMode 会在挂载后模拟一次「卸载→重挂载」—— 父层 effect 刚把字段配置回填进表单，就被这次模拟卸载连带清掉；同步指纹（`seededSigRef`）判定「已回填」而跳过重试，于是对话框停在「请先选择目标表 / 暂无引用字段」空态，目标表的字段列表接口也不会被请求（表现为编辑时看不到引用字段数据，关掉重开一次又正常）。修复：去掉 `preserve={false}`，改由类型切换时显式重置 `config` 为新类型默认值（创建/编辑一致，保留原先「换类型不留旧配置」的语义）。单测补两条（StrictMode 回填回归、「切换类型不残留旧类型配置」，修复前均失败），并在 dev 模式 E2E 套件加一条端到端回显用例 —— 生产构建里 StrictMode 是空实现，该现象只在 dev 现形，常规 e2e（生产产物）抓不到，故兜在 dev 套件（修复前字段名回填即为空而失败）
- **输错一次密码后立刻改对提交，会被踢回登录页**：登录接口自身的 401（凭证错误）也会走「会话过期」流程 —— `clearToken()` + `auth:expired` 事件（500ms 防抖）；当用户在防抖窗口内完成下一次成功登录时，延迟触发的 `notifyExpired` 会把刚拿到的会话清掉，`ProtectedRoute` 因 `user=null` 弹回 `/login?return_to=...`。修复：鉴权端点自身的 401（login / register / refresh / logout）是凭证错误而非会话过期，不再 `clearToken`、不再发过期事件；业务接口的 401（令牌过期）行为不变（刷新失败仍清会话并提示）。该竞态由新增的 dev 模式 E2E 在自动化连续操作下必然踩中而发现（人工操作间隔常大于 500ms 防抖窗口，此前被掩盖）
- **登录页报 `Cannot add property current, object is not extensible`**：`rc-field-form` 的摇树补丁把默认导出改成了裸组件（`export default FieldForm`），丢掉了 `React.forwardRef` 包装 —— antd 的 `Form` 依赖 ref 取表单实例，导致开发态报「Function components cannot be given refs」、点登录直接抛错，登录页不可用（生产构建走 antd 内部深路径，未暴露，属只在 dev 出现的坑）。补丁改为**只删静态属性挂载、保留 `React.forwardRef(FieldForm)`**，摇树收益不变（主入口仍 175.2 KiB）。新增 `frontend/scripts/check-patches.mjs` 并接入 `pnpm dev` / `pnpm build` / `make check-fast`：校验补丁后的 forwardRef 语义、静态属性与 `sideEffects`，补丁被漏打或改坏时立即失败（单测守不住 —— vitest 里 antd 走 CJS 的 `lib`，dev/build 走 `es`，坏版本在单测中照样通过）

### 变更
- **大模型能力平台化：能力从 datasource / accounts 抽到独立插件 `plugins/llm/`（表 `llm_user_config` + `llm_run`、端点 `/api/v1/llm`、HTTP 传输层上移）**（ADR 0020 P0）：大模型能力此前混在 `datasource` provider 内、配置路由挂在 `accounts` 上，其它功能复用只能复制代码或反向依赖。本轮按 ADR 0020 归位 —— ① **平台插件**：新增 `src/cndb/plugins/llm/`（`models.py` / `plugin.py`、`services/{connection,client,parsing,gateway,actions,errors}.py`、`routers/{config,actions,runs}.py`），`llm_prompt` provider 保留消息构造与「提示词 → 行 → 幂等落表」领域语义，连接 / 调用 / 解析改由平台层提供（经 `RequestPlan.fetcher` 注入的 `client.py`，重试与 SSRF 白名单统一）。② **表迁移**：新迁移 `7b8c9d0e1f2a`（`down_revision = 6a7b8c9d0e1f`）建 `llm_user_config` 并搬运 `datasource_user_llm_config` 数据后删旧表，同时建调用留痕表 `llm_run`（不存提示词 / 输出全文）；`HEAD_REVISION` 同步为 `7b8c9d0e1f2a`。③ **端点迁移**：`GET|PUT /api/v1/llm/config`、`POST /api/v1/llm/config/test` 替代 `GET|PUT|POST /api/v1/accounts/llm-config*`（旧端点删除），新增 `GET /api/v1/llm/actions`、`GET /api/v1/llm/runs`。④ **HTTP 上移**：`tables/services/importing/api_fetch.py` 的 `fetch_json` / `validate_url` / `FetchConfig` 实现迁到 `src/cndb/core/http.py`，原模块保留 re-export shim（其它 provider 与测试 import 不变）。⑤ **隐私修正**：保存同步任务不再把个人 `base_url` / `model` 写回 `request_spec`，工作区备份不再携带个人地址 / 模型。⑥ **前端**：`frontend/src/api/llmConfig.ts` → `frontend/src/api/llm.ts`（`llmConfigApi` → `llmApi`，新增 actions / runs 封装），设置页与数据源页同轮切端点。测试：新增平台层（客户端重试 / JSON 解析 / 网关 / 连接解析 / actions 目录）与接口用例，重写 `tests/test_datasource_llm_config.py`，`tests/test_datasource_migration.py` / `tests/test_migration_missing_model_columns.py` 同步 head 与旧表断言，`tests/test_datasource_api.py` 改为断言 `request_spec` 不含个人 url/model，前端 `LlmConfigPanel.test.tsx` 的 msw handler 切到 `/api/v1/llm/config*`、`SettingsModal.test.tsx` 回归
- **大模型配置从工作区级迁移到个人级（个人设置 → 大模型），工作区备份升 v7 不再导出个人配置**（ADR 0019 P3）：此前「大模型连接」按工作区存一条，同一用户跨工作区要重复配置、共享工作区下归属与 Key 可见性也说不清。改为 **个人级配置**：① **数据模型**：新表 `datasource_user_llm_config`（`user_id` 唯一、级联删除，字段 `base_url` / `model` / `api_key` 密文 / `system_prompt`），迁移 `6a7b8c9d0e1f` 建新表、把旧 `datasource_llm_config` 按 `created_by` 迁给用户（同用户多行取 id 最小一条，无归属丢弃）后**删除旧表**；downgrade 重建旧空表（数据不恢复）；`HEAD_REVISION` 同步为 `6a7b8c9d0e1f`。② **接口**：新增 `GET|PUT /api/v1/accounts/llm-config`（登录即可，只操作当前用户，Key 只写不回显、`clear_api_key` 清除）与 `POST /api/v1/accounts/llm-config/test`（可用未保存的地址 / 模型 / Key 测试、不落库）；**删除**工作区级 `GET|PUT /{wid}/datasource/llm-config` 与 `POST /{wid}/datasource/test-connection`，`sync-jobs` 保存 / 预览 / 运行改按当前用户或 `job.created_by` 解析个人连接，缺 Key 文案改为「请先在「个人设置 → 大模型」配置 API Key」。③ **前端**：新增 `api/llmConfig.ts` 与「个人设置 → 大模型」页签（`LlmConfigPanel`：地址 / 模型 / Key 只写不回显并可清除 / 系统提示词覆盖 / 内置默认全文 / 未保存直测），数据源页删除「大模型连接」按钮 / 状态 Tag / 弹窗与未配置引导，`llm_prompt` 抽屉提示去个人设置配置，高级设置 `max_tokens` 默认 4096。④ **备份**：工作区备份 v6 → **v7**，不再导出 `llm_config`（个人数据不随工作区备份，避免把 A 的 Key / 模型选择带给 B），导入端接受 1-7，v6 备份残留的 `llm_config` 键忽略。测试：重写 `tests/test_datasource_llm_config.py`（用户隔离 / 未登录 401 / 未保存 Key 直测 / 不回显），`tests/test_datasource_migration.py` 补新旧表搬迁与 downgrade，`test_datasource_api.py` / `test_datasource_backup.py` / `test_datasource_llm_provider.py` 与前端 `LlmConfigPanel.test.tsx`、`SettingsModal.test.tsx`、`DatasourcePage.test.tsx` 同步
- **ADR 收敛：删除未实施的后端加固方案，0015 定稿 Implemented**：未实施的加固 ADR（只有极端用例基线落地，R1-R10 与后续分期从未开始）按「需求作废直接删除」移除文件、索引行与引用，`tests/test_backend_extreme_cases.py` 保留为既有行为回归基线；0015 的 P1/P2（行内容快照、FTS5 行索引）属无排期的后续演进，按「不留以后备用段落」从 ADR、索引、ADR 0012 交接与 CHANGELOG 中删除，`Status` 定稿 `Implemented`
- **ADR 校验并入 GitHub CI（一次推送只出现一个 workflow）**：`adr-check.yml` 与 `ci.yml` 各自监听 `docs/adr` / `CHANGELOG.md`，同一次推送经常同时触发两条流水线。改为 `ci.yml` 新增 `changes` job 判定变更范围（`git diff` 比对 PR `base.sha` / push `before`）：变更文件全部落在 `docs/adr/**`、`CHANGELOG.md`、`scripts/check_adr_landing.py` 时只跑 `ADR Landing` job，其余 job 全部跳过；有代码改动时 `ADR Landing` 跳过，改由 `Lint & Typecheck` 顺带执行 `check_adr_landing.py`（同口径、复用已装 uv 环境）；首次推送 / 手动触发按全量处理。`paths` 补 `docs/adr/**`、`CHANGELOG.md`，删除独立 workflow 文件
- **补行级权限 Playwright 专项用例**（ADR 0004 P2）：新增 `frontend/tests/e2e/critical/row-permissions.spec.ts`，把 ADR §10 的 e2e 清单落到真实三账号场景 —— admin（工作区 OWNER）经 API 建临时表（姓名 / 部门）并配置默认档 `row_filters=部门=销售部`；UI 在表设置「权限」Tab 走完规则增删改（选主体「编辑者（成员级档）」→ 动作「可查看」→ 条件「部门包含技术」→ 预览命中 1 行 → 保存 → 改 AND 为 OR），结论同时走 API 与 UI 断言：编辑者（write 档）可见销售部 + 技术部、查看者（read 档）仅销售部、owner 豁免全量；查看者越界 PATCH 单行 → 404（I6）；编辑者编辑技术部行 → 提示「已提交修改申请，处理后生效」且不落库（D8）；删除规则后读范围收紧、owner 仍可直编。临时表在 finally 软删除；ADR 0004 已评审通过，`Status` 定稿为 `Implemented`
- **ADR 编号冲突与落地回填清理**：认证页动态背景 ADR 与数据源 LLM 同步 ADR 同占 0014（后者先建）→ 前者改为 **0016**，同步需求卡片、`docs/adr/README.md` 索引、`CONTEXT.md`、CHANGELOG 与前端注释引用；两个 ADR 的 P0-P2 提交列回填真实 sha（`7eba8c37` / `f8b79dba`），并因全期落地定稿 `Status=Implemented`；ADR 0002 的「vitest 分片」已否决分期从落地表移除（云效无法消费 ArtifactUpload 产物），交接同步
- **工作区搜索增加 15s 结果缓存**（ADR 0015 P0）：搜索原先每次输入（250ms 去抖后）都要逐表 `list_rows($query)` 全扫，关键词不存在时成本最高，重复搜索与范围切换没有任何收益。新增进程内 `search_cache`（`TTLCache`，256 条 / 15s），键含工作区 / 用户 / 范围 / 关键词 / 表 / 视图 / 上限，空结果同样缓存（最坏情况最需要），`scope=all` 的 `view_id` 归一为 0 避免无意义分片；失效复用统一事件流（`record.*` / `table.*` / `row_rule.*` / `datasource.*` / `document.*` → 清 `search|{wid}`），批量导入 / 数据源同步这类不写 audit 的写入在 `bulk_create` / `bulk_update` / `bulk_update_rows` 末尾显式清，权限变化最迟 15s 生效
- **顶栏工作区搜索改为相对居中**（ADR 0012）：搜索框原先紧跟工作区切换器靠左，宽屏下离右侧操作区较远、来回操作要跨半屏。改为由新增的 `cn-header-search` 弹性容器接管导航组与右侧操作组之间的剩余横向空间，搜索框在这段空间内居中且保持 420px 宽度上限，窄屏下不与两侧挤压重叠；移动端图标入口与搜索抽屉的位置不变
- **数据分析页改为 GitHub 风格双栏工作台**：原页面是「页头标题 + 长描述 + 7 个平铺控件」加一列贯到底的卡片流，配置公式时要来回滚动才能看到结果。改为 —— ① **页头单行**：图标 + 标题 + 「当前模板 · 更新时间」单行元信息（模板描述走 `title` 悬停，不再撑高三行），右侧依次为模板下拉、「分析列表」入口、保存 / 另存为 / 重命名 / 删除图标按钮与常驻的「运行分析」主按钮（运行前置条件以极小字提示跟在旁边）；② **双栏工作台**：左栏固定 420px 放数据源 / 智能推荐 / 计算模板 / 可视化 / 分组汇总（配置），右栏自适应放图表 / 分组汇总 / 描述统计 / 派生数据（结果），窄屏自动换行为单列；③ **数据源面板降噪**：去掉「可用字段：a、b、c…」长文本（字段已在公式 chips 中可见），表名 / 字段数 / 行数收进方盒标题条右侧，分析范围收成「范围字段 + 起始值 + 结束值」三列；④ 结果区 4 个 antd Card 统一换成 `AnalyticsBox` 方盒（标题条带图标、右侧放行数 / 导出按钮，派生列说明移到盒脚）
- **移除 baostock 日线源（避免依赖膨胀）**（ADR 0013 D8）：baostock 只为一条日线源就把 pandas / numpy 拖进依赖图（lock 里连带 `pandas` / `numpy` / `python-dateutil` 共 4 个包），且被设计成可选 extra `market`「缺依赖时提示安装」，等于默认安装永远跑不通这条示例任务、生产镜像还得单独开开关。改为整源移除：删 `providers/baostock_kline.py` 与注册项、`pyproject.toml` 的 extra `market`（`uv.lock` 同步瘦身）、`RequestSpec` 的 `baostock://` 伪协议白名单、`SourceProvider.fetch_plan` 与 `RequestPlan.variables` 两个纯为它存在的扩展点、管线里的 `fetch_plan` 分支；主表 `股市日线` 改由 `tencent_kline`（前复权）承担，示例任务从 3 个收敛为 2 个。同步把示例里的 `成交额` 列与依赖它的视图 / 模板一并去掉（两个 HTTP 源都不提供），量价模板改用累计成交量。依赖图回到纯 HTTP + 标准库，`uv sync` 默认安装即可跑通全部示例同步
- **工作区列表改为 GitHub 风格可折叠行列表**：原卡片网格一屏只能放 8 个工作区，且每张卡片底部常驻「置顶 / 备份 / 设置」三个入口，次要信息与操作抢同一块视觉空间。改为行式列表 —— ① **收起态只留两个图标按钮**：左侧 `›` 展开、右侧 `☆` 收藏（复用 pin 状态，语义统一为「收藏」），行内只剩类型图标 / 名称 / 公开性 / 类型与角色标签，桌面端右侧补表数·成员数·更新时间，移动端隐藏次要元信息；② **展开后才出现更多操作**：点 `›` 原地展开详情区，含完整描述、全部标签、「编辑已关闭」说明、数据表速览（按需拉取前 8 张表，点表名直达该表，超出走「查看全部」）与「进入工作区 / 工作区设置 / 备份导出」按钮，`aria-expanded` 同步；③ **收藏单独成组**：已收藏的工作区集中到顶部「已收藏」分组并显示计数，其余归入「其他工作区」，收藏状态变化即时换组；④ 多行可同时展开（与 GitHub 文件树一致），样式类由 `cn-ws-card` 换为 `cn-ws-row` / `cn-ws-detail`，深浅色均走主题变量。测试补 5 例（默认收起不渲详情与更多操作 / 展开收起 / 表速览跳转 / 文档类工作区不请求表列表 / 收藏分组与 `aria-pressed`），原「置顶」断言改为收藏图标入口
- **「数据源示例」样本从 180 行 / 3 个月扩到约 2.2 万行 / 5 年，同步任务收敛为 tencent / sina 一源一表**（ADR 0013 P1-P2）：原示例只有 3 标的 × 60 交易日（2026-07-01 ~ 09-22），MA60 / 年度涨跌 / 量价关系这类模板拿不到真实形态。改为 **10 只 A 股（白酒 ×2 / 银行 ×2 / 保险 / 电池 / 汽车 / 有色 / 电力 / 家电）× 2021-10-18 ~ 2026-10-20**，单标的约 1,210 根，与 StockMaster 线上（7,778 标的 / 189 万条 / 单标的 1,212 根）同口径。**一源一表**：`股市日线`（腾讯前复权）/ `股市日线-新浪`（不复权），复权口径不混写；`datasource.json` 只剩 2 个任务（17:30 / 17:45 错峰），移除 eastmoney 的 6 个示例任务（provider 代码与 `cndb sync batch-kline` 保留，「自选股」表与 kline 视图保留为静态示例，标的收敛为与两源一致的 10 只 A 股）。`views.json` 两表各配「全部」+ 单标的 K 线，主表另加放量日 / 最近一年 / 成交量图 / 量价散点图；`analytics.json` 三模板 `limit` 1000 → 3000，量价模板的「区间累计成交额」改为「区间累计成交量」（两个 HTTP 源都不提供成交额列）。示例 CSV 由新增的 `scripts/build_example_kline.py` 实抓生成（区间裁剪 + 幂等去重，抓空时保留原文件）
- **文档协作者功能下线（含站内通知）**：文档可见性回到「按状态判定」的唯一口径 —— `published` 全工作区可见，`draft` / `archived` 仅创建者与工作区 `OWNER`；删除文档级授权能力（`DocumentPermission` 模型与 `documents_permission` 表、`document_permissions` 服务、`GET|POST|DELETE /{doc_id}/permissions` 三个端点、`resolve_document_write_mode` 的 editor 越权直编、`update_content(enforce_role=...)` 绕过入口、序列化的 `collaborator_count` 与 `visibility=shared` 档）。前端移除编辑器「协作者」按钮与 `DocumentCollaboratorsModal`、文档树/列表的「共享 N 人」标记、`documentsApi` 的 permissions 封装；`DocumentEditorPage` 窄屏「更多」菜单同步删项。站内通知的**唯一产生方**就是协作者邀请，随之整体下线（`Notification` 模型与 `accounts_notification` 表、`/api/v1/accounts/notifications` 三个端点、`accounts/services/notifications.py`、`NotificationBell` 顶栏铃铛与 `notificationsApi`）。迁移 `2c3d4e5f6a70` 幂等删除两张表（downgrade 可重建结构，历史数据不回填）；`docs/DOCUMENT_EDITING_AND_PERMISSIONS.md` 删除「文档级协作者授权」整节并同步可见性口径、写模式分派、权限矩阵与端点速查
- **项目配置文件精简（去重 / 去死配置）**：覆盖率阈值原先在 `Makefile`（`COV_THRESHOLD`）、`pyproject.toml`（`fail_under`）、两套 CI（`--cov-fail-under=95`）四处维护，现收敛为 `pyproject.toml` 一处 —— 实测 pytest-cov 直接继承 `[tool.coverage.report].fail_under`，故 `make cov` 与 `.github/workflows/ci.yml`、`.codeup/pipelines/ci.yml` 均不再传该参数；`Makefile` 的 `.PHONY` 补上遗漏的 `patch` / `minor` / `major` 与 `dd` / `ddd` / `db` / `de` 短别名。`.gitignore` 去掉重复的 `.idea/`、已被无前缀规则覆盖的 `frontend/node_modules/` 与 `frontend/package-lock.json`、Sphinx 残留 `docs/_build/` 与无生产者的 `.preview`、根级 `.eslintcache/`（eslint 只在 `frontend/` 跑，缓存落在 `frontend/.eslintcache`），并把 `.uploads/`（`UPLOAD_DIR` 实际在数据目录，仓库内该目录只是调试残留）纳入忽略、从索引移出；`frontend/.gitignore` 删掉转义失效的 `..\/src\/cndb\/static\/` 行；`.dockerignore` 删掉 tox 残留；`pyproject.toml` 的 coverage `omit` 去掉恒无效的 `tests/*`（`source = ["cndb"]` 已限定统计范围）。顺带修正 `docker-compose.prod.yml` 的 `CNDATABASE_URL` 拼写（应为 `DATABASE_URL`；此前该行是无效配置，实际靠 `CNDB_DATA_DIR` 派生的默认值生效，修正后行为不变）
- **Makefile 精简（165 → 128 行，目标 40+ → 28）**：删除两端别名（`fs`/`fl`/`ft`/`fp`/`fst`/`ftest`/`fcov`/`fcov-html`/`fc`/`fb`/`b`/`c`/`cf`/`cd-check`）与薄包装目标（`frontend-lint` / `frontend-typecheck` / `frontend-patches` / `frontend-test` / `frontend-check` / `frontend-coverage-html`）—— 前端单跑 lint / typecheck / 覆盖率 HTML 直接用 `pnpm check` / `pnpm test:coverage` / `pnpm test:coverage:html`；门禁分级（`check-docs` / `check-fast` / `flow` / `check`）与全名前端口（`frontend-static` / `frontend-coverage` / `frontend-build`）保持不变，文档与技能里的引用无需跟着改。三段内联 Python 一行流下沉为 `scripts/help.py`（帮助）、`scripts/clean.py`（清理）、`scripts/push.py`（推送）；前端依赖改用 `frontend/node_modules/.make-sync` stamp 驱动（lock / `package.json` 未变时零开销跳过，`make sync` 只装后端，前端由 `dev` / 前端目标按需安装）；pytest worker 固定 8（`make test PYTEST_JOBS=4` 可覆盖），删掉 cgroup / 平台探测 20 行；`pack` 交给 fspack 默认「当前平台」，删掉三处重复的平台探测
- **首屏主包瘦身 190.10 → 175.22 KiB（-7.8%），修复 CI 体积门禁超限**：主入口一直被 `rc-field-form`（95.4 KB）+ `@rc-component/async-validator`（39.7 KB）占着，但首屏根本不渲染表单 —— 链路是 `Button` 的 style token → `antd/es/color-picker` → `antd/es/form/context` → `import { FormProvider } from 'rc-field-form'`，而 rc-field-form 未声明 `sideEffects` 且 barrel 顶层给默认导出挂静态属性（`RefForm.FormProvider = …`，属性赋值被 Rollup 判为副作用），导致整库无法摇树。经 `pnpm patch rc-field-form@2.7.1`（补 `"sideEffects": false` + 去掉 barrel 顶层静态属性挂载、保留 `forwardRef` 包装，antd 在自己的 `Form` 上重挂 `Item/List/useForm/useWatch/Provider`，默认导出的静态属性无人使用）后表单代码回到按需 chunk（`useForm-*.js`，21.9 KB）；`bundle-budget.json` 主入口基线同步下调至 175.22 KiB 以锁住净收益，`docs/BUNDLE_BUDGET.md` 补「第三方依赖隐性膨胀」排查手法与判据
- **gitignore 收敛生成产物**：`src/cndb/static/` 只保留 `.gitkeep`（前端构建产物由 CI / 部署构建，不再可能被误提交）、Playwright 登录态 `frontend/.auth/`（含 access token）与 `.auth/`、e2e 隔离数据 `.e2e-data/`、`frontend/blob-report/`

### 新增
- **大模型提示词配置简化：工作区级连接 + 内置系统提示词 + 空表自动建表 / 补字段 / 自动幂等键 + 5 组推荐提示词**（ADR 0019 P0-P2）：此前 `llm_prompt` 任务必须逐条填 API 地址 / 模型 / 系统提示词 / 幂等键，且目标表必须预先存在，等于「想写一句提示词」要先懂完整数据源配置。现在改为 —— ① **工作区级大模型连接**（ADR 0019 P0）：新增表 `datasource_llm_config`（`workspace_id` 唯一，`base_url` / `model` / `api_key`（Fernet 密文）/ 可选 `system_prompt`）与迁移 `5e6f7a8b9c01`（幂等建表 / downgrade 删表）；新增 `GET|PUT /api/v1/workspaces/{wid}/datasource/llm-config`（viewer 读 / editor 写，密钥只写不回显、`clear_api_key` 可清空），`services/connection.py` 统一解析连接与默认值（`https://api.deepseek.com` / `deepseek-chat`），任务 `request_spec` 缺省 url/model 时自动补齐，API Key 优先级仍为会话 > 连接。② **内置系统提示词**（ADR 0019 P0）：`providers/llm_prompt.py` 新增完整 `DEFAULT_SYSTEM_PROMPT`（角色 / 只输出 JSON / `rows` 结构 / 字段命名与类型约定 / 不得编造 / 日期口径），未配置 system 时自动使用；提示词模板改为宽松求值（JSON 裸花括号可直接写，未知 `{xxx}` 原样保留，仅替换 `{today}` 等已注册变量）；任务保存只强制用户提示词，cron 不再强制 `match_keys`，`test-connection` 未传 session 时回退工作区连接；备份升 v6（导出连接配置但不含 api_key，导入兼容 1-5）。③ **空表自动落表**（ADR 0019 P1）：新增 `services/auto_table.py`（目标表留空按任务名建表 / 同名复用、空表判定、`infer_match_keys` 自动识别幂等键），`upsert_rows` 支持空表自动补字段与自动幂等键，`runner` 仅在 `llm_prompt` 且行非空时启用并把 `auto_fields` / `auto_match_keys` 写入 `run.detail`、推断出的键回填任务；抓取预览返回 `suggested_match_keys`。④ **前端极简表单 + 推荐提示词**（ADR 0019 P2）：任务抽屉只保留「任务名称 / 用户提示词 / 目标表（留空自动建表）」，连接 / 系统提示词 / 幂等键 / 调度等收进高级设置；页头新增「大模型连接」弹窗（含测试连接）与已配置状态；新增 `llmPromptPresets.ts` 5 组预设（每日新闻摘要 / 城市天气 / 股票行情快照 / 电商竞品价格 / 行业政策公告，每组带适用场景、建议目标表字段、建议幂等键与 prompt 示例）一键套用。⑤ **测试**：新增 `tests/test_datasource_llm_config.py`、`tests/test_datasource_auto_table.py` 并扩展 provider / 接口 / 备份 / 迁移用例，前端补 `llmPromptPresets.test.ts` 与 `DatasourcePage.test.tsx`（极简表单 / 预设套用 / 连接弹窗 / 预览幂等键）
- **大模型推荐提示词扩为 8 组**（ADR 0019 P2 追加）：在首批 5 组之外新增「商业航天新闻动态 / 美食推荐做法 / 国际形势发展动态」3 组预设（含建议目标表字段、建议幂等键与可直接运行的 prompt），页面按钮按预设数量动态显示、一键套用；文档附录与需求卡片同步补 3 组说明；工作区「大模型连接」沿用 DeepSeek 默认（`https://api.deepseek.com` / `deepseek-chat`），API Key 留空由用户在页面填写
- **大模型连接弹窗支持输入 Key 后直接测试**（ADR 0019 P2 追加）：`POST /test-connection` 新增可选 `api_key`（仅本次请求使用、不落库、不回显），Key 优先级为 请求 `api_key` > 会话 Key > 工作区连接 Key；前端连接弹窗「测试连接」优先使用当前填写的 Key，无需先保存即可验证，未填写时回退已保存 Key；接口与页面测试同步补齐
- **导入数据表自动识别表头行（顶部合并行兼容 + 概率提示 + 人工改选）**（ADR 0018 P0-P2）：此前解析层固定把「文件第一个非空行」当表头，顶部带跨列合并标题行的 Excel/CSV（如 A1:D1 合并写「2024 年销售报表」）会被当成唯一列名，导致空列名报错或整表列错位。现在改为**两个导入入口共用一套判定**：① **判定入口** `transfer/header_detect.py` 对前 20 个非空行按「列覆盖率 / 文本率 / 唯一性 / 简短度 / 与下方数据的类型反差 / 上方行稀疏度 / 空洞率」打分，softmax 归一为概率并按绝对合理性校准（无后续数据 ≤0.55、单列 ≤0.7、纯数值行 ≤0.45），返回表头行号、置信度、跳过行数、中文提示与候选列表；`confidence < 0.6` 标记 `requires_review`。② **两条链路接入**：新建表 `parse_file_to_rows_with_detection` / `create_table_from_file_with_detection` 与已有表 `Importer._parse_csv` / `_parse_xlsx` 均支持自动识别与显式 `header_row`；JSON 无表头概念（`header_detection=null`）。识别只缓冲 20 行后继续流式，WPS 虚假范围与大文件上限不变。③ **落库一致**：表头行写入既有 `ImportTask.validation_report`（analyze→execute 载体，零 DDL / 零迁移），analyze 写、execute 读，reanalyze / confirm 可覆盖，保证预览与落库同一行。④ **前端**：`FileImportPreview`（新建表）与 `ImportPanel`（已有表）展示识别提示条 + 置信度 Tag（低置信 warning）+ 候选行下拉，改选后重新 analyze / reanalyze 并刷新字段与样本，建表 / 确认导入回传 `header_row`。⑤ **测试**：新增 `tests/test_import_header_detection.py`（判定层、CSV/XLSX 解析含真实合并单元格、两个入口接口共 28 例），前端两个组件单测覆盖提示 / 改选 / 回传 / JSON 不渲染，既有导入回归全绿
- **文档游客级只读分享（匿名分享链接，免登录）**（ADR 0017 P0-P2）：把既有「半条链路」的匿名分享补成可交付的游客只读能力 —— ① **后端判定单入口**：新增 `resolve_public_share`，未知 token / 已撤销 / 已过期 / 未发布 / 归档 / 软删一律返回 404 且文案一致（不再用 403 泄露 token 存在性）；`GET|POST /api/v1/documents/share/{token}`、`/{token}/meta`、新增的 `/{token}/files/{file_key}` 全部先经该入口。② **最小披露**：公开响应改为显式白名单 `{title, content, updated_at}`（文件夹无 `content`），不再复用内部详情序列化；`meta` 只回 `{title, has_password}` 且不计数；分享列表继续只回显 `has_password`。③ **只读与计数**：匿名路由只有 `GET`（密码入口 `POST` 仅换取读取）；成功取正文 `view_count` 原子 +1，`meta` 与密码失败不计。④ **免登录图片**：公开图片端点只放行归属当前分享文档的栅格图片（`FileOwner.document_id` 收口，svg/html 等脚本化类型 404），路径校验统一走新增的 `files_service.resolve_workspace_file`（`tables/routers/files.py` 同步改为调用它，单一路径校验实现）；匿名成功响应加 `Cache-Control: no-store`，图片加 `X-Content-Type-Options: nosniff`。⑤ **前端公开页**：新增 `/public/share/:token` 独立路由（注册在 `ProtectedRoute` 之外，不请求任何工作区鉴权接口）与 `PublicSharePage`，覆盖加载 / 密码 / 不存在或已失效三态，兼容历史密码分享；`MarkdownPreview` / `DocumentImage` 新增 `publicFileBase` 走免登录图片 URL，外部图片在公开模式加 `referrerPolicy="no-referrer"`。⑥ **分享管理入口**：`DocumentShareModal` 支持创建 / 复制链接 / 访问次数 / 撤销（创建固定 `viewer`，仅已发布文档可建），编辑器「更多」菜单与顶栏按 `owner` / `editor` 且非文件夹展示；viewer 不显示且后端 `require_editor` 仍 403。⑦ **测试**：新增 `tests/test_document_public_share.py`（判定统一 404 / 白名单 / 密码流程 / 计数 / 只读方法 / 图片归属与扩展名 / 路径穿越 / 表视图匿名分享仍 404），`test_cov_documents_extra.py` 过期分享断言由 403 改 404；前端补 `PublicSharePage` / `DocumentShareModal` / `DocumentImage` / `MarkdownPreview` / `DocumentEditorPage` 单测；e2e `document-public-share.spec.ts` 覆盖匿名上下文直达公开页、不请求工作区鉴权接口、撤销与取消发布后失效（显式空 `storageState` + `localStorage` 无 token 断言，避免 test runner 带入登录态）
- **认证页背景新增可切换的宇宙星系动效（多座星系 + 多轴进动 + 切换器 / 偏好）**（ADR 0016 P2）：在既有 Perlin 流场粒子基础上新增 `galaxy` 效果 —— ① **多座星系**：固定种子生成桌面 3 座共 1600 星点 / 移动 2 座共 700 星点，每座由核球（18%）+ 两条对数螺线星臂（36%）+ 弥散星尘（46%）组成，大小 / 倾角 / 色相 / 自转方向各异；星点只存盘面极坐标，按内快外慢差分角速度自转，再经每座独立的三轴倾斜矩阵 `Rz·Rx·Ry` 投影到屏幕，pitch / yaw / roll 以不同相位与方向缓慢进动，几座星系相互翻滚；② **朦胧感**：每座星系缓存外晕（5 色标）+ 核球（3 色标）两层径向渐变并按包围盒裁剪，星臂 / 星尘提量，亮星额外垫低透明度柔光；首帧即完整可见，reduced-motion 为同一套采样的完整静帧；③ **切换与持久化**：右下角原生切换器循环 `flowfield ↔ galaxy`，偏好写 `localStorage['cndb_auth_bg']`（非法值 / 存储异常回落 `flowfield`），刷新保持；切换先 dispose 旧实例再挂载新实例，仍单 rAF；④ 切换器独立于 `aria-hidden` 背景层，`type="button"` + `aria-label`，移动端 12px 内缩、reduced-motion 去过渡。测试：galaxy 8 例（多座渐变 / 色标 / 批量着色 / 移动端 2 座 / 固定种子 / 视差）、preference / 切换器 / AuthBackground / engine / AuthLayout 共 41 例，login / register smoke 补切换与刷新保持
- **认证页动态背景改为 Perlin 流场粒子（青紫渐变，固定深色舞台）**（ADR 0016 P0-P1）：`/login`、`/register` 共用 `AuthLayout` 接入原生 Canvas 2D + `requestAnimationFrame` 背景层，零第三方动画依赖，保留**唯一动效**——固定种子 improved Perlin 2D 噪声方向场驱动粒子漂移（桌面 800 / 移动 320），每颗粒子维护一段环形尾迹（桌面 40 / 移动 26 个历史点）并每帧连成青紫渐变流线（`--cn-auth-accent` 青 `#22d3ee` → `--cn-auth-accent-alt` 紫 `#a855f7` → 青），首帧预热「尾迹点数 + 8」步灌满缓冲后直接给出稳定流线静帧（单帧位移仅 0.x px，只画单帧线段几乎不可见）。页面舞台固定近黑 + 青紫双色径向光晕 + ink 网格（独立 `:root` 块，不随 10 套主题），登录卡片继续跟随主题；删除 5 个旧变体（星座 / 星云 / 极光 / 数字雨 / 光点）、右下角切换器与 `localStorage['cndb_auth_bg']` 偏好。`prefers-reduced-motion: reduce` 只画预热静帧、画布 `aria-hidden` + `pointer-events:none`；无 Canvas / 取色失败回落 `.auth-shell` 固定深色 CSS 背景。引擎单 rAF、`document.hidden` 暂停、resize 150ms 节流、dispose 幂等，移动端 DPR ≤ 1.5 / 30fps、桌面指针仅作 ≤ 0.36 rad 轻微偏转；背景经 `lazy()` 独立 chunk（gzip 2.72 KiB ≤ 8 KiB）。测试：flowfield / palette / engine / AuthBackground / AuthLayout 单测，login / register smoke 补 `data-effect="flowfield"` 与画布可见性断言
- **数据源同步接入大模型：`llm_prompt` provider + 提示词 + cron + 连通测试**（ADR 0014 P0-P2）：新增 `llm_prompt` 数据源适配器，按 OpenAI 兼容 `POST {base_url}/chat/completions` 发提示词并把模型返回的 JSON 落表 —— ① **配置**：API 地址、`prompt.system` / `prompt.user_template`（内置占位符 `{entrant}` / `{start}` / `{end}` / `{today}`，未知占位符保存即 400）、`llm.model / temperature / max_tokens / json_mode`；API Key 只走既有凭证会话（`secrets.api_key`，Fernet 密文，运行期渲染 `Authorization: Bearer`）。② **结果**：模型回复必须是 JSON（对象 / 对象数组 / `{"rows": [...]}`），去 Markdown 围栏后经字段映射与 `match_keys` 走既有 `upsert_rows`；解析失败直接 `failed` 且不写任何行，`run.detail.response_metadata` 留痕模型名与 token 用量。③ **调度**：复用既有 cron；`llm_prompt` + cron 强制配置 `match_keys`，避免每轮重复插入。④ **连通测试**：新增 `POST /api/v1/workspaces/{wid}/datasource/test-connection`，用未保存的 `request_spec` + `session_id` 发一次最小请求，返回 `ok / latency_ms / model / message`，不落库、不写运行记录、不推进游标；失败也返回 200 便于前端展示。⑤ **前端**：任务抽屉按 `provider=llm_prompt` 条件渲染 API 地址 / 模型 / 系统与用户提示词 / temperature / max_tokens / JSON 模式，隐藏分页与响应数组路径，新增「连通测试」按钮与成功 / 失败提示，cron 时提示幂等键必填。测试：provider 单测 36 例、接口层 `TestLlmPrompt` 10 例、页面 6 例（条件渲染 / payload 组装 / 连通测试成功与失败 / cron 提示 / 非 LLM 不渲染）
- **行情 provider `sina_kline`（HTTP）**（ADR 0013 P0）：解析新浪 `getKLineData` 的平铺数组（`day→trade_date`、空值行剔除、非法响应显式报错），只给最近 `datalen` 根（上限 1023）且仅不复权。配套协议扩展：`uses_custom_parse`（专用 provider 的 `parse` 通过注入 `response_handler` 真正生效，见「修复」第一条）、`pipeline.fill_entrant`（响应不带标的时按请求维度 `setdefault` 补齐，新浪因此具备幂等键）。测试：新增 `tests/test_datasource_sina.py`（9 例，平铺数组解析 / 空日剔除 / 非法响应 / 类型归一 / handler 注入 / 补标的，全部离线）
- **工作区顶栏统一搜索（文档 + 数据表，默认按激活视图收敛）**（ADR 0012 P0-P2）：把散在文档模块里的检索入口收敛成**一个顶栏搜索区**，参考 GitHub header —— ① **后端**新增 `GET /api/v1/workspaces/{wid}/search`（`scope=all|documents|tables`），一次请求同时给文档（复用文档插件的 FTS5，含中文子串兜底与未发布可见性口径）与数据表两路结果：表名/描述命中 + 表内行命中；行检索复用 `list_rows`（`$query` 全局关键词、行级权限、字段隐藏、软删除排除与网格完全同口径），无视图上下文时最多扫 8 张表 / 每表 3 行 / 总命中 ≤ 20，单表异常不影响整体。② **数据表默认只搜当前激活视图**：表上下文（`/w/:wid/tables/:tid` + `?view=`）时前端下发 `table_id` + `view_id`，后端把视图 `filters` 按原 AND/OR 语义作为前置条件再与关键词 AND 组合；视图不可见 / 不属于该表 / 参数失效则退化为整表检索，面板底部回显「表名 · 视图「名称」」。③ **前端**新增 `GlobalSearch`（范围三档「工作区 / 数据表 / 文档」+ 结果按「数据表 / 表内数据 / 文档」分组带计数、`↑↓`/`Enter`/`Esc` 键盘操作、`Ctrl K` 与 `/` 聚焦、范围偏好落 localStorage），桌面端嵌在顶栏工作区切换器右侧、移动端收为图标 + 顶部抽屉；点击文档进编辑器、点表/行进该表网格。④ **移除旧入口**：文档总览「全文搜索」按钮与 `SearchDrawer` 删除（「本页标题过滤」保留），文档编辑器工具栏「查找」按钮删除（查找替换仅保留 `Ctrl+F` 与右键菜单）。测试：后端 11 例（范围分路 / 视图收敛 / OR 语义 / 坏视图退化 / 跨表不串数据 / 非成员 403）、前端 6 例（分组结果 / 跳转 / 范围切换 / 视图回显 / Esc），文档页与编辑器既有 201 例全绿
- **股市 K 线增强（多周期复权、全历史字段与行内 K 线视图）**（ADR 0011 P0-P1）：「数据源示例」工作区新增 **自选股** 表与 `view_type=kline` 视图，落地「一只股一行、K 线按选中行切换」——① **数据形态**：一标的一行，代码 / 名称 / 市场 / 行业 / 是否自选 / 最新行情快照 + 5 个 `json` 列（日线前 / 后 / 不复权、周线 / 月线前复权），K 线元素含日期 / 开 / 收 / 高 / 低 / 成交量 / 成交额 / 振幅 / 涨跌幅 / 涨跌额 / 换手率 11 字段；seed 由 `自选股.json` + `股市日线.csv` 生成日线前复权并在 Python 派生周 / 月前复权，**手动建表**避免 K 线 list 被自动推断成 multiselect。② **数据源**：新增 `eastmoney_kline` provider（东方财富，`secid` 按 sh/sz/hk/us 前缀换算，`klt` 日 / 周 / 月、`fqt` 前 / 后 / 不复权、`beg=0&lmt=100000` 全历史，一只股一行）；`normalize` 新增 `json` 类型分支（字符串校验后落库、对象 / 数组紧凑序列化）；示例 `datasource.json` 配 5 个分列 job（日线三口径 + 周 / 月前复权），`match_keys=["股票代码"]`、`cursor=none`。③ **部分列 upsert**：`RowValidator` / `Importer` 新增 `partial` 参数（不跑 gap_filling、未提供的字段不参与必填校验与更新），数据源落表 `upsert_rows` 固定 `partial=True`，多 job 分列写同一行互不清空，普通导入语义不变。④ **视图**：`view_type=kline` 新增 `KlineView`（左侧标的列表搜索 / 单选 / 键盘操作，右侧 ECharts 双 grid 价格 + 成交量、dataZoom 联动、MA5/10/20/60、周期与复权切换、红涨绿跌、窄屏 Select、缺列 / 坏 JSON 空态），纯逻辑抽到 `klineBoard.ts`（解析兼容字符串 / 数组 / 字段别名 / 数值字符串，排序去重，周 / 月由日线重采样）；后端 `routers/views.py` 与 seed `cli/seed/views.py` 两处字段白名单 + 语义校验同口径扩展；`viewModes` / `GridPage` / `viewOptionSchema` / `CreateEditViewForm` 同步注册新模式与 17 项配置。⑤ **全市场（P1）**：新增 `eastmoney_symbols` provider（行情列表分页，A / HK / US / 全部）写入自选股表，新行 `是否自选` 由字段默认值落 false、已勾选行不被覆盖；新增 `cndb sync batch-kline`：从自选股表读标的（默认只取自选）按市场过滤、每批 ≤100 只 × 每个序列幂等创建 / 更新 `eastmoney_kline` 任务，支持错峰调度、`--prune`、`--dry-run`、`--json`。测试：后端 provider / partial upsert / 视图校验 / seed / batch-kline 等 177 例，前端 klineBoard / KlineView / viewModes 单测与 e2e「切 K 线视图 → 切换标的 / 周期 / 复权空态」
- **Docker 开发模式与离线部署文档**：新增 `make docker-dev` / `make docker-dev-down` —— 用新增的 `docker-compose.dev.yml` + `deploy/Dockerfile.dev` 在容器内起后端（uvicorn `--reload`，:8772）与前端（Vite，:5173），仓库根 bind mount 进容器、改源码即热更，等价宿主 `make dev` 但无需本机 Python / Node；开发数据落独立命名卷 `cndb-dev-data`，前端 `node_modules` 落 `cndb-dev-node-modules` 卷（容器重建不重复下载），均不碰宿主 `~/.cndb` 与宿主 `node_modules`。开发镜像只装运行时依赖（`uv sync --no-install-project --no-group dev`，装到 `/opt/venv` 以免被挂载覆盖），`import cndb` 经 `PYTHONPATH=/app/src` 命中挂载源码，并补 `/opt/venv/bin/cndb` 包装脚本（`--no-install-project` 不会生成 `[project.scripts]` 入口，容器内 `cndb seed` 因此可用），与生产镜像 `Dockerfile.prod` 关注点分离。镜像构建默认走国内源：基础镜像经 `docker.m.daocloud.io` 代理、apt 换腾讯云 Debian 源、pip / uv 依赖用腾讯云 PyPI（`pyproject` 已配 `[tool.uv.index]`）、pnpm 与依赖用 npmmirror（corepack 经 `COREPACK_NPM_REGISTRY` 拉取），可用 `CNDB_PYTHON_IMAGE` / `CNDB_APT_MIRROR` / `CNDB_PIP_INDEX` / `CNDB_NODE_IMAGE` 逐项切回官方源。README 展开「离线打包与部署」为可照抄的三段式命令（`make docker-build` → `make docker-export` → `OFFLINE=1 ./deploy/deploy.sh`）并补交付包与边界说明；`docs/DEPLOY_TENCENT.md` 第八节仍为完整链路
- **文档通用文件导入（单文件 / 文件夹，md·docx·html）**（ADR 0010 P0-P2）：文档总览新增「导入」入口，支持**单文件**（1 文件 → 1 文档）与**文件夹**（目录 + 相对路径 → 文件夹层级 + 文档）两种模式，覆盖 `.md` / `.markdown` / `.docx` / `.html` / `.htm` 三类源；导入时**自动格式化**——正文统一转 Markdown（docx 按 body 流序转标题/段落/列表/表格、html 经标准库 `html.parser` 转标题/段落/列表/链接/表格，md 走规整），**自动识别标题**（内嵌标题 > 首个显式标题行 > 文件名，命中标题行从正文剥离）与正文，**自动清理多余空格**（保守清理：行尾空白、连续空行折叠、行内连续空格折叠、无效行首缩进；跳过代码围栏 / front-matter / 表格，不改中英文间空格）；内嵌图片抽取为站内附件并改写为 `![](file:<key>)`。逐条隔离（单条失败只记 `skipped`，整批继续）；批次校验条目数 / 单文件 / 总量三层上限。后端新增 `services/importers/`（reader / normalize / markdown / docx / html / importer）与端点 `POST /{wid}/documents/import/files/analyze`（只读预览）、`POST /{wid}/documents/import/files`；前端新增 `DocumentImportModal.tsx`（单文件 / 文件夹模式、冲突策略、附件开关、状态选择、预览与结果明细）与工具栏「导入」按钮（原 Obsidian 入口改名「导入库」保留）。测试：转换管线 + 接口层 115 例、前端单测 6 例、e2e 单文件 / 文件夹 2 例
- **股市日线典型示例（数据源同步 + K 线等关键视图）**（ADR 0009 P0-P2）：「数据源示例」工作区的**股市日线**表补齐端到端典型链路 —— ① 图表视图新增 `chart_type=candlestick`（K 线）：`view_options` 配 `time_field` + 开/高/低/收四价字段，前端注册 ECharts `CandlestickChart` 渲染蜡烛（中国市场红涨绿跌），统计面板以收盘价字段算描述统计，必填缺失落空态；后端 `routers/views.py` 与 seed `cli/seed/views.py` 两处视图字段校验白名单同步放行新字段键（含 `charts[i].*` 条目，校验单一口径）。② 新增 seed 数据源种子：`cli/seed/datasource.py` 扫描各工作区 `examples/datasets/<工作区>/datasource.json` 注入 `datasource_sync_job`（表名解析为真实 `table_id`，字段映射/幂等键引用列不存在则告警跳过，按 `(workspace_id, name)` 幂等），示例配 `tencent_kline` 单任务多标的（`entrant_keys=[sh600519,sz000001,sz300750]` → 每代码一个 URL）幂等 upsert 到同一张表，`enabled=true` 但 seed 只注入配置不触发联网抓取。③ 「数据源示例」`views.json` 增 K线图 / 成交量图 / 量价散点图三个图表视图（K线与成交量图经 `filters` 收窄到单一标的，避免同轴多标的重叠）；把示例 CSV `股市日线.csv` 的股票代码统一为带市场前缀格式（`600519` → `sh600519`），与同步标的 `match_keys` 口径对齐，避免「CSV 预置行 + 同步行」重复落表。测试新增 `tests/test_seed_datasource.py`（注入/幂等/坏表跳过/坏字段跳过/真实配置结构）与 chartBoard·ChartView·viewOptionSchema·view API 的 candlestick 用例，e2e 增「切到 K线图视图渲染 candlestick + 收盘价统计面板」
- **离线部署（无外网隔离环境）**（ADR 0008 P0-P2）：原有取镜像只有「服务器本地构建」与「TCR pull」两条**需要出网**的路径，隔离环境无从部署。新增三段式离线链路 —— 联网机 `deploy/build-image.sh` 本地构建（复用服务器端同一套 `Dockerfile.base` / `Dockerfile.prod` 与依赖指纹，默认无 registry 前缀的本地名 `cndb:<version>`）→ `deploy/export-image.sh` 导出交付包 `cndb-<version>-offline-bundle.tar.gz`（应用镜像 tar + nginx 反代镜像 tar + `docker-compose.prod.yml` + `deploy/` + `.env` 模板 + `SHA256SUMS` + 包内说明）→ 离线机 `OFFLINE=1 ./deploy/deploy.sh <version>`。`deploy.sh` 新增离线模式：按 `SHA256SUMS` 校验、`docker load` 镜像 tar 后走原有预备份 / 重建 / 健康探测 / 失败回滚，全程不出网；离线模式下跳过 TCR 仓库地址的 `/` 强校验以放行本地 tag。构建上下文改为复用仓库根 `.dockerignore`（不再生成临时覆盖文件），并排除 `dist/offline` 交付包产物。新增 `make docker-build` / `make docker-export`；`docs/DEPLOY_TENCENT.md` 补第八节「离线部署」；脚本回归由 `tests/test_deploy_scripts.py`（`bash -n` + 假 docker 桩的交付包结构与校验清单）守门
- **dev 模式端到端回归兜底**（`make e2e-dev` / `pnpm e2e:dev`，CI 在 e2e job 的 shard 1 同步执行）：跑在 **vite dev**（源码直出、不做摇树）上的 Playwright 用例 —— 生产构建经 Rollup 会绕开 `rc-field-form` 的 es barrel，登录页崩溃（`Cannot add property current, object is not extensible`）那类依赖补丁回归**只在 dev 现形**，常规 e2e 全绿也发现不了。用例串成「空提交校验 → 错误密码 → 立即改对登录 → 进入工作区」，并对全程 `pageerror` 零容忍（直接钉死 forwardRef 链路与上条会话竞态）；vite dev 由用例自托管（`tests/e2e/dev/start-dev-server.ts`，显式轮询端口就绪）——Playwright 的 webServer 探活在 Windows + `pnpm exec` 包装下不可靠（探活命中后进程仍可能退场），自托管是最稳做法；dev 代理目标经 `CNDB_API_TARGET` 指向 e2e 隔离后端（开发者本地默认 :8772 不受影响）
- **典型示例支持数据源领域场景 + 数据源示例工作区**（ADR 0006 M4 追加）：字段智能推荐的典型示例按字段名识别两类时序表并追加领域示例——同表存在最高 / 最低气温（且有时间字段）时追加「昼夜温差」（`round([最高气温] − [最低气温], 2)`，折线按城市分区逐日观察 + 汇总比较各城市平均温差），存在最高 / 最低 / 收盘价时追加「振幅与量价」（振幅 =（最高 − 最低）/ 收盘 × 100，有成交量时叠加 5 日量能均线，窗口公式自动带 `partition_by` / `order_by`）；按字段名匹配、纯增量追加，通用业务表的推荐结果不变。新增 seed 示例工作区**数据源示例**：`天气每日`（3 城市 × 92 天的最高 / 最低 / 平均气温与降水量）、`股市日线`（3 标的 × 60 交易日的开高低收 / 成交量 / 成交额）两张表，各带 3 个预置分析模板（温度趋势与均温线 / 昼夜温差分析 / 高温与降水分布；股价走势与 5 日均线 / 涨跌幅与振幅 / 量价关系）与高温日 / 降雨日 / 放量日过滤视图，与数据源同步的实际落表形态一致；顺带修复 seed 分析模板归一化丢失窗口公式 `partition_by` / `order_by` 的问题
- **数据源同步 · 遗留项清零**（ADR 0006 定稿 `Implemented`）：**密钥字段级加密** —— 凭证会话的密钥列改为 Fernet 密文入库（`enc:v1:<token>`），密钥由 `DATASOURCE_SECRET_KEY` 派生、留空回退 `JWT_SECRET`；**键名仍为明文**（读接口要回显「已配置哪些密钥」），历史明文无前缀原样返回因此**存量零迁移**；解密失败（换过密钥 / 密文损坏）会让本次运行落 `failed` 并给出可读原因，而不是静默拿空密钥去打接口变成难查的 401。**分析取数范围** —— `POST .../analytics/compute` 新增 `filters` / `filter_logic`（语法同列表接口），扫描前先按条件收窄，时序表用「时间字段 >= 起点」即可绕开单次扫描行数上限；上限本身提为 `ANALYTICS_MAX_SCAN_ROWS` 可配，但**过滤仍是首选**；未知过滤字段直接 400（列表接口只记 warning 跳过，那等于静默退化成全表扫描）；前端「数据源」卡片新增「分析范围」一行（字段 + 起止值），换表自动清空，结果区截断提示同步引导用范围收窄。**会话管理 UI** —— 由「只能新建」升级为列表 + 新建 / 编辑 / 删除：编辑时密钥**留空表示不修改**（不传该键，避免误清空）、填写则整体替换，删除前提示「引用它的任务会自动解绑」。**`rank` 支持非数值列** —— 全列可数值化时按数值排，否则按原始值字符串排（时间列的 ISO / 定宽格式字典序即时间序），空值仍为空、并列取最小名次，时序表可直接 `rank([日期])` 得行序号
- **数据源同步 · 凭证会话 / 限流 / 列式记录 / 领域模板包**（ADR 0006 M5，迁移 `1b2c3d4e5f60`）：新增 **凭证会话** `datasource_session`（请求头 + 密钥集中管理，任务以 `session_id` 引用）—— 运行期会话 `headers` **铺底**、任务自己的同名头优先，密钥作为**模板变量**注入（请求模板写 `{api_key}` 即可），**读接口只回显键名、密钥不随工作区导出**，删除会话时自动解绑任务（不级联删任务）。新增 **请求限速** `rate_limit_ms`：同一任务内相邻请求的最小间隔，pipeline 只对**真正发出的请求**等待（空页终止后跳过的请求不计），默认 0 不限速。新增 **列式记录**解析：`request_spec.record_mode=columns` + `record_layout` 把「列名 → 数组」响应（如 Open-Meteo 的 `daily.time[]` / `daily.temperature_2m_max[]`）按索引拼成行，长度不齐补空，配 `examples/datasource/weather-open-meteo.json` 可直接照抄的天气示例。新增 **领域模板包**（`GET /datasource/domain-templates`，可按 provider 过滤）：股票日线趋势（收盘价 + 5 日均线 + 涨跌幅）、股票波动与量能（振幅 + 量能均线 + 当日量能排名）、天气日趋势（温差 + 3 日均温）、新闻来源产出，全部带 M4 窗口函数与分区，前端任务行可**一键套用**为分析模板。备份导出改为记 `session_name`（**不导出密钥**），导入按同名会话重绑、找不到则解绑。前端编辑抽屉增「凭证会话」（含新建会话弹窗，密钥保存后不可回读）与「请求间隔」两项
- **数据分析 · 时序窗口函数与通用模板**（ADR 0006 M4）：公式引擎新增 10 个**窗口函数** —— `prev` / `lag([字段], n)` / `lead([字段], n)` / `diff` / `pct_change` / `cumsum` / `rank` / `ma([字段], n)` / `rolling_sum` / `rolling_std`，作用域是「**同一分区内按排序键排列的行序列**」，公式可带 `partition_by`（如股票代码 / 城市 / 来源）与 `order_by`（时间列）+ 升降序；分区键空即全表一个分区、排序键空保持原始行序、排序空值恒排最后。语义细节：`pct_change` 用 `|前值|` 做分母且前值为 0 时返回空，`rolling_*` **不满窗返回空**（不用部分窗口凑数）、`cumsum` 跳过空值、`rank` 并列取最小名次；聚合函数（sum/avg/count/min/max）口径**仍是整列**，不随分区变化。实现上把「列缓存丢空值」改为**行对齐数组**，滚动与累计用**前缀和 / 前缀平方和**、名次用分区预处理表，按分区 O(n)；不含窗口函数的公式仍走原逐行路径，零额外开销。分析模板与计算请求同步携带窗口上下文（保存时校验分区 / 排序字段存在）；**字段智能推荐**新增 `partition_dimension` 角色（表内存在时间字段时，把 symbol/city/source 之类粒度列标出），「时间趋势」示例改为**分区叠加多线 + 3 点均线**，并新增「环比变化」示例（`pct_change` + `ma`）。前端公式编辑器在检测到窗口函数时展开「分区字段 / 排序字段 / 升降序」选择器，快捷函数区补 10 个窗口函数片段、语法提示同步
- **周期性外部数据同步 · 专用适配器与前端任务页**（ADR 0006 M3）：新增两个内置 provider —— `tencent_kline` 解析腾讯 `fqkline` 嵌套 JSON（`qfqday` / `hfqday` / `day` 依次回退，单条数组按「日期·开·收·高·低·量」展开，错误码与非法响应显式报错，未配字段映射时按 K 线语义默认归类型），`rss_atom` 把 RSS 2.0 与 Atom 统一成 `title / link / summary / published_at / source`（`pubDate` 的 RFC 822 与 Atom 的 ISO 8601 都归一为 `YYYY-MM-DD HH:MM:SS`，时间解析失败留空而不中断）；`GET /providers` 随之返回三者及参数表单描述。前端新增**数据源同步页**（工作区页签「数据源同步」，按工作区类型门控，doc 类不开放）：任务列表展示适配器 / 目标表 / 调度 / 上次运行状态，Provider 驱动的编辑抽屉可配请求模板、标的占位符与取值、幂等键、增量策略与调度（手动 / 每天 / 间隔 / cron）、分页与时间切片，保存后可直接「抓取预览」（不落库，展示失败明细与归一失败），运行历史抽屉展示游标区间与新增 / 更新计数。新增后端 18 条 provider 单测（离线 JSON / XML 样例）、前端 8 条页面集成测试、e2e 5 条（进入页签 / 新建保存落库 / 编辑回填 / 必填校验）
- **周期性外部数据同步 · 任务化与调度**（ADR 0006 M2，迁移 `0a1b2c3d4e5f`）：新增两张表 —— `datasource_sync_job`（Provider 引用 / 目标表 / 标的集合 / 幂等键 / 字段映射 / 游标 / 调度 / 启停 / 租约）与 `datasource_sync_run`（状态 / 触发来源 / 游标区间 / fetched·inserted·updated·skipped / 逐请求失败明细），幂等建表、downgrade 可完整还原、存量零迁移。**增量游标四策略**：`date`（按日推进）、`datetime`（按时刻）、`key_set`（无稳定时序，靠幂等键去重）、`none`（每次全量）；首跑按 `backfill_start` 回填，**无新数据不推进**（与「同步失败」区分），源侧乱序返回时**只前进不后退**。**调度四种**：`manual` / `daily@HH:MM` / `interval`（秒） / 5 段 `cron` 表达式，时区按 `tz_offset_minutes`（默认 UTC+8）而非服务器本地时区；失败后按 `retry_backoff_seconds`（默认 300s）退避，避免故障源被每分钟打一次。**调度器**：`tick()` 扫到期任务并按 `lease_owner / lease_until` **原子抢占 DB 租约**，多副本、`cron` 与内置调度器混跑都只有一个执行者；到期配置坏掉的 job 跳过而不中断整轮。**运行编排**：抓取 → 归一 → 按 `match_keys` 落表 → 推进游标 → 写运行记录 + `datasource.sync` 事件（并纳入记录 / 表列表缓存失效）；配置非法（游标 / 调度 / 目标表缺失）也落 `failed` 记录而不炸调度器。**端点**（`/api/v1/workspaces/{wid}/datasource`）：`GET /providers`、`sync-jobs` 增删改查、`POST .../run`（同步执行，租约被占返 **409**）、`POST .../preview`（只抓不落库、不推游标）、`GET .../runs`；viewer 可读、editor 可写，创建时逐项校验 URL 模板 / 游标策略 / 调度表达式 / `match_keys` 是否为目标表字段。**CLI**：`cndb sync list|run|tick|preview`（`--job-id` / `--all` / `--dry-run` / `--json`），生产用 `deploy/sync.sh` 配 `* * * * *` cron。**工作区备份升 v5**：同步任务随导出（跨工作区 id 不可移植 → 用表名引用），导入端按同名表重绑、同名任务跳过、旧版备份（无 `sync_jobs` 键）按空还原
- **周期性外部数据同步 · 通用抓取管线**（ADR 0006 M1）：新增 `datasource` 插件骨架与一套**领域无关**的抓取管线 —— `SourceProvider` 协议（`build_requests` / `parse` / `normalize` + `params_schema`）+ 内置 `http_json` 适配器：请求 URL / headers / params / body 由**模板**声明（`{entrant}` / `{start}` / `{end}` / `{page}` / `{page_size}` / `{offset}`，只做字面替换、缺参即报错、`{{` / `}}` 转义），按「标的 × 时间窗口 × 页码」展开请求；分页支持 `page` 与 `offset` 两种模式并带 `max_pages` 硬上限，时间区间支持 `chunk_days` 按天切片（接口限制单次区间时用）；响应侧复用 `api_fetch` 的 SSRF 防护 / 超时 / 重试 / 体积上限，按 `data_path` 或 `data`/`items`/`results` 等常见键取数组。归一为 `Normalizer`：字段改名、显式丢弃、类型归一（text/int/float/date/datetime/bool，含 `20240305`、epoch 秒/毫秒、`Z` 后缀等形态），**单字段转换失败只降级为 `NULL` 并留痕**，不丢整行。管线失败口径：单请求失败记 `partial` 并继续，分页遇空页提前终止，全部失败为 `failed`。落表复用 `Importer`，按 `match_keys` **应用层先查后写**实现幂等（不引入复合唯一索引，D8），重复运行只更新不新增。新增 72 条单测（模板求值 / 归一 / 请求展开 / 管线 / 落表幂等）
- **修改申请同行合并视图与冲突裁决**（ADR 0005 M1-M3）：列表接口新增 `group_by=row`，按 `row_id` 聚合为行组（组间按最近提交时间倒序、组内按申请时间倒序，`op=create` 归 `ungrouped`），并标出 `conflict_fields` / `drift_fields` / `row_missing`；新增行组批量合并端点 `POST .../change-requests/rows/{row_id}/merge`，一次审批同行的多份 open 申请 —— 无冲突字段自动 apply，**交汇冲突字段必须经 `resolutions` 显式裁决**（采用某份申请值 / 保留当前值），未裁决 409、任一校验失败整体回滚并保持 open，`delete` 与其他写的互斥经 `row_action` 裁决；落库后同行其余 open 申请置 `stale`。前端列表新增「同行合并 / 平铺」视图切换与批量审批，新增冲突处理页 `/w/:wid/tables/:tid/change-requests/rows/:rowId/merge`（当前值 · 各申请目标值 · 逐字段裁决）；`usePendingChanges` 改走聚合端点，行级「编辑中标识」不再逐条拉详情（N+1 消除）
- **行级权限规则**（ADR 0004 的 P0/P1/P2，迁移 `c8d9e0f1a2b3`）：表可在既有「默认行过滤」(`TablePermission.row_filters`) 之上，按**主体 × 动作**配行范围 —— 主体为「指定成员」或「表级成员档」(read/write)，动作为 `view` / `edit`；每个主体每个动作至多一条规则，多段行范围用 `filter_type=OR` 合进一条。新表 `tables_rowpermission` 与 `TablePermission` 同域、独立生命周期，`row_filters` 原样保留不迁移（不变量 I3）。判定收敛为唯一入口 `services/core/row_access.py`：读范围 = 默认档 ∪ view 命中 ∪ edit 命中，写范围 = `[有 EDIT_RECORDS 时: 默认档] ∪ edit 命中`，**读 ⊇ 写**（I4），管理员（表所有者 / 工作区 OWNER / 超管）照旧豁免（D3）；`member_role` 按**有效档位**匹配（靠工作区角色获权的成员也能命中，D5），`edit` 规则的写权独立于表 `EDIT_RECORDS`（D2）；规则 filters 引用到当前用户被隐藏的字段时静默丢弃并标 `degraded_filters`（防侧信道）。写路径下沉到**按行**分派：目标行在写范围内直编；可看不可改写为修改申请并返 **202**；读范围外返 **404**（不泄露存在性，I6）；`create` 与批量端点沿用表级 `EDIT_RECORDS`（不为「仅有行级 edit 权」的主体开旁路）；审计与工作区导出同步改用 `row_read_scope_where`，导出不得越过读范围
- **行级权限配置面与前端**（ADR 0004 的 P2）：新增 `GET|POST /{wid}/tables/{tid}/row-permissions`、`PATCH|DELETE /{wid}/tables/{tid}/row-permissions/{rule_id}`、`GET .../row-permissions/subjects`（可授权对象：本工作区成员 ∧ 对该表有 `READ`）与 `POST .../row-permissions/preview`（命中行 dry-run）；配置入口需 `EDIT_SCHEMA`，普通成员只能按规则效果隐式生效、读不到规则明文，增删改写 `tables_auditlog`，规则变更后清记录缓存（防收紧后泄漏）；备份导出 / 导入携带规则（旧备份无该键时按空规则还原）；前端表设置「权限」页新增行级规则编辑器（成员选择 / 成员档、view·edit、条件组与命中预览）
- **后端极端用例基线**：新增 `tests/test_backend_extreme_cases.py`（40+ 条极端用例，覆盖滑动窗口限流的阈值边界/键归一化/`configure` 钳制/并发、登录限流账号与 IP 双维度、令牌哈希与声明、缓存不变量（负 TTL / producer 异常或返回 None / 幂等删除 / `invalidate_all`）、就绪探测三分支、错误契约默认值、认证头极端形态）；仅锁定既有行为、不改业务逻辑，覆盖率门禁维持 95%
- **文档代码块语法高亮**：Markdown 围栏代码块在**实时预览**与**查看模式**下按语言着色（JS/TS、Python、JSON、Shell、SQL、HTML/XML、CSS/SCSS、YAML、Go、Java、Rust、C/C++ 系），配色走 `--cn-code-*` 主题变量（浅色 GitHub Light / 深色 GitHub Dark 两套，换主题自动跟随）；实时预览里围栏行淡色、内容行带左侧色条，光标进入不打断高亮；查看模式代码块新增语言标签、行数与一键复制（http 非安全上下文退回 `execCommand`）。词法层为零依赖扫描器 `components/Document/codeHighlight.ts`（不引入 highlight.js / shiki，守住文档页体积预算），未知语言按纯文本渲染不猜语法，单块超 100 KB 跳过高亮避免长文卡顿；同时修正 `<pre>` 包 `<div>` 的非法嵌套
- **工作区类型选择**：新增 / 修改工作区时可选用三类 —— **数据 + 文档**（默认，全部功能）/ **数据**（仅数据表与数据分析）/ **文档**（仅文档）；前端按类型门控顶部页签与侧栏表导航（仅数据隐藏文档页签、仅文档隐藏数据表与数据分析），工作区根路由按类型落地（doc → 文档、其余 → 数据表），落在未开放功能区的 URL 自动重定向到合法落地页；工作区列表卡片与设置页展示类型标签，备份导出 / 导入兼容该字段（旧备份无字段按默认回填）。后端新增枚举 `WorkspaceType`、`workspaces_workspace.workspace_type` 列（落库为枚举成员名 DATA_DOC/DATA/DOC）与迁移 `e7f8a9b0c1d2`（幂等加列，存量回填默认值）
- **科研项目管理示例整合原《项目管理》工作区（WBS / 待办 / 资源排期）**：新建 `科研任务分解`（31 行，4 个课题根任务 + 三层 WBS，父任务进度留空由子任务自动汇总）、`科研待办事项`（16 行，7 行空责任人用于演示「未分派」看板分组）、`科研资源排期`（26 行，数据组 / 实验组 / 算法组 / 论文组按周排期）三张表，全部带 `课题编号` 列，经 `fields.json` 的 `link_lookups` 与《科研项目》建「关联课题」link + `项目名称` lookup 实时关联；`views.json` 新增 21 个视图（任务分解 10：全部 / WBS 工作分解结构 / WBS 进行中 / WBS 已交付 / 甘特 / 状态看板 / 优先级看板 / 日历 / 课题任务矩阵 / 执行概览；待办 7：全部 / 按责任人看板 / 按类别看板 / 日历 / 待分派 / 未完成 / 类别占比；排期 4：全部 / 资源排期矩阵 / 团队月度投入矩阵 / 投入概览），整合后该工作区覆盖 grid / kanban / calendar / gantt / wbs / matrix / chart 全部 7 种视图模式；`analytics.json` 新增「任务进度与工期」「课题任务工期分布」「团队投入结构」3 个分析模板；`documents/03-项目执行方法/` 新增 5 篇文档（任务分解规范 / 里程碑与交付计划 / 资源排期与投入规则 / 待办跟进机制 / 周报模板），含 `{{table:…}}` 动态引用与双链
- **用户管理支持批量导入 / 导出**：系统管理台「用户管理」工具栏新增「导入 / 导出」——导出按当前关键词 / 角色 / 状态筛选生成 CSV（UTF-8 BOM，Excel 直接打开）或 Excel，字段含用户名 / 邮箱 / 电话 / 昵称 / 角色 / 启用状态 / 超管标记 / 创建时间，**不含密码哈希**，每次导出记一条操作日志；导入支持 CSV / Excel（列头兼容中英文：username/用户名、email/邮箱、phone/电话、nickname/昵称、role/角色、is_active/启用状态、password/密码），选文件后先做**只读预演**展示可导入 / 跳过 / 失败明细，确认后才逐行创建、单行失败不影响其他行；已存在的用户名 / 邮箱跳过且不修改，密码留空自动生成 12 位并在结果中**仅展示一次**、可下载初始密码 CSV，导入汇总写入操作日志。后端新增 `GET /api/v1/accounts/users/export`、`POST /api/v1/accounts/users/import`（仅超级管理员；单次 2MB / 1000 行上限），CLI `cndb users import` 与 API 共用同一张列头别名表
- **文档版本历史页增强（时间线重做 + 差异原地展开）**：版本抽屉取消「时间线 / 差异对比」两个 Tab，改为单栏时间线卡片 —— 左侧圆点轨道 + 卡片（版本号 / 当前·导入·回滚徽标 / 相对时间（悬停看绝对时间）/ 较上一版体积增减 / 内容体积 / 变更说明），最新版高亮为当前；点「与上一版对比」在**该版本卡片下方原地展开**差异，再点收起，不切页、不跳 Tab，同一时刻只展开一处（上千行 diff 多开会卡）；补充差异加载骨架、计算失败提示、`aria-expanded` 与移动端整宽；回滚改为抽屉内二次确认（说明「不会覆盖当前内容」），回滚成功后同时失效版本列表与 diff 缓存，版本总数超过返回上限时提示「仅显示最近 N 个」。相对时间格式化落地为 `utils/datetime.ts#formatRelativeTime`（<1 分钟=刚刚、分钟 / 小时 / 天、超 30 天回落日期，可注入 now），新增 `VersionsDrawer.test.tsx` 覆盖渲染 / 展开收起 / 加载与错误态 / 回滚确认 / 空态与折叠提示
- **文档结构树支持排序**（参考 Obsidian 文件浏览器）：左栏工具栏新增「排序方式」菜单，可选 手动拖拽 / 名称 A→Z / 名称 Z→A / 创建时间 新旧 / 修改时间 新旧；**文件夹恒在文件之前、置顶恒在最前**，且**每个层级各自排序**（文件夹内部同样生效）；排序偏好存本地（`localStorage`，与 Obsidian 的全局设置同口径），下次进入自动沿用；非手动排序下拖拽仍可改父级（拖进文件夹），仅同级换位被忽略并提示。排序纯函数抽到 `pages/documents/docTreeSort.ts`（中文按拼音、数字感知：项目2 在 项目10 之前），单测覆盖文件夹优先/置顶优先/三字段升降/递归/持久化
- **文档支持 Obsidian 文档库导入 / 导出**：文档总览新增「导入 / 导出」入口 —— 上传库 zip 先出**只读预览**（笔记 / 新建文件夹 / 附件数量、同名冲突清单、front-matter 标签、被忽略条目与告警），确认策略后才落库；导入保留**目录层级**（目录 → 文件夹）、以 front-matter `title` 为文档标题（缺省用文件名）、`tags` 建为工作区标签并关联、`![[图片]]` 与 `![](attachments/x.png)` 上传为站内附件并改写为 `![](file:<key>)`、`[[笔记#锚点|别名]]` 统一规范化为 `[[标题]]`（与站内反链口径一致），`.obsidian` / `.trash` / 隐藏项一律忽略；同名冲突支持**保留两份（自动改名）/ 覆盖（生成新版本，历史可回溯）/ 跳过**，可选导入到指定文件夹、可选是否导入附件与标签、可选文档状态；导出按可见性裁剪后输出 `<库名>/<文件夹>/<标题>.md` + `attachments/` + 最小 `.obsidian/app.json`（解包即可被 Obsidian 打开），正文 `file:` 引用反向改写为 `![[attachments/…]]`，导出物可再次导入（回环自测覆盖）。后端新增 `POST /documents/import/analyze`、`POST /documents/import`、`GET /documents/export/vault`；安全边界：仅 `.zip`、解压总与单项体积上限、条目数上限、zip 路径穿越条目丢弃、viewer 不可导入
- **Obsidian 导入转换增强（双链保真 + 结构文件转文档）**：导入不再丢双链信息 —— `[[笔记/设计稿#架构|设计]]` 只剥掉库内路径前缀与 `.md` 后缀，**锚点与别名原样保留**，渲染时显示别名（无别名则显示「标题 › 锚点」）并按标题跳转；反链、出链、断链修复全链路改为按目标标题匹配，断链修复改写同样保留锚点/别名（`[[旧#锚点|别名]]` → `[[新#锚点|别名]]`），出链抽屉展示正文原始写法；`.canvas` / `.base` 不再被丢弃，而是转换为文档导入：Canvas 转成「卡片 / 连线 / 文件引用」结构化正文（文本卡片正文原样保留、文件卡片转双链、连线带标签），Base 保留为 yaml 代码块，两者均在文末附原始内容（Canvas 附完整 JSON），预览与结果分别展示「转换文件」数量；其余不支持的扩展名改为列出具体文件名
- **数据分析智能增强**：新增**字段智能推荐**（选表后按字段类型 + 抽样画像标注 metric/dimension/time/identifier/ignored 角色，给出基数、非空率、理由，并推荐公式 / 图表 / 分组汇总），新增**典型示例**（分类对比 / 数值分布 / 占比构成 / 时间趋势 / 比率分析 / 数据概览，按当前表字段动态生成、一键应用），新增**分析列表** Drawer（集中打开 / 复制 / 删除 / 新建多个分析，复制走后端 `POST /analytics/templates/{id}/duplicate`，默认「原名 副本」并自动递增重名）；后端新增 `GET /analytics/recommendations`，推荐结果确定性可单测、复用行级权限与字段隐藏
- **数据分析模块完善**：分析模板支持「另存为副本 / 重命名 / 未保存修改确认 / `?template=<id>` 深链刷新保持 / 源表已删除提示」；图表新增维度聚合方式（sum/avg/count/min/max，随模板持久化）；新增**分组汇总**（分组字段 × 指标聚合，可排序 + Top N，基于全量扫描行，结果可导出 CSV）；描述统计补充方差 / 极差 / 非空率；派生数据预览支持分页与列排序，统计 / 派生数据 / 分组汇总均可一键导出 CSV（Excel BOM），图表可导出 PNG；公式编辑器支持字段与函数快捷插入、示例片段、Ctrl/Cmd+Enter 运行与本地重复键名提示；后端 analytics 插件同步扩展 schema 与校验，seed 预置模板补充聚合方式与分组汇总示例
- 数据表**图片字段支持剪贴板粘贴上传**（新增行 / 更新行 / 行详情抽屉三处同口径）：编辑态聚焦图片区或直接截图后 `Ctrl/Cmd+V` 即可上传并追加，一次粘贴多张按顺序串行上传不会互相覆盖；剪贴板同时带**非空文本**时按粘贴文本处理，不劫持 Excel / Word / 网页复制的内容；粘贴同样受字段级 `allowed_mime_types` 与 `multiple` 配置约束，只读态（`readOnly` 行详情 / 无编辑权限）不注册粘贴入口。图片字段编辑区抽为共用组件 `pages/grid/cells/ImageFieldEditor.tsx`，内联编辑与抽屉不再各写一份，并顺带修正内联图片上传未登记 `table_id`/`row_id` 归属（下载不再绕过表/行权限校验）
- 生产部署支持**内置反向代理**：`docker-compose.prod.yml` 新增 `nginx` 服务（`--profile proxy` 可选启用），配置位于 `deploy/nginx/`；`deploy/deploy.sh` 支持 `CNDB_ENABLE_PROXY=1`（自动带 profile）并在部署末尾经代理探测健康端点验证链路；`deploy/bootstrap-server.sh`、`.env.prod.example`、`docs/DEPLOY_TENCENT.md` 同步更新
- 新增**进程内缓存**（不依赖 Redis）：TTL + LRU + 统计 + 前缀失效（`core/cache.py`，并预留 Redis 后端接入点），接入工作区列表与数据表列表两个热点读接口 + 写路径主动失效，新增运维端点 `GET /api/v1/admin/cache/stats`、`POST /api/v1/admin/cache/clear`；实测同会话 A/B：数据表列表 p50 **16.1ms → 3.4ms（提速 79%）**、工作区列表 4.8ms → 2.2ms
- 新增**统一事件/审计流**：跨插件的 `core_event` 表（actor/action/target/summary/detail/request_id）与 `GET /api/v1/admin/events`（超管或审计管理员可读，支持动作/操作人/目标/工作区/request_id/关键词/时间筛选与分页）、`GET /api/v1/admin/events/actions`（动作统计）；认证动作（登录成功/失败、登出、改密、会话下线、**刷新令牌复用检测**）、用户管理操作、表记录变更均已接入；事件自动携带 `request_id`，可与访问日志/慢查询日志串联；系统管理台新增「事件流」标签页（筛选写入 URL，可分享/刷新保持）；迁移 `b4d2e7a9c1f3`
- 新增**会话/授权生命周期**：登录同时返回访问令牌与刷新令牌（不透明随机串，库中只存 SHA-256）；`POST /auth/refresh` 一次性轮换（旧令牌复用视为泄露，吊销全部会话）、`POST /auth/logout`（单枚 / `all=true` 全部下线）、`POST /auth/password` 自助改密、`GET|DELETE /auth/sessions` 会话列表与按会话下线；`accounts_user.token_version` 让改密与强制下线后既有访问令牌**立即失效**；登录失败限流（账号 5 次 / 来源 IP 20 次 / 5 分钟）返回 429 + `Retry-After`；前端 401 自动刷新一次并重放原请求（并发去重），登出会调用服务端吊销接口；新增迁移 `a3f1c9d2e7b4`（`accounts_refreshtoken` + `token_version`）与配置项 `JWT_REFRESH_EXPIRE_DAYS` / `LOGIN_MAX_FAILURES` / `LOGIN_WINDOW_SECONDS`
- 新增**请求级可观测性**：每个响应回写 `X-Request-ID`（客户端可传、缺省生成），访问日志输出 `method/path/status/duration_ms/request_id/user_id`（超过 `SLOW_REQUEST_MS` 升 WARNING 并标 `slow=true`，健康检查与静态资源降为 DEBUG），既有慢查询日志也带上同一 `request_id` 便于串联；新增 `ACCESS_LOG_ENABLED` / `SLOW_REQUEST_MS` / `SLOW_QUERY_MS` 三个可配置项
- 文档总览新增**按标签筛选**：下拉选择标签（写入 URL `?tag=`，可分享/刷新保持），文件夹层级过滤在前后端同口径；按标签筛选时隐藏系列卡片（文件夹无标签）
- 文档编辑器工具栏补两处编辑能力：**Markdown 表格骨架**下拉（2×2 / 3×3 / 4×4 一键插入，带空单元格占位）与**标题层级**下拉（一级/二级/三级/四级标题、正文=取消标题），此前标题按钮只能固定切 H2
- 文档总览新增**「最近打开」**：打开文档时记录到本地（按工作区分键、去重、最多 8 条），根层展示可点直接回到该文档，支持一键清除；已删除条目自动过滤避免死链
- 文档总览补上**置顶标识**：置顶的系列卡片与列表项显示「置顶」标签（此前只在树里有图标）
- 文档总览支持**多选批量移动 / 删除**：当前层级逐项勾选（含「全选」），批量栏提供「移动到…」与「批量删除」；后端新增 `POST /documents/batch` 逐项校验（防环 / 目标必须是文件夹 / 已删除或跨工作区跳过），失败项在 `skipped` 中返回并在前端提示「已移动 N 项，跳过 M 项（原因）」
- 文档编辑器支持**直接粘贴图片**：剪贴板含图片时自动上传并插入 `![名称](file:<file_key>)`（普通文本粘贴不受影响）；一次粘贴多张按顺序串行上传，插入采用函数式更新不会互相覆盖
- 编辑器新增**状态栏**：实时显示「字数 · 行数 · 预计阅读时长」（按 300 字/分钟估算），随输入即时刷新
- 文档编辑器支持**插入图片**：上传到工作区文件存储（复用既有 `POST /workspaces/{wid}/files`），正文写入站内引用 `![名称](file:<file_key>)`；非图片文件被拒、上传失败不改动正文；桌面顶栏「图片」按钮与窄屏「更多」菜单同一入口
- Markdown 预览渲染站内图片：`file:` 引用经带鉴权的 axios 取 blob 后展示（`<img src>` 无法携带 Authorization 头），支持点击放大预览、加载占位与失败提示；外部图片 URL 原样渲染
- 文档总览支持**排序切换**（手动顺序 / 最近更新 / 创建时间 / 标题）：系列卡片与列表同步排序、置顶项恒在最前；排序口径写入 URL（`?order=`），可分享与刷新保持
- 文档总览的**当前文件夹**改为 URL 承载（`?parent=`）：支持深链直达、刷新与浏览器后退（此前只存在于组件内存状态）
- 文档编辑器顶部新增**路径面包屑**（文档 / 各级文件夹，可点回对应文件夹列表），层级较深时不再需要靠左侧树回忆位置
- 文档编辑器支持**查找与替换**：Ctrl/Cmd+F 打开（接管浏览器查找）、Ctrl/Cmd+H 同开，Esc 关闭；实时计数「第几处 / 共几处」、上一个 / 下一个（越界环绕，Enter / Shift+Enter 亦可）、区分大小写开关、替换当前并自动跳到下一处、全部替换（字面量替换，不解释 `$1`）；选中正文后按 Ctrl+F 自动带入查询词
- 文档支持**个人置顶**：树/列表/详情返回 `pinned`，置顶项始终排在同级最前（其余保持手动顺序）；置顶按用户隔离（A 置顶不影响 B 看到的顺序），随文档彻底删除自动清理
- 文档树节点新增「更多」按钮：桌面悬停显现、窄屏常显，与右键菜单同一套入口（此前触摸端完全无法触发右键菜单，新建/重命名/移动/删除/置顶在手机上均不可达）
- 文档编辑器新增 Markdown 快捷工具栏与快捷键：加粗 / 斜体 / 行内代码 / 二级标题 / 无序列表 / 有序列表 / 引用 / 代码块 / 链接，作用于当前选区（再次点击可取消包裹、行级语法幂等切换），并支持 Ctrl/Cmd+B · I · K；纯函数层 `components/Document/markdownEdit.ts` 与工具栏组件 `MarkdownToolbar` 解耦，窄屏工具栏可横滑
- 表格视图自动补「序号」列：置于选择列之后、字段列之前，按当前分页 offset 续号（第 2 页从 51 起），列宽随总行号位数自适应（1 位 52px / 3 位 55px，上限 88px）；非字段列不参与排序 / 筛选 / 列宽拖拽，新增行（草稿）显示「—」；窄屏固定复选框与序号列作为行标识（不再固定首个字段列，保证约 260px 横滑窗口）

- 统一错误契约：core/errors.py 定义 CndbError 族（400/403/404/409），全局 handler 映射为统一 `{"detail","code"}` 响应体，未捕获异常返回统一 500
- 健康检查拆分：`/api/health`（liveness，进程存活）与 `/api/health/ready`（readiness，DB ping + 迁移版本，DB 不可达返回 503）
- 慢查询日志：SQLAlchemy 引擎级监听，超过 0.5s 的 SQL 记 warning
- 外部导入源（api_fetch）：幂等 GET 有限重试 + 指数退避
- 导入任务幂等守卫：analyze/execute 重复派发静默忽略，不崩后台线程
- 启动迁移失败给出可操作指引（备份恢复/重建），不再裸 traceback
- 示例文档种子：`examples/datasets/<工作区>/documents/` 目录树（2 个正例工作区共 20 篇典型文档，含 `[[标题]]` 双向链接与 `{{table:表名|view=视图名|limit=N}}` 数据表动态引用），`cndb seed` 按目录树注入文件夹 / 文档并解析为真实表 / 视图 ID
- 文档回收站：`GET /{wid}/documents/trash`（按删除时间倒序）、`POST /{wid}/documents/{doc_id}/restore`、`DELETE /{wid}/documents/{doc_id}/purge`；文件夹级联删除整棵子树共用同一删除批次，恢复时精确还原同批次子项、不连带复活先前单独删除的节点，彻底删除一并清理版本 / 标签关联 / 分享 / 权限 / FTS 索引与外存内容
- 文档出链解析 `GET /{wid}/documents/{doc_id}/links`：返回正文 `[[标题]]` 命中文档 ID 与断链清单（代码围栏内不计入）
- 文档断链修复 `POST /{wid}/documents/{doc_id}/links/repair`：把正文 `[[旧标题]]` 改指为指定现存文档（生成新版本可回溯；全部条目未命中返回 409）
- 文档前端：文档页新增回收站抽屉（软删除列表 / 恢复 / 彻底删除），编辑器新增出链抽屉（已解析与断链分栏，按目标文档修复断链）
- CLI 新增 `cndb docs gc`：文档外存孤儿文件体检与物理回收（默认 dry-run，`--apply` 实际删除，`--json` 输出报告；软删除文档的外存内容视为有效引用不回收）
- 文档导出：`GET /{wid}/documents/{doc_id}/export?format=md|docx|pdf` 把文档最新正文导出为 Markdown / Word / PDF 文件（工作区成员可用；文件夹与非法格式返回 400），编辑器顶栏新增「导出」下拉入口；DOCX/PDF 渲染器迁至 `documents/services/export/`，PDF 保留中文字体自动发现与页眉页脚
- 文档修改申请（双轨制写入）：viewer（或关闭直编的 editor）保存正文不再 403，而是由 `PUT /{wid}/documents/{doc_id}/content` 返回 202 + 申请载荷，待审正文只存 `documents_changerequest.proposed_content` 不写版本表；新增 `/{wid}/document-change-requests` 的列表 / 详情（含基准→待审正文 DIFF）/ merge（落库为新版本）/ close / update-base / 删除草稿端点，申请记录 `base_version_number` 基准，文档版本前进后其余 open 申请自动置 stale
- 文档彻底删除时一并清理该文档的待审修改申请，避免孤儿数据
- 差异对比可视化：新增 `components/DiffView`（unified diff 解析 / 增删配对 / token 级行内高亮 / 并排模型 + 纯函数单测），文档版本对比支持统一·并排双视图与增减统计，数据表变更项改为「字段 / 修改前 / 修改后（基准漂移时含当前值）」表格；样式全部由 `color-mix + var(--cn-*)` 组合，各主题自动适配
- 文档区二级导航：进入 `/w/:wid/documents*` 时在工作区 Tabs 右侧以竖线分割渲染「文档」根入口 + 二级页签（修改申请 / 问题清单），形式与表级页签一致；新增 `/w/:wid/documents/change-requests`（工作区级文档修改申请清单，支持状态筛选与内容 DIFF 审核）与 `/w/:wid/documents/issues`（文档问题清单）两个页面
- 文档问题清单：新增 `documents_issue` / `documents_issuecomment` / `documents_issueevent` 三张表（迁移 `e4f5a6b7c8d9`）与 `/{wid}/document-issues` 端点（列表 / 提交 / 详情 / 评论 / 关闭 / 重开），类别与状态取值同数据表问题清单；文档彻底删除时问题、评论与事件流水一并清理
- **数据表视图可见性升为三档模型**（ADR 0003 的 P2，迁移 `b5c6d7e8f9a0`）：`tables_dataview` 新增 `visibility`（`table` 继承表权限 / `shared` 指定成员 / `private` 仅创建者，**默认 `private`**）与 `scope_key`（命名空间：`0` = 共享，`user_id` = 创建者私有）；**新建视图默认仅本人可见**，要放宽到「表内所有人」须持有表 `EDIT_VIEWS`（不变量 I1：视图权限永不超过表权限）。唯一键由 `(table_id, name)` 换成 `(table_id, scope_key, name)`，使不同成员可以各自拥有同名私有视图。新增 `tables_dataviewpermission` 白名单表承载 `shared` 档授权名单（`shared` 档的写入端点与前端入口在 P3）。配套改动：`ViewCreate`/`ViewResponse`/`ViewBrief` 暴露 `visibility`；新增 `POST /views/{id}/visibility` 用于切换档位；备份导出/导入携带三键并**兼容旧备份**（无 `visibility` 键时按旧语义推断）；seed 与默认视图查询同步改口径
- **`owner_id` 外键改为 `ON DELETE SET NULL`**（迁移 `b5c6d7e8f9a0`）：账号被删除后其视图作为「孤儿」保留而不是被级联清空，以便管理员事后重建或被创建者重新加入工作区后恢复（ADR 0003 决策 D3）；孤儿视图对任何人（含超管）均不可见，清理出口 `cndb views prune-orphans` 归 P3
- 视图可见性判定补上**批处理路径的零 N+1 约束**：`visible_view_filter` 改为纯函数（只返回 SQLAlchemy 列表达式），表列表/表详情复用一个请求内已预取的 `TableAccessPreload.member_role` 求可见视图集；表详情一次性预取视图授权名单后再逐条判定，不再逐视图查库（回归：`test_query_count_does_not_scale_with_table_count`）
- 前端跟进新档位语义（**避免 P2 改动引入的静默错位**）：`View`/`ViewCreate` 类型暴露 `visibility` 与含义更新后的 `owner_id`；视图标签栏不再用 `owner_id != null` 推断「个人视图」（新模型下 `table` 档视图也带 created-by，会给每个自建视图都打上「我的」），改按档位显示「我的」/「指定成员」；同处**编辑入口的可用性也改按档位判定**（否则 viewer 会对他人 `table` 档视图拿到编辑入口、点下去 403）；表格设置页的「设为默认视图」按钮仅对 `table` 档视图可点（`is_default` 是表级标记，后端对非 `table` 档返回 400）。`visibility` 缺失时（老响应 / 测试 mock）一律回落到旧判据，行为不变
- **视图共享名单（ADR 0003 的 P3）**：`shared` 档从"只有判定、没有写入面"补全为可用的开放功能。新增 `GET|PUT|DELETE /views/{id}/members[/{user_id}]`（读写共享名单，`PUT` 的 role ∈ `viewer`/`editor`）与 `GET /views/{id}/shareable-members`（可授权对象列表：本工作区成员 ∧ 对该表有 `READ`，附 `can_edit_views` 供前端禁用 editor 选项）；`POST /views/{id}/visibility` 支持携带 `members` **一次完成开档 + 授权**。授权对象逐条校验（非本工作区成员 / 表内无 `READ` / `editor` 但无表 `EDIT_VIEWS` → 422，规则见 §4），生效权 = min(视图授权, 表权限) 且**实时求值**——被授权者随后被表侧降级，视图授权自动失效，无需回填清理
- 视图列表/详情响应新增**能力位** `can_edit` / `can_manage` / `grantee_count`：由后端按三档统一判定后下发，前端不再自行用 `visibility` + `owner_id` 推断（口径只此一处，避免前后端漂移）；批量场景复用一次性预取的工作区角色 / 管理视角 / 本人授权名单 / 授权人数，查询次数与视图数量无关
- 可见性变更与授权 / 收回写入 `tables_auditlog`（动作 `view_visibility` / `view_grant` / `view_revoke`，含档位前后值与授权对象）
- 前端新增**视图权限 Drawer**（`pages/grid/ViewPermissionDrawer.tsx`）：「更多 → 视图权限」进入，三档单选（仅本人可见 / 指定成员可见 / 表内所有人可见）+ 成员选择器 + 逐行「只读 / 可编辑」+ 收权；交互为**即时生效**（切档走 `visibility`，加人/改权/收权走 `members` 端点）。「表内所有人可见」档按表 `EDIT_VIEWS` 门控并给出原因（决策 D4）；`can_manage` 决定入口是否可点。非 `shared` 档保留的历史名单会提示「切回后自动恢复生效」，失效授权标注「已失效」
- CLI 新增 `cndb views prune-orphans --workspace X [--table T] [--apply] [--json]`：孤儿视图（`private` 档且创建者已注销 / 已离开工作区）体检与回收，**默认 dry-run**，输出归属表 / 名称 / 归属原因 / 创建时间 / 最后修改时间。这是 ADR 0003 决策 D3 的**唯一**清理出口——D2 关闭了管理员可见通道，孤儿视图没有任何界面可以触达

### 移除

- **示例工作区「低质量数据」移除**：`examples/datasets/工作区-低质量数据/` 整目录（15 个低质量 xlsx + 4 个极端值 CSV + `views.json`）与配套生成脚本 `scripts/generate_low_quality_xlsx.py` 一并删除，`cndb seed` 不再注入该工作区。测试只保留不依赖该目录的必要覆盖：`test_seed_documents.py` 去掉反面示例工作区断言，改为所有示例工作区均需 `documents/` 且不少于 5 篇文档；图表极端维度单测（boolean 按是/否分桶、非法日期归未分组、空度量不崩等）改用内联数据继续保留。7 种视图模式仍由「某企业销售管理」「科研项目管理」完整覆盖，`test_all_seven_view_types_covered` 不受影响
- **独立示例工作区「项目管理」删除**：其 WBS 任务分解 / 待办事项 / 资源排期三张表及甘特 / 矩阵等视图已并入「科研项目管理」并改写为科研语境，`examples/datasets/工作区-项目管理/` 整目录移除；e2e `image-field-upload.spec.ts` 的示例工作区名、`view-mode-switch.spec.ts` 与 `viewModes.test.ts` 的视图模式说明同步改为「科研项目管理」
- **文档「今日笔记」功能移除**：该入口（文档树工具栏「今日笔记」按钮）实质是「按 `YYYY-MM-DD` 标题幂等创建一篇普通文档」，与手动新建同标题文档完全等价，却额外承担一条专用端点与一套模板约定，产品上收益低。移除范围：后端 `POST /documents/daily-note` 端点、`services/content.get_or_create_daily_note` 与 `DAILY_NOTE_TITLE_FMT`、`schemas.DailyNoteRequest`；前端 `documentsApi.dailyNote` / `DailyNoteResponse`、`DocumentTree` 的按钮与 mutation、msw 桩与对应用例；后端 `TestDailyNote` 4 个用例。**数据不受影响**：历史上由该入口创建的文档就是普通文档（标题为日期），仍可在文档树中正常打开与编辑，不涉及迁移。若需「按日期归档」，直接用「新建文档」把标题写成日期即可
- **移除视图 `role` 型授权（按工作区角色批量放行）**（ADR 0003 决策 D6）：该能力在模型与判定层早有预留，但**从未有任何写入端点**（`set_view_grant` / `revoke_view_grant` / `replace_view_grants` 恒写 `subject_type='user'`），CLI 与前端亦无入口 —— 因此生产数据零依赖，移除无数据丢失风险。删除范围：`services/core/view_access.py` 的 `role_codes_for_workspace`、`visible_view_filter` / `grants_for_user` / `grant_role_for_view` 的 `role_codes` 参数与角色匹配分支、`_GRANT_RANK`（唯一键已保证每视图至多一条名单记录），以及已退化为纯 wrapper 的 `view_visibility_filter`（调用方改用 `visible_view_filter(<user>.id)`，涉及 `routers/views.py` / `routers/tables.py` / `accounts/routers/preferences.py` 共 6 处）；`ViewGrantSubject` 收敛为只含 `USER`。`tables_dataviewpermission.subject_type` 列**保留**（值恒为 `user`），以免为抹掉一个无害列而在 SQLite 上重建表。顺带收益：`GET /views` 每次请求少 1 条工作区角色 SQL（原先 role 型授权与 `is_table_admin` 各自解析了同一角色）
- **数据表视图「匿名公开分享」整体移除**（**破坏性**，ADR 0003 决策 D5）：视图可见性的口径是「最大放宽至数据表范围内」，而匿名公开分享本质是**表范围之外**的读取通道 —— 拿到链接的人无需登录、不受表权限约束、也不走字段隐藏。它与本次建立的「分档可见性 + 表权限硬上限」模型互斥（飞书开启高级权限后原「链接分享」会整体失效，即同一取舍）。移除范围：`GET /api/v1/public/share/{slug}`、`POST /views/{id}/share`、`DELETE /views/{id}/share` 三个端点与整份 `routers/public.py`；`tables_dataview.is_public` / `public_slug` 两列与唯一索引（迁移 `a4b5c6d7e8f9`，SQLite 下先删索引再删列，downgrade 可还原结构但 slug 值不可还原）；前端 `/public` 整条路由及 `PublicSharePage` / `publicApi` / `PublicLayout`。**旧公开链接与旧书签全部失效**。移除后产品边界收敛为：**不存在任何绕过表权限的数据读取路径**；对外分发改由登录态深链承接（链接携带 `view_id`，访问校验表 `READ` + 视图 `VIEW_READ`），P3 之后可用「指定成员可见」视图替代。文档公开分享（`/api/v1/documents/share/{token}`）本次未动，口径已不一致，建议另开决策同批收敛
- reports 插件（报表模板 + Jinja2 渲染）：模型 / 路由 / 渲染器 / 前端页面与编辑器 / seed 示例模板整体移除，`reports_template` 表由新增迁移 `c2d3e4f5a6b7` 删除（历史迁移保留，downgrade 可重建空表）；工作区列表 `report_count` 字段与前端报表页签同步下线
- 依赖 `jinja2` 移除（仅报表模板使用）

- wechat_auth 插件（微信小程序登录）：路由/模型/客户端/配置项/依赖 `requests` 及配套测试整体移除；历史迁移保留，存量库中的 wechat_accounts 孤儿表不影响升级
- 前端死代码：未使用的 `userApi` 封装、`USER_ROLE_LABEL` 常量与 hooks barrel 重导出（ruff/knip/eslint 证据驱动）
- 死配置：Sphinx 文档骨架（`docs/*.rst`、`docs/conf.py`、`docs/_static/`）、`.readthedocs.yaml`、`tox.ini`（0.1.12 已声明删除但文件残留；tox 引用的 `docs` extra 早已不存在）；`.gitignore` 中失效的 `.tox/` 与重复的 `.mypy_cache/`
- 空目录：`src/cndb/plugins/{forms,workflows}`（源码已随表单/审批流插件移除，仅剩 `__pycache__`）
- 前端未使用生产依赖：zod、@tanstack/react-table、react-hotkeys-hook、zundo、immer（全仓库零引用）
- 与主测试重复的补覆盖率用例 12 个、零引用 fixture 2 个、只有 `pass` 的空壳测试 1 个（test_coverage_patch / test_cov_routers_records / test_edge_patch / test_cov_quick / test_tables_coverage / test_roles_e2e）
- 前端死导出：`LoginResponse`、`WorkspaceTrashResponse`、`getTagColor`（自称兼容旧 API，生产已全用 `getTagColorName`）、`ANTD_COLOR_NAMES`（仅被自身测试断言长度/内容）
- 前端第二套设置持久化：`theme/tableSettings.loadTableSettings` / `saveTableSettings` —— 与 `store/tableSettings` 的 zustand persist **共用同一个 localStorage key `cndb_table_settings`**，存在互相覆盖隐患；持久化职责收敛到 store，本模块只留类型/默认值/`densityToSize`
- 重复类型定义：`ViewMode`（`store/gridView.ts` 的副本）与 `WorkspaceRole`（issues/changeRequests 详情页各一份副本）
- 死条件：`GridCell` 的 `isReadonlyField` 中 `|| Boolean(field.is_primary && field.field_type === 'auto_id')` 被前一项 `readonly.has(field.field_type)` 完全覆盖（auto_id 本就在该集合内）
- 前端 `Field.is_primary` 与 6 个伪系统字段类型（`auto_id` / `formula` / `created_time` / `updated_time` / `created_by` / `updated_by`）的**全部恒假分支**（19 文件 +51/-100）。经确认无存量库使用后删除：后端 registry 的 19 种类型里没有这 6 个，`FieldResponse` 无 `is_primary`，且 `normalize_field_type` 对未知类型原样放行 —— 这些分支只可能来自存量库。一并删除只为其服务的 `includePrimary` schema 选项。**保留** `long_text`/`decimal`/`multi_select`（后端真实别名）与 `json`（真实类型），以及 `created_by`/`updated_by` 作为记录元数据的用法

### 变更
- **ADR 失效口径统一为「直接删除」**：ADR 被新方案替代或需求作废时，直接删除该 ADR 文件、`docs/adr/README.md` 索引行与全仓引用（追溯走 `git log -- docs/adr/`），不再使用 `Superseded` / `Deprecated` 状态、也不在仓库保留失效文档；编号不复用。`AGENTS.md`、`.trae/rules/design.md`、`.trae/skills/adr-writer`、`docs/adr/README.md`、`docs/adr/TEMPLATE.md`、`docs/AI_DRIVEN_DEV_FLOW.md` 与 `scripts/check_adr_landing.py`（失效 Status 直接报 error）全链同口径
- **门禁分级（按改动类型裁剪）**：`AGENTS.md` 新增「门禁分级」——L0 纯文档（`*.md`）只跑 `make check-docs`（`gitkeep-check` + `adr-check`）、L1 纯配置（`Makefile` / `pyproject.toml` / lock / workflow / `deploy/` / `scripts/` 等）跑 `make check-fast`（触及测试发现、依赖、打包或 CI 行为时加 `make test`）、L2 代码仍走 `make flow`（`check-fast` → `test`）；混合改动取最高级、拿不准按 L2，CI 不因分级放宽。`Makefile` 新增 `check-docs` 目标，`.trae/rules/dev-workflow.md`（含开工基线命令）与 `docs/AI_DRIVEN_DEV_FLOW.md`（驱动机制 / 护栏 / 落地清单）同步，避免只改文档或项目配置也全量跑测试
- **CI 前端门禁拆分并行**（ADR 0002）：前端静态链（eslint + build + bundle budget）与覆盖率测试拆为 `frontend_static` / `frontend_test` 两个并行 job，`Makefile` 提供同名目标 `frontend-static` / `frontend-coverage`；覆盖率门禁只在完整报告上执行。vitest 4 分片 + blob 合并方案**未采用**——云效普通 Command job 无法消费 ArtifactUpload 产物，如需分片须先换平台或触发形态
- **面向 Trae 云端沙箱模式的开发配置清理**：`Makefile` 的 worker 并行度不再直接取宿主核数（`nproc`），改为优先读 cgroup CPU 配额（v2 `cpu.max`、v1 `cfs_quota÷cfs_period`，取不到才退回宿主核数）——云端容器常见「宿主核数多、配额 2~4 核」，按宿主核数开 `pytest -n` 会超订反而更慢（与 `frontend/vite.config.ts` 的配额取值同口径）；`.pre-commit-config.yaml` 去掉两个需联网拉取的远端 hook 仓库（`astral-sh/ruff-pre-commit`、`pre-commit/pre-commit-hooks`），全部改为 `repo: local` 本地钩子（ruff check/format 复用项目已安装的 `uv run ruff`），提交时不再依赖访问 GitHub；删除残留的死配置 `tox.ini` 与 `.gitignore` 中失效的 `.tox/`
- **前端统一设计标尺（Design Tokens）**：新增 `frontend/src/theme/tokens.ts` 作为间距（4px 网格）/ 字号（t-shirt 六级）/圆角 / 控件高度 / 断点的**唯一数值来源**，`index.css` 以 `--cn-space-* / --cn-text-* / --cn-radius-*` 同名声明确认，`tokens.test.ts` 解析 CSS 逐条比对、双写漂移直接失败；`theme.ts` 把全局标尺（`baseTokens` / `compactComponents`）与主题配色**逐组件深合并**（此前整体浅合并会让只写配色的主题丢掉组件尺寸 token），圆角改由 `themeCssVars()` 运行时以 CSS 变量下发，CSS 里手写的卡片/浮层不再是固定 8/10px；页面级行内样式改读常量，CSS 中不再出现游离的 3/5/7/9/14px 间距与 9/15/17px 字号
- **文档结构树的状态标记改为按状态区分的图标**（原来所有状态都是一个 6px 色点）：草稿 = 笔形（灰）、已发布 = 对勾圆（绿）、归档 = 归档箱（橙），**颜色沿用既有状态色**不变；悬停提示「状态：草稿 / 已发布 / 归档」，`aria-label` 同步带状态文案，不再只靠颜色区分（色弱可用）
- **示例数据集收敛为三个「正面示例」**：移除数据过薄的**「某地区数据」**（房价/气温两张小表）与**「股票信息管理」**（依赖外网实时行情接口，离线 seed 后只剩空壳），避免示例工作区列表里出现无内容可看的空壳；同时**增强「科研项目管理」**——四本台账从 15/18/31/32 行扩到 **40 个课题 / 77 位负责人 / 348 条季度进展 / 220 条经费记录**（2022Q1—2026Q3 连续季度，含在研 / 已结题 / 延期整改 / 已中止四种状态），`科研项目` 新增 `项目级别 / 论文数 / 专利数 / 合作单位数` 四个分析列并保证「经费总额 = 各科目预算之和」「结题项目进度 100% + 验收结题 + 经费已结清」等口径自洽；新增 6 个视图（`项目投入产出` 散点、`高产出项目`、`按项目级别看板`、`待拨付清单`、`超支预警`、`延期整改进展`）与 `analytics.json`（4 个分析模板：项目产出效率 / 按级别的经费与产出 / 经费执行率分布 / 阶段进度分布），补文档《科研数据台账与指标口径》；删除与 `科研经费.csv` 重复的 `科研经费.xlsx`（同名双表）。e2e 的 matrix 用例改指「科研经费」矩阵视图，`test_seed_documents` 的带文档工作区阈值随工作区数量收敛为 3
- **数据表图片字段编辑 UI 优化（P0）**：去掉编辑态常驻的整块 `Upload.Dragger`，改为**紧凑缩略图网格 + 「+ / 替换」方块**（行高不再被撑到 100px+）；新增图片上传队列（本地 objectURL 先预览、并发 2、进度环、单张失败原位重试/取消），失败不再只靠 toast；单图字段（`multiple=false`）改为**替换语义**（新图上传成功后才丢弃旧图，修复此前会追加第二张的缺陷）；上传前按字段配置校验 `allowed_mime_types` 与 `max_size_mb`（此前前端完全未使用该配置）；展示态缩略图收为 32px、超过 3 张显示 `+N` 角标。涉及 `ImageFieldEditor`、新增 `useImageUploadQueue`、`fileApi.upload`（进度/取消）、`DisplayCell` 与图片字段样式
- **数据表图片字段编辑 UI 优化（P1）**：行详情大图模式（`thumbSize≥48`）支持**逐图替换**（新图成功后清理旧图、位置不变）与**拖拽排序**（`@dnd-kit`，仅多图且空闲时启用，排序顺序即字段值数组顺序）；瓦片悬停显示「替换 / 删除」按钮，并提示文件名 + 体积；上传队列新增 `replaceKey`（逐图替换）与 `reorder`（排序）能力
- **图片字段 P2（数据一致性 + 列表性能）**：附件下载端点支持 `?thumb=N`（32–1024，服务端转 WebP 并落盘缓存；非图片 / 解码失败静默回退原图，删除附件时清理缓存），表格展示态缩略图改用 96px 缩略图、原图在悬停或打开预览时才懒加载；附件 / 图片字段新增 `max_count`（0=不限）配置并在保存时校验；上传接口新增 `field_id`，后端按字段配置校验大小 / MIME / 图片类型（413/415），字段级限制不再只靠前端提示
- **网格内图片字段浮层（P1.5）**：双击图片单元格不再把整行撑入内联编辑，改为锚定 Popover（360px）打开大图模式编辑器（64px 瓦片、逐图替换、拖拽排序）；浮层内只改草稿，「完成」提交、「取消 / 点击外部」回滚，行高保持紧凑不变
- 前端门禁：覆盖率默认不再生成 html 报告（改由 `pnpm test:coverage:html` / `make fcov-html` 显式开启，省去写数百个报告文件），`vitest` worker 数改为按**容器 CPU 配额**（cgroup v2/v1）取值并支持 `VITEST_MAX_WORKERS` 覆盖（避免云端容器把宿主核数当核数用导致超订，反而更慢）；CodeUp 流水线把前端拆成 `frontend-static`（eslint + build + bundle budget）与 `frontend-test`（覆盖率）两条并行 job，覆盖率 job 实例由 2 核提到 4 核
- 生产部署通道由 **SSH 直连改为 TAT（自动化助手）云端下发**：GitHub Actions 不再用 `root` 密钥登录 22 端口（此前 3 处 `scp` + 4 处 `ssh` 会在云主机安全留下「异地登录」高危告警，且 runner 出口 IP 属动态段、白名单加不完），改为调 `tat:RunCommand` 下发、`DescribeInvocationTasks` 轮询回传日志；部署配置（`deploy/` + `docker-compose.prod.yml` + 依赖锁定清单）压成 tar.gz 内联进命令（约 46 KiB，上限 64 KiB），wheel 改由服务器自行下载并在**循环内校验 sha256**；`.github/workflows/deploy-tencent.yml` 重写，新增 `scripts/deploy_via_tat.py`（标准库手写 TC3 签名，不引入 SDK）与 `scripts/build_tat_command.py`（载荷打包与命令生成）；`docs/DEPLOY_TENCENT.md` 同步链路图、Secrets 表与排错表。**入站 22 端口此后可对公网关掉**
- 文档导出 Markdown 时，若正文含**可解析的站内图片**则改为打包 zip：`<标题>.md`（引用改写为 `assets/<file_key>`）+ `assets/` 图片文件；无图片仍为单文件 .md（行为不变），解析不到的引用原样保留不丢信息；前端按响应类型自适应 `.zip` / `.md` 文件名
- 文档导出 Word / PDF 时**嵌入站内图片**：`![alt](file:<file_key>)` 会被替换为真实图片（按正文可用宽度等比缩放），引用缺失或图片格式不支持时降级为「[图片缺失/无法嵌入：alt]」占位，不再静默丢图；Markdown 导出保留应用内引用（单文件无法内嵌二进制）

- 后端测试补齐覆盖率：新增 9 个补覆盖测试文件（覆盖 documents/obsidian、tables 的 lookups/links/records/fields、importing/transfer、cli/core/workspaces/backup、analytics/change_requests 等此前偏低的模块），`pytest -m "not slow" --cov=cndb` 由 93.25% 提升至 98.06%，CI `--cov-fail-under=95` 门禁恢复通过
- 拆分超大文件（全部保持既有导入路径与导出面，行为不变）：
  - `cli/seed.py` 2703 行 → `cli/seed/` 包 11 个模块（sqlite/paths/datasets/fields/documents/views/templates/samples/permission_demo/runner），`__init__` re-export 历史符号
  - `plugins/reports/routers/reports.py` 1510 行 → 路由 495 行 + `renderers/{context,docx,pdf,pdf_fonts,xlsx,html,markdown}` + `services/stats` + `jinja`
  - 前端 `ReportsPage.tsx` 1047 → 267 行 + `TemplateEditorModal`/`RenderParamsModal`/`reportsConstants`
  - 前端 `GridCell.tsx` 839 → 188 行 + `EditCell`/`DisplayCell`/`cellValueUtils`（保留 4 个历史具名导出）
  - 前端 `GanttView.tsx` 1301 → 655 行 + `views/gantt/` 六个模块
  - 前端 `api/types.ts` 968 行 / 120 个导出 → `api/types/` 12 个按资源域拆分的模块 + `index.ts` 聚合；`api/index.ts` 原先手写列举的 90 个类型名改为 `export type * from './types'`
  - 前端 `ImportPanel.tsx` 958 → 615 行 + `ImportQualityPanel` / `ImportDiffTable` / `MiniStat`
  - 前端 `DocumentsPage.tsx` 792 → 553 行 + `SearchDrawer` / `TrashDrawer`（两者改为自持查询与状态，页面不再摊平 5 处 state 与 3 个 query/mutation）+ `seriesStats` / `documentDisplay`
  - 前端 `CalendarView.tsx` 770 → 205 行 + `calendar/{YearView,MonthView,WeekView,calendarUtils,calendarTypes}`
  - 后端 `workspaces/routers/workspaces.py` 1041 → 505 行 + `routers/member_routes.py`（成员/转让子路由）+ `services/backup_io.py`（备份落库）+ `routers/deps.py`（共享受保护依赖）
  - 后端 `tables/services/fields/field_ops.py` 1027 → 53 行 + `field_import.py`(502) / `select_options.py`(508)；field_ops 保留为兼容外观，使 7 处 `monkeypatch.setattr(field_ops, ...)` 继续生效
  - 前端 `KanbanView.tsx` 789 → 132 行 + `kanban/{KanbanCard,KanbanColumn,kanbanDensity,kanbanVisuals}`
  - 前端 `FileImportPreview.tsx` 774 → 609 行 + `importPreviewConvert.ts`（4 个纯转换函数）与 `useTableFlexFillStyle.ts`
  - 后端 `tables/routers/bulk.py` 752 → 35 行（聚合）+ `bulk_crud.py` / `bulk_export.py` / `bulk_import.py`；前缀与 tags 留在聚合 router 上，11 条路径逐条不变
  - 后端 `tables/services/transfer/normalize.py` 758 行 → `normalize/` 包（values 单值推断 / promote 列级提升 / coerce 精度与类型映射 + 转发全部 60 个符号）
  - 后端 `cli/users.py` 739 行 → `cli/users/` 包（io / db / commands / printing）；`users_command` 与 `register_users_subparser` 必须留在包 `__init__`，否则 10 处 `monkeypatch.setattr("cndb.cli.users.<cmd>")` 会静默失效
  - 后端 `cli/restore.py` 727 行 → `cli/restore/` 包（types / inspect / apply）
  - 前端 `theme.ts` 695 → 108 行 + `theme/meta.ts`、`theme/fonts.ts`、`theme/presets/{light,dark,common}.ts`；`THEMES` 仍写显式字面量以保证键序与 `THEME_MODES` 一致
  - 前端 `DocumentEditorPage.tsx` 802 → 640 行 + `DiffView` / `TagEditor` / `OutlineDrawer` / `BacklinksDrawer`
  - 前端 `DocumentEditorPage.tsx` 640 → 498 行 + `LinksDrawer` / `VersionsDrawer` / `InsertTableModal`（query 结果解包为 props）
  - 前端 `WorkspaceSettingsContent.tsx` 679 → 525 行 + `settings/{workspaceRoles,MemberZones,AddMemberModal,TransferOwnerModal}`
  - 前端 `TemplateEditorModal.tsx` 630 → 474 行 + `reports/useTemplateEditorData.ts`（7 个 query + 跨工作区扫描 effect + 9 个派生 memo 抽成 hook，JSX 原样保留）
  - 前端 `FileImportPreview.tsx` 609 → 357 行 + `FieldsList` / `SelectedFieldEditor` / `DataPreviewTable` 三个渲染闭包组件 + 共享的 `importPreviewTypes` / `importPreviewOptions`
  - 前端 `ViewConfigDialog.tsx` 523 → 214 行 + `viewTabItems.tsx`（四个 Tab 构造器）+ `ViewOptionItem.tsx`
- 重复实现收敛：
  - 后端 CSV 编码探测统一走 `transfer.decode_bytes_auto`（`cli/users._read_csv` 与 `import_tasks._parse_to_rows` 不再各写一套；后者原为硬编码 utf-8，GBK CSV 会 UnicodeDecodeError）
  - 前端新增 `utils/paletteColor`（GanttView 与 CalendarView 逐字相同的色板 + hash，WbsView 同一公式）、`utils/datetime`（issues/changeRequests 4 页各自的 formatTime）、`utils/formatSize`（文档页与管理面板）
- 覆盖率口径统一：Makefile `cov` 由裸 `--cov`（把 tests/ 自身计入分母，本地虚高到 97.9%）改为 `--cov=$(PACKAGE)`，与 CI 同口径（真实 95.4%），本地绿灯不再与 CI 脱节
- 配置一致性：`pyproject` 固定 `ruff==0.16.8`（与 `.pre-commit-config.yaml` 的 rev 真正对齐，注释不再失实）；`ci.yml` 用 YAML 锚点消除 push/pull_request 两份逐项相同的 paths；`Makefile .PHONY` 补齐 `gitkeep-check` 与全部短别名并去重
- 部署链路改为服务器端构建：CI 不再构建镜像、不再经 COS 中转，改为同步 wheel/锁定依赖/Dockerfile 到服务器后由 `deploy.sh`（SERVER_BUILD=1）本地 `docker build` 并部署；Dockerfile.prod 基础镜像与 pip 源支持 `--build-arg` 换源，手动回滚仍走 TCR pull
- **发布到云服务器的耗时优化**：① 部署不再作为独立 workflow 与 Release 并行抢跑，改由 `release.yml` 在 `pypi` job 成功后以 `workflow_call` 调用，省掉「重试等 PyPI 元数据同步」的 0-3 分钟；② wheel 下载从「腾讯镜像 → 官方源」两跳改为「腾讯 / 阿里 / 清华镜像快速失败 → 官方源长超时兜底」，避免镜像同步延迟时直接掉到跨境约 14KB/s 的官方源；③ 镜像拆成 `deploy/Dockerfile.base`（系统字体 + 锁定依赖，按 `requirements.lock.txt` + `Dockerfile.base` 内容指纹打 tag `cndb-base:deps-<hash>`）+ `deploy/Dockerfile.prod`（只装 wheel），依赖未变时服务器只重建 20-40s 的薄层，Docker 层缓存被清也不会再触发 5-15 分钟冷启动；`deploy.sh` 自动复用/构建基础镜像并分别清理应用镜像（保留 5 个）与基础镜像（保留 3 个），TAT 轮询间隔 15s→5s；`uv publish` 增加 `--check-url`（同版本已存在则跳过），并让 deploy job 在 pypi job 失败时仍尝试 —— 本仓库 CodeUp / GitHub 两条 release 流水线都会发 PyPI，后到的一方不再因 duplicate 阻断部署
- `get_db` 请求路径异常时显式 rollback，避免半提交状态污染连接池
- 文档列表 / 文档树改为批量序列化：版本数与标签各用一次聚合查询，大文档树不再逐节点 N+1
- 反向链接扫描改为单条 SQL 取各文档最新版本，替换逐文档查询
- README 修正项目结构树、CLI 命令、e2e 包管理器与特性清单等失实内容
- **Python 支持矩阵放宽为 3.12 ~ 3.14**：`requires-python` 改为 `>=3.12,<3.15`；其中 **Windows 仍只支持 3.12**（Win7/8 兼容钉版依赖只在该版本验证），`requires-python` 无法表达平台差异，改由 `cndb` 包导入时校验兜底（可用 `CNDB_SKIP_PY_VERSION_CHECK=1` 绕过）
- **依赖钉版只对 Windows 生效**：所有仅为 Win7/8 兼容而存在的依赖上限（`fastapi<0.126`、`pydantic<2.7`、`pydantic-settings<2.3`、`bcrypt<6`、`cryptography<51`）统一挂 `sys_platform == 'win32'` 标记，Linux / macOS 只保留版本下限，可自由升级

### 修复
- **数据表编辑关联字段时首次进入无法同步「引用字段」**：编辑对话框打开期间靠一个「同步指纹」判断 fields 是否变化来决定要不要重新回填，旧指纹只取关联字段**自身**的 `config`；而关联字段的「引用字段」是从同表归属它的 `lookup` 行**反推**而来的，当这些 lookup 行在对话框打开后（首次进入时 fields 尚未含它们的典型情形）才异步到达，字段自身 config 未变 → 指纹不变 → effect 误判「无变化」跳过回填，「引用字段」区停在打开时的空态。现指纹改为基于**回填用的完整 config**（`buildEditConfig` 的结果，含反推出的引用字段），lookup 行到达即重新回填；补回归测试覆盖「打开后 lookup 行才回流」场景
- **导入预览「更新数据比对」把未变化的关联字段行误判为全部需更新**：`_fetch_old_rows_by_ids` 只按物理列批量查旧值，而关联（link）字段无物理列（值存独立关联表），旧值恒为 `None`；`_build_field_diffs` 逐字段比较时 `None` 对比 `list[int]` 必然不等 —— 于是**只要目标表含任一关联字段，所有命中行都会被标成"有变更"**（用户只改了部分行的关联字段，却被提示全部行需更新）。现从关联表补读旧关联值（复用 `load_links`，无关联表时跳过），并让多值集合按**无序**比较（同一集合顺序不同不再判为变更）；补回归 `tests/test_import_pipeline.py::TestImporterUpsertAnalyze::test_link_field_unchanged_not_flagged`
- **E2E 门禁三处断言与 seed / 并行分片脱节**：`view-mode-switch` 的「产品开发」模式按钮数断言停在旧值 5，而 seed `views.json` 已含 `flow` 视图、实际共 6 个模式（grid+kanban+calendar+gantt+chart+flow），改为 6 与 seed 1:1 对齐；`tables-permissions` 的临时表用例结束未清理该表，并行分片下会向同工作区（WID=1）多留一行，冲垮 `workspace` / `navigation` 中硬编码的「恰好 9 张表」断言——现补 `finally` 软删除临时表（`DELETE /workspaces/{wid}/tables/{tid}`），并把两处精确行数断言改为 `expect.poll(...).toBeGreaterThanOrEqual(9)`（只要求 seed 的 9 张表都在，不锁死精确行数）
- **数据表编辑关联字段时「引用字段」为空**：后端 `_validate_field_config` 归一化 link 配置时会写入 `reference_fields=[]`（schema 用 `default_factory=list` 保证键恒存在），而 `buildEditConfig` 旧逻辑只在**键缺失**时从同表归属于它的 lookup 行反推引用字段，真实返回的空数组被当成有效配置直接跳过，导致编辑关联字段时「引用字段」区始终为空、保存还会以空列表覆盖并误删既有引用字段。现改为按**数组是否为空**判定，缺失或空数组一律反推，与字段列表口径一致；补回归测试覆盖空数组场景
- **图表视图多图换行后底部描述统计卡错位**：多图（`view_options.charts`）用 grid 平铺，行高取默认 `auto` 时会被图表容器（`flex:1 1 0%`）的低估 min-content 拖成卡片的 `minHeight`（420px），而单卡内容实需 ~550px —— 320px 图表 + 描述统计卡溢出卡边 118~141px，被下一行卡片压住（描述统计卡只露出表头一行）。现网格改 `gridAutoRows: min-content` + `alignItems: start`，行高与卡片高度一律按自身内容算；同时列模板改 `minmax(min(420px, 100%), 1fr)`，容器窄于 420px 时不再横向溢出。补 `ChartView.test.tsx` 断言（行高按内容计算、卡片不拉伸）
- **数据分析调整可视化配置时整页崩溃**（`Failed to execute 'removeChild' on 'Node'`）：`ChartCard` 在「必填字段缺失」时把整棵子树换成 `Empty`，React 复用了同一个图表容器 `div`；而 ECharts 的 `dispose()` 会清空容器 `innerHTML`，React 随后卸载容器内的节点就抛 `NotFoundError`——清空维度/指标后再选回即必现（单次切换不报，`有图 → 空态 → 有图` 才炸）。现改为**图表容器常驻且永不承载 React 子节点**，空态用同级绝对定位覆盖层表达（容器加 `data-chart-ready`），`dispose` 包 `try/catch` 防宿主已移除容器；新增 `ChartCard.container.test.tsx`（真实 ECharts，不走 mock）锁定该 DOM 归属契约，多图用例改为断言两卡容器常驻
- **图片字段点击即弹文件选择框、挡住粘贴**：图片字段编辑区整块是 antd `Upload.Dragger` 的「点击即上传」区域，用户想先点一下字段再 `Ctrl+V` 粘贴截图时，系统文件选择框会立刻弹出挡在前面，必须先取消弹窗才能粘贴。现改为点击字段只**聚焦**粘贴区（聚焦后描一圈细边提示「当前粘贴目标」），打开文件选择框只在显式「选择图片」按钮上触发；整块区域的拖拽上传、`allowed_mime_types` / `multiple` 校验保持不变。只读态不再显示上传入口（无图时显示「—」占位）。表格内联编辑与行详情抽屉共用 `ImageFieldEditor`，两处同源生效；并补 Playwright E2E `tests/e2e/critical/image-field-upload.spec.ts`（真实 `filechooser` 事件断言新增行 / 整行编辑下「点击字段不弹框、按钮才弹框、聚焦后粘贴可上传」）
- **CI 云服务部署失败**：`deploy/bootstrap-server.sh` 的 JWT 占位符替换失效 —— `set_env` 语义是「只补不覆盖」，遇到 `.env` 中已存在的 `JWT_SECRET=` 行会直接返回，`CHANGE_ME` 占位值原样残留；随后 `scripts/build_tat_command.py` 的守卫（`grep -q 'CHANGE_ME' .env`）非零退出，TAT 命令失败、整条部署中止。新增原子覆盖式写入 `set_env_force`（读全文 → 替换 → 临时文件 → `mv`，不遗留 `.env.bak`、不写坏配置）并用于该分支；顺带修正日志 ANSI 颜色码未闭合（`\033[0s` → `\033[0m`）与 `deploy/backup.sh` 中未定义的 `warn()`
- **CI E2E 门禁偶发超时**：`grid-more-menu` 等「触发器 + 说明 Tooltip」组合在视口顶部会把 Tooltip 翻转到按钮**下方**，正好盖住刚展开的下拉菜单；Tooltip 浮层默认可交互（指针移入保持展开），菜单项被遮挡且点击被拦截——`critical/view-field-visibility` 的「重置列宽与列序」用例因此 30s 超时（run 39012828781，shard 2/3 同时失败）。新增 `components/TooltipDropdown.tsx` 统一该组合（菜单展开期间强制关闭 Tooltip，收起后恢复悬浮），替换 Grid 工具栏 / 视图栏（模式切换 + 移动端/桌面端「更多」）/ Markdown 工具栏的 6 处写法
- **CI 分片静默失效**：workflow 里 `pnpm e2e -- --shard=N/4 --grep-invert=...` 在 bash 下会把 `--` 原样传给 playwright，其后的 `--shard` 与 `--grep-invert` 全被当作位置参数忽略——四个 shard 实际各跑全量 52 条（含 `@perf`），分片与排除都未生效（由日志 `Running 52 tests` 发现）。命令改为 `pnpm e2e --shard=N/4 --grep-invert=...`（参数直接跟在脚本名后），并删掉已无引用的 `E2E_SHARD_INDEX` 环境变量
- **视图导出 PDF 放大后发糊**：旧实现把内容等比压进 A4 宽度（1390px 看板压到 785pt，字号只剩 75%，用户必须放大、一放大就虚）。现改为按「屏幕实际大小」1:1 排版（`1 CSS px = 0.75pt`），页面尺寸随内容长大（不低于 A4）；位图按 300 DPI（`computeRenderScale`，受像素预算约束）渲染并以 JPEG 0.95 写入 —— PNG 在 jsPDF 4 下会退化成未压缩流（实测同一页 1.4MB → 33MB）
- **数据表视图可见性整体收口**（安全，ADR 0003 的 P0）：视图的「可见性」此前散落在各接口自行判断、且多个入口**完全没判**，任何人只要拿到视图 id 即可越权读取或写入他人视图。现把判定收敛为单一入口 `services/core/view_access.py`（`resolve_view_action` / `get_view_or_404` / `visible_view_filter`），所有视图接口共用。逐项修复：
  - **视图驱动查询补可见性校验**：`GET /views/{id}/rows|kanban|calendar` 原先只校验「表 READ + 视图归属」，凭**他人个人视图的 id** 即可套用其筛选/排序规则取数、并从结果差集反推其筛选条件。现补 `VIEW_READ`，不可见一律 **404**
  - **数据表导出补视图可见性校验**：`GET /tables/{id}/export?view_id=` 原先只比对 `table_id`，同样可借用他人视图的筛选规则导出数据，且**视图名会出现在下载文件名里**（连名字一起泄露）。现同样按 `VIEW_READ` 收口
  - **表详情不再返回他人个人视图**：`GET /tables/{id}` 的 `views` 原先直接取 `dt.views` 全量，现按可见性过滤；`view_count` 同步改为「当前用户可见的视图数」，避免用计数泄露他人私有视图的存在
  - **`reorder` 不再泄露/篡改他人视图**：`POST /views/reorder` 原先要求 `EDIT_VIEWS` 却返回该表**全部**视图，且会按传入 id 改写任何视图的 `order`（含他人个人视图）。现只重排**当前用户可改**的子集、响应只含**可见**视图
  - **个人视图对非创建者一律 404**（含表 owner / 工作区 OWNER / 超管）：`GET` / `PATCH` / `DELETE` 他人个人视图此前对 `EDIT_VIEWS` 持有者**完全放行**（列表里看不到、但可以按 id 直接改删）。现个人视图判定**先于**任何管理豁免，越权改删返回 404 且不暴露存在性（新增 `tests/test_view_access_p0.py` 覆盖，含超管反向断言）
  - **公共视图「列表可见却点开 403」口径统一**：详情原要求 `EDIT_VIEWS`，与列表（仅 READ 可见）矛盾。现公共视图**读**由表 `READ` 决定、**改/删**仍需表 `EDIT_VIEWS`（不变量 I7：放宽可见性不提升可改性）
  - **个人视图不得持有 `is_default`**：`is_default` 是表级标记（写入时会清掉同表其它默认视图），而仅 READ 的用户可以建个人视图 —— 此前其 `is_default=True` 会把**全表**落地视图置空（其他成员进表看到无默认视图）。现创建/更新/导入三条路径统一守卫（更新返回 400，导入静默降级）
  - **激活视图偏好同步收口**：`PUT /accounts/preferences/tables/{id}/active-view` 之前只校验「视图属于该表」，现要求该视图对当前用户可见
  - 设计文档：`docs/adr/0003-view-visibility-permission-model.md`（可见性三档模型 + 开放范围上限，P1 移除匿名分享已于同日落地、P2 落 `visibility` 列）
- **默认视图被落成 owner 私有**（ADR 0003 的 P2，修缺陷 #6）：`ensure_default_view` 与建表路径过去把新表的「全部」视图也写成 `owner_id = <创建者>`，于是**表 owner 的默认视图对其他成员不可见**——其他成员进表看到的是空视图列表（或被迫自建一个）。现在「全部」默认视图一律落 `visibility=table` / `scope_key=0`；`ensure_default_view` 对**已存在**的「全部」视图也会就地修正档位（升到新版本即自愈），迁移里 `owner_id IS NULL OR is_default = 1` 的存量映射保证零行为变化。配套收紧：`is_default` 只能落在 `table` 档视图上（创建 / 更新 400，导入静默降级），因为它是**表级**标记——仅 READ 的用户建个人视图时携带它会把全表默认视图置空
- **私有视图同名互相冲突**（ADR 0003 的 P2，修缺陷 #7）：唯一键原为 `(table_id, name)`，导致 A 建了「我的待办」之后 B 无法再建同名私有视图——但两者本该互不干扰。现唯一键改为 `(table_id, scope_key, name)`，私有视图只在创建者自己的命名空间内唯一（真名冲突返回 409）；`_scoped_name_conflict` 取代原先的全局同名判定
- **每表至少保留一个表内可见视图**（ADR 0003 决策 D1）：把最后一个 `table` 档视图转成 `private`/`shared` 会让其他成员的表页面无视图可用，现直接 400（`LAST_TABLE_VIEW_DETAIL`）；`delete_view` 的默认位转移候选也限定为 `table` 档视图
- **视图开放为「指定成员」后创建者自己反而看不到自己的视图**（ADR 0003 的 P3 发现并修复）：`visible_view_filter` / `is_view_visible` 原先只覆盖「`table` 档全表可见 / `shared` 档命中授权名单 / `private` 档本人」三种情形，**漏了"创建者对自己视图恒可见"**——而 `shared` 档的创建者并不在自己的授权名单里，于是把视图共享出去的瞬间它就从前端列表里消失（刷新也回不来），`is_default` 之类的表级操作也随之失去落点。现两个函数统一为「**创建者优先** → `table` 档 → `shared` 名单 → `private` 档仅创建者」，后者简化为 `owner_id == user_id` 一条分支（孤儿视图 `owner_id IS NULL` 仍对所有人不可见）。回归：`tests/test_view_share_p3.py::TestCapabilityFlags::test_list_exposes_can_edit_can_manage_and_count`
- **匿名分享绕过字段隐藏**（安全，已随上条移除一并消失）：`GET /api/v1/public/share/{slug}` 以 `user=None` 调用 `list_rows`，而 `hidden_fields` 按角色键取值 —— 匿名访问没有角色，被隐藏的字段对拿到链接的人**完全可见**；视图匿名读取也不写审计。该端点整体移除后此缺陷不再存在
- **修复数据表导入「确认后卡在 25% 且无报错」**：导入的"自动新增字段"（`unknown_cols_strategy=add_text_field`）只按**未删除字段**判重，而 `tables_datafield` 的 `(table_id, name)` 唯一约束**不区分软删除** —— 表里存在同名软删除字段（删过同名列）时，INSERT 直接撞约束抛 `IntegrityError`，整个 execute 阶段失败；更糟的是此刻 Session 已进入 `PendingRollback` 状态，旧的失败处理在 `except` 里直接 `commit` 又抛 `PendingRollbackError`，第二个异常逃逸出后台线程，任务行永远停在 `running` + 「执行子步骤 25%」，前端表现为"进度卡住、无从判断该等还是该重试"（线上实测：更新已有数据表时导入 WPS 生成的 XLSX）。两根因分别修复：新增字段前先给同名软删除字段**让位改名**（复用 `rename_trashed_field_aside`，与手工建字段同一策略，改名先 `flush` 再 INSERT）；`analyze / execute / reanalyze` 三处失败路径统一走 `_mark_task_failed()` —— **先 `rollback()` 再写 `failed`**，并把 ORM/DB 异常压成一句可读原因（完整堆栈留在服务日志），失败一定能落库并展示给用户
- **协作者通知**：新增 `accounts_notification` 与用户级 API（`GET /accounts/notifications` 列表 + 未读数、`POST /{id}/read`、`POST /read-all`）；文档授权（`POST /documents/{id}/permissions`）时向被授权者写入「X 邀请你协作《文档》（可编辑/只读）」—— 此前授权是静默的，被授权者只能自己翻目录树才会发现。顶栏新增**通知铃铛**（未读角标 + 下拉列表，点击条目即标记已读并跳转到该文档，支持「全部已读」）；通知写入为尽力而为，失败不影响授权本身；撤销授权不产生噪音通知
- **附件跟随宿主权限**（安全）：新增 `files_fileowner` 记录上传文件归属（表 + 行 / 文档 / 仅工作区），下载与删除不再只看「工作区成员 + 不可猜键」：受限表（`read_role` 高于普通成员）的附件、未发布文档的图片、以及被 `row_filters` 挡掉的行的附件，对无权者一律 403/404；上传时校验对宿主的写权限（表 → `EDIT_RECORDS`，文档 → 可见且可直接写）。历史文件无归属记录，保持原工作区级语义（不做回填）
- 前端上传携带归属上下文：表格附件单元格 / 行详情抽屉传 `table_id` + `row_id`，文档图片上传传 `document_id`；新增 API 层用例校验表单字段
- **行级过滤口径统一**：`TablePermission.row_filters` 原无角色维度、对所有人（含表所有者与工作区 OWNER）生效，与 `check_action` 优先级链、`hidden_fields` 按角色键的口径不一致（表现为「所有者看不到自己表里的部分行」）。现统一为：**表所有者 / 工作区 OWNER / 超管豁免行过滤**，普通成员仍受约束；记录读取、写入、审计、工作区导出四处口径一致；`user=None` 的内部/后台调用保持不变
- **preferences 激活视图校验表可读性**：`GET/PUT /accounts/preferences/tables/{id}/active-view` 原先只校验「表存在」，任何登录用户都能回显任意表 id 的偏好（存在性提示）。现要求 `TableAction.READ`，不可读返回 403
- **表列表统计字段去 N+1**：`field_count` / `view_count` 改分组查询、`record_count` 改一次 UNION ALL（表名白名单校验，>100 张表退化逐表），列表查询数不再随表数增长（6 张表 ≤14 次，此前约 3N+base）
- **修复桌面端无法管理文档协作者**：文档级授权（协作者）入口此前只挂在窄屏的「更多」菜单里，桌面端工具栏没有入口 —— 桌面用户实际上无法把草稿开放给同事。现补上工具栏「协作者」按钮（对所有成员可见；非创建者/所有者打开为只读名单，便于知情协作）
- 多用户端到端改为**真实 UI 驱动**：授权与撤销都走「协作者」弹窗（选成员 → 添加 / 移除），再用 API 断言实际可见性变化（同事从看不到 → 能看到 → 再次看不到），覆盖协作模式从界面到后端的完整链路
- **修复表审计日志泄露受限表行数据**（安全）：`AuditLog.detail` 在新增/修改行时保存**整行数据快照**，而 `GET /workspaces/{wid}/tables/{tid}/audit` 原先只校验工作区 EDITOR、未校验表 READ —— `read_role=owner/editor` 的受限表行数据可被任何编辑者从审计日志读到，且未按 `row_filters` 裁剪、未按角色 `hidden_fields` 剔除字段。现与记录读取同口径：READ 权限 + 行级过滤 + 字段隐藏（响应改为构造副本，避免改写 ORM 对象导致共享会话下把裁剪结果 flush 回库）
- **修复工作区导出绕过表权限与行级过滤**（安全）：`GET /workspaces/{id}/export` 原先只校验「工作区成员」，随后直接导出**所有表的所有数据行** —— 既绕过 `check_action(READ)`（`read_role=owner/editor` 的受限表连数据结构与数据行一并泄露），也绕过 `row_filters` 行级规则。现与导入端口对齐要求 **EDITOR+**（备份/恢复本就是对等操作，且该接口无前端调用），逐表按 READ 判定并叠加行级过滤条件，与读取接口同一口径
- **文档读取面整体可见性回归**（`tests/test_document_surface_visibility.py`）：以参数化清单覆盖文档读取的每个入口（详情/正文/版本列表/单版本/差异/导出/反链/出链/协作者名单/分享列表），对普通成员与工作区编辑者**全部 404**，对创建者**全部 200**（正向对照，避免「全 404 也算过」）；集合入口（列表/目录树/搜索）不含该草稿且响应体内不出现其正文；挂在草稿下的问题清单与修改申请同样不可达
- 彻底删除（purge）收紧为**先判可见性**：不可见者不得销毁看不见的草稿（返回 404 不泄露存在性），可见者仍需 editor+；已发布/归档文档在回收站中按文档策略对全员可见，故正常清理不受影响（有正向对照用例）
- **修复修改申请（document change request）绕过文档可见性的泄露**（安全）：此前所有读写只校验「工作区成员」，未按文档可见性过滤 —— 工作区成员可凭 `GET /document-change-requests/{id}` 读到他人草稿的**待审正文**，可按 `document_id` 列出他人草稿的申请，可对不可见文档发起申请并拿到 DIFF，工作区 editor 还能对看不见的草稿执行 merge/close/delete/update-base（merge 会把待审正文写进草稿）。现统一按文档可见性收口：不可见一律 404（列表按可见性过滤，返回空而非报错）；回收站文档仍允许可见者读到申请（保持「请先恢复文档」的业务提示）
- 新增**数据表 + 问题清单多用户端到端验收**（`frontend/tests/e2e/critical/tables-permissions.spec.ts`）：表级读取门槛从默认提到 owner 后，普通成员的表列表不再含该表、表详情 403、**挂在表上的问题清单与其单条详情也一并 403**（避免「表看不到但问题清单还能翻到」的跨入口泄露）；管理员列表返回 `read_role=owner` / `is_restricted=true` 且 UI 显示「受限」标签；门槛恢复后同事重新可见
- E2E 多账号能力收敛到共享 helper（`tests/e2e/helpers/api.ts`：`sessionAs` / `apiCall` / `sharedWorkspaceId`），两份多用户 spec 复用同一实现，避免各写一份易漏改
- 文档**主列表**在状态标签后补充可见性提示：未发布且未授权显示「仅自己可见」（悬浮说明「未发布：仅你与工作区所有者可见」），已授权协作者显示「共享 N 人」（悬浮说明授权人数）；已发布文档不显示（成员均可见）。至此目录树、主列表、编辑器三处口径一致
- **E2E 收为真正门禁**：去掉 `continue-on-error: true` —— 此前 E2E 失败不会阻断 pipeline，曾掩盖一次真实回归（新增用例助手丢失导致四个 shard 全挂而 run 仍显示成功）。稳定性依据：连续 6 次 CI 中 5 次四 shard 全绿、唯一失败为真实缺陷；抖动由 retries=2 兜底
- Playwright worker 数固定为 4：实测 12 worker 有 11 个用例 30s 超时失败、8 worker 有 8 个失败、4 worker 时 35 passed / 0 failed 且总耗时更短（25.3s vs 51s）—— 超时代价高于并行收益
- 新增**多用户端到端验收**（`frontend/tests/e2e/critical/documents-visibility.spec.ts`）：admin 建草稿 → 同事账号在目录树/详情完全看不到（404）→ 创建者 UI 显示「仅自己可见」→ 授权 viewer 后同事可见（树内 `visibility=shared`、详情 200、创建者 UI 变为「已共享给协作者」）→ 撤销后立即收回（树消失 + 404）。至此「不互相看到草稿/未发布版」从后端单测延伸到真实双账号浏览器验证
- 数据表列表新增 **read_role / is_restricted** 字段并修正 `my_access` 语义（工作区默认可读的表现在正确显示为 `read`，此前恒为 `none`）；前端列表对「读取门槛高于普通成员」的表显示**「受限」标记**与说明性提示（只有能读到该表的人才会看到这一行，便于管理员理解「为什么同事说找不到这张表」）
- 表列表的权限判定改为**一次性预取 + 纯计算**（`preload_table_access` / `TableAccessPreload`）：查询数从每表约 3 次降为固定 3 次，并新增「批量判定 == 逐表 `check_action`」的等价性测试与查询数回归测试，避免优化引入权限漂移
- 文档序列化新增 **`visibility` / `collaborator_count`**（已发布=workspace、未发布已授权=shared、未发布未授权=private；批量接口一次分组查询避免 N+1），前端文档树据此显示「仅自己可见」/「已共享给 N 人」标记与说明性悬浮提示，避免同事以为文档丢失；编辑器头部草稿标签改为「草稿（仅自己可见）」
- 新增**行级/字段级权限端到端测试**（记录列表接口）：无权限行的表不受任何行过滤与字段隐藏影响（钉死此前“权限行取错表”的缺陷）、配置了 `row_filters`/`hidden_fields` 的表按规则裁剪、修改配置后仅影响本表；并如实记录当前语义（`row_filters` 无角色维度，对所有人含所有者生效，而 `hidden_fields` 按角色键生效）作为后续待统一项
- **草稿协作者（文档级权限）**：补齐既有的 `documents_permission` 半成品能力 —— 创建者/工作区所有者可把未发布草稿授权给指定同事（`viewer` 只读 / `editor` 可直接编辑，仅对未发布内容生效）；被授权者可见该草稿（列表/目录树/详情/正文/版本/导出），撤销后立即收回；授权者限创建者/OWNER/超管，被授权者必须是工作区成员；新增 `GET/POST/DELETE /workspaces/{wid}/documents/{doc_id}/permissions` 与编辑器「协作者」入口
- **可见性与权限收口**：文档 `status` 首次参与读取过滤 —— 草稿/归档仅创建者与工作区所有者可见，已发布对全部成员可见；列表/目录树/搜索/详情/版本/差异/导出/反链/回收站/文档问题清单全部收口，不可见按 404 处理（不泄露存在性）；分享仅限已发布文档，取消发布后公开链接立即失效；编辑器新增「发布 / 转为草稿」入口
- 修复**表级权限按表隔离**缺陷：`access.py` 曾用 `db.get(TablePermission, table.id)`（按主键查）取权限行，实际读到其它表的规则 → 读阈值/隐藏字段/行级过滤错位；改为按 `table_id` 查，并让角色字符串大小写兼容（避免 `"OWNER"` 被静默当作拒绝）
- 数据表**列表按 `TableAction.READ` 过滤**（此前详情拦、列表不拦，泄露受限表名称/成员数），权限与成员变更时失效列表缓存
- 修复 CI 偶发失败：`DocumentEditorPage` 三个标题用例在文本域渲染后立即改标题，文档内容尚未加载时操作作用在空内容上（CI 上偶发 `expected false to be true`），改为先等待内容加载
- CI 警告清理：runner 固定 `ubuntu-24.04`（`ubuntu-latest` 将于 2026-10-19 迁移到 Ubuntu 26）；为每个 job 的 `setup-uv` 配置独立 `cache-suffix`，消除并行 job 抢占同一缓存键的「Unable to reserve cache」告警
- 前端警告清理：TreeSelect 根节点 `key`/`value` 不一致（antd TreeNode 告警）改为由 value 派生；Markdown 中仅含图片的段落改用 `<div>` 承载，消除 `<div>` 嵌套 `<p>` 的非法 DOM 结构；测试控制台过滤应用级待迁移的 antd 静态 `message` 上下文告警
- 测试警告清理：`workspaces_workspacemember` 批量删除改用 `synchronize_session="fetch"`，消除 SQLAlchemy「DELETE expected to delete N row(s); 0 were matched」告警；类作用域 fixture 改为 `@classmethod`，消除 pytest 的类作用域实例方法弃用告警
- 修复**已有数据表更新失败**（新建表导入正常）：`add_text_field` 自动新增列时，类型推断对非标量值做了 `str()`，WPS 图片元数据（list）被推断成 `text`，写入时 SQLite 抛 `Error binding parameter: type 'list' is not supported`。现在自动新增列会把图片元数据识别为 `image`、其它 list/dict 识别为 `json`；同时标量字段类型遇到 list/dict 兜底序列化为 JSON 字符串，使目标列已存在且为 text 时也不会中断导入
- 导入**确认执行**阶段补齐可观测性：① 子步骤进度（解析 15% / 校验 25% / 准备写入 45% / 写入 60% / 同步字段选项 85%）与逐步 INFO 日志，卡住时可直接看出停在哪一步，不再是笼统的一个 5%；② 进程**关闭时**把仍在执行的任务标记为中断（「服务重启导致任务中断，请重试」），部署重建容器不再留下无声停在 5% 的任务行
- 导入任务**不再出现「卡住且无报错」**：① 应用启动时回收上一进程遗留的「进行中」任务（进程重启/容器重建会直接把后台线程带走，任务行会永远停在 5%）→ 标记失败并说明原因；② 查询任务详情时按「无进展时长」兜底判定为中断（阈值=单阶段超时，默认 600s）并返回 `stalled_seconds`；③ 前端轮询**连续 3 次失败**不再静默忽略，而是明确提示「无法获取导入任务状态，请刷新后重试」，无进展超 180s 时提前给出警告；④ analyze/execute 阶段补充 INFO 心跳日志（文件名/字节数/进度），便于服务端定位
- 修复**导入 WPS 导出的带图 XLSX 时进度卡在 5%、且无任何报错**：WPS 会把「仅样式」的整行/整列写进文件，把工作表声明范围撑到 1048576 行（实际几十行），旧解析实现（非只读 + 全量 `iter_rows`）会物化百万空行 → 内存暴涨/等同卡死，线程里没有异常所以前端看不到报错。现改为**有界流式读取**（`read_only` + `reset_dimensions` + 行/列上限，超限给可读错误），导入/建表/预览三条解析路径统一；并给导入任务加**阶段超时看门狗**（默认 600s，超时即判失败并提示「另存为干净副本后重试」），不再出现无声卡住
- 修复内置 nginx 反代的 `client_max_body_size` 用了 envsubst 变量却位于非模板文件（会导致 nginx 启动失败），改为常量并在注释中说明原因
- 缓存扩展到 **文档树**（10s，写请求统一失效）与**记录列表**（5s，按 `record.*` 事件失效）：实测 p50 6.3ms → 3.6ms（-43%）与 7.9ms → 4.1ms（-48%），记录列表 p95 22.6ms → 4.9ms（-78%）
- 修复**未认证请求返回 500**：`get_current_user` 在 AUTH_ENABLED=True 时，「缺少认证头 / 认证头格式非法 / 令牌为空」原先返回 None，端点解引用 `current_user.id` 便抛 `AttributeError` → 现在统一返回 **401**（带 `WWW-Authenticate: Bearer`），前端既有的 401 登出逻辑可正常生效；`AUTH_ENABLED=False` 仍返回 None，匿名可用路由继续使用 `get_optional_user`
- 修复**中文全文检索命中为 0**：FTS5 的 `unicode61` 分词把连续中文当作单个 token，搜索「销售」「管理」「文档」这类常用词片段此前无结果 → 现在 FTS 无命中时自动追加**子串兜底通道**（title/summary/content 的大小写不敏感 LIKE，多词 AND、标题命中优先），只增不减、不改变既有命中；`_` 等 LIKE 通配符按字面转义

- 源字段类型变更后其他表引用它的 lookup 字段未同步类型：改为同步刷新 `config.source_field_type` 并在新类型占用物理列时清除 `broken`（源字段被删除或改为 link/lookup 时才失效），字段管理列表展示「引用 · 源类型」
- Windows 下附件上传恒返回「非法的文件标识符」：路径越界校验由字符串前缀比较改为 `Path.is_relative_to`，兼容反斜杠分隔符
- 外存（>2MB）文档多版本内容串档：历史版本读取改为按 `data/docs/{doc_id}/v{版本号}.md.gz` 定位，不再依赖只指向最新版本的 `Document.content_path`（此前 v1 会读到 v2 内容）
- 文档检索对非法 FTS5 输入不再 500：裸 `AND`/`OR`/`NOT`、裸 `*`、未闭合引号、含 `-`/`:` 的裸词统一按字面词加引号检索，解析层漏网时兜底转 400
- 文档外存文件缺失或损坏、内联 gzip+base64 内容损坏时降级为空内容并记 warning，详情 / 版本 / diff / 检索 / 分享读路径不再 500
- 软删除文档或文件夹后标签 `doc_count` 未刷新（已删文档仍被计数）；删除递归增加环保护，历史脏数据成环不再无限递归
- 文档并发保存触发的版本号唯一约束冲突返回 409 `doc_version_conflict`，不再裸穿 500
- 彻底删除回收站文档的响应字段命名冲突修正：布尔 `purged` 与数量键重名导致数量覆盖布尔值，数量改为 `purged_count`
- 手机端数据表视图切换困难：视图切换栏在窄屏下把所有控件（7 个模式按钮 + 搜索框 + 4 个操作按钮）挤在同一行，视图页签被压缩到几乎不可用。移动端改为「视图页签占满剩余宽度（可横滑）+ 模式 / 筛选 / 更多」三控件布局——模式切换收进带文字标签的下拉（表格 / 看板 / 日历 / 甘特图 / WBS / 矩阵 / 图表），新建 / 编辑 / 删除 / 导入 / 导出 / 表格设置收进「更多」菜单，搜索折叠为可展开的第二行（搜索词非空时常显）；桌面端布局不变
- 手机端宽表格排版崩坏：管理台用户表 8 列在窄屏被压缩到「昵称」逐字竖排、「邮箱」裁切在卡片外，工作区成员表用户名/邮箱被挤成多行。统一改为窄屏不压缩列宽、容器横向滚动（`scroll={{ x: 'max-content' }}`），成员表用户列固定 220px；管理台筛选控件窄屏整行排布
- 手机端管理台用户管理由 8 列表格改为卡片列表：用户名（昵称）/ 邮箱 / 电话 / 角色标签 / 状态 / 编辑·日志一屏一实体、无需左右滑动；勾选框保留以支持批量启用·禁用·改角色，分页信息保留；桌面端仍为可横滑表格
- 手机端表权限编辑：成员表窄屏保留列宽改横向滚动（用户列 220px），「隐藏字段」网格由三列改单列（三列在 390px 下每列约 110px，字段名被截断）
- 手机端导入预览：4 个页签（含计数，行宽 396px > 可视 342px）切换后把激活页签自动滚入视口，报告到达 / 参考列变化时重新校准（复用顶部导航的 tabScroll 逻辑）
- 手机端管理台「系统信息 / 系统备份」的描述列表由两列改单列、标签置于值上方（原先 390px 下标签列仅约 40px，「应用名称」被压成一字一行、数据库路径被挤成多行），桌面端保持两列
- 手机端数据表网格无法横滑：虚拟滚动表格的横向滚动由 rc-virtual-list 自绘细滚动条驱动（`.ant-table-tbody-virtual-holder` 的 `overflow` 为 hidden），触摸设备既不能原生横滑、也几乎点不中滚动条 → 窄屏关闭虚拟滚动改用原生滚动容器（实测 `.ant-table-body` 可滚动，页大小受分页约束故性能可接受）
- 手机端网格横滑时丢失行标识：窄屏固定选择列与首个数据列（`fixed: 'left'`），横滑时复选框与主字段常驻左侧并可读；桌面端不受影响
- 手机端导航层级感偏弱：工作区页签与二级页签（表级 / 文档级）同处一条横滑行，横滑后竖线分割移出视口后无法分辨层级 → 窄屏给二级段加浅底圆角容器并隐藏竖线（桌面保持原有 GitHub 风格分割）
- 手机端文档编辑页悬浮「文档树」按钮遮挡正文末行：内容区底部留出 72px（实测内容底 592 / 按钮顶 608，间隙 16px）
- 手机端数据表列表由 4 列表格改为卡片列表：一屏一表（表名 + 访问标签 / 记录·字段·成员 / 更新时间 / 打开·更多），操作菜单与表格共用同一套入口（重命名·复制表·删除表）并改为 click 触发（触摸设备无 hover）；拖拽排序仅在桌面端提供（触摸端拖拽手势不可靠），桌面端表格保持原样
- 手机端数据表设置页左侧竖排页签吃掉内容宽度、统计条第 4 项「创建日期」被裁切：窄屏页签改为顶部横排，`.ts-stats` 允许换行
- 手机端弹窗/抽屉适配：个人设置「用户资料」三字段并排时每格仅约 110px 导致昵称/邮箱被截断 → 窄屏纵向堆叠；表格设置「间距 / 每页行数」允许换行；帮助中心窄屏主题导航由左侧 150px 竖排菜单改为顶部横向可滚动胶囊，底部提示与重播按钮纵向排列
- 手机端甘特图不可用：工具栏 4 个区块合计约 570px 挤在一行，标题与「共 N 个任务」被压成竖排文字；左列固定 250px 使时间轴只剩约 90px。窄屏下工具栏换行、标题/统计 nowrap，左列收窄到 140px，时间轴宽度翻倍到约 218px
- 手机端数据表工具栏标题被压成「产…」：窄屏隐藏记录数徽标（底部「共 N 条」已给出）、把表设置 / 更新导出 / 数据治理 / 编辑行收进「更多」菜单（菜单改为 click 触发，兼容触摸设备），标题恢复完整展示
- 手机端数据表列表筛选分段控件把「我可编辑的」截断成「我可编…」：窄屏改用短文案（我拥有 / 可编辑 / 可读）
- 手机端顶部导航工作区页签被挤成 0 宽：同排的二级页签（表名 + 修改申请/问题清单/数据表设置）宽约 448px 且不收缩，把可收缩的工作区页签（数据表 / 文档 / 工作区设置）压到不可见。窄屏改为页签保持内容宽度 + 整行横滑，并在路由/计数徽标变化后把**当前子页的激活页签**自动滚入视口（桌面端布局不变）
- 手机端文档编辑器工具栏 9 个按钮折成三行挤掉正文：窄屏只保留「大纲」+「保存」，其余（反向链接 / 文档链接 / 插入表格引用 / 标签 / 修改申请 / 版本 / 导出）收进「更多」菜单（导出为二级子菜单）
- 手机端文档编辑器左右分栏在 390px 屏上每侧仅约 190px（正文一行只放得下几个字）：窄屏改为「编辑 / 预览」分段控件二选一、面板独占整宽（实测编辑区 390×428、预览区 358px 宽），桌面端保持左右分屏；窄屏点击大纲锚点会自动切到预览面板再定位

## [0.2.7] — 2026-10-01

### 新增

- 环境检查端口结果状态着色

## [0.2.6] — 2026-09-30

### 新增

- Windows 开机自启后台服务
- GUI 环境检查区新增端口占用终止按钮与端口占用兜底强杀逻辑
- 导出数据按时间命名；看板视图当天任务置顶、按严重程度区分

### 修复

- 表选项变更后同步存量数据；xlsx 导出兼容 openpyxl 不接受的复杂类型
- GUI 端口占用终止对死 PID 谎报成功、残留 PID 误报失败与停止服务不彻底问题；进程判活与进程名查询改用 Win32 API，移除 tasklist 依赖

### 变更

- 清理既有 lint/格式化债务；新手友好语言表述优化

## [0.2.5] — 2026-09-29

### 新增

- CLI 服务默认绑定 0.0.0.0，允许局域网访问
- 丰富日常待达示例数据与关联/引用字段回填

### 修复

- 启动时新增 schema 自愈机制，修复报表模板缺列报错
- 导出文档表格首行渲染问题；看板负责人与额外字段空值渲染占位标签

## [0.2.4] — 2026-09-28

### 新增

- **矩阵视图**：支持纵横两轴分类交叉，轴区双色淡染、分轴分界线与单元格高度自适应
- 备份文件名标注软件版本与数据库格式版本
- 报表按工作区过滤，工作区 tab 数量徽标
- 个人设置：右上角显示昵称、用户资料紧凑化、新增字体设置与主题恢复默认、用户默认主题样式配置
- 工作区级导航移入 Content 分页导航；表格骨架屏列数对齐最近已加载表可见字段数，优化表与页面切换加载态及过渡动画

### 变更

- 性能优化：Gzip 压缩、SQLite 缓存、反射缓存；seed 数据库写入耗时 16.1s → 5.1s

### 修复

- 主行与 link 字段写入合并为同一事务，修复 SQLite 隐式 ROLLBACK 导致的数据丢失
- Segmented 激活项改为主题色滑块加反色文字；隐藏字段勾选项三列网格对齐

### 移除

- 个人设置表格边框/表头/斑马纹装饰性配置（显示模式收编进表格页签）

## [0.2.3] — 2026-09-26

### 新增

- **引用（lookup）字段类型**：支持 link 模式跨表字段关联、过滤排序、嵌套分组（or/and）条件过滤与前端引入模式选择
- link 字段必填/唯一保存前预检与写入路径校验，lookup 字段约束明确拒绝
- 工作区导出导入升级至 v4，支持跨表引用重映射
- 报表：新增 HTML 输出格式、主题风格设置与 DOCX/PDF 渲染主题应用、模板编辑弹窗页签布局与校验失败自动跳转、员工名册参数下拉选择、多组示例报告模板与数据集
- 表格：列宽自适应拖拽调宽、列序拖拽调整、列宽双击重置与重置列布局菜单、表头字段类型图标
- 字段配置统一面板，聚合基础属性、默认值与类型专属配置
- 个人设置支持编辑昵称与邮箱；关联字段下拉选项使用目标表主字段值
- seed 新增 fields.json 字段设置种子（唯一/必填/关联/引用示例）

### 变更

- 表头关联/引用字段名移除下划线标识，仅保留图标
- CI 流水线并行与缓存优化，新增 CodeUp CI/CD 流水线；项目名称表述更新为通用数据管理平台

### 修复

- 报表跨工作区额外表字段与预览请求错误工作区、模板参数长内容截断、预览过滤统计显示为 0
- 物理列与 link 字段互转后行编辑 500；引入 lookup 后编辑行 500
- 备份 v4 字段 id 映射时机与关联回取值错误；备份导出导入数据行全部丢失与日期字段归一
- 工作区导入与自动默认视图「全部」重名冲突；表头多次点击无法取消排序
- 时间戳转换受运行时区影响；SQLite 数据库锁错误

### 安全

- 脱敏示例数据邮箱，消除密钥/通用密码字面量扫描误报并补充黑名单说明

## [0.2.2] — 2026-09-23

### 新增

- 字段自动预填锁定配置（表级开关）
- 看板视图截止日期徽章样式与显示逻辑优化

## [0.2.1] — 2026-09-23

### 新增

- **看板完成标志**：支持日期类型字段双向切换、判定操作符与无值操作符（统一视图判定模型），卡片完成态绿底灰字、完成勾选框与庆祝动画
- 备份恢复向前兼容：旧备份恢复时自动迁移 schema；native 备份内嵌 SQLAlchemy 兜底导出；GUI 恢复端新增恢复模式选择与降级报告呈现
- 导入推断层新增 Unix 时间戳与长文本识别；CSV/XLSX 结构守卫，空列名/重复列名明确报错
- 报表模板字段插入语法统一并完善预览对齐
- 项目 Logo

### 变更

- 后端拆分重构：field_types 按类型族拆分子模块、transfer.py 拆分为 services/transfer 子包（聚合导出 API 不变）、tables 插件服务归位 services/{core,fields,importing}、辅助脚本归位 cndb.cli 包
- 前端拆分重构：GridPage 按工具栏/视图栏/表格主体等域拆分、FieldManager 与 ImportExportDialog 目录化
- 前端性能与构建体积控制优化

### 修复

- 并发注册竞态导致的 500 错误并优化错误提示
- 深色主题白色元素与导出界面背景；看板新增项日期自动填充
- 旧浏览器兼容：Array.prototype.at polyfill、dayjs 导入方式调整

### 安全

- CSV/XLSX 导出增加公式注入防护

### 移除

- 画廊视图相关代码与测试
- 用户级视图偏好，改用默认视图作为落地基准

## [0.2.0] — 2026-09-20

### 新增

- 交互式新手引导与应用内帮助中心，全站升级功能 Tooltip 并在表单对话框内嵌新手说明
- 字段默认值：单行文本支持自动编号默认值，字段行展示必填/唯一备注；字段自动填充与默认值设置 UI 优化

### 修复

- 编辑字段保存前预检必填/唯一数据冲突
- text 字段 config 隐藏注册槽，修复编辑自动编号字段时模式 Radio 无法激活
- Header 报表/工作区设置按钮显式绑定当前工作区，无上下文时禁用
- Windows CI 控制台 cp1252 无法编码盒子绘制字符导致 info 命令崩溃

### 移除

- 完整界面按钮及冗余代码

## [0.1.14] — 2026-09-19

### 新增

- 完善视图导出功能
- 全项目字段类型标签统一为中文类别标签与统一配色

### 变更

- 表设置 Modal 改左侧竖向导航紧凑布局，字段列表改类型图标行卡片并统一主题变量
- PyPI 镜像更换为华为云

### 修复

- 导入预览样本值按首次出现顺序去重，避免重复值挤占样本位
- 字段选项颜色与编辑字段不同步及智能推荐撞色；表设置 initialTab=permissions 不加载数据与 row_filters 误清空

### 移除

- 回收站功能代码与测试

## [0.1.13] — 2026-09-19

### 新增

- Select 字段配色优化；选项列表标签与智能推荐优化

### 变更

- fspack 依赖升级至 0.6.6

### 移除

- 分享视图与表设置入口

## [0.1.12] — 2026-09-19

### 新增

- 导入 DIFF 展示字段级新旧对比与变更汇总，无更新行区分空态提示；导入参考列智能推荐与 DIFF 归一化识别
- multiselect 列表识别接入 JSON/XLSX 导入路径，支持负百分比落库
- 新增行交互：自动聚焦与自动滚动（E2E 回归覆盖）；新增 useDebouncedValue/useDebouncedCallback/useElementSize 通用 hooks
- GUI 日志文本组件支持复制与全选

### 变更

- httpx 从运行时依赖移至 test extra（源码仅使用 httpx2）；显式声明 requests 运行时依赖（wechat_auth 插件实际使用）
- ruff/pyrefly 配置收敛：移除不存在目录的排除项，修正 UP045 注释表述
- 表格视图切换性能优化；导入导出界面交互优化

### 修复

- xlsx 日期单元格被误推断为 select；导入日期序列化崩溃
- 身份证号预览精度丢失；新增行位置分页；工作区创建后跳转逻辑
- docker-compose.yml 源码部署构建上下文 `context: ..` → `context: .`（compose 文件位于仓库根目录）
- README 失实内容：npm → pnpm、`make bench` 改为脚本调用、移除不存在的 `.env.example` 指引、项目结构树对齐实际目录

### 移除

- 空壳包 `cndb.services` / `cndb.schemas`（模板脚手架遗留，无任何引用）
- Sphinx 文档骨架 `docs/` 与 `.readthedocs.yaml`、pyproject `docs` extra（文档入口以 FastAPI `/docs` 为准）
- `tox.ini` 与 Makefile `tox` / `doc` / `check-fast-par` 死目标（门禁统一由 `make check` 承载）

## [0.1.11] — 2026-09-19

### 新增

- Grid 行内编辑模式，替换原有新增弹窗；新增行改为新建行表单收集必填字段
- 数据实时转换预览与异常视觉标记；文件导入预览优化
- Excel 导入自动识别字段生成
- GUI：持久化与界面布局优化、归档文件备份管理、备份进度与结果反馈、系统信息界面刷新、服务启动端口与文件监控

### 变更

- 前端三层测试体系落地：vitest 283 用例接入 make check 门禁
- E2E 提速：信号化等待替换固定 sleep

### 修复

- Select 字段选项串扰与配色；seed 流程 alembic 版本标记缺失导致启动报错
- 抑制 Windows ProactorEventLoop 连接重置噪音，净化 e2e 与生产日志

### 移除

- 字段评论发表功能
- GUI 用户管理 Tab，用户管理仅保留 CLI 方式

## [0.1.10] — 2026-09-18

### 修复

- 打包环境下 GUI 服务启动路径查找与报错提示
- Windows 下启动服务弹出黑窗与进程启动失败问题
- 多场景交互与错误处理问题

## [0.1.9] — 2026-09-18

### 新增

- **报表功能增强**：多表引用 + DOCX/PDF/XLSX 富文本输出 + 前端编辑器增强（拖拽、固定区域滚动、布局优化）
- **桌面管理台（GUI）**：cndbw GUI 设计与 fspack 打包配置、`~/.cndb` 目录结构、桌面管理台功能完善
- 简化注册流程并新增 Admin CLI
- CSV 建表改造为导入数据表；导入预览支持重新 DIFF 与字段级对比视图
- 字段选项自动识别与 E2E；字段引入支持跨表映射预览与智能建议
- 自动数据库迁移机制与多版本迁移脚本

### 变更

- `__init__.py` 业务逻辑迁移到子模块并同步 alembic 双目录；目录路径与运行环境检测逻辑重构
- 构建方式改为 pyc 优化并禁用 site 包（fspack）；fastapi 版本范围限制以兼容 Win7

### 修复

- 导入后 select 字段选项丢失与无法编辑
- cndbw 脚本入口模块路径错误

## [0.1.8] — 2026-09-16

### 新增

- 导入器可配置字段映射与空隙填充选项；导入 upsert 增强（参考列匹配 + 未知列策略 + 分 Tab 预览）
- fspack 打包 CI/CD
- 甘特图时间刻度缩放

### 变更

- 批量操作权限检查逻辑简化；health 相关代码清理
- 补充边界测试，覆盖率提升至 95%

### 修复

- 数据表分页跳转异常，增强后端排序/过滤参数容错

## [0.1.7] — 2026-09-15

### 变更

- Python 版本锁定 3.12，移除过时的 Python 3.13/3.14 版本分类
- Makefile bump/push 命令简化与 pypi 上传匹配规则优化

### 修复

- 成员表选择用户下拉显示数字问题
- tables router 复制表接口类型提示与异常代码格式

## [0.1.6] — 2026-09-15

### 新增

- WBS 视图与甘特图显示优化；甘特图日期标签修复
- 字段引入（数据表引入字段设计与前端 UI）
- 工作区权限 Tab，修复数据表权限成员可见性
- 角色权限系统（E2E）

### 变更

- Windows 7 兼容：认证依赖版本调整，Python 版本支持降级到 3.12 并更新依赖约束
- fspack 打包配置接入并修复 fsp b 打包无法运行问题；Makefile 依赖安装与清理脚本重构

### 修复

- SQLAlchemy 遗留 API 警告与 pytest 配置；make check 乱码问题
- release workflow 中 pnpm 安装失败

## [0.1.5] — 2026-09-15

### 变更

- 强制 make check 门禁流程

### 修复

- 甘特图视角切换问题

### 新增

- 报表生成开发计划与测试基建；测试覆盖率最大化提升

## [0.1.4] — 2026-09-14

### 新增

- 三员用户账户注册功能
- 主题切换：3 套主题与 E2E
- 工作区详情与成员管理；备份恢复功能
- API 股票建表功能（API 数据自动建表与抓取）
- 表设置弹窗重构：embedded 模式与字段管理器；复制表功能 UI 刷新与 E2E

### 变更

- 视图组件拆分重构，统一 view_options 真相源
- 前端入口设计与 E2E 完善；ESLint 规则调整

### 修复

- 深色模式日历配色、深色视图白色背景、主题卡片与设置问题
- 工作区/表格多处交互细节（grid、api-import）；CI/CD 错误

## [0.1.3] — 2026-09-13

### 新增

- **多视图系统重构**：统一视图类型配置，支持看板/日历/画廊等多种视图
- 看板视图卡片排序与紧急置顶
- 用户偏好功能、表格视图体验与数据导入能力增强
- wheel docker 部署支持；前端打包集成与包资源打包配置
- 示例数据集与登录后流程优化

### 变更

- 视图模式按钮与左侧 Segmented 双向联动
- smart-color 颜色匹配与 fallback 逻辑优化

### 修复

- 看板 link 类型字段分组渲染为 [object Object]
- 日期字段编辑适配；非 grid 视图数据获取

## [0.1.2] — 2026-09-13

### 新增

- **Playwright E2E 测试**：smoke（登录 → Grid → 退出）+ critical（行 CRUD 全链路），配置见 `frontend/playwright.config.ts`
- **生产部署定型**：多阶段 `deploy/Dockerfile`（前端构建 + uvicorn）+ `deploy/nginx.conf` 反代 + `docker-compose.yml` 生产编排（SQLite/PostgreSQL 双形态）
- **示例数据集**：`examples/datasets/` 5 个 CSV（学生成绩 / 电商销售 / 房价预测 / 客户流失 / 气温天气）
- **`.env.example`**：部署环境变量模板

### 变更

- docker-compose.yml 从开发形态更新为生产形态（nginx 入口 + app 容器 + pg profile）
- `.gitignore` 添加 Playwright 产物目录

## [0.1.1] — 2026-09-11

### 新增

- 前端完成 F1–F9：登录注册 / 工作区 / Grid inline 编辑 / 视图 Tab / 导入导出 / 成员管理 / 主题切换 / 关系图 / 报表 / 公开分享页
- SPA fallback：`app.py` 中间件自动处理前端路由回退
- 前端构建产物挂载到 `src/cndb/static/`，uvicorn 统一提供

### 变更

- RowResponse 类型对齐后端扁平结构（移除嵌套 values 字段）

## [0.1.0] — 2026-09-10

### 新增

- 后端 P0–P4 完成：框架基础 + 6 插件 + 95%+ 测试覆盖率
- 插件架构：accounts / workspaces / tables / reports / health
- 动态数据表：SQLAlchemy Core 运行时 DDL
- link 字段多对多存储与查询
- 审计日志 + 回收站闭环
- 字段类型补齐至 11 种
