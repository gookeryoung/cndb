# 流水线检查 DSL 使用指南

流水线检查是工作区级的声明式质量检查：用一份 YAML 定义检查目标与动作，保存时编译成快照，之后由手动、事件或定时触发执行，产出结构化发现物（finding）。设计口径见 [ADR 0076](adr/0076-pipeline-check-dsl.md)。

- 检查只读，不修改业务数据；
- 发现物只记录定位信息（字段名 / 行 ID / 引用原文），不携带单元格值与文档正文；
- 保存期完成结构校验，运行期只可能出现数据层面的发现，不会出现语法错误；
- 同一定义同一时刻最多一个活跃运行（单飞），重复触发静默跳过。

## 1. 入口与快速开始

| 入口 | 位置 |
|---|---|
| 前端 | 工作区「质量检查」页签 → 新建流水线（YAML 编辑抽屉带保存前校验） |
| API | `POST /api/v1/workspaces/{wid}/pipelines`，请求体 `{"content": "<YAML>", "enabled": true}` |
| 纯校验 | `POST /api/v1/workspaces/{wid}/pipelines/validate`（不落库，返回 `ok/error/job_count/step_count`） |
| 手动运行 | `POST /api/v1/workspaces/{wid}/pipelines/{id}/run`（202；活跃运行冲突 409） |
| 定时运行 | `cndb pipeline tick`（生产由系统 cron 每分钟调用） |
| 演示种子 | `cndb seed` 把 `examples/datasets/<工作区>/pipelines/*.yaml` 幂等注入为示例流水线（可复制改造） |

最小可用示例：

```yaml
name: 库存空值巡检
on:
  manual: true
jobs:
  空值检查:
    steps:
      - uses: table/null-rate
        with:
          table: 商品库存
          fields: [商品名称, 库存数量]
          max_rate: 0.02
```

保存后在工作区「质量检查」页签点击运行，即可在运行详情看到逐 job / step 结论与发现物。

命令行手动跑一次定时扫描：

```bash
cndb pipeline tick --workspace-id 1          # 只处理该工作区
cndb pipeline tick --workflow-id 12 --json  # 只跑一条定义并以 JSON 输出汇总
```

生产部署（宿主机 crontab）：

```cron
* * * * * /opt/cndb/deploy/pipeline.sh >> /opt/cndb/data/pipeline.log 2>&1
```

## 2. DSL 结构

顶层只允许 `name` / `on` / `vars` / `jobs` 四个键，其他键会在保存时报错。

```yaml
name: 库存质量巡检            # 必填（或由创建记录的名称兜底），≤120 字符，同工作区唯一
on:                          # 触发声明
  manual: true
  events: [record.updated, sync.finished]
  schedule: "0 9 * * *"
vars:                        # 可复用的标量 / 表达式
  null_limit: 0.02
  sync_only: ${{ on.event == 'sync.finished' }}
jobs:                        # 非空映射；键为 job ID
  空值检查:
    needs: []                # 依赖的 job（字符串或列表），可省略
    if: ${{ vars.sync_only }} # 必须是 ${{ }} 表达式，可省略
    steps:                   # 非空列表
      - uses: table/null-rate
        with:
          table: 商品库存
          max_rate: ${{ vars.null_limit }}
        severity: error
        continue-on-error: false
```

### 2.1 `on` 触发声明

| 键 | 类型 | 说明 |
|---|---|---|
| `manual` | 布尔，默认 `true` | 手动触发声明。当前手动运行接口不因 `manual: false` 拒绝，该标记用于声明入口意图并保留给后续统一收口 |
| `events` | 事件名列表 | 订阅业务事件；仅启用（`enabled=true`）的定义会命中 |
| `schedule` | 5 段 cron 字符串 | 定时触发；按 UTC+8 解释，分钟级粒度 |

支持的事件与可用 `on.*` 字段：

| 事件 | 触发时机 | 触发上下文字段 |
|---|---|---|
| `record.updated` | 数据表记录批量建行 / 改行 / 删行提交后 | `on.table_id`、`on.table_name`、`on.action`、`on.row_ids`、`on.count` |
| `document.saved` | 文档正文保存后 | `on.document_id`、`on.title` |
| `sync.finished` | 数据同步运行结束（成功或失败） | `on.job_id`、`on.run_id`、`on.status`、`on.table_id` |

三种触发都会额外带上 `on.event`（`record.updated` / `document.saved` / `sync.finished`；定时为 `schedule`）。

cron 为「分 时 日 月 周」，周字段取值 0–6（周日 0、周一 1 … 周六 6）。示例：

| 表达式 | 含义 |
|---|---|
| `* * * * *` | 每分钟 |
| `0 9 * * *` | 每天 09:00（UTC+8） |
| `0 9 * * 1` | 每周一 09:00 |
| `*/30 * * * *` | 每 30 分钟 |
| `0 6 1 * *` | 每月 1 日 06:00 |

定时触发去重：同一分钟槽只触发一次；若该定义已有活跃运行则本轮记 `skipped_conflict`，不重复建运行。

### 2.2 `vars` 与表达式

`vars` 的键必须是标识符，值只能是标量（字符串 / 数值 / 布尔 / null）或 `${{ }}` 表达式。变量按声明顺序求值，可引用更早声明的变量与 `on.*`。

表达式是受限白名单子集（不使用 `eval` / Jinja2）：

- 变量路径：`vars.*`、`on.*`、`jobs.<id>.conclusion`
- 运算符：`== != < <= > >= && || !`，支持括号
- 函数：`len(x)`、`contains(x, y)`、`startswith(x, y)`、`endswith(x, y)`、`to_number(x)`
- 字面量：数字、单 / 双引号字符串、`true` / `false` / `null`

示例：

```yaml
vars:
  is_sync: ${{ on.event == 'sync.finished' }}
  sync_ok: ${{ on.event == 'sync.finished' && on.status == 'success' }}
  has_rows: ${{ len(on.row_ids) > 0 }}
  is_price_table: ${{ startswith(on.table_name, '商品') }}
```

运行期表达式求值失败（变量缺失 / 类型不匹配）不会中断运行：`jobs.<id>.if` 按 `false` 处理，`with` 参数按 `null` 处理，并把原因写入运行 `stats.warnings`。

### 2.3 `jobs` 与执行顺序

- `needs`：依赖的 job，可为单个字符串或列表；依赖成环、依赖不存在、依赖自身都会在保存时报错。
- 执行按拓扑序；同层保持 YAML 声明顺序。
- 上游 job 结论必须为 `success`，否则下游 `skipped`。
- `if` 必须是 `${{ }}` 表达式；求值为假时该 job 及其下游跳过。
- job 内 step 顺序执行；任一 step 结论为 `failed` 时 job 结论为 `failed`。

### 2.4 `steps` 与严重度

| 键 | 说明 |
|---|---|
| `uses` | 检查动作名（见第 3 节目录），保存期校验必须已注册 |
| `with` | 动作参数；未知键、缺失必填、静态类型不符都会保存报错。参数值可写 `${{ }}` 表达式或字符串列表 |
| `severity` | 该 step 发现物的默认严重度：`error` / `warn` / `info`（缺省取动作声明） |
| `continue-on-error` | 默认 `false`；为 `true` 时本 step 即使产出 `error` 级发现也不把 job 判为失败 |

严重度与运行结论：

- 动作产出的单条发现可自带严重度（如扫描截断提示为 `info`），优先于 step 默认值；
- 任一 step 失败且未豁免 → job `failed` → 运行 `failed`；
- 没有 failed job 但存在任意发现物 → 运行 `partial`；
- 无失败且无发现物 → 运行 `success`；
- 单次运行内同一检查动作最多落 1000 条发现物，超出部分合并为一条「截断」提示。

`with` 静态类型注意：

- 声明为 `string` 的参数（如 `table/value-range` 的 `min` / `max`）必须带引号：`min: "0"`，裸 `min: 0` 会被当作整数而校验失败；
- 声明为 `string_list` 的参数可写单个字符串或字符串列表：`fields: 商品名称` 与 `fields: [商品名称, 库存数量]` 等价；
- 声明为 `json` 的参数可传对象 / 数组（如 `document/sensitive` 的 `rules`）；嵌套里的 `${{ }}` 表达式同样做语法校验，类型不匹配在保存期拒绝；其余参数仍是标量 / 字符串列表。

## 3. 内置检查动作目录

| 动作 | 标题 | 必填参数 | 可选参数 | 默认严重度 | 适用目标 |
|---|---|---|---|---|---|
| `table/null-rate` | 字段空值率检查 | `table` | `fields`（默认 `all`）、`max_rate`（默认 `0.05`） | warn | table / field |
| `table/duplicates` | 重复行检查 | `table`、`fields` | `ignore_case`（默认 `false`）、`ignore_whitespace`（默认 `false`） | warn | table |
| `table/stale` | 时间字段新鲜度检查 | `table`、`field` | `max_age_days`（默认 `30`） | warn | table / field |
| `table/value-range` | 字段取值区间检查 | `table` | `fields`（默认 `all`）、`min`、`max`（至少一个） | warn | table / field |
| `document/links` | 站内链接断链检查 | 无 | 无 | warn | document |
| `document/broken-refs` | 文档引用失效检查 | 无 | `scopes`（`chart` / `table` / `file`，默认三者全查） | warn | document |
| `document/chart-blocks` | 内嵌图表块检查 | 无 | `max_blocks`、`max_block_bytes` | warn | document |
| `document/sensitive` | 文档敏感内容检查 | 无 | `keywords`、`patterns`、`rules`、`logic`（默认 `any`） | warn | document |

各动作的数据口径：

- `table/null-rate`：SQL 聚合统计空值率，表为空不产出发现；发现物只带字段名与比率。
- `table/duplicates`：按判重键分组，每组产出一条发现（带成员行 ID，不带值）；扫描达到行数上限时追加一条 `info` 截断提示。
- `table/stale`：取时间字段最大值与当前时刻比较，未来时间不算过期；只支持 `date` / `datetime` / `timestamp` 字段。
- `table/value-range`：数值列按数值比较，日期列按 ISO 日期，时间戳列按整数秒或 ISO 时间；只统计越界行数。
- `document/links`：检查 `[[标题]]` wikilink 是否指向存在的文档（代码围栏内不计）。
- `document/broken-refs`：检查 `{{table:<表ID>|view=<视图ID>}}`、内嵌图表模板、`![alt](file:<key>)` 附件引用是否可解析。
- `document/chart-blocks`：检查单篇块数量、单块字节数与坏块；默认上限与文档编辑器口径一致。
- `document/sensitive`：扫描标题与正文；`keywords` 不区分大小写、`patterns` 按 Python `re` 语义；`rules` 声明命名规则（每条规则任一关键词 / 正则命中即算命中），`logic` 用 `any` / `all` / 布尔表达式（`and` / `or` / `not` / 括号，规则名按字面引用）组合多条规则。发现物只带规则名、命中的关键词 / 正则原文与标题 / 正文行号，不回传命中的正文片段。

动作目录可通过 `GET /api/v1/workspaces/{wid}/pipelines/checks` 获取（含参数 schema），前端编辑抽屉据此提供插入辅助。

## 4. 完整示例

### 4.1 库存质量巡检（手动 + 事件 + 定时）

```yaml
name: 库存质量巡检
on:
  manual: true
  events: [record.updated, sync.finished]
  schedule: "0 9 * * *"
vars:
  null_limit: 0.02
  is_sync: ${{ on.event == 'sync.finished' }}
jobs:
  空值与时效:
    steps:
      - uses: table/null-rate
        with:
          table: 商品库存
          fields: [商品名称, 库存数量]
          max_rate: ${{ vars.null_limit }}
        severity: error
      - uses: table/stale
        with:
          table: 商品库存
          field: 更新时间
          max_age_days: 3
  一致性与区间:
    needs: [空值与时效]
    if: ${{ !vars.is_sync || on.status == 'success' }}
    steps:
      - uses: table/duplicates
        with:
          table: 商品库存
          fields: [商品编码]
          ignore_case: true
          ignore_whitespace: true
      - uses: table/value-range
        with:
          table: 商品库存
          fields: [售价]
          min: "0"
          max: "99999"
        continue-on-error: true
```

要点：

- `空值与时效` 产出 `error` 级空值发现时 job 失败，下游 `一致性与区间` 跳过；
- `一致性与区间` 只在非同步事件或同步成功时执行，避免同步失败时重复告警；
- 区间检查失败不阻断 job（`continue-on-error: true`），运行结论仍因存在发现物为 `partial`。

### 4.2 文档体检（保存即检查）

```yaml
name: 文档体检
on:
  manual: true
  events: [document.saved]
jobs:
  链接:
    steps:
      - uses: document/links
  引用:
    needs: 链接
    steps:
      - uses: document/broken-refs
        with:
          scopes: [table, chart, file]
  图表块:
    needs: 链接
    steps:
      - uses: document/chart-blocks
        with:
          max_blocks: 30
          max_block_bytes: 32768
```

文档正文每次保存后触发；同一文档连续保存时，若上一次运行仍在执行，本轮事件触发会被单飞语义静默跳过。

### 4.3 同步完成后的针对性校验

```yaml
name: 同步后数据校验
on:
  events: [sync.finished]
jobs:
  同步表空值:
    if: ${{ on.status == 'success' }}
    steps:
      - uses: table/null-rate
        with:
          table: 销售明细
          fields: [订单号, 金额]
          max_rate: 0
  失败不检查:
    if: ${{ on.status != 'success' }}
    steps:
      - uses: table/null-rate
        with:
          table: 销售明细
          fields: [订单号]
          max_rate: 0
```

### 4.4 仅定时触发的周报前检查

```yaml
name: 周一开盘前检查
on:
  manual: false
  schedule: "0 9 * * 1"
jobs:
  基础质量:
    steps:
      - uses: table/null-rate
        with:
          table: 股票日线
          fields: [代码, 收盘价]
          max_rate: 0.01
      - uses: table/stale
        with:
          table: 股票日线
          field: 交易日期
          max_age_days: 1
```

### 4.5 客户主数据清洗前体检（判重 + 全字段空值）

```yaml
name: 客户主数据体检
on:
  manual: true
  events: [record.updated]
jobs:
  判重:
    steps:
      - uses: table/duplicates
        with:
          table: 客户主数据
          fields: [手机号]
          ignore_case: true
          ignore_whitespace: true
        severity: error
  空值:
    needs: 判重
    steps:
      - uses: table/null-rate
        with:
          table: 客户主数据
          fields: all
          max_rate: 0.1
```

要点：

- 判重键（手机号）大小写与首尾空白不敏感，`张三 ` 与 `张三` 视为重复；
- 判重 `severity: error`，发现重复即 job 失败，空值检查被跳过（清洗前先解决源头）；
- `fields: all` 覆盖整表，适合清洗前一次性摸底；日常巡检建议收敛到关键字段。

### 4.6 数值与日期区间（字段口径校验）

```yaml
name: 订单字段口径校验
on:
  schedule: "30 7 * * *"
jobs:
  区间:
    steps:
      - uses: table/value-range
        with:
          table: 销售明细
          fields: [金额, 数量]
          min: "0"
      - uses: table/value-range
        with:
          table: 销售明细
          fields: [下单日期]
          min: "2024-01-01"
```

要点：

- `min` / `max` 声明为字符串，必须带引号（见 2.4 节）；
- 数值列按数值比较，`date` 列按 ISO 日期比较，`timestamp` 列支持整数秒或 ISO 时间；
- 只写 `min` 不写 `max` 合法（至少提供其一），适合「不允许负数」这类单边口径；
- 越界只统计行数，定位信息在发现物 `locator.field_name`，不含具体值。

### 4.7 按触发上下文分流（记录变更事件）

```yaml
name: 变更后抽检
on:
  events: [record.updated]
vars:
  is_delete: ${{ on.action == 'delete' }}
  is_stock: ${{ startswith(on.table_name, '商品') }}
jobs:
  删行后全量抽检:
    if: ${{ vars.is_delete && vars.is_stock }}
    steps:
      - uses: table/null-rate
        with:
          table: 商品库存
          fields: [商品编码, 库存数量]
  大批量变更后判重:
    if: ${{ len(on.row_ids) >= 100 }}
    steps:
      - uses: table/duplicates
        with:
          table: 商品库存
          fields: [商品编码]
```

要点：

- `on.table_id` / `on.table_name` / `on.action` / `on.row_ids` / `on.count` 来自触发上下文（见 2.1 节）；
- 删行往往破坏引用完整性，适合触发更严格的抽检；大批量变更（`len(on.row_ids)`）才值得跑判重，避免逐行编辑时反复扫描。

### 4.8 上下游结论联动（`jobs.<id>.conclusion`）

```yaml
name: 两级体检
on:
  manual: true
jobs:
  基础体检:
    steps:
      - uses: table/null-rate
        with:
          table: 销售明细
          fields: [订单号]
          max_rate: 0
  深度体检:
    needs: 基础体检
    if: ${{ jobs.基础体检.conclusion == 'success' }}
    steps:
      - uses: table/duplicates
        with:
          table: 销售明细
          fields: [订单号]
  复检:
    needs: 基础体检
    if: ${{ jobs.基础体检.conclusion != 'success' }}
    steps:
      - uses: document/broken-refs
```

要点：

- `conclusion` 取值 `success` / `failed` / `skipped`；
- 基础体检失败时，深度体检被 `skipped`（`needs` 默认语义），也可像 `复检` 一样用 `!= 'success'` 显式订阅失败分支；
- 深度检查（判重扫描成本高）放在基础检查之后，避免基础口径已破时浪费扫描。

### 4.9 信息级巡检（`severity: info` + `continue-on-error`）

```yaml
name: 新鲜度巡检
on:
  schedule: "0 8 * * *"
jobs:
  巡检:
    steps:
      - uses: table/stale
        with:
          table: 股票日线
          field: 交易日期
          max_age_days: 5
        severity: info
        continue-on-error: true
      - uses: document/links
        severity: info
```

要点：

- 纯提醒类检查（数据不是最新、链接偶发失效）用 `severity: info`，运行结论保持 `partial` 而不是 `failed`，不污染「失败」口径；
- `continue-on-error: true` 双保险：即使检查本身产出 `error` 级发现也不阻断 job；
- 巡检类定义与门禁类定义建议拆成两条流水线，分别设定时频率与严重度。

### 4.10 数据表 + 文档混合巡检

```yaml
name: 工作区综合巡检
on:
  manual: true
  schedule: "0 6 * * 1"
vars:
  warn_rate: 0.05
jobs:
  数据表:
    steps:
      - uses: table/null-rate
        with:
          table: 商品库存
          max_rate: ${{ vars.warn_rate }}
      - uses: table/stale
        with:
          table: 商品库存
          field: 更新时间
          max_age_days: 7
  文档:
    steps:
      - uses: document/links
      - uses: document/broken-refs
        with:
          scopes: [table, chart, file]
      - uses: document/chart-blocks
        with:
          max_blocks: 40
```

要点：

- 数据表检查与文档检查共用同一套 run / finding 模型，一个工作区一条巡检即可覆盖全部内容物；
- 无 `needs` 时两个 job 并列执行，互不阻断；结论取全部 job 的最差口径；
- `chart-blocks` 的上限可覆盖文档编辑器默认值（此处放宽到 40 块），用于承接已人工确认的超限文档。

### 4.11 文档敏感内容巡检（关键词 + 正则 + 逻辑组合）

```yaml
name: 文档敏感内容巡检
on:
  manual: true
  events: [document.saved]
jobs:
  敏感内容:
    steps:
      - uses: document/sensitive
        with:
          rules:
            - name: 身份证号
              patterns: ['\b\d{17}[\dXx]\b']
            - name: 邮箱地址
              patterns: ['\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b']
            - name: 内部资料
              keywords: [内部资料, 内部底价, 商业机密, 仅限内部]
          logic: 身份证号 or 邮箱地址 or 内部资料
        severity: warn
```

示例工作区中「客户资料交接（敏感内容示例）」一文含虚构身份证号、邮箱与内部资料标记，运行后应产出 3 条发现；其余文档为对照组不产出发现。

要点：

- **规则命中口径**：一条规则内「任一关键词或正则命中」即算该规则命中；关键词不区分大小写，正则用 Python `re`（`(?i)` 可忽略大小写）。
- **逻辑组合**：`logic: any`（默认，任一规则命中）/ `logic: all`（全部规则命中）/ 布尔表达式（`and` / `or` / `not` / 括号，也支持 `&&` / `||` / `!`），例如 `身份证号 and (内部资料 or 邮箱地址)`；未被表达式引用的规则只参与计算、不产出发现物。
- **简写**：顶层 `keywords` / `patterns` 会合并为名为 `default` 的隐式规则，可与 `rules` 混用（`logic` 里用 `default` 引用）。
- **定位与展示**：发现物带规则名、命中的关键词 / 正则原文、`field`（title / content）、文档标题、正文行号，以及命中行前后各 80 字符、最长 240 字符的有界上下文片段（前端按高亮渲染，形如 GitHub 注解）；不返回整篇正文。文档对当前查看者不可见（他人草稿 / 归档）时，接口会裁剪上下文并标记 `redacted`。规则名不能含空白 / 括号，单次最多 50 条规则。
- **校验时机**：规则结构、正则语法与 `logic` 表达式在运行期进入检查时校验（配置错误记为该 step 失败），保存期只校验 JSON 类型；表达式里引用不存在的规则会给出可用规则名。

## 5. 最佳实践

1. **阈值收口到 `vars`**：`max_rate` / `max_age_days` 等阈值统一在 `vars` 声明，多个 step 引用同一变量，调整口径只改一处。
2. **区分门禁与巡检**：阻断性口径（脏数据必须处理）用 `severity: error`；提醒性口径用 `warn` / `info`。运行结论 `failed` 只留给前者，避免告警疲劳。
3. **控制事件触发频率**：高频写路径（`document.saved` / 逐行 `record.updated`）搭配单飞语义会静默丢弃并发触发，建议改为 `schedule` 定时巡检，或用 `if` 表达式按 `on.action` / `len(on.row_ids)` 收窄触发面。
4. **发现物排查路径**：发现物只带字段名 / 行 ID / 计数 / 阈值（不带单元格值），按 `locator` 的行 ID 回表查具体数据；`detail.truncated=true` 表示扫描达上限按采样执行，结论可能不完整。
5. **发现物转 Issue**：`table` 目标的发现物可在运行详情一键转为目标表的 Issue（标题取严重度 + 消息，类别 `data_error`），需要目标表读权限；文档 / 字段目标暂不支持。
6. **扫描成本预算**：判重与全字段空值率是最重的两类检查；大表优先收敛 `fields`，或把重检查放到低频定时流水线（如每周）。
7. **表达式容错**：运行期表达式求值失败按 `false`（`if`）或 `null`（`with`）处理并记入 `stats.warnings`，保存前用纯校验接口确认表达式拼写，避免静默跳过。

## 6. 校验错误与排查

保存 / 校验接口返回中文错误信息，常见类型：

| 错误 | 原因 | 修正 |
|---|---|---|
| `顶层存在未知键：...` | 多写了顶层键 | 只保留 `name` / `on` / `vars` / `jobs` |
| `jobs 必须是非空映射` | `jobs` 缺失或为空 | 至少声明一个 job |
| `jobs.<id> 依赖不存在的 job` / `存在环` | `needs` 写错或成环 | 修正依赖或删掉环路 |
| `未知检查动作：...` | `uses` 拼错或动作未注册 | 对照第 3 节目录或 `/pipelines/checks` |
| `... 缺少必填参数` / `不支持参数` / `类型不匹配` | `with` 与动作 schema 不符 | 对照目录参数；字符串阈值加引号 |
| `jobs.<id>.if 必须写成 ${{ ... }} 表达式` | `if` 未包裹表达式 | 改为 `if: ${{ ... }}` |
| `表达式使用了不支持的函数` / 语法错误 | 超出白名单子集 | 只用第 2.2 节列出的函数与运算符 |
| `DSL 缺少 name` | 顶层未写 `name` 且记录名为空 | 补 `name` |
| `同名流水线已存在` | 工作区内定义名重复 | 改名 |

运行期排查顺序：

1. 运行详情页的 job / step 结论树：先看哪个 step `failed` 与 `error` 字段；
2. `stats.warnings`：表达式求值失败、事件触发时的降级信息；
3. 发现物分页：按严重度 / 目标类型 / 检查动作过滤；
4. 定时触发：`cndb pipeline tick --json` 查看 `examined / executed / failed / skipped_conflict`；
5. 权限：手动运行需工作区 `editor`，查看运行与发现物需 `viewer`；表目标发现物转问题还需目标表读权限。

## 7. 相关文档

- [ADR 0076：流水线检查系统与专用 DSL](adr/0076-pipeline-check-dsl.md)
- [需求卡片 0076](requirements/0076-pipeline-check-dsl.md)
- [部署与定时任务](DEPLOY_TENCENT.md)
