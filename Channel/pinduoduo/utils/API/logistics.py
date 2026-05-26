"""拼多多物流轨迹查询。

文档：https://open.pinduoduo.com/application/document/api?id=pdd.logistics.ordertrace.get
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .open_platform_client import OpenPlatformAPI


class LogisticsManager(OpenPlatformAPI):
    """物流相关开放平台接口。"""

    def get_order_trace(self, order_sn: str) -> Optional[Dict[str, Any]]:
        """查询订单物流轨迹（需订单号 order_sn）。"""
        order_sn = (order_sn or "").strip()
        if not order_sn:
            return None
        params: Dict[str, Any] = {
            "type": "pdd.logistics.ordertrace.get",
            "order_sn": order_sn,
        }
        return self._call_open_platform(params)


def format_order_trace_reply(order_sn: str, raw: Optional[Dict[str, Any]]) -> str:
    """将接口返回格式化为买家可读文案。"""
    if raw is None:
        return (
            "亲，物流查询暂时不可用，请稍后再试或联系人工客服。"
            "（请确认已在 config.json 中配置拼多多开放平台 pinduoduo_open）"
        )

    err = raw.get("error_response")
    if err and isinstance(err, dict):
        msg = err.get("error_msg") or err.get("sub_msg") or "接口错误"
        code = err.get("error_code") or err.get("code") or ""
        tail = f"（{code}）" if code else ""
        return f"亲，暂时查不到物流信息：{msg}{tail}。如有疑问可联系人工客服帮您核实订单号是否正确。"

    # 响应节点名随接口版本可能变化，做宽松解析
    body = raw
    for key in (
        "logistics_order_trace_get_response",
        "order_trace_get_response",
        "logistics_order_trace_response",
    ):
        if key in raw and isinstance(raw[key], dict):
            body = raw[key]
            break

    traces = _extract_trace_list(body)
    if not traces:
        # 无结构化轨迹时退回简短 JSON 摘要（避免空白）
        summary = _summarize_trace_dict(body)
        if summary:
            return f"订单 {order_sn} 物流信息：\n{summary}"
        return (
            f"亲，已提交查询订单「{order_sn}」，暂未解析到轨迹明细。"
            "请在拼多多订单详情查看物流，或发订单号让人工帮您核对。"
        )

    lines: List[str] = [f"订单 {order_sn} 物流轨迹："]
    for item in traces[:30]:
        if isinstance(item, dict):
            t = item.get("action_time") or item.get("time") or item.get("trace_time") or ""
            desc = (
                item.get("action_desc")
                or item.get("desc")
                or item.get("status_desc")
                or item.get("remark")
                or ""
            )
            extra = item.get("shipping_name") or item.get("tracking_number") or ""
            seg = " ".join(x for x in (str(t).strip(), str(desc).strip(), str(extra).strip()) if x)
            if seg:
                lines.append(f"- {seg}")
        else:
            lines.append(f"- {item}")
    return "\n".join(lines)


def _extract_trace_list(body: Dict[str, Any]) -> List[Any]:
    for key in (
        "trace_list",
        "logistics_trace_list",
        "traces",
        "track_list",
        "track_info_list",
        "list",
    ):
        val = body.get(key)
        if isinstance(val, list) and val:
            return val
    return []


def _summarize_trace_dict(d: Dict[str, Any], depth: int = 0) -> str:
    if depth > 4:
        return ""
    parts: List[str] = []
    for k, v in d.items():
        if k in ("trace_list", "logistics_trace_list", "traces") and isinstance(v, list):
            continue
        if isinstance(v, (str, int, float)) and str(v).strip():
            parts.append(f"{k}: {v}")
        elif isinstance(v, dict):
            inner = _summarize_trace_dict(v, depth + 1)
            if inner:
                parts.append(inner)
    return "\n".join(parts[:12])
