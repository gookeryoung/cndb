"""微信小程序登录认证插件.

通过 code → openid 换取微信身份，自动关联或创建 cndb User，
统一签发 JWT access_token（复用 accounts 插件的 token 格式）.
"""
