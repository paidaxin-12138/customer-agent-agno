"""
美甲灯客服 AI 知识库集成模块
优化知识库检索和回复生成，提高召回率。

知识库层级（逻辑）：
- 父知识库：`platform_shop_id` 为空 → 全店通用；
- 子知识库：绑定某拼多多 `platform_shop_id`；
- 可选 `inherit_key`：父子填同一键时，子库可声明覆盖意图；
- 仅当父条显式 `allow_child_override=true` 时，检索才会隐藏父条、采用子店文案；未标记的父条与子店同键时并列出现，不被隐藏。
物理上仍是一套本地文档存储与向量索引，不按账号拆多份文件。
"""

from typing import List, Optional, Dict, Any, Tuple
import re
import threading
from datetime import datetime
from pathlib import Path
import json
import math
from contextvars import ContextVar
from dataclasses import dataclass

# 客服进线时由 CustomerAgent 注入，检索只返回「全店通用 + 本店」文档
_CURRENT_PLATFORM_SHOP_ID: ContextVar[Optional[str]] = ContextVar(
    "current_platform_shop_id", default=None
)

from openai import OpenAI
from config import Config
from utils.runtime_path import get_temp_path
from utils.logger_loguru import get_logger
import lancedb


def get_current_platform_shop_id() -> Optional[str]:
    return _CURRENT_PLATFORM_SHOP_ID.get()


def set_platform_shop_context(shop_id: Optional[str]) -> Any:
    """设置当前线程/协程的店铺 ID，返回用于 reset 的 token。"""
    return _CURRENT_PLATFORM_SHOP_ID.set(shop_id)


def reset_platform_shop_context(token: Any) -> None:
    _CURRENT_PLATFORM_SHOP_ID.reset(token)


def _tabular_sheet_payload(df: Any, name: str, max_rows: int = 1000) -> Dict[str, Any]:
    """将 pandas DataFrame 转为可 JSON 序列化的表格（供 UI 按表格展示）。"""
    columns = [str(c) for c in df.columns]
    truncated = len(df) > max_rows
    sub = df.head(max_rows)
    rows = sub.fillna("").astype(str).values.tolist()
    return {
        "name": name,
        "columns": columns,
        "rows": rows,
        "truncated": truncated,
        "total_rows": int(len(df)),
    }


def _excel_display_payload_json(path: Path) -> Optional[str]:
    try:
        import pandas as pd
    except ImportError:
        return None
    try:
        excel_file = pd.ExcelFile(str(path))
        sheets = []
        for sheet_name in excel_file.sheet_names:
            df = pd.read_excel(excel_file, sheet_name=sheet_name)
            sheets.append(_tabular_sheet_payload(df, str(sheet_name)))
        return json.dumps({"type": "excel", "sheets": sheets}, ensure_ascii=False)
    except Exception:
        return None


def _csv_display_payload_json(content: str, label: str) -> Optional[str]:
    try:
        import io
        import pandas as pd
        df = pd.read_csv(io.StringIO(content))
        sheet = _tabular_sheet_payload(df, label)
        return json.dumps({"type": "csv", "sheets": [sheet]}, ensure_ascii=False)
    except Exception:
        return None


@dataclass
class DocumentLike:
    """兼容 UI 的轻量文档对象。"""
    id: str
    data: str
    metadata: Dict[str, Any]


class NailLampKnowledgeManager:
    """美甲灯知识库管理器 - 优化检索召回率"""
    # UI 线程与商品同步线程共用，避免 LanceDB/JSON 并发写导致卡死
    _global_io_lock = threading.RLock()

    # 打分仅在正文前若干字内进行，避免超长导入拖慢检索；返回仍用全文
    _SCORE_SNIPPET_CHARS = 12000
    # 参与 embedding 的扩展查询总长上限
    _EMBED_QUERY_TEXT_MAX = 3800
    # 超过该长度的文档按块建向量，避免「整篇均值向量」淹没局部语义、以及仅嵌入前 4000 字丢后半篇的问题
    _CHUNK_LONG_DOC_THRESHOLD = 520
    _CHUNK_TARGET = 480
    _CHUNK_OVERLAP = 96
    _CHUNK_MIN_MERGE = 72

    def __init__(self):
        # 向后兼容属性（UI 代码期望的属性）
        self.knowledge = {}  # 兼容旧 UI 代码
        self.documents = []  # 文档列表
        self.logger = get_logger("NailLampKnowledgeManager")
        self._config = Config()
        self._embedder_client = self._init_embedder_client()
        self._embedder_model = (self._config.get("embedder.model_name", "") or "").strip()
        self._store_file = get_temp_path() / "knowledge_docs.json"
        
        # LanceDB 向量数据库
        self._lancedb_path = get_temp_path() / "lancedb"
        self._lancedb_path.mkdir(parents=True, exist_ok=True)
        self._db = None
        self._knowledge_table = None
        # 产品数据（硬编码兜底数据，当知识库未加载时使用）
        self.products = [
            {
                'id': '111127661',
                'name': 'LIMEGIRL SUNone UV LED 美甲灯',
                'price': '$10.28',
                'price_num': 10.28,
                'power': '24W',
                'bulb_count': 12,
                'features': ['智能感应', '4 档定时', 'USB 供电', '便携', '自动感应'],
                'suitable': ['家庭使用', '美甲沙龙', '旅行携带', '家用'],
                'recommend_for': '家用首选，性价比高',
                'keywords': ['limegirl', 'sunone', 'sun', '家用', '便携', '智能', 'usb']
            },
            {
                'id': '58216780',
                'name': 'SUN X5 Plus UV LED 美甲灯',
                'price': '$13.93',
                'price_num': 13.93,
                'power': '48W',
                'bulb_count': 21,
                'features': ['大功率', '21 颗灯珠', 'LCD 显示屏', '智能感应', '快速固化'],
                'suitable': ['专业美甲店', '家庭工作室', '高频使用', '开店', '商用'],
                'recommend_for': '专业使用，固化速度快',
                'keywords': ['sun', 'x5', 'plus', '专业', '大功率', 'lcd', '开店']
            },
            {
                'id': '16240585',
                'name': 'LKE UV 美甲灯 72W',
                'price': '$8.78',
                'price_num': 8.78,
                'power': '72W',
                'bulb_count': 36,
                'features': ['超大功率', '36 颗灯珠', '可充电', '数显屏幕', '无线'],
                'suitable': ['专业美甲店', '高频使用场景', '开店'],
                'recommend_for': '性价比之王，功率最大',
                'keywords': ['lke', '72w', '大功率', '充电', '性价比', '专业']
            },
            {
                'id': '160636318',
                'name': 'XEIJAYI 粉色迷你鼠标美甲灯',
                'price': '$3.99',
                'price_num': 3.99,
                'power': '6W',
                'bulb_count': 6,
                'features': ['迷你便携', '可爱造型', 'USB 供电', '超低价', '鼠标'],
                'suitable': ['美甲新手', '学生党', '旅行携带', '入门'],
                'recommend_for': '入门首选，价格亲民',
                'keywords': ['xeijayi', '迷你', '鼠标', '便宜', '入门', '新手', '学生', '粉色']
            }
        ]
        
        # 常见问题回复模板 - 扩展关键词
        self.faq_templates = {
            '家用推荐': {
                'keywords': ['家用', '自己用', '家里', '家庭', '个人', '在家'],
                'response': """亲，家用话小美推荐这两款哦~ 💅

✨ **LIMEGIRL SUNone** - $10.28
- 24W 功率，家庭使用刚刚好
- 智能感应，手放进去自动开始
- 4 档定时，满足不同需求
- USB 供电，携带方便
👉 适合：日常家用、偶尔美甲

✨ **SUN X5 Plus** - $13.93
- 48W 大功率，固化速度快
- 21 颗灯珠，全角度覆盖
- LCD 显示屏，时间一目了然
👉 适合：对效果要求高、使用频率高

两款都是热销款，看您的预算选择哦~ 有疑问随时问我！😊"""
            },
            '开店推荐': {
                # 勿用「美甲」等易与「美甲灯」混淆的词根；依赖 _match_intent 严格匹配
                'keywords': ['开店', '商用', '店里', '美甲店', '沙龙', '专业', '工作室'],
                'response': """亲，开店的话小美强烈推荐专业款！💪

✨ **SUN X5 Plus** - $13.93
- 48W 大功率，快速固化
- 21 颗灯珠，效率高
- 耐用可靠，适合高频使用

✨ **LKE UV 72W** - $8.78
- 72W 超大功率，市面最高
- 36 颗灯珠，全方位固化
- 可充电设计，无线使用
- 性价比无敌！

开店建议选功率大的，客户等待时间短，体验更好！需要我发您详细参数吗？😊"""
            },
            '新手推荐': {
                'keywords': ['新手', '入门', '第一次', '不会用', '学生', '初学'],
                'response': """亲，新手入门小美推荐这款！🎀

✨ **XEIJAYI 粉色迷你鼠标款** - $3.99
- 价格超便宜，试错成本低
- 迷你可爱，放包里不占地方
- USB 供电，操作简单
- 6 颗灯珠，日常够用

✨ **LIMEGIRL SUNone** - $10.28
- 功能齐全，智能感应
- 4 档定时，不用自己记时间
- 品质可靠，用个几年没问题

预算有限选迷你款，想要好用点选 SUNone！都很多小姐姐买~ 💖"""
            },
            '固化时间': {
                'keywords': ['固化', '照干', '多久', '时间', '几分钟', '秒', '照灯'],
                'response': """亲，固化时间看指甲油类型哦~ ⏱️

💅 **LED 胶**: 30-60 秒
💅 **UV 胶**: 60-90 秒
💅 **建构胶**: 90-120 秒
💅 **封层**: 60-90 秒

小贴士：
✅ 薄涂多层，每层都彻底固化
✅ 不要涂太厚，不然照不干
✅ 某些胶有浮胶层，需要用清洁液擦拭

具体看您用的胶 brand 和厚度，第一次可以照久一点试试~ 😊"""
            },
            '产品价格': {
                'keywords': ['价格', '多少钱', '价位', '贵', '便宜', '价', '$', '卖', '元', '块', '标价', '定价'],
                'response': """亲，我们家美甲灯价格区间是$3.99-$13.93哦~ 💰

📊 **价格档位**:
- 入门级：$3-8（迷你款、基础款）
- 进阶级：$8-15（SUNone、X5 Plus）
- 专业级：$15-30（大功率、多功能）

现在热销的是：
✨ SUNone - $10.28（家用首选）
✨ X5 Plus - $13.93（专业首选）
✨ 迷你款 - $3.99（入门首选）
✨ LKE 72W - $8.78（性价比王）

看您的预算，我帮您推荐合适的！😊"""
            },
            '物流发货': {
                'keywords': ['发货', '物流', '快递', '多久到', '几天', '运输', '邮'],
                'response': """亲，物流信息如下~ 📦

🚚 **发货时间**: 
- 工作日 24 小时内发货
- 周末和节假日顺延

⏱️ **配送时效**:
- 中国大陆：3-5 天
- 港澳台：5-7 天
- 美国/欧洲：7-15 天

🎁 **运费**:
- 满$50 包邮
- 不满$50 运费$5

下单后我们会第一时间为您安排发货，物流信息会短信通知您~ 😊"""
            },
            '售后保障': {
                'keywords': ['售后', '质保', '退换', '保修', '维修', '坏了', '质量'],
                'response': """亲，售后这边直接给你处理，不需要你先提供单号或商品ID。💪

✅ **30 天无理由退换** - 收到货不满意随时退
✅ **1 年主机质保** - 非人为损坏免费维修
✅ **6 个月灯珠质保** - 灯珠问题免费更换
✅ **终身技术支持** - 使用问题随时咨询

退款场景统一按 **退货退款** 处理（以平台流程为准）。

质保范围：
✅ 质量问题（灯珠不亮、无法启动等）
✅ 运输损坏
❌ 人为损坏（摔坏、进水等）

有任何问题随时联系小美，一定帮您解决到底！💖"""
            },
            '产品介绍': {
                'keywords': ['介绍', '产品', '款式', '推荐', '有什么', '哪些', '看看'],
                'response': ''  # 动态生成
            }
        }
        
        # 同义词映射
        self.synonyms = {
            '家用': ['自己用', '家里', '家庭', '个人', '在家'],
            '开店': ['商用', '店里', '美甲店', '沙龙', '专业', '工作室'],
            '新手': ['入门', '第一次', '不会用', '学生', '初学'],
            '固化': ['照干', '烤干', '烘干', '时间', '多久'],
            '价格': ['钱', '价位', '贵', '便宜', '$'],
            '发货': ['物流', '快递', '运输', '邮'],
            '售后': ['质保', '保修', '维修', '退换', '坏', '退'],
            '功率': ['w', '瓦', 'w'],
            '灯珠': ['灯', 'led', 'uv', '颗', '数量'],
        }

        # 启动时恢复历史知识库，避免重启后丢失
        self._load_documents()
        self._init_lancedb()
        # 启动即补齐缺失向量，避免进入页面才触发
        self.ensure_embeddings_ready()

    def _detect_vector_dimension(self) -> int:
        """推断向量维度（已有 embedding > 探针请求 > 配置/默认 1024）。"""
        for doc in self.documents:
            emb = doc.get("embedding")
            if isinstance(emb, list) and emb:
                return len(emb)
            for chunk in doc.get("chunks") or []:
                if not isinstance(chunk, dict):
                    continue
                ce = chunk.get("embedding")
                if isinstance(ce, list) and ce:
                    return len(ce)
        probe = self._embed_text(".")
        if probe:
            return len(probe)
        cfg_dim = self._config.get("embedder.dimensions")
        if cfg_dim is not None:
            try:
                return max(1, int(cfg_dim))
            except (TypeError, ValueError):
                pass
        return 1024

    @staticmethod
    def _lancedb_seed_row(dim: int) -> Dict[str, Any]:
        """创建空表时用的占位行（创建后立即删除）。"""
        return {
            "id": "__lancedb_init__",
            "content": "",
            "vector": [0.0] * dim,
            "platform_shop_id": "",
            "inherit_key": "",
            "allow_child_override": False,
            "title": "",
            "filename": "",
            "source": "",
        }

    def _init_lancedb(self) -> None:
        """初始化 LanceDB 向量数据库"""
        try:
            self._db = lancedb.connect(str(self._lancedb_path))

            if "knowledge" in self._db.table_names():
                self._knowledge_table = self._db.open_table("knowledge")
                self.logger.info("LanceDB 知识库表打开成功")
                return

            dim = self._detect_vector_dimension()
            self._knowledge_table = self._db.create_table(
                "knowledge", [self._lancedb_seed_row(dim)]
            )
            try:
                self._knowledge_table.delete("id = '__lancedb_init__'")
            except Exception as del_err:
                self.logger.debug(f"删除 LanceDB 占位行失败（可忽略）：{del_err}")

            self.logger.info(f"LanceDB 知识库表创建成功 (vector_dim={dim})")
            if self.documents:
                synced = self._sync_all_docs_to_lancedb()
                self.logger.info(f"LanceDB 已同步历史文档：{synced} 条")
        except Exception as e:
            self.logger.error(f"LanceDB 初始化失败：{e}")
            self._db = None
            self._knowledge_table = None

    @staticmethod
    def _doc_visible_for_shop(doc: Dict[str, Any], shop_id: Optional[str]) -> bool:
        """
        未设置 platform_shop_id（或空）→ 父知识库（全店通用）；设置了则仅匹配该拼多多店铺 ID（子知识库）。
        shop_id 为空且需要过滤时：非通用文档不可见（避免串店）。
        """
        raw = doc.get("platform_shop_id")
        if raw is None or str(raw).strip() == "":
            return True
        if shop_id is None or str(shop_id).strip() == "":
            return False
        return str(raw).strip() == str(shop_id).strip()

    @staticmethod
    def _inherit_key(doc: Dict[str, Any]) -> str:
        """同一业务键下，子库可覆盖父库；未设置则每条文档独立（不参与覆盖合并）。"""
        ik = (doc.get("inherit_key") or "").strip()
        return ik

    @staticmethod
    def _parent_allows_child_override(doc: Dict[str, Any]) -> bool:
        """父库条目是否显式允许被子店同 inherit_key 覆盖（默认否，兼容旧数据）。"""
        v = doc.get("allow_child_override")
        if v is True:
            return True
        if v is False or v is None:
            return False
        s = str(v).strip().lower()
        return s in ("1", "true", "yes", "on")

    def _shop_override_inherit_keys(
        self, pool: List[Dict[str, Any]], shop_id: Optional[str]
    ) -> set:
        """当前店铺下、带 inherit_key 的子库文档所声明的键（仅用于与「允许被覆盖」的父条配对）。"""
        if not shop_id or not str(shop_id).strip():
            return set()
        sid = str(shop_id).strip()
        keys: set = set()
        for d in pool:
            ps = (d.get("platform_shop_id") or "").strip()
            if ps != sid:
                continue
            ik = self._inherit_key(d)
            if ik:
                keys.add(ik)
        return keys

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
            if not ps and ik and ik in override_keys and self._parent_allows_child_override(d):
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

    def _load_documents(self) -> None:
        """从本地 JSON 恢复文档数据。"""
        try:
            self._store_file.parent.mkdir(parents=True, exist_ok=True)
            if not self._store_file.exists():
                return
            raw = self._store_file.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, list):
                self.documents = data
        except Exception:
            # 持久化恢复失败不应阻断应用启动
            self.documents = self.documents or []

    @staticmethod
    def _ensure_doc_created_at(doc: Dict[str, Any]) -> None:
        """为文档打上 created_at，供生命周期向量清理使用。"""
        if not isinstance(doc, dict):
            return
        if doc.get("created_at"):
            return
        meta = doc.get("metadata")
        if isinstance(meta, dict) and meta.get("created_at"):
            doc["created_at"] = meta["created_at"]
            return
        doc["created_at"] = datetime.now().isoformat(timespec="seconds")

    def _save_documents(self) -> None:
        """将文档数据持久化到本地 JSON。"""
        with self._global_io_lock:
            try:
                for d in self.documents:
                    self._ensure_doc_created_at(d)
                self._store_file.parent.mkdir(parents=True, exist_ok=True)
                self._store_file.write_text(
                    json.dumps(self.documents, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception:
                # 保存失败不抛出，避免影响主流程
                pass

    def ensure_embeddings_ready(self) -> int:
        """
        启动时补齐缺失 embedding。
        返回本次补齐数量。
        """
        if not self.documents:
            return 0
        if not self._embedder_client or not self._embedder_model:
            self.logger.warning("embedding 配置不完整，跳过启动向量补齐")
            return 0

        updated = 0
        for d in self.documents:
            if self._ensure_doc_chunks_and_embeddings(d):
                updated += 1

        if updated > 0:
            self._save_documents()
            self.logger.info(f"启动补齐 embedding 完成: {updated} 条")
        return updated

    def _init_embedder_client(self) -> Optional[OpenAI]:
        """初始化 embedding 客户端（可选）。"""
        api_key = (self._config.get("embedder.api_key", "") or "").strip()
        api_base = (self._config.get("embedder.api_base", "") or "").strip()
        if not api_key or not api_base:
            return None
        try:
            return OpenAI(api_key=api_key, base_url=api_base)
        except Exception:
            return None

    def _embed_text(self, text: str) -> Optional[List[float]]:
        """生成文本向量，失败时返回 None。"""
        if not self._embedder_client or not self._embedder_model or not text.strip():
            return None
        try:
            # 限制长度避免超限
            sample = text[:4000]
            resp = self._embedder_client.embeddings.create(
                model=self._embedder_model,
                input=sample
            )
            return list(resp.data[0].embedding)
        except Exception:
            return None

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
        if '美甲灯' in query:
            expanded.extend(['美甲', '灯', '光疗灯', 'uv 灯', 'led 灯'])
        if '多少钱' in query:
            expanded.extend(['价格', '价', '$', '贵', '便宜'])
        if '家用' in query:
            expanded.extend(['自己用', '家里', '家庭'])
        if '开店' in query:
            expanded.extend(['商用', '店里', '专业'])

        return list(set(expanded))

    def _split_content_chunks(self, text: str) -> List[str]:
        """按段落与长度切分，适合中文长文检索。"""
        text = (text or "").strip()
        if not text:
            return []
        if len(text) <= self._CHUNK_TARGET:
            return [text]

        paras = [p.strip() for p in re.split(r"\n\s*\n+", text) if p.strip()]
        if not paras:
            return [text[: self._CHUNK_TARGET]]

        chunks: List[str] = []
        buf = ""
        for p in paras:
            if len(p) > self._CHUNK_TARGET:
                if buf:
                    chunks.append(buf)
                    buf = ""
                start = 0
                while start < len(p):
                    end = min(start + self._CHUNK_TARGET, len(p))
                    chunks.append(p[start:end])
                    if end >= len(p):
                        break
                    start = end - self._CHUNK_OVERLAP
                    if start < 0:
                        start = 0
                continue
            if not buf:
                buf = p
            elif len(buf) + 2 + len(p) <= self._CHUNK_TARGET:
                buf = buf + "\n\n" + p
            else:
                chunks.append(buf)
                buf = p
        if buf:
            chunks.append(buf)

        merged: List[str] = []
        for c in chunks:
            if merged and len(c) < self._CHUNK_MIN_MERGE:
                merged[-1] = merged[-1] + "\n\n" + c
            else:
                merged.append(c)
        return merged if merged else [text[: self._CHUNK_TARGET]]

    def _build_chunk_entries(self, content: str) -> List[Dict[str, Any]]:
        """为长文档生成带向量的分块列表。"""
        parts = self._split_content_chunks(content)
        out: List[Dict[str, Any]] = []
        for part in parts:
            emb = self._embed_text(part)
            out.append({"text": part, "embedding": emb})
        return out

    @staticmethod
    def _header_for_doc(doc: Dict[str, Any]) -> str:
        parts = [str(doc.get("title") or ""), str(doc.get("filename") or "")]
        return " ".join(x.strip() for x in parts if x and str(x).strip()).strip()

    def _document_should_use_chunks(self, content: str) -> bool:
        return len((content or "").strip()) > self._CHUNK_LONG_DOC_THRESHOLD

    def _ensure_doc_chunks_and_embeddings(self, doc: Dict[str, Any]) -> bool:
        """
        长文档补全 chunks；短文档保证顶层 embedding。
        若内容已变更需调用方自行处理；此处仅补齐缺失结构。
        返回是否修改了 doc（需写盘）。
        """
        content = str(doc.get("content", "")).strip()
        if not content:
            return False
        changed = False
        if self._document_should_use_chunks(content):
            raw_chunks = doc.get("chunks")
            need_rebuild = not isinstance(raw_chunks, list) or len(raw_chunks) == 0
            if not need_rebuild:
                for c in raw_chunks:
                    if not isinstance(c, dict) or not str(c.get("text", "")).strip():
                        need_rebuild = True
                        break
            if need_rebuild:
                doc["chunks"] = self._build_chunk_entries(content)
                ce = doc["chunks"][0].get("embedding") if doc["chunks"] else None
                if isinstance(ce, list) and ce:
                    doc["embedding"] = ce
                changed = True
            else:
                for c in doc["chunks"]:
                    if not isinstance(c, dict):
                        continue
                    txt = str(c.get("text", "")).strip()
                    if not txt:
                        continue
                    if not (isinstance(c.get("embedding"), list) and c.get("embedding")):
                        vec = self._embed_text(txt)
                        if vec:
                            c["embedding"] = vec
                            changed = True
                ch0 = doc["chunks"][0] if doc["chunks"] else None
                e0 = ch0.get("embedding") if isinstance(ch0, dict) else None
                if isinstance(e0, list) and e0 and not (
                    isinstance(doc.get("embedding"), list) and doc.get("embedding")
                ):
                    doc["embedding"] = e0
                    changed = True
        else:
            if not (isinstance(doc.get("embedding"), list) and doc.get("embedding")):
                vec = self._embed_text(content)
                if vec:
                    doc["embedding"] = vec
                    changed = True
        return changed

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
                units.append(
                    (sn, emb if isinstance(emb, list) and emb else None)
                )
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
        comb = (header + "\n" + unit_snippet_lower).lower() if header else unit_snippet_lower
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

    def _match_intent(self, query: str, template_keywords: List[str]) -> Tuple[bool, int]:
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
                intro += f"   功率：{p['power']} | 特点：{','.join(p['features'][:2])}\n"
                intro += f"   👉 {p['recommend_for']}\n\n"
            intro += "亲告诉我您的使用场景（家用/开店）和预算，我帮您推荐最合适的！😊"
            return intro
        
        # 根据场景推荐 - 使用宽松匹配
        scenario_lower = scenario.lower()
        
        # 家用匹配
        if any(kw in scenario_lower for kw in ['家用', '自己', '家里', '家庭', '个人']):
            return self.faq_templates['家用推荐']['response']
        # 开店匹配
        elif any(kw in scenario_lower for kw in ['开店', '商用', '店里', '专业', '沙龙']):
            return self.faq_templates['开店推荐']['response']
        # 新手匹配
        elif any(kw in scenario_lower for kw in ['新手', '入门', '第一次', '学生']):
            return self.faq_templates['新手推荐']['response']
        else:
            # 默认返回家用推荐
            return self.faq_templates['家用推荐']['response']
    
    def answer_question(self, question: str) -> str:
        """回答问题，使用宽松匹配策略"""
        question_lower = question.lower()
        
        # 特殊问题处理 - 最优先匹配
        # 功率相关
        if any(kw in question_lower for kw in ['功率', 'w', '瓦']):
            return self._answer_power_question()
        # 灯珠相关 - 优先匹配数量相关词
        if any(kw in question_lower for kw in ['灯珠数量', '多少颗', '几颗灯', '灯珠', 'led 灯', 'uv 灯']):
            return self._answer_bulb_question()
        # 售后相关 - 优先匹配质保、保修
        if any(kw in question_lower for kw in ['质保', '保修', '坏了', '退', '维修', '售后']):
            return self.faq_templates['售后保障']['response']
        # 对比相关
        if any(kw in question_lower for kw in ['对比', '区别', '哪个好']):
            return self._answer_comparison_question()
        # 使用相关 - 精确匹配，避免误匹配"家庭使用"
        if any(kw in question_lower for kw in ['怎么用', '如何使用', '操作', '教程', '用法']):
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
                keywords = template_data.get('keywords', [])
                response = template_data.get('response', '')
                
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
    
    def search_knowledge(self, query: str, top_k: int = 5, **kwargs) -> List[Dict]:
        """向后兼容 - 旧 UI 代码使用"""
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
                    results = self._knowledge_table.search(query_vec).limit(limit * 2).to_pandas()
                    
                    if not results.empty:
                        # 过滤店铺可见性
                        eff_shop = explicit_shop if explicit_shop is not None else get_current_platform_shop_id()
                        filtered = []
                        for _, row in results.iterrows():
                            doc = {
                                "id": row["id"],
                                "content": row["content"],
                                "platform_shop_id": row.get("platform_shop_id", ""),
                                "inherit_key": row.get("inherit_key", ""),
                                "allow_child_override": row.get("allow_child_override", False),
                                "title": row.get("title", ""),
                                "filename": row.get("filename", ""),
                                "source": row.get("source", ""),
                            }
                            if self._doc_visible_for_shop(doc, eff_shop):
                                filtered.append((row.get("_distance", 0), doc))
                        
                        # 按距离排序（越小越相关）
                        filtered.sort(key=lambda x: x[0])
                        top = filtered[:limit]

                        self.logger.debug(f"LanceDB 检索：query='{query[:50]}...', top_k={limit}, 返回 {len(top)} 条")

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
                                        "platform_shop_id": d.get("platform_shop_id") or "",
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
                                            {"display_payload": str(d["display_payload"])}
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
            eff_shop = explicit_shop if explicit_shop is not None else get_current_platform_shop_id()
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
        ranked = self._apply_parent_override_filter(ranked, pool, explicit_shop if explicit_shop is not None else get_current_platform_shop_id())
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
    
    def add_document(self, doc: Dict) -> None:
        """向后兼容 - 旧 UI 代码使用"""
        self.documents.append(doc)
        self._save_documents()
        
        # 同步到 LanceDB
        self._add_doc_to_lancedb(doc)
    
    def _add_doc_to_lancedb(self, doc: Dict) -> bool:
        """将文档添加到 LanceDB"""
        if not self._knowledge_table:
            return False
        
        try:
            content = str(doc.get("content", ""))
            if not content.strip():
                return False
            
            # 生成向量
            query_text = self._build_embedding_query_text(content)
            vector = self._embed_text(query_text) if query_text else None
            
            if not vector:
                self.logger.warning(f"文档 {doc.get('id', 'unknown')} 无法生成向量")
                return False
            
            # 准备数据
            data = {
                "id": str(doc.get("id", "")),
                "content": content,
                "vector": vector,
                "platform_shop_id": str(doc.get("platform_shop_id", "") or ""),
                "inherit_key": str(doc.get("inherit_key", "") or ""),
                "allow_child_override": bool(doc.get("allow_child_override", False)),
                "title": str(doc.get("title", "") or ""),
                "filename": str(doc.get("filename", "") or ""),
                "source": str(doc.get("source", "") or ""),
            }
            
            # 添加到 LanceDB
            self._knowledge_table.add([data])
            self.logger.debug(f"LanceDB 添加文档：id={data['id']}, content_len={len(content)}")
            return True
            
        except Exception as e:
            self.logger.error(f"LanceDB 添加文档失败：{e}")
            return False
    
    def _sync_all_docs_to_lancedb(self) -> int:
        """同步所有文档到 LanceDB"""
        if not self._knowledge_table:
            return 0
        
        count = 0
        for doc in self.documents:
            if self._add_doc_to_lancedb(doc):
                count += 1
        
        self.logger.info(f"LanceDB 同步完成：{count} 条文档")
        return count
    
    def remove_document(self, doc_id: str) -> None:
        """向后兼容 - 旧 UI 代码使用"""
        self.documents = [d for d in self.documents if d.get('id') != doc_id]
        self._save_documents()
    
    def get_content_count(self) -> int:
        """向后兼容 - 旧 UI 代码使用 - 返回内容数量"""
        return len(self.documents)
    
    def get_knowledge_count(self) -> int:
        """向后兼容 - 旧 UI 代码使用 - 返回知识数量"""
        return len(self.documents)
    
    def get_all_documents(self) -> List[Dict]:
        """向后兼容 - 旧 UI 代码使用 - 返回所有文档"""
        return self.documents
    
    def get_all_contents(self) -> List[Dict]:
        """向后兼容 - 旧 UI 代码使用 - 返回所有内容"""
        return self.documents

    def update_document(self, doc_id: str, updates: Dict[str, Any]) -> bool:
        """更新文档（UI 编辑）；正文变更时清除表格类 display_payload。"""
        doc_id = str(doc_id)
        for i, doc in enumerate(self.documents):
            if str(doc.get("id")) != doc_id:
                continue
            merged = dict(doc)
            for k, v in (updates or {}).items():
                if k == "display_payload" and v is None:
                    merged.pop("display_payload", None)
                    continue
                merged[k] = v
            if "content" in (updates or {}):
                merged.pop("display_payload", None)
            self.documents[i] = merged
            self._save_documents()
            if self._knowledge_table:
                try:
                    self._knowledge_table.delete(f"id = '{doc_id}'")
                except Exception:
                    pass
            self._add_doc_to_lancedb(merged)
            return True
        return False

    async def add_content_from_file(
        self,
        file_path: str,
        platform_shop_id: Optional[str] = None,
        inherit_key: Optional[str] = None,
        allow_child_override: bool = False,
    ) -> int:
        """
        向后兼容 - UI 导入入口（异步）。
        返回新增记录数。
        """
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        suffix = path.suffix.lower()
        content = ""
        title = path.stem

        if suffix in {".txt", ".text", ".md", ".markdown", ".csv"}:
            content = path.read_text(encoding="utf-8", errors="ignore")
        elif suffix == ".json":
            raw = path.read_text(encoding="utf-8", errors="ignore")
            try:
                obj = json.loads(raw)
                content = json.dumps(obj, ensure_ascii=False, indent=2)
            except Exception:
                content = raw
        elif suffix in {".xlsx", ".xls"}:
            # Excel 文件解析
            try:
                import pandas as pd
                if suffix == ".xlsx":
                    df = pd.read_excel(str(path), engine="openpyxl")
                else:  # .xls
                    df = pd.read_excel(str(path), engine="xlrd")
                
                # 将所有列的内容合并
                content_parts = []
                for col in df.columns:
                    col_content = df[col].dropna().astype(str).tolist()
                    if col_content:
                        content_parts.append(f"## {col}\n" + "\n".join(col_content))
                
                content = "\n\n".join(content_parts).strip()
                
                if not content:
                    # 尝试读取所有 sheet
                    excel_file = pd.ExcelFile(str(path))
                    all_parts = []
                    for sheet_name in excel_file.sheet_names:
                        df_sheet = pd.read_excel(excel_file, sheet_name=sheet_name)
                        sheet_parts = []
                        for col in df_sheet.columns:
                            col_content = df_sheet[col].dropna().astype(str).tolist()
                            if col_content:
                                sheet_parts.append(f"### {sheet_name} - {col}\n" + "\n".join(col_content))
                        all_parts.extend(sheet_parts)
                    content = "\n\n".join(all_parts).strip()
                    
            except ImportError as ie:
                raise RuntimeError(f"Excel 解析失败：缺少依赖库 - {ie}. 请运行 `uv add openpyxl xlrd`") from ie
            except Exception as e:
                raise RuntimeError(f"Excel 解析失败：{e}") from e
        elif suffix == ".pdf":
            try:
                from pypdf import PdfReader
                reader = PdfReader(str(path))
                parts = []
                for p in reader.pages:
                    t = (p.extract_text() or "").strip()
                    if t:
                        parts.append(t)
                content = "\n\n".join(parts).strip()
            except Exception as e:
                raise RuntimeError(f"PDF 解析失败: {e}") from e
        else:
            # 其它类型先尝试文本方式兜底读取
            content = path.read_text(encoding="utf-8", errors="ignore")

        if not content.strip():
            raise ValueError("导入完成，但文件未提取到可用文本内容")

        import_format_map: Dict[str, str] = {
            ".md": "markdown",
            ".markdown": "markdown",
            ".txt": "text",
            ".text": "text",
            ".csv": "csv",
            ".json": "json",
            ".xlsx": "excel",
            ".xls": "excel",
            ".pdf": "pdf",
        }
        import_format = import_format_map.get(suffix, "text")
        display_payload: Optional[str] = None
        if import_format == "excel":
            display_payload = _excel_display_payload_json(path)
        elif import_format == "csv":
            display_payload = _csv_display_payload_json(content, path.name)

        doc_id = f"doc_{len(self.documents)+1}"
        ps = (platform_shop_id or "").strip() or None
        ik = (inherit_key or "").strip() or None
        allow_ov = bool(allow_child_override) if (not ps and ik) else False
        rec: Dict[str, Any] = {
            "id": doc_id,
            "title": title,
            "filename": path.name,
            "content": content,
            "source": "import_file",
            "import_format": import_format,
            "platform_shop_id": ps,
            "inherit_key": ik,
            "allow_child_override": allow_ov,
        }
        if display_payload:
            rec["display_payload"] = display_payload
        if self._document_should_use_chunks(content):
            rec["chunks"] = self._build_chunk_entries(content)
            rec["embedding"] = (
                rec["chunks"][0].get("embedding")
                if rec["chunks"]
                else self._embed_text(content[:4000])
            )
        else:
            rec["embedding"] = self._embed_text(content)

        self.documents.append(rec)
        self._save_documents()
        self._add_doc_to_lancedb(rec)
        return 1

    async def add_text_content(
        self,
        title: str,
        content: str,
        platform_shop_id: Optional[str] = None,
        inherit_key: Optional[str] = None,
        allow_child_override: bool = False,
    ) -> bool:
        """向后兼容 - 添加文本内容（异步）。"""
        if not title or not content:
            return False
        doc_id = f"doc_{len(self.documents)+1}"
        psid = (platform_shop_id or "").strip() or None
        ik = (inherit_key or "").strip() or None
        allow_ov = bool(allow_child_override) if (not psid and ik) else False
        row: Dict[str, Any] = {
            "id": doc_id,
            "title": title,
            "filename": f"{title}.txt",
            "content": content,
            "source": "manual_input",
            "import_format": "manual",
            "platform_shop_id": psid,
            "inherit_key": ik,
            "allow_child_override": allow_ov,
        }
        if self._document_should_use_chunks(content):
            row["chunks"] = self._build_chunk_entries(content)
            row["embedding"] = (
                row["chunks"][0].get("embedding")
                if row["chunks"]
                else self._embed_text(content[:4000])
            )
        else:
            row["embedding"] = self._embed_text(content)
        self.documents.append(row)
        self._save_documents()
        self._add_doc_to_lancedb(row)
        return True

    def list_documents_for_ui(self, platform_shop_id: Optional[str] = None) -> List[Dict]:
        """知识库 UI：仅展示全店通用 + 指定店铺子库，并隐藏已被子库覆盖的父条。"""
        sid = (platform_shop_id or "").strip() or None
        if not sid:
            return list(self.documents)
        visible = [d for d in self.documents if self._doc_visible_for_shop(d, sid)]
        return self._drop_overridden_parents_from_list(visible, sid)

    def delete_goods_sync_documents(self, platform_shop_id: str) -> int:
        """删除某店铺此前 goods_sync 写入的文档（全量同步前清理）。"""
        with self._global_io_lock:
            sid = str(platform_shop_id or "").strip()
            if not sid:
                return 0
            remove_ids: List[str] = []
            kept: List[Dict[str, Any]] = []
            for d in self.documents:
                ps = (d.get("platform_shop_id") or "").strip()
                src = (d.get("source") or "").strip()
                if src == "goods_sync" and ps == sid:
                    remove_ids.append(str(d.get("id")))
                else:
                    kept.append(d)
            if not remove_ids:
                return 0
            self.documents = kept
            if self._knowledge_table:
                for doc_id in remove_ids:
                    try:
                        self._knowledge_table.delete(f"id = '{doc_id}'")
                    except Exception as e:
                        self.logger.warning(f"LanceDB 删除 goods_sync 文档失败：{e}")
            self._save_documents()
            return len(remove_ids)

    def _build_goods_sync_row(
        self,
        *,
        platform_shop_id: str,
        goods_id: str,
        title: str,
        content: str,
        compute_embedding: bool = True,
    ) -> Optional[Dict[str, Any]]:
        sid = str(platform_shop_id or "").strip()
        gid = str(goods_id or "").strip()
        if not sid or not gid or not title or not content:
            return None
        doc_id = f"goods_sync_{sid}_{gid}"
        row: Dict[str, Any] = {
            "id": doc_id,
            "title": title,
            "filename": f"{title}.md",
            "content": content,
            "source": "goods_sync",
            "import_format": "markdown",
            "platform_shop_id": sid,
            "inherit_key": f"goods:{gid}",
            "allow_child_override": False,
        }
        if compute_embedding:
            if self._document_should_use_chunks(content):
                row["chunks"] = self._build_chunk_entries(content)
                row["embedding"] = (
                    row["chunks"][0].get("embedding")
                    if row["chunks"]
                    else self._embed_text(content[:4000])
                )
            else:
                row["embedding"] = self._embed_text(content)
        return row

    def upsert_goods_sync_document(
        self,
        *,
        platform_shop_id: str,
        goods_id: str,
        title: str,
        content: str,
    ) -> bool:
        """
        写入/更新店铺商品子知识库。
        inherit_key=goods:{id} 与父库同键时，父条需 allow_child_override 才会在检索中被隐藏。
        """
        row = self._build_goods_sync_row(
            platform_shop_id=platform_shop_id,
            goods_id=goods_id,
            title=title,
            content=content,
        )
        if not row:
            return False
        doc_id = str(row["id"])
        with self._global_io_lock:
            updated = False
            for i, doc in enumerate(self.documents):
                if str(doc.get("id")) == doc_id:
                    self.documents[i] = row
                    updated = True
                    break
            if not updated:
                self.documents.append(row)
            if self._knowledge_table:
                try:
                    self._knowledge_table.delete(f"id = '{doc_id}'")
                except Exception:
                    pass
            self._add_doc_to_lancedb(row)
            self._save_documents()
        return True

    def bulk_upsert_goods_sync_documents(
        self,
        rows: List[Dict[str, Any]],
    ) -> int:
        """
        批量写入商品同步文档（单次落盘 + 向量索引），供后台同步使用，避免每商品写盘卡 UI。
        """
        if not rows:
            return 0
        written = 0
        with self._global_io_lock:
            for row in rows:
                doc_id = str(row.get("id") or "")
                if not doc_id:
                    continue
                updated = False
                for i, doc in enumerate(self.documents):
                    if str(doc.get("id")) == doc_id:
                        self.documents[i] = row
                        updated = True
                        break
                if not updated:
                    self.documents.append(row)
                written += 1
            if self._knowledge_table:
                for row in rows:
                    doc_id = str(row.get("id") or "")
                    if not doc_id:
                        continue
                    try:
                        self._knowledge_table.delete(f"id = '{doc_id}'")
                    except Exception:
                        pass
                for row in rows:
                    self._add_doc_to_lancedb(row)
            self._save_documents()
        return written

    def delete_document(self, doc_id: str) -> bool:
        """向后兼容 - 删除文档。"""
        before = len(self.documents)
        self.documents = [d for d in self.documents if str(d.get("id")) != str(doc_id)]
        changed = len(self.documents) < before
        if changed:
            self._save_documents()
            if self._knowledge_table:
                try:
                    self._knowledge_table.delete(f"id = '{doc_id}'")
                except Exception as e:
                    self.logger.warning(f"LanceDB 删除文档失败：{e}")
        return changed
    
    def format_product_card(self, product: Dict) -> str:
        """格式化产品卡片，不暴露内部 ID"""
        card = f"✨ **{product['name']}**\n"
        card += f"💰 价格：{product['price']}\n"
        card += f"⚡ 功率：{product['power']}\n"
        card += f"🌟 特点：{'、'.join(product['features'])}\n"
        card += f"👥 适合：{'、'.join(product['suitable'])}\n"
        card += f"💡 推荐：{product['recommend_for']}"
        return card


# 全局单例
knowledge_manager = NailLampKnowledgeManager()


# 向后兼容 - 旧代码使用的类名
KnowledgeManager = NailLampKnowledgeManager


def get_nail_lamp_response(user_message: str, context: Optional[Dict] = None) -> str:
    """
    获取美甲灯客服回复
    
    Args:
        user_message: 用户消息
        context: 对话上下文（可选）
    
    Returns:
        客服回复
    """
    # 使用知识库管理器生成回复
    return knowledge_manager.answer_question(user_message)
