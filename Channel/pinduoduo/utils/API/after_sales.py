"""拼多多售后处理 API 模块。

实现 AI 客服自动处理退货退款申请。
参考：https://open.pinduoduo.com/application/document/api?id=pdd.refund.returngoods.agree
"""

from __future__ import annotations

from typing import Dict, Any, Optional, List
from .open_platform_client import OpenPlatformAPI


class AfterSalesManager(OpenPlatformAPI):
    """拼多多售后管理器。
    
    支持功能：
    - 同意/拒绝退货退款申请
    - 查询售后单状态
    - 批量处理售后
    - 自动识别售后场景
    """
    
    def __init__(self, shop_id: str, user_id: str, channel_name: str = "pinduoduo"):
        super().__init__(shop_id, user_id, channel_name)
        
        # 售后相关 API
        self.api_methods = {
            'agree_refund': 'pdd.refund.returngoods.agree',  # 同意退货退款
            'reject_refund': 'pdd.refund.returngoods.reject',  # 拒绝退货退款
            'query_status': 'pdd.after.sale.status.get',  # 查询售后状态
            'list_orders': 'pdd.after.sale.list.order.get',  # 获取售后单列表
            'limit_info': 'pdd.after.sale.limit.info.get',  # 售后限额查询
        }
    
    def agree_return_goods(self, after_sale_id: str, refund_amount: float, 
                          remark: str = "") -> Dict[str, Any]:
        """同意退货退款申请。
        
        Args:
            after_sale_id: 售后单号
            refund_amount: 退款金额（单位：分）
            remark: 备注信息
            
        Returns:
            {
                "success": bool,
                "message": str,
                "after_sale_id": str
            }
        """
        params = {
            "type": self.api_methods['agree_refund'],
            "after_sale_id": after_sale_id,
            "refund_amount": int(refund_amount * 100),  # 转换为分
        }
        
        if remark:
            params["remark"] = remark
        
        result = self._call_open_platform(params)
        
        if result and result.get("success"):
            self.logger.info(f"同意退货退款成功：after_sale_id={after_sale_id}")
            return {
                "success": True,
                "message": "同意退货退款成功",
                "after_sale_id": after_sale_id
            }
        else:
            error_msg = result.get("error_response", {}).get("error_msg", "未知错误") if result else "调用失败"
            self.logger.error(f"同意退货退款失败：{error_msg}")
            return {
                "success": False,
                "message": f"处理失败：{error_msg}",
                "after_sale_id": after_sale_id
            }
    
    def reject_return_goods(self, after_sale_id: str, refuse_reason: str, 
                           refuse_refund_amount: Optional[float] = None) -> Dict[str, Any]:
        """拒绝退货退款申请。
        
        Args:
            after_sale_id: 售后单号
            refuse_reason: 拒绝原因
            refuse_refund_amount: 拒绝退款金额（可选，单位：分）
            
        Returns:
            {
                "success": bool,
                "message": str,
                "after_sale_id": str
            }
        """
        params = {
            "type": self.api_methods['reject_refund'],
            "after_sale_id": after_sale_id,
            "refuse_reason": refuse_reason,
        }
        
        if refuse_refund_amount is not None:
            params["refuse_refund_amount"] = int(refuse_refund_amount * 100)
        
        result = self._call_open_platform(params)
        
        if result and result.get("success"):
            self.logger.info(f"拒绝退货退款成功：after_sale_id={after_sale_id}")
            return {
                "success": True,
                "message": "拒绝退货退款成功",
                "after_sale_id": after_sale_id
            }
        else:
            error_msg = result.get("error_response", {}).get("error_msg", "未知错误") if result else "调用失败"
            self.logger.error(f"拒绝退货退款失败：{error_msg}")
            return {
                "success": False,
                "message": f"处理失败：{error_msg}",
                "after_sale_id": after_sale_id
            }
    
    def query_after_sale_status(self, after_sale_id: str) -> Dict[str, Any]:
        """查询售后单状态。
        
        Args:
            after_sale_id: 售后单号
            
        Returns:
            {
                "success": bool,
                "status": str,  # 售后状态
                "refund_amount": float,  # 退款金额
                "reason": str,  # 申请原因
                "create_time": str,  # 申请时间
            }
        """
        params = {
            "type": self.api_methods['query_status'],
            "after_sale_id": after_sale_id
        }
        
        result = self._call_open_platform(params)
        
        if result and result.get("after_sale_status_response"):
            status_data = result["after_sale_status_response"]
            return {
                "success": True,
                "status": status_data.get("status", ""),
                "refund_amount": float(status_data.get("refund_amount", 0)) / 100,
                "reason": status_data.get("refund_reason", ""),
                "create_time": status_data.get("created_at", ""),
                "order_sn": status_data.get("order_sn", ""),
                "goods_name": status_data.get("goods_name", "")
            }
        else:
            error_msg = result.get("error_response", {}).get("error_msg", "查询失败") if result else "调用失败"
            return {
                "success": False,
                "error": error_msg
            }
    
    def get_after_sale_list(self, start_time: str, end_time: str, 
                           status: Optional[int] = None, 
                           page: int = 1, page_size: int = 20) -> Dict[str, Any]:
        """获取售后单列表。
        
        Args:
            start_time: 开始时间（格式：2024-01-01 00:00:00）
            end_time: 结束时间（格式：2024-01-31 23:59:59）
            status: 售后状态（可选）
                1: 待处理
                2: 已同意
                3: 已拒绝
                4: 已完成
            page: 页码
            page_size: 每页数量
            
        Returns:
            {
                "success": bool,
                "total": int,
                "list": List[Dict]
            }
        """
        params = {
            "type": self.api_methods['list_orders'],
            "start_time": start_time,
            "end_time": end_time,
            "page": page,
            "page_size": page_size
        }
        
        if status is not None:
            params["status"] = status
        
        result = self._call_open_platform(params)
        
        if result and result.get("after_sale_list_get_response"):
            response = result["after_sale_list_get_response"]
            return {
                "success": True,
                "total": response.get("total", 0),
                "list": response.get("list", [])
            }
        else:
            error_msg = result.get("error_response", {}).get("error_msg", "查询失败") if result else "调用失败"
            return {
                "success": False,
                "error": error_msg
            }
    
    def get_refund_limit_info(self) -> Dict[str, Any]:
        """查询售后限额信息。
        
        Returns:
            {
                "success": bool,
                "limit": int,  # 每日限额
                "used": int,  # 已使用
                "remaining": int  # 剩余
            }
        """
        params = {
            "type": self.api_methods['limit_info']
        }
        
        result = self._call_open_platform(params)
        
        if result and result.get("refund_limit_info"):
            limit_info = result["refund_limit_info"]
            return {
                "success": True,
                "limit": limit_info.get("daily_limit", 0),
                "used": limit_info.get("used_count", 0),
                "remaining": limit_info.get("remaining_count", 0)
            }
        else:
            error_msg = result.get("error_response", {}).get("error_msg", "查询失败") if result else "调用失败"
            return {
                "success": False,
                "error": error_msg
            }
    
class AIAfterSalesHandler:
    """AI 售后自动处理器。
    
    根据用户消息和售后规则自动处理售后申请。
    """
    
    def __init__(self, sales_manager: AfterSalesManager):
        self.manager = sales_manager
        
        # 自动处理规则
        self.auto_rules = {
            'auto_agree_amount': 50.0,  # 自动同意退款金额上限（元）
            'auto_agree_reasons': ['质量问题', '发错货', '破损'],  # 自动同意的原因
            'manual_check_amount': 100.0,  # 需要人工审核的金额上限
        }
    
    def process_refund_request(self, after_sale_id: str, 
                              refund_amount: float,
                              reason: str) -> Dict[str, Any]:
        """处理退款申请。
        
        Args:
            after_sale_id: 售后单号
            refund_amount: 退款金额
            reason: 申请原因
            
        Returns:
            处理结果
        """
        # 1. 检查是否满足自动处理条件
        should_auto_agree = self._should_auto_agree(refund_amount, reason)
        
        if should_auto_agree:
            # 自动同意
            result = self.manager.agree_return_goods(after_sale_id, refund_amount, "系统自动处理")
            result["auto_processed"] = True
            return result
        else:
            # 转人工处理
            return {
                "success": False,
                "auto_processed": False,
                "message": "需要人工审核",
                "reason": f"金额超限或原因不符合自动处理规则"
            }
    
    def _should_auto_agree(self, refund_amount: float, reason: str) -> bool:
        """判断是否应该自动同意。
        
        Args:
            refund_amount: 退款金额
            reason: 申请原因
            
        Returns:
            是否自动同意
        """
        # 金额在自动处理范围内
        if refund_amount > self.auto_rules['auto_agree_amount']:
            return False
        
        # 原因符合自动处理规则
        for auto_reason in self.auto_rules['auto_agree_reasons']:
            if auto_reason in reason:
                return True
        
        return False
    
    def set_auto_rule(self, rule_name: str, value: Any) -> None:
        """设置自动处理规则。
        
        Args:
            rule_name: 规则名称
            value: 规则值
        """
        if rule_name in self.auto_rules:
            self.auto_rules[rule_name] = value
            self.manager.logger.info(f"更新自动处理规则：{rule_name}={value}")
