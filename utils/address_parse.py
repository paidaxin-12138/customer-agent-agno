"""从买家消息解析改址所需字段。"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class AddressParseLevel(str, Enum):
    NONE = "none"
    PARTIAL = "partial"
    COMPLETE = "complete"


@dataclass
class ParsedAddress:
    name: str = ""
    mobile: str = ""
    province: str = ""
    city: str = ""
    district: str = ""
    detail: str = ""
    full_text: str = ""

    def summary(self) -> str:
        parts = [self.province, self.city, self.district, self.detail]
        body = "".join(p for p in parts if p)
        tail = f" {self.name} {self.mobile}".strip()
        return (body + " " + tail).strip() or self.full_text


_MOBILE_RE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
_NAME_BEFORE_MOBILE = re.compile(
    r"([\u4e00-\u9fa5A-Za-z·]{2,20})\s*[,，]?\s*(1[3-9]\d{9})"
)
_REGION_RE = re.compile(
    r"([\u4e00-\u9fa5]{2,8}(?:省|自治区|特别行政区))?"
    r"([\u4e00-\u9fa5]{2,8}(?:市|自治州|地区|盟))?"
    r"([\u4e00-\u9fa5]{2,8}(?:区|县|市|旗))?"
)


def parse_address_from_text(text: str) -> ParsedAddress:
    raw = (text or "").strip()
    parsed = ParsedAddress(full_text=raw)
    if not raw:
        return parsed

    m = _MOBILE_RE.search(raw)
    if m:
        parsed.mobile = m.group(1)

    nm = _NAME_BEFORE_MOBILE.search(raw)
    if nm:
        parsed.name = nm.group(1).strip()

    rm = None
    for m in _REGION_RE.finditer(raw):
        if any(g for g in m.groups() if g):
            rm = m
            break
    if rm:
        parsed.province = (rm.group(1) or "").strip()
        parsed.city = (rm.group(2) or "").strip()
        parsed.district = (rm.group(3) or "").strip()
        end = rm.end()
        rest = raw[end:].strip(" ,，;；\n\t")
        rest = _MOBILE_RE.sub("", rest).strip(" ,，;；")
        if parsed.name and rest.endswith(parsed.name):
            rest = rest[: -len(parsed.name)].strip(" ,，;；")
        if rest:
            parsed.detail = rest

    if not parsed.detail:
        without_mobile = _MOBILE_RE.sub("", raw).strip(" ,，;；")
        if parsed.name:
            without_mobile = without_mobile.replace(parsed.name, "").strip(" ,，;；")
        if without_mobile and without_mobile != parsed.name:
            parsed.detail = without_mobile

    return parsed


def address_parse_level(parsed: ParsedAddress) -> AddressParseLevel:
    if not parsed.full_text.strip():
        return AddressParseLevel.NONE

    has_mobile = bool(parsed.mobile)
    has_region = bool(parsed.province or parsed.city or parsed.district)
    has_detail = bool(parsed.detail and len(parsed.detail) >= 4)
    has_name = bool(parsed.name)

    if has_mobile and has_region and has_detail and has_name:
        return AddressParseLevel.COMPLETE
    if has_mobile or has_region or has_detail or has_name:
        return AddressParseLevel.PARTIAL
    return AddressParseLevel.NONE


def is_address_change_intent(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    phrases = (
        "改收件人",
        "修改收件人",
        "换收件人",
        "改收货人",
        "修改收货人",
        "改电话",
        "改手机",
        "改手机号",
        "修改电话",
        "修改手机",
        "修改手机号",
        "改收货地址",
        "修改收货地址",
        "换收货地址",
        "更改地址",
        "换地址",
        "修改地址",
        "改地址",
        "收货地址",
        "详细地址",
        "修改订单",
        "改订单",
        "修改订单信息",
        "收货信息",
        "联系地址",
        "收件信息",
    )
    return any(p in t for p in phrases)
