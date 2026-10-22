/** 大模型提示词任务 —— 8 组典型场景的推荐用户提示词（首批 5 组 + 2026-10-22 追加 3 组：商业航天 / 美食做法 / 国际形势）.
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
    description: '每天汇总国内要闻 / 财经 / 科技三个板块的重点新闻，按 date + category + title 去重，适合做资讯看板。基于已有公开信息整理，不因无法联网返回空。输出对象数组（或 rows 包裹对象）。',
    target_fields: ['date', 'category', 'title', 'summary', 'source', 'url', 'importance'],
    match_keys: ['date', 'category', 'title'],
    prompt: [
      '请基于你已掌握的近期公开信息，汇总 {today} 前后的每日新闻摘要，覆盖国内要闻、财经、科技三个板块。',
      '每个板块挑选最重要的 3-5 条，按重要度从高到低排列；每条给出一句话摘要（不超过 120 字）。',
      '字段要求（全部使用英文 snake_case）：date（日期 YYYY-MM-DD）、category（板块）、title（标题）、summary（摘要）、source（来源媒体）、url（原文链接）、importance（重要度 1-5 的整数）。',
      'source 无法确认具体媒体时写「综合整理」；url 无法确认时用空字符串，不要编造链接；不要因为无法联网就返回空数组。',
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
      '天气属于实时预报：无法确认的气温 / 降水概率用 null，无法确认的天气现象与空气质量标注「综合整理」，不要返回空数组。',
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
      '行情属于实时数据：无法确认的最新价格 / 涨跌幅用 null 或标注「综合整理」，不要编造精确数字，也不要返回空数组。',
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
      '价格属于实时数据：无法确认的最新售价 / 销量标注「综合整理」或用空字符串，不要编造精确数字，也不要返回空数组。',
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
      '政策公告属于实时信息：无法确认的最新公告日期 / 原文请标注「综合整理」、url 用空字符串，不要编造链接，也不要返回空数组。',
      '只输出 JSON：一个行对象数组；如需包裹，使用 {{"rows": [行对象, ...]}}。不要输出 Markdown 代码围栏或解释文字。',
    ].join('\n'),
  },
  {
    id: 'commercial_aerospace',
    name: '商业航天新闻动态',
    description: '跟踪商业航天公司的发射、融资、政策与订单动态，date + company + title 去重，适合行业情报看板。输出对象数组（或 rows 包裹对象）。',
    target_fields: ['date', 'company', 'event_type', 'title', 'summary', 'source', 'url', 'importance'],
    match_keys: ['date', 'company', 'title'],
    prompt: [
      '请汇总 {today} 商业航天领域的新闻动态，覆盖国内外主要商业航天公司（如 SpaceX、Blue Origin、Rocket Lab、蓝箭航天、星际荣耀、星河动力等）以及监管机构与发射场。',
      '重点收集：发射任务与结果、融资与并购、政策与监管、订单与合作协议、关键技术进展；同一天同一公司同一标题只保留一条。',
      '字段要求（全部使用英文 snake_case）：date（日期 YYYY-MM-DD）、company（公司或机构）、event_type（事件类型：发射/融资/政策/订单/技术）、title（标题）、summary（一句话摘要，不超过 150 字）、source（来源媒体）、url（原文链接）、importance（重要度 1-5 的整数）。',
      '同一天同一公司同一标题只能有一条记录，date + company + title 为稳定键。',
      '新闻属于实时信息：无法确认的日期 / 来源标注「综合整理」、url 用空字符串，不要编造链接，也不要返回空数组。',
      '只输出 JSON：一个行对象数组；如需包裹，使用 {{"rows": [行对象, ...]}}。不要输出 Markdown 代码围栏或解释文字。',
    ].join('\n'),
  },
  {
    id: 'food_recipes',
    name: '美食推荐做法',
    description: '按菜名 + 菜系整理家庭可操作的美食做法，适合菜谱库与每日菜单推荐；dish_name + cuisine 即天然幂等键。输出对象数组（或 rows 包裹对象）。',
    target_fields: ['dish_name', 'cuisine', 'difficulty', 'cook_time_min', 'ingredients', 'steps', 'tips'],
    match_keys: ['dish_name', 'cuisine'],
    prompt: [
      '请推荐 {today} 适合家庭制作的美食做法，覆盖家常菜、汤羹、主食、甜点四类，每类 2 道，共 8 道，优先当季食材。',
      '每道菜给出：菜名、菜系、难度、烹饪时长、主要食材、分步做法、关键小贴士。',
      '控制输出规模：每道菜的 ingredients 不超过 6 种主要食材；steps 用编号与分号分隔，每步不超过 60 字；tips 一句话即可，避免输出过长被截断。',
      '字段要求（全部使用英文 snake_case）：dish_name（菜名）、cuisine（菜系，如 川菜/粤菜/西餐）、difficulty（难度：简单/中等/困难）、cook_time_min（烹饪时长，分钟，整数）、ingredients（主要食材，用顿号分隔的文本）、steps（分步做法，用编号与分号分隔的文本）、tips（关键小贴士，无则空字符串）。',
      '同一菜名同一菜系只能有一条记录，dish_name + cuisine 为稳定键；不要返回空数组。',
      '只输出 JSON：一个行对象数组；如需包裹，使用 {{"rows": [行对象, ...]}}。不要输出 Markdown 代码围栏或解释文字。',
    ].join('\n'),
  },
  {
    id: 'global_affairs',
    name: '国际形势发展动态',
    description: '梳理大国关系、地区冲突、全球经济与多边机制等国际动态，date + region + title 去重，适合形势研判与每日晨报。输出对象数组（或 rows 包裹对象）。',
    target_fields: ['date', 'region', 'topic', 'title', 'summary', 'source', 'url', 'trend'],
    match_keys: ['date', 'region', 'title'],
    prompt: [
      '请梳理 {today} 的国际形势发展动态，覆盖大国关系、地区冲突、全球经济与贸易、多边机制与外交活动等主题，覆盖主要地区（亚太、欧洲、中东、北美、非洲、拉美）。',
      '每条记录给出：日期、地区/国家、主题、标题、摘要、来源、原文链接、趋势判断。',
      '字段要求（全部使用英文 snake_case）：date（日期 YYYY-MM-DD）、region（地区或国家）、topic（主题分类）、title（标题）、summary（摘要，不超过 150 字）、source（来源媒体）、url（原文链接）、trend（趋势判断：缓和/升温/僵持/不确定）。',
      '同一天同一地区同一标题只能有一条记录，date + region + title 为稳定键。',
      '形势动态属于实时信息：无法确认的摘要 / 来源标注「综合整理」、url 用空字符串，不要编造链接，也不要返回空数组。',
      '只输出 JSON：一个行对象数组；如需包裹，使用 {{"rows": [行对象, ...]}}。不要输出 Markdown 代码围栏或解释文字。',
    ].join('\n'),
  },
]
