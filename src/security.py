from __future__ import annotations

DANGEROUS_PATTERNS = (
    "启动广告",
    "开启广告",
    "暂停广告",
    "关掉广告",
    "停掉广告",
    "改预算",
    "提高预算",
    "降低预算",
    "新建广告",
    "创建广告",
    "删除广告",
    "修改广告",
    "发布广告",
    "投放广告",
    "改折扣",
    "修改折扣",
    "改产品",
    "修改产品",
    "删除产品",
    "改主题",
    "修改主题",
    "改导航",
    "修改导航",
    "发真实订单",
    "下真实订单",
    "补发purchase",
    "补发 purchase",
)

REJECTION_MARKDOWN = (
    "⚠️ 这个命令属于 DingTalk MVP 的高风险操作范围，已拦截。\n\n"
    "当前 DingTalk 网关只允许读取分析、生成本地报告和低风险日志写入。"
    "涉及广告启停/预算/创建、店铺产品/折扣/主题/导航、订单或 purchase 回传的操作，"
    "请回到 Codex CLI 主会话里手动执行，并进行明确确认。"
)


def normalize_text(text: str) -> str:
    return " ".join((text or "").strip().split())


def find_dangerous_pattern(text: str) -> str | None:
    lowered = normalize_text(text).lower()
    for pattern in DANGEROUS_PATTERNS:
        if pattern.lower() in lowered:
            return pattern
    return None
