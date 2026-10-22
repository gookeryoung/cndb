/** 大模型提示词任务 —— 5 组典型场景的推荐用户提示词.
 *
 * 设计口径（ADR 0019 P2）：
 * - 只描述业务任务，不依赖任何具体数据源；API 地址 / 模型 / API Key 由工作区级
 *   「大模型连接」统一提供，任务里不再填写；
 * - prompt 必须强制模型只输出 JSON（对象数组，或 `{"rows": [...]}` 包裹），
 *   字段名统一用英文 snake_case，并带稳定键方便后端推导幂等键；
 * - `{today}` 由运行时注入，其余花括号是 JSON 字面量，须按后端模板语法写成
 *   `{{` / `}}`（运行时还原为 `{` / `}`），否则保存时会被模板校验拦下。
 *
 * 后端模板语法见 `src/cndb/plugins/datasource/providers/template.py`。
 */

export interface LlmPromptPreset {
  /** 稳定 id（列表 key / 测试定位） */
  id: string
  /** 场景名称 */
  name: string
  /** 适用场景说明（含输出格式口径） */
  description: string
  /** 建议的目标表字段（英文 snake_case） */
  target_fields: string[]
  /** 建议的幂等键（须是 target_fields 子集） */
  match_keys: string[]
  /** 用户提示词模板（可含 `{today}`） */
  prompt: string
}

export const LLM_PROMPT_PRESETS: LlmPromptPreset[] = [
  {
    id: 'daily_news',
    name: '每日新闻摘要',
    description: '每天汇总国内要闻 / 财经 / 科技三个板块的重点新闻，按 date + category + title 去重，适合做资讯看板。输出对象数组（或 rows 包裹对象）。',
    target_fields: ['date', 'category', 'title', 'summary', 'source', 'url', 'importance'],
    match_keys: ['date', 'category', 'title'],
    prompt: [
      '请汇总 {today} 的每日新闻摘要，覆盖国内要闻、财经、科技三个板块。',
      '每个板块挑选最重要的 3-5 条，按重要度从高到低排列；每条给出一句话摘要（不超过 120 字）。',
      '字段要求（全部使用英文 snake_case）：date（日期 YYYY-MM-DD）、category（板块）、title（标题）、summary（摘要）、source（来源媒体）、url（原文链接）、importance（重要度 1-5 的整数）。',
      '同一天同一板块下的标题应稳定，date + category + title 组合用于去重。',
      '只输出 JSON：一个行对象数组；如需包裹，使用 {{"rows": [行对象, ...]}}。不要输出 Markdown 代码围栏或任何解释文字。',
    ].join('\n'),
  },
  {
    id: 'city_weather',
    name: '城市天气预报',
    description: '按城市 + 日期生成当天及未来两天的天气预报，适合天气日报表；date + city 即天然幂等键。输出对象数组（或 rows 包裹对象）。',
    target_fields: ['date', 'city', 'weather', 'temp_high', 'temp_low', 'precip_prob', 'wind', 'aqi_level'],
    match_keys: ['date', 'city'],
    prompt: [
      '请生成城市天气预报，基准日期：{today}。默认覆盖北京、上海、广州、深圳；若指定了城市列表，以指定城市为准。',
      '每个城市给出当天及未来 2 天（共 3 天）的预报：白天/夜间天气现象、最高/最低气温、降水概率、风向风力、空气质量等级。',
      '字段要求（全部使用英文 snake_case）：date（预报日期 YYYY-MM-DD）、city（城市名）、weather（天气现象）、temp_high（最高气温，摄氏度整数）、temp_low（最低气温）、precip_prob（降水概率 0-100 的整数）、wind（风向风力）、aqi_level（空气质量等级）。',
      '同一城市同一日期只能有一条记录，date + city 为稳定键。',
      '只输出 JSON：一个行对象数组；如需包裹，使用 {{"rows": [行对象, ...]}}。不要输出 Markdown 代码围栏或解释文字。',
    ].join('\n'),
  },
  {
    id: 'market_snapshot',
    name: '股票 / 基金行情快照',
    description: '抓取指定标的的收盘行情快照（价格 / 涨跌幅 / 成交量），trade_date + symbol 去重，适合行情日表与趋势分析。输出对象数组（或 rows 包裹对象）。',
    target_fields: ['trade_date', 'symbol', 'name', 'close', 'change_pct', 'volume', 'amount', 'turnover_rate'],
    match_keys: ['trade_date', 'symbol'],
    prompt: [
      '请整理 {today} 的股票 / 基金行情收盘快照。默认覆盖沪深 300 成分股中市值前 10 的标的；若指定了代码列表，以指定列表为准。',
      '每个标的给出：证券代码、证券名称、收盘价、涨跌幅、成交量、成交额、换手率。',
      '字段要求（全部使用英文 snake_case）：trade_date（交易日 YYYY-MM-DD）、symbol（证券代码）、name（证券名称）、close（收盘价，元）、change_pct（涨跌幅百分比，1.23 表示 +1.23%）、volume（成交量，股）、amount（成交额，元）、turnover_rate（换手率百分比）。',
      '同一标的同一交易日只能有一条记录，trade_date + symbol 为稳定键。',
      '只输出 JSON：一个行对象数组；如需包裹，使用 {{"rows": [行对象, ...]}}。不要输出 Markdown 代码围栏或解释文字。',
    ].join('\n'),
  },
  {
    id: 'ecommerce_price',
    name: '电商竞品价格监控',
    description: '按平台 + 商品监控竞品售价与促销信息，date + platform + product_id 去重，适合价格波动看板与调价提醒。输出对象数组（或 rows 包裹对象）。',
    target_fields: ['date', 'platform', 'product_id', 'title', 'price', 'list_price', 'promotion', 'sales'],
    match_keys: ['date', 'platform', 'product_id'],
    prompt: [
      '请监控 {today} 的电商竞品价格。默认覆盖 3 个主要竞品，可替换为指定商品 ID / 链接列表。',
      '每个竞品给出：平台、平台商品 ID、商品标题、当前售价、划线价、优惠信息、销量。',
      '字段要求（全部使用英文 snake_case）：date（抓取日期 YYYY-MM-DD）、platform（平台，如 jd / taobao）、product_id（平台商品 ID）、title（商品标题）、price（当前售价，元）、list_price（划线价，元）、promotion（优惠信息，无则空字符串）、sales（销量，整数）。',
      '同一平台同一商品同一日期只能有一条记录，date + platform + product_id 为稳定键。',
      '只输出 JSON：一个行对象数组；如需包裹，使用 {{"rows": [行对象, ...]}}。不要输出 Markdown 代码围栏或解释文字。',
    ].join('\n'),
  },
  {
    id: 'policy_tracker',
    name: '行业政策公告跟踪',
    description: '跟踪部委 / 地方 / 行业协会发布的政策公告，date + agency + title 去重，适合政策台账与合规提醒。输出对象数组（或 rows 包裹对象）。',
    target_fields: ['date', 'agency', 'title', 'summary', 'policy_type', 'effective_date', 'url'],
    match_keys: ['date', 'agency', 'title'],
    prompt: [
      '请跟踪 {today} 发布的行业政策与监管公告，覆盖国家部委、地方主管部门和行业协会官网。',
      '每条记录给出：发布日期、发文机构、政策标题、政策摘要（不超过 200 字）、政策类型、生效日期、原文链接。',
      '字段要求（全部使用英文 snake_case）：date（发布日期 YYYY-MM-DD）、agency（发文机构）、title（政策标题）、summary（摘要）、policy_type（政策类型：通知 / 征求意见 / 办法 / 规划等）、effective_date（生效日期 YYYY-MM-DD，暂无则空字符串）、url（原文链接）。',
      '同一机构同一日期同一标题只能有一条记录，date + agency + title 为稳定键。',
      '只输出 JSON：一个行对象数组；如需包裹，使用 {{"rows": [行对象, ...]}}。不要输出 Markdown 代码围栏或解释文字。',
    ].join('\n'),
  },
]
