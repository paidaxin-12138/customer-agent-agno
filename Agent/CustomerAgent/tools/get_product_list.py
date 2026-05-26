from agno.tools import tool
from Channel.pinduoduo.utils.API.product_manager import ProductManager
from agno.run import RunContext
from utils.logger_loguru import get_logger

logger = get_logger("GetProductListTool")


def _format_sku_block(sku_list: list) -> str:
    """格式化 SKU 名称 / 价格 / 库存。"""
    if not sku_list:
        return "   SKU: 暂无明细\n"
    lines = ["   SKU 规格:"]
    for sku in sku_list:
        name = sku.get("sku_name") or "默认规格"
        parts = [f"     - {name}"]
        if sku.get("price") is not None:
            parts.append(f"¥{sku['price']}")
        if sku.get("quantity") is not None and sku.get("quantity") != "":
            parts.append(f"库存{sku['quantity']}件")
        lines.append(" | ".join(parts))
    return "\n".join(lines) + "\n"


def _fetch_product_info(product_manager: ProductManager, goods_id) -> dict:
    """拉取商品详情并返回 product_info（含 sku_list）。"""
    if not goods_id:
        return {}
    raw = product_manager.get_product_detail(goods_id)
    if not isinstance(raw, dict) or not raw.get("success"):
        return {}
    info = raw.get("product_info")
    return info if isinstance(info, dict) else {}


def _format_products_output(
    products,
    total,
    page,
    *,
    sku_by_goods_id: dict | None = None,
) -> str:
    """格式化商品列表；sku_by_goods_id 为 goods_id -> product_info。"""
    if not products:
        return "未找到商品"

    sku_map = sku_by_goods_id or {}
    output = f"商品列表 (共{total}个商品，第{page}页，含实时 SKU):\n\n"

    for i, product in enumerate(products, 1):
        goods_id = product.get("goods_id", "未知ID")
        goods_name = product.get("goods_name", "未命名商品")
        price = product.get("price", "")
        sold_quantity = product.get("sold_quantity", 0)
        sold_quantity_30d = product.get("sold_quantity_30d", 0)
        quantity = product.get("quantity", 0)
        is_spike = product.get("is_spike", False)
        support_customize = product.get("support_customize", False)
        tag = product.get("tag", "")

        output += f"{i}. {goods_name} (ID: {goods_id})\n"

        if price:
            output += f"   价格: {price} 元\n"
        if sold_quantity:
            output += f"   已售: {sold_quantity}\n"
        if sold_quantity_30d:
            output += f"   30天销量: {sold_quantity_30d}\n"
        if quantity:
            output += f"   库存: {quantity}\n"
        if is_spike:
            output += f"   [秒杀商品]\n"
        if support_customize:
            output += f"   [支持定制]\n"
        if tag:
            output += f"   标签: {tag}\n"

        info = sku_map.get(goods_id) or sku_map.get(str(goods_id)) or {}
        output += _format_sku_block(info.get("sku_list") or [])

        output += "\n"

    return output


@tool(
    name="get_shop_products",
    description="获取店铺在售商品列表（实时 API），含各商品 SKU 名称、价格、库存。无需先同步知识库。",
)
def get_shop_products(run_context: RunContext) -> str:
    """
    获取店铺商品列表（实时），并逐个拉取详情中的 SKU 明细。
    """
    try:
        try:
            from core.ops_telemetry import record_tool_call

            record_tool_call("get_shop_products", "fetch product list with SKU")
        except Exception:
            pass
        shop_id = run_context.dependencies["shop_id"]
        user_id = run_context.dependencies["user_id"]
        if not shop_id or not user_id:
            return "获取商品列表失败：缺少必要的shop_id或user_id参数"

        product_manager = ProductManager(shop_id=shop_id, user_id=user_id)
        result = product_manager.get_product_list(page=1, size=10)

        if not result.get("success"):
            error_msg = result.get("error_msg", "未知错误")
            logger.error(f"获取商品列表失败: {error_msg}")
            return f"获取商品列表失败: {error_msg}"

        products = result.get("products", [])
        total = result.get("total", 0)
        if not products:
            return f"店铺当前暂无商品 (shop_id: {shop_id})"

        sku_by_goods_id: dict = {}
        for product in products:
            gid = product.get("goods_id")
            if not gid:
                continue
            try:
                info = _fetch_product_info(product_manager, gid)
                if info:
                    sku_by_goods_id[gid] = info
            except Exception as e:
                logger.warning(f"获取商品 {gid} SKU 失败: {e}")

        return _format_products_output(
            products, total, page=1, sku_by_goods_id=sku_by_goods_id
        )

    except Exception as e:
        logger.error(f"工具执行异常: {str(e)}")
        return f"获取商品列表时发生异常: {str(e)}"


@tool(
    name="get_product_skus",
    description="根据商品 goods_id 实时查询该商品全部 SKU 的名称、价格、库存。",
)
def get_product_skus(run_context: RunContext, goods_id: str) -> str:
    """按商品 ID 查询 SKU 明细（实时，无需同步知识库）。"""
    try:
        shop_id = run_context.dependencies["shop_id"]
        user_id = run_context.dependencies["user_id"]
        if not shop_id or not user_id:
            return "查询失败：缺少 shop_id 或 user_id"
        gid = str(goods_id or "").strip()
        if not gid:
            return "查询失败：goods_id 不能为空"

        pm = ProductManager(shop_id=shop_id, user_id=user_id)
        info = _fetch_product_info(pm, gid)
        if not info:
            return f"未获取到商品 {gid} 的详情，请确认商品 ID 与登录状态"

        name = info.get("goods_name") or "未知商品"
        lines = [f"商品: {name} (ID: {gid})", ""]
        sku_list = info.get("sku_list") or []
        if not sku_list:
            return lines[0] + "\n暂无 SKU 明细"

        for sku in sku_list:
            row = f"- {sku.get('sku_name') or '默认规格'}"
            if sku.get("price") is not None:
                row += f" | ¥{sku['price']}"
            if sku.get("quantity") is not None and sku.get("quantity") != "":
                row += f" | 库存 {sku['quantity']} 件"
            if sku.get("sku_id") is not None:
                row += f" | sku_id={sku['sku_id']}"
            lines.append(row)
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"get_product_skus 异常: {e}")
        return f"查询 SKU 时发生异常: {e}"
