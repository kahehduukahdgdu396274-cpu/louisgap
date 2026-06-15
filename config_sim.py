# ==================== 模拟盘专用配置（禁止修改） ====================
SIMULATED_TRADING = True

# REST Base URL
REST_BASE_URL = "https://openapi.okx.com"

# WS 地址
WS_PUBLIC = "wss://wspap.okx.com:8443/ws/v5/public"
WS_PRIVATE = "wss://wspap.okx.com:8443/ws/v5/private"
WS_BUSINESS = "wss://wspap.okx.com:8443/ws/v5/business"

# 模拟盘Header
SIMULATED_HEADER = {"x-simulated-trading": "1"}

print("✅ 已加载模拟盘专用配置")
