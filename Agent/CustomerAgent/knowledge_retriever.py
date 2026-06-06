"""检索打分、FAQ 直答与 search_knowledge。"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Optional, Tuple

from Agent.CustomerAgent.knowledge_storage import (
    DocumentLike,
    get_current_platform_shop_id,
)


class KnowledgeRetrieverMixin:
    _SCORE_SNIPPET_CHARS = 12000
    _EMBED_QUERY_TEXT_MAX = 3800

    def _apply_parent_override_filter(
        self,
        ranked: List[Tuple[float, Dict[str, Any]]],
        pool: List[Dict[str, Any]],
        shop_id: Optional[str],
    ) -> List[Tuple[float, Dict[str, Any]]]:
        """
        继承语义：子知识库（platform_shop_id=当前店）与父知识库（无店铺）共用同一 inherit_key 时，
        仅当父条 `allow_child_override` 为真，检索结果中才跳过父库条目，保留子库（重写）版本。
        """
        override_keys = self._shop_override_inherit_keys(pool, shop_id)
        if not override_keys:
            return ranked
        out: List[Tuple[float, Dict[str, Any]]] = []
        for score, d in ranked:
            ps = (d.get("platform_shop_id") or "").strip()
            ik = self._inherit_key(d)
            if (
                not ps
                and ik
                and ik in override_keys
                and self._parent_allows_child_override(d)
            ):
                continue
            out.append((score, d))
        return out

    def _drop_overridden_parents_from_list(
        self, docs: List[Dict[str, Any]], shop_id: Optional[str]
    ) -> List[Dict[str, Any]]:
        """列表视图用：去掉已被本店子库 inherit_key 覆盖的父库文档。"""
        keys = self._shop_override_inherit_keys(docs, shop_id)
        if not keys:
            return docs
        out: List[Dict[str, Any]] = []
        for d in docs:
            ps = (d.get("platform_shop_id") or "").strip()
            ik = self._inherit_key(d)
            if not ps and ik and ik in keys and self._parent_allows_child_override(d):
                continue
            out.append(d)
        return out

    def _documents_for_retrieval(
        self,
        *,
        ignore_shop_filter: bool,
        platform_shop_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if ignore_shop_filter:
            return list(self.documents)
        eff = platform_shop_id
        if eff is None:
            eff = get_current_platform_shop_id()
        return [d for d in self.documents if self._doc_visible_for_shop(d, eff)]

    @staticmethod
    def _cosine_similarity(v1: List[float], v2: List[float]) -> float:
        if not v1 or not v2 or len(v1) != len(v2):
            return 0.0
        dot = sum(a * b for a, b in zip(v1, v2))
        n1 = math.sqrt(sum(a * a for a in v1))
        n2 = math.sqrt(sum(b * b for b in v2))
        if n1 == 0 or n2 == 0:
            return 0.0
        return dot / (n1 * n2)

    def _expand_query(self, query: str) -> List[str]:
        """扩展查询词 - 提高召回率"""
        expanded = [query.lower()]
        ql = query.lower()

        # 同义词：标准词 → 扩展；用户说法命中别名时补回标准词（反向扩展）
        for keyword, synonyms in self.synonyms.items():
            if keyword in ql:
                expanded.extend(synonyms)
            else:
                for syn in synonyms:
                    if syn and syn in ql:
                        expanded.append(keyword)
                        break

        # 添加简写和变体
        if "美甲灯" in query:
            expanded.extend(["美甲", "灯", "光疗灯", "uv 灯", "led 灯"])
        if "多少钱" in query:
            expanded.extend(["价格", "价", "$", "贵", "便宜"])
        if "家用" in query:
            expanded.extend(["自己用", "家里", "家庭"])
        if "开店" in query:
            expanded.extend(["商用", "店里", "专业"])

        return list(set(expanded))

    def _iter_scorable_units(
        self, doc: Dict[str, Any]
    ) -> List[Tuple[str, Optional[List[float]]]]:
        """返回用于打分的文本片段及对应向量（长文档按块、短文档按篇）。"""
        content = str(doc.get("content", ""))
        chs = doc.get("chunks")
        if isinstance(chs, list) and chs:
            units: List[Tuple[str, Optional[List[float]]]] = []
            for c in chs:
                if not isinstance(c, dict):
                    continue
                t = str(c.get("text", "")).strip()
                if not t:
                    continue
                sn = (
                    self._snippet_for_scoring(t)
                    if len(t) > self._SCORE_SNIPPET_CHARS
                    else t
                )
                emb = c.get("embedding")
                units.append((sn, emb if isinstance(emb, list) and emb else None))
            if units:
                return units
        sn = self._snippet_for_scoring(content)
        emb = doc.get("embedding")
        return [(sn, emb if isinstance(emb, list) and emb else None)]

    def _lexical_score(self, snippet_lower: str, query_text: str) -> float:
        score = 0.0
        q_raw = query_text.strip()
        qn = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", q_raw.lower())
        cn = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", snippet_lower)
        if qn and qn in cn:
            score += 5.5
        tokens = re.findall(r"[A-Za-z0-9\-\+]+|[\u4e00-\u9fff]{2,}", query_text)
        score += sum(1 for t in tokens if t.lower() in snippet_lower) * 1.05
        qchars = re.sub(r"[^\u4e00-\u9fff]", "", q_raw)
        if len(qchars) >= 2:
            for i in range(len(qchars) - 1):
                bg = qchars[i : i + 2]
                if bg in snippet_lower:
                    score += 0.35
        return score

    def _score_document_unit(
        self,
        doc: Dict[str, Any],
        unit_snippet_lower: str,
        unit_embedding: Optional[List[float]],
        query_text: str,
        query_vec: Optional[List[float]],
    ) -> float:
        header = self._header_for_doc(doc)
        comb = (
            (header + "\n" + unit_snippet_lower).lower()
            if header
            else unit_snippet_lower
        )
        score = 0.0
        if query_vec and unit_embedding:
            score += self._cosine_similarity(query_vec, unit_embedding) * 12.0
        score += self._lexical_score(comb, query_text)
        return score

    def _snippet_for_scoring(self, content: str) -> str:
        if not content:
            return ""
        if len(content) <= self._SCORE_SNIPPET_CHARS:
            return content
        head = content[: self._SCORE_SNIPPET_CHARS // 2]
        tail = content[-self._SCORE_SNIPPET_CHARS // 2 :]
        return head + "\n…\n" + tail

    def _build_embedding_query_text(self, query: str) -> str:
        """原始问题 + 同义词扩展，一并送入向量模型，提高语义召回。"""
        base = (query or "").strip()
        if not base:
            return ""
        parts: List[str] = [base]
        seen = {base.lower()}
        try:
            for term in self._expand_query(base):
                t = (term or "").strip()
                if len(t) < 2:
                    continue
                low = t.lower()
                if low in seen:
                    continue
                seen.add(low)
                parts.append(t)
                if len(parts) >= 24:
                    break
        except Exception as e:
            self.logger.debug(f"同义词扩展中断，使用已收集项: {e}")
        merged = "\n".join(parts)
        return merged[: self._EMBED_QUERY_TEXT_MAX]

    def _best_matching_product(self, question: str) -> Optional[Dict[str, Any]]:
        """从用户句子里粗略命中一款内置 product（用于价格/规格直答）。"""
        q = (question or "").strip()
        if not q:
            return None
        qn = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", q.lower())
        ql = q.lower()
        best: Optional[Dict[str, Any]] = None
        best_score = 0
        for p in self.products:
            name = str(p.get("name", ""))
            nn = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", name.lower())
            score = 0
            if nn and len(nn) >= 4 and (nn in qn or qn in nn):
                score += 12
            elif nn and len(nn) >= 6 and nn[:6] in qn:
                score += 8
            for kw in p.get("keywords", []) or []:
                k = str(kw).lower()
                if k and len(k) >= 2 and k in ql:
                    score += 4
            nlow = name.lower()
            if "x5" in ql and "plus" in ql and "x5" in nlow and "plus" in nlow:
                score += 10
            if "sunone" in ql and "sunone" in nlow:
                score += 10
            if score > best_score:
                best_score = score
                best = p
        return best if best_score >= 6 else None

    def _answer_price_or_currency_question(self, question: str) -> Optional[str]:
        """
        针对「是不是卖 299」「多少钱」类：先正面回应币种/口径，避免套错 FAQ 模板。
        """
        q = (question or "").strip()
        if not q:
            return None
        ql = q.lower()
        price_hint = any(
            k in ql
            for k in (
                "卖",
                "价",
                "钱",
                "元",
                "块",
                "$",
                "多少钱",
                "价位",
                "贵",
                "便宜",
                "标价",
                "定价",
                "包邮",
            )
        )
        if not price_hint:
            return None

        p = self._best_matching_product(q)
        if not p:
            return None

        user_price: Optional[int] = None
        m_sale = re.search(r"(?:卖|￥|¥)\s*(\d+)", q)
        if m_sale:
            user_price = int(m_sale.group(1))
        else:
            m_cny = re.search(r"(\d+)\s*(?:元|块|人民币)(?:\s|$|[吗呢呀])", q)
            if m_cny:
                user_price = int(m_cny.group(1))
        if user_price is None:
            big = [int(x) for x in re.findall(r"\d+", q) if int(x) >= 10]
            user_price = big[0] if big else None

        name = str(p.get("name", "该款"))
        ref = str(p.get("price", "") or "").strip()
        parts = [
            f"亲，**{name}** 在我们维护的参考数据里是 **{ref}**（美元标价，用于演示/对照，不是您拼多多后台实时页面）。"
        ]
        if user_price is not None:
            parts.append(
                f"您问的 **{user_price}** 一般是 **人民币￥** 或页面活动价；和上面的 **美元 $** 不是同一币种，不能直接等同「是不是卖 {user_price}」。"
            )
        parts.append(
            "最终以您当前这条拼多多链接的商品详情页、下单结算页标价为准；不同活动、规格会变动。"
        )
        return "\n".join(parts)

    def _match_intent(
        self, query: str, template_keywords: List[str]
    ) -> Tuple[bool, int]:
        """
        匹配意图 - 返回是否匹配和匹配分数。
        禁止「关键词前两字 ∈ 问题」这种宽松规则：例如「美甲店」会误命中「美甲灯」。
        """
        query_lower = query.lower()
        match_count = 0

        for keyword in template_keywords:
            if not keyword:
                continue
            if keyword in query_lower:
                match_count += 2
                continue
            # 仅对较长词使用前三个字做弱命中（避免两字前缀误触）
            if len(keyword) >= 3 and keyword[:3] in query_lower:
                match_count += 1

        return (match_count >= 1, match_count)

    def get_product_introduction(self, scenario: Optional[str] = None) -> str:
        """获取产品介绍，根据场景推荐"""
        if not scenario:
            # 没有指定场景，介绍全部产品
            intro = "亲，我们家美甲灯有 4 款热销产品哦~ 💅\n\n"
            for i, p in enumerate(self.products, 1):
                intro += f"✨ **{i}. {p['name']}** - {p['price']}\n"
                intro += (
                    f"   功率：{p['power']} | 特点：{','.join(p['features'][:2])}\n"
                )
                intro += f"   👉 {p['recommend_for']}\n\n"
            intro += "亲告诉我您的使用场景（家用/开店）和预算，我帮您推荐最合适的！😊"
            return intro

        # 根据场景推荐 - 使用宽松匹配
        scenario_lower = scenario.lower()

        # 家用匹配
        if any(kw in scenario_lower for kw in ["家用", "自己", "家里", "家庭", "个人"]):
            return self.faq_templates["家用推荐"]["response"]
        # 开店匹配
        elif any(
            kw in scenario_lower for kw in ["开店", "商用", "店里", "专业", "沙龙"]
        ):
            return self.faq_templates["开店推荐"]["response"]
        # 新手匹配
        elif any(kw in scenario_lower for kw in ["新手", "入门", "第一次", "学生"]):
            return self.faq_templates["新手推荐"]["response"]
        else:
            # 默认返回家用推荐
            return self.faq_templates["家用推荐"]["response"]

    def answer_question(self, question: str) -> str:
        """回答问题，使用宽松匹配策略"""
        question_lower = question.lower()

        # 特殊问题处理 - 最优先匹配
        # 功率相关
        if any(kw in question_lower for kw in ["功率", "w", "瓦"]):
            return self._answer_power_question()
        # 灯珠相关 - 优先匹配数量相关词
        if any(
            kw in question_lower
            for kw in ["灯珠数量", "多少颗", "几颗灯", "灯珠", "led 灯", "uv 灯"]
        ):
            return self._answer_bulb_question()
        # 售后相关 - 优先匹配质保、保修
        if any(
            kw in question_lower
            for kw in ["质保", "保修", "坏了", "退", "维修", "售后"]
        ):
            return self.faq_templates["售后保障"]["response"]
        # 对比相关
        if any(kw in question_lower for kw in ["对比", "区别", "哪个好"]):
            return self._answer_comparison_question()
        # 使用相关 - 精确匹配，避免误匹配"家庭使用"
        if any(
            kw in question_lower
            for kw in ["怎么用", "如何使用", "操作", "教程", "用法"]
        ):
            return self._answer_usage_question()

        price_reply = self._answer_price_or_currency_question(question)
        if price_reply:
            return price_reply

        # 扩展查询词
        expanded_queries = self._expand_query(question)

        # 遍历所有 FAQ 模板，找最佳匹配
        best_match = None
        best_score = 0

        for template_name, template_data in self.faq_templates.items():
            if isinstance(template_data, dict):
                keywords = template_data.get("keywords", [])
                response = template_data.get("response", "")

                # 检查每个扩展查询词
                for exp_query in expanded_queries:
                    matched, score = self._match_intent(exp_query, keywords)
                    if matched and score > best_score:
                        best_score = score
                        best_match = response
                        break

        # 如果有匹配，返回匹配结果
        if best_match:
            return best_match

        # 默认兜底回复
        return self.get_fallback_response(question)

    def _answer_power_question(self) -> str:
        """回答功率相关问题"""
        return """亲，我们家美甲灯功率选择很多哦~ ⚡

📊 **功率对比**:
- XEIJAYI 迷你款：6W（入门便携）
- LIMEGIRL SUNone：24W（家用推荐）
- SUN X5 Plus：48W（专业推荐）
- LKE UV 72W：72W（功率最大）

💡 **怎么选**:
- 家用：24W 足够
- 开店：建议 48W 以上
- 追求速度：选 72W

您是什么使用场景呢？我帮您推荐合适的！😊"""

    def _answer_bulb_question(self) -> str:
        """回答灯珠相关问题"""
        return """亲，灯珠数量影响固化效果哦~ 💡

📊 **灯珠对比**:
- XEIJAYI 迷你款：6 颗灯珠
- LIMEGIRL SUNone：12 颗灯珠
- SUN X5 Plus：21 颗灯珠
- LKE UV 72W：36 颗灯珠

✨ **灯珠越多**:
- 照射角度越全面
- 固化速度越快
- 无死角固化

💖 寿命都是 50000 小时以上，正常使用 3-5 年没问题！

有其他问题随时问我哦~ 😊"""

    def _answer_comparison_question(self) -> str:
        """回答对比相关问题"""
        return """亲，给您对比一下 4 款热销款~ 📊

| 款式 | 价格 | 功率 | 灯珠 | 推荐 |
|------|------|------|------|------|
| 迷你款 | $3.99 | 6W | 6 颗 | 入门 |
| SUNone | $10.28 | 24W | 12 颗 | 家用 |
| X5 Plus | $13.93 | 48W | 21 颗 | 专业 |
| LKE 72W | $8.78 | 72W | 36 颗 | 性价比 |

💡 **选购建议**:
- 预算有限：迷你款
- 家庭使用：SUNone
- 开店专业：X5 Plus
- 追求性价比：LKE 72W

您更看重哪方面呢？😊"""

    def _answer_usage_question(self) -> str:
        """回答使用方法相关问题"""
        return """亲，美甲灯使用方法很简单~ 💅

📋 **使用步骤**:
1️⃣ 插上 USB 电源
2️⃣ 涂好光疗胶
3️⃣ 手放进灯内
4️⃣ 自动感应启动（或按定时键）
5️⃣ 等待 30-90 秒
6️⃣ 取出完成！

✨ **小贴士**:
- 薄涂多层，每层都照干
- 不要涂太厚
- 第一次可以照久一点

有具体哪步不明白，随时问我哦~ 😊"""

    def get_fallback_response(self, question: str) -> str:
        """兜底回复 - 当知识库没有匹配时的友好回复"""
        response = """亲，小美理解您的问题啦~ 💖

美甲灯这块小美做了 3 年，有什么问题尽管问我！😊

我可以帮您：
✅ 推荐合适的产品（告诉我家用还是开店用）
✅ 介绍产品价格和优惠活动
✅ 解答使用方法和固化时间
✅ 说明物流发货和售后保障
✅ 对比不同款式的区别

您具体想了解哪方面呢？或者直接告诉我您的需求（比如：家用、预算$10 左右），我帮您推荐！💅✨"""

        return response

    def _ensure_lazy_embeddings(self) -> None:
        if self._embeddings_ready:
            return
        self._embeddings_ready = True
        try:
            self.ensure_embeddings_ready()
            self._sync_all_docs_to_lancedb(force=True)
        except Exception as e:
            self.logger.debug("延迟 embedding 补齐跳过: {}", e)

    def search_knowledge(self, query: str, top_k: int = 5, **kwargs) -> List[Dict]:
        """向量检索（LanceDB 优先，本地打分兜底）。"""
        self._ensure_store_initialized(wait=True)
        self._ensure_lazy_embeddings()
        limit = kwargs.get("limit", top_k or 5)
        limit = max(1, int(limit))
        ignore_shop_filter = bool(kwargs.get("ignore_shop_filter", False))
        explicit_shop = kwargs.get("platform_shop_id")

        # 优先使用 LanceDB 向量检索
        if self._knowledge_table and self._embedder_client and self._embedder_model:
            try:
                # 生成查询向量
                query_text = self._build_embedding_query_text(query.strip())
                query_vec = self._embed_text(query_text) if query_text else None

                if query_vec:
                    # 使用 LanceDB 进行向量检索
                    results = (
                        self._knowledge_table.search(query_vec)
                        .limit(limit * 2)
                        .to_pandas()
                    )

                    if not results.empty:
                        # 过滤店铺可见性
                        eff_shop = (
                            explicit_shop
                            if explicit_shop is not None
                            else get_current_platform_shop_id()
                        )
                        filtered = []
                        for _, row in results.iterrows():
                            doc = {
                                "id": row["id"],
                                "content": row["content"],
                                "platform_shop_id": row.get("platform_shop_id", ""),
                                "inherit_key": row.get("inherit_key", ""),
                                "allow_child_override": row.get(
                                    "allow_child_override", False
                                ),
                                "title": row.get("title", ""),
                                "filename": row.get("filename", ""),
                                "source": row.get("source", ""),
                            }
                            if self._doc_visible_for_shop(doc, eff_shop):
                                filtered.append((row.get("_distance", 0), doc))

                        # 按距离排序（越小越相关）
                        filtered.sort(key=lambda x: x[0])
                        top = filtered[:limit]

                        self.logger.debug(
                            f"LanceDB 检索：query='{query[:50]}...', top_k={limit}, 返回 {len(top)} 条"
                        )

                        out_docs: List[DocumentLike] = []
                        for dist, d in top:
                            score = round(1.0 / (1.0 + float(dist or 0.0)), 4)
                            out_docs.append(
                                DocumentLike(
                                    id=str(d.get("id", "")),
                                    data=str(d.get("content", "")),
                                    metadata={
                                        "title": d.get("title", ""),
                                        "filename": d.get("filename", ""),
                                        "source": d.get("source", ""),
                                        "platform_shop_id": d.get("platform_shop_id")
                                        or "",
                                        "inherit_key": d.get("inherit_key") or "",
                                        "allow_child_override": bool(
                                            d.get("allow_child_override", False)
                                        ),
                                        "rerank_score": score,
                                        "vector_distance": float(dist or 0.0),
                                        **(
                                            {"import_format": str(d["import_format"])}
                                            if d.get("import_format")
                                            else {}
                                        ),
                                        **(
                                            {
                                                "display_payload": str(
                                                    d["display_payload"]
                                                )
                                            }
                                            if d.get("display_payload")
                                            else {}
                                        ),
                                    },
                                )
                            )
                        return out_docs
            except Exception as e:
                self.logger.warning(f"LanceDB 检索失败，回退到本地检索：{e}")

        # 回退到本地检索
        pool = self._documents_for_retrieval(
            ignore_shop_filter=ignore_shop_filter,
            platform_shop_id=explicit_shop if explicit_shop is not None else None,
        )

        # 空查询用于 UI 列表加载：直接返回全部（受 limit 限制）
        if not query or not query.strip():
            eff_shop = (
                explicit_shop
                if explicit_shop is not None
                else get_current_platform_shop_id()
            )
            pool_list = (
                self._drop_overridden_parents_from_list(pool, eff_shop)
                if not ignore_shop_filter
                else pool
            )
            docs = pool_list[:limit]
            return [
                DocumentLike(
                    id=str(d.get("id", "")),
                    data=str(d.get("content", "")),
                    metadata={
                        "title": d.get("title", ""),
                        "filename": d.get("filename", ""),
                        "source": d.get("source", ""),
                        "platform_shop_id": d.get("platform_shop_id") or "",
                        "inherit_key": d.get("inherit_key") or "",
                        "allow_child_override": bool(
                            self._parent_allows_child_override(d)
                        ),
                        **(
                            {"import_format": str(d["import_format"])}
                            if d.get("import_format")
                            else {}
                        ),
                        **(
                            {"display_payload": str(d["display_payload"])}
                            if d.get("display_payload")
                            else {}
                        ),
                    },
                )
                for d in docs
            ]

        query_text = query.strip()
        embed_q = self._build_embedding_query_text(query_text)
        query_vec = self._embed_text(embed_q) if embed_q else None
        ranked: List[Tuple[float, Dict[str, Any]]] = []

        for d in pool:
            content = str(d.get("content", ""))
            if not content:
                continue
            best = 0.0
            for unit_snip, unit_emb in self._iter_scorable_units(d):
                u = (unit_snip or "").lower()
                s = self._score_document_unit(d, u, unit_emb, query_text, query_vec)
                if s > best:
                    best = s
            if best > 0:
                ranked.append((best, d))

        ranked.sort(key=lambda x: x[0], reverse=True)
        ranked = self._apply_parent_override_filter(
            ranked,
            pool,
            (
                explicit_shop
                if explicit_shop is not None
                else get_current_platform_shop_id()
            ),
        )
        top_ranked = ranked[:limit]
        out_ranked: List[DocumentLike] = []
        for score_val, d in top_ranked:
            norm = round(min(1.0, float(score_val) / 20.0), 4) if score_val else 0.1
            out_ranked.append(
                DocumentLike(
                    id=str(d.get("id", "")),
                    data=str(d.get("content", "")),
                    metadata={
                        "title": d.get("title", ""),
                        "filename": d.get("filename", ""),
                        "source": d.get("source", ""),
                        "platform_shop_id": d.get("platform_shop_id") or "",
                        "inherit_key": d.get("inherit_key") or "",
                        "allow_child_override": bool(
                            self._parent_allows_child_override(d)
                        ),
                        "rerank_score": norm,
                        "retrieval_score": float(score_val),
                        **(
                            {"import_format": str(d["import_format"])}
                            if d.get("import_format")
                            else {}
                        ),
                        **(
                            {"display_payload": str(d["display_payload"])}
                            if d.get("display_payload")
                            else {}
                        ),
                    },
                )
            )
        return out_ranked

    def format_product_card(self, product: Dict) -> str:
        """格式化产品卡片，不暴露内部 ID"""
        card = f"✨ **{product['name']}**\n"
        card += f"💰 价格：{product['price']}\n"
        card += f"⚡ 功率：{product['power']}\n"
        card += f"🌟 特点：{'、'.join(product['features'])}\n"
        card += f"👥 适合：{'、'.join(product['suitable'])}\n"
        card += f"💡 推荐：{product['recommend_for']}"
        return card
