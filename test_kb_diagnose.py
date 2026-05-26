"""
知识库诊断脚本
检查知识库文档的加载和可见性问题
"""
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from Agent.CustomerAgent.agent_knowledge import NailLampKnowledgeManager, get_current_platform_shop_id, set_platform_shop_context, reset_platform_shop_context

def diagnose():
    print("=" * 60)
    print("知识库诊断报告")
    print("=" * 60)
    
    # 创建知识库管理器
    km = NailLampKnowledgeManager()
    
    print(f"\n1. 文档总数：{len(km.documents)}")
    
    if not km.documents:
        print("   ❌ 知识库为空！请导入文档")
        return
    
    # 统计文档分布
    shop_docs = {}
    empty_shop_count = 0
    
    print("\n2. 文档店铺分布:")
    for i, doc in enumerate(km.documents):
        shop_id = doc.get("platform_shop_id")
        title = doc.get("title", "无标题")[:30]
        
        if shop_id is None or str(shop_id).strip() == "":
            empty_shop_count += 1
            shop_key = "(通用)"
        else:
            shop_key = str(shop_id).strip()
            if shop_key not in shop_docs:
                shop_docs[shop_key] = []
            shop_docs[shop_key].append(doc)
        
        print(f"   [{i+1}] {title:30s} -> 店铺 ID: {shop_key if shop_key else '(空)'}")
    
    print(f"\n   通用文档（platform_shop_id 为空）: {empty_shop_count} 条")
    for shop_id, docs in shop_docs.items():
        print(f"   店铺文档（{shop_id}）: {len(docs)} 条")
    
    # 测试检索
    print("\n3. 检索测试:")
    test_query = "美甲灯"
    print(f"   查询：'{test_query}'")
    
    # 测试 1：不设置店铺上下文
    print("\n   【测试 1】不设置店铺上下文")
    current_shop = get_current_platform_shop_id()
    print(f"   当前店铺上下文：{current_shop}")
    results = km.search_knowledge(test_query, top_k=5)
    print(f"   检索结果：{len(results)} 条")
    for i, r in enumerate(results):
        title = r.metadata.get('title', '无标题')[:30]
        shop = r.metadata.get('platform_shop_id', '空') or '(空)'
        print(f"      [{i+1}] {title:30s} (店铺：{shop})")
    
    # 测试 2：设置店铺上下文为空
    print("\n   【测试 2】设置店铺上下文为空")
    tok = set_platform_shop_context(None)
    current_shop = get_current_platform_shop_id()
    print(f"   当前店铺上下文：{current_shop}")
    results = km.search_knowledge(test_query, top_k=5)
    print(f"   检索结果：{len(results)} 条")
    for i, r in enumerate(results):
        title = r.metadata.get('title', '无标题')[:30]
        shop = r.metadata.get('platform_shop_id', '空') or '(空)'
        print(f"      [{i+1}] {title:30s} (店铺：{shop})")
    reset_platform_shop_context(tok)
    
    # 测试 3：设置店铺上下文为具体值
    print("\n   【测试 3】设置店铺上下文为 'test_shop'")
    tok = set_platform_shop_context("test_shop")
    current_shop = get_current_platform_shop_id()
    print(f"   当前店铺上下文：{current_shop}")
    results = km.search_knowledge(test_query, top_k=5)
    print(f"   检索结果：{len(results)} 条")
    for i, r in enumerate(results):
        title = r.metadata.get('title', '无标题')[:30]
        shop = r.metadata.get('platform_shop_id', '空') or '(空)'
        print(f"      [{i+1}] {title:30s} (店铺：{shop})")
    reset_platform_shop_context(tok)
    
    # 检查 embedding
    print("\n4. Embedding 检查:")
    docs_without_embedding = 0
    docs_with_chunks = 0
    for i, doc in enumerate(km.documents):
        has_embedding = False
        if doc.get("embedding"):
            has_embedding = True
        elif doc.get("chunks"):
            chunks = doc.get("chunks", [])
            if chunks and any(c.get("embedding") for c in chunks):
                has_embedding = True
            docs_with_chunks += 1
        
        if not has_embedding:
            docs_without_embedding += 1
            title = doc.get("title", "无标题")[:30]
            print(f"   ❌ 文档 [{i+1}] {title} 缺少 embedding")
    
    if docs_without_embedding == 0:
        print("   ✅ 所有文档都有 embedding")
    else:
        print(f"\n   共 {docs_without_embedding} 条文档缺少 embedding，{docs_with_chunks} 条文档使用分块")
        print("   建议：在知识库界面点击'重新生成向量'或重启应用")
    
    # 可见性测试
    print("\n5. 文档可见性测试:")
    test_shop_id = "test_shop_123"
    print(f"   模拟店铺 ID: {test_shop_id}")
    
    visible_count = 0
    invisible_count = 0
    
    for i, doc in enumerate(km.documents):
        doc_shop_id = doc.get("platform_shop_id")
        is_visible = km._doc_visible_for_shop(doc, test_shop_id)
        title = doc.get("title", "无标题")[:30]
        
        if is_visible:
            visible_count += 1
            status = "✅ 可见"
        else:
            invisible_count += 1
            status = "❌ 不可见"
        
        print(f"   [{i+1}] {title:30s} 文档店铺={doc_shop_id or '(空)':20s} -> {status}")
    
    print(f"\n   总结：{visible_count} 条可见，{invisible_count} 条不可见")
    
    print("\n" + "=" * 60)
    print("诊断完成")
    print("=" * 60)

if __name__ == "__main__":
    diagnose()
