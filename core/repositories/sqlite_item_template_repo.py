import sqlite3
import threading
from typing import Optional, List, Dict, Any

# 导入抽象基类和领域模型
from .abstract_repository import AbstractItemTemplateRepository
from ..domain.models import Fish, Rod, Bait, Accessory, Title, Item

class SqliteItemTemplateRepository(AbstractItemTemplateRepository):
    """物品模板仓储的SQLite实现"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._local = threading.local()
        # 内存模板缓存，彻底消除背包/状态/钓鱼时的 N+1 重复查询
        self._fish_cache: Dict[int, Fish] = {}
        self._all_fish_cached: bool = False
        self._rod_cache: Dict[int, Rod] = {}
        self._all_rods_cached: bool = False
        self._accessory_cache: Dict[int, Accessory] = {}
        self._all_accessories_cached: bool = False
        self._bait_cache: Dict[int, Bait] = {}
        self._all_baits_cached: bool = False
        self._item_cache: Dict[int, Item] = {}
        self._all_items_cached: bool = False
        self._title_cache: Dict[int, Title] = {}
        self._all_titles_cached: bool = False
        self._title_by_name_cache: Dict[str, Title] = {}
        self._item_by_name_cache: Dict[str, Item] = {}
        self._cache_lock = threading.Lock()

    def _get_connection(self) -> sqlite3.Connection:
        """获取一个线程安全的数据库连接。"""
        conn = getattr(self._local, "connection", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode = WAL;")
            conn.execute("PRAGMA synchronous = NORMAL;")
            conn.execute("PRAGMA cache_size = -64000;")
            self._local.connection = conn
        return conn

    # --- 私有映射辅助方法 ---
    def _row_to_fish(self, row: sqlite3.Row) -> Optional[Fish]:
        if not row:
            return None
        return Fish(**row)

    def _row_to_rod(self, row: sqlite3.Row) -> Optional[Rod]:
        if not row:
            return None
        return Rod(**row)

    def _row_to_bait(self, row: sqlite3.Row) -> Optional[Bait]:
        if not row:
            return None
        return Bait(**row)

    def _row_to_accessory(self, row: sqlite3.Row) -> Optional[Accessory]:
        if not row:
            return None
        return Accessory(**row)

    def _row_to_title(self, row: sqlite3.Row) -> Optional[Title]:
        if not row:
            return None
        return Title(**row)

    def _row_to_item(self, row: sqlite3.Row) -> Optional[Item]:
        if not row:
            return None
        return Item(**row)

    def _to_domain(self, row: sqlite3.Row) -> Item:
        return Item(
            item_id=row[0],
            name=row[1],
            description=row[2],
            rarity=row[3],
            effect_description=row[4],
            cost=row[5],
            is_consumable=bool(row[6]),
            icon_url=row[7],
            effect_type=row[8] if len(row) > 8 else None,
            effect_payload=row[9] if len(row) > 9 else None,
        )


    def add(self, item: Item):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO items (name, description, rarity, effect_description, cost, is_consumable, icon_url, effect_type, effect_payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item.name,
                    item.description,
                    item.rarity,
                    item.effect_description,
                    item.cost,
                    item.is_consumable,
                    item.icon_url,
                    item.effect_type,
                    item.effect_payload,
                ),
            )
            conn.commit()
        with self._cache_lock:
            self._item_cache.clear()
            self._item_by_name_cache.clear()
            self._all_items_cached = False

    def get_by_id(self, item_id: int) -> Optional[Item]:
        with self._cache_lock:
            if item_id in self._item_cache:
                return self._item_cache[item_id]
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT item_id, name, description, rarity, effect_description, cost, is_consumable, icon_url, effect_type, effect_payload FROM items WHERE item_id = ?",
                (item_id,),
            )
            row = cursor.fetchone()
            item = self._to_domain(row) if row else None
            if item:
                with self._cache_lock:
                    self._item_cache[item_id] = item
            return item

    def get_all(self) -> List[Item]:
        with self._cache_lock:
            if self._all_items_cached:
                return list(self._item_cache.values())
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT item_id, name, description, rarity, effect_description, cost, is_consumable, icon_url, effect_type, effect_payload FROM items"
            )
            rows = cursor.fetchall()
            items = [self._to_domain(row) for row in rows] if rows else []
            with self._cache_lock:
                for item in items:
                    self._item_cache[item.item_id] = item
                self._all_items_cached = True
            return items

    def get_by_name(self, name: str) -> Optional[Item]:
        with self._cache_lock:
            if name in self._item_by_name_cache:
                return self._item_by_name_cache[name]
        with self._get_connection() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                "SELECT item_id, name, description, rarity, effect_description, cost, is_consumable, icon_url, effect_type, effect_payload FROM items WHERE name = ?",
                (name,),
            )
            row = cursor.fetchone()
            item = self._to_domain(row) if row else None
            if item:
                with self._cache_lock:
                    self._item_by_name_cache[name] = item
                    self._item_cache[item.item_id] = item
            return item

    def update(self, item: Item):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE items
                SET name = ?, description = ?, rarity = ?, effect_description = ?, cost = ?, is_consumable = ?, icon_url = ?, effect_type = ?, effect_payload = ?
                WHERE item_id = ?
                """,
                (
                    item.name,
                    item.description,
                    item.rarity,
                    item.effect_description,
                    item.cost,
                    item.is_consumable,
                    item.icon_url,
                    item.effect_type,
                    item.effect_payload,
                    item.item_id,
                ),
            )
            conn.commit()
        with self._cache_lock:
            self._item_cache.clear()
            self._item_by_name_cache.clear()
            self._all_items_cached = False

    def _to_domain_from_row(self, row: sqlite3.Row) -> Item:
        """从 sqlite3.Row 对象转换到领域模型"""
        return Item(
            item_id=row["item_id"],
            name=row["name"],
            description=row["description"],
            rarity=row["rarity"],
            effect_description=row["effect_description"],
            cost=row["cost"],
            is_consumable=bool(row["is_consumable"]),
            icon_url=row["icon_url"],
            effect_type=row["effect_type"] if "effect_type" in row.keys() else None,
            effect_payload=(
                row["effect_payload"] if "effect_payload" in row.keys() else None
            ),
        )

    # --- Fish Read Methods ---
    def get_fish_by_id(self, fish_id: int) -> Optional[Fish]:
        with self._cache_lock:
            if fish_id in self._fish_cache:
                return self._fish_cache[fish_id]
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM fish WHERE fish_id = ?", (fish_id,))
            fish = self._row_to_fish(cursor.fetchone())
            if fish:
                with self._cache_lock:
                    self._fish_cache[fish_id] = fish
            return fish

    def get_all_fish(self) -> List[Fish]:
        with self._cache_lock:
            if self._all_fish_cached:
                return sorted(self._fish_cache.values(), key=lambda f: (f.rarity, f.base_value), reverse=True)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM fish ORDER BY rarity DESC, base_value DESC")
            fishes = [self._row_to_fish(row) for row in cursor.fetchall()]
            with self._cache_lock:
                for fish in fishes:
                    self._fish_cache[fish.fish_id] = fish
                self._all_fish_cached = True
            return fishes

    def get_random_fish(self, rarity: Optional[int] = None) -> Optional[Fish]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if rarity is not None:
                cursor.execute("SELECT * FROM fish WHERE rarity = ? ORDER BY RANDOM() LIMIT 1", (rarity,))
            else:
                cursor.execute("SELECT * FROM fish ORDER BY RANDOM() LIMIT 1")
            row = cursor.fetchone()
            return self._row_to_fish(row) if row else None

    def get_fishes_by_rarity(self, rarity: int) -> List[Fish]:
        with self._cache_lock:
            if self._all_fish_cached:
                return [f for f in self._fish_cache.values() if f.rarity == rarity]
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM fish WHERE rarity = ?", (rarity,))
            return [self._row_to_fish(row) for row in cursor.fetchall()]

    # --- Rod Read Methods ---
    def get_rod_by_id(self, rod_id: int) -> Optional[Rod]:
        with self._cache_lock:
            if rod_id in self._rod_cache:
                return self._rod_cache[rod_id]
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM rods WHERE rod_id = ?", (rod_id,))
            rod = self._row_to_rod(cursor.fetchone())
            if rod:
                with self._cache_lock:
                    self._rod_cache[rod_id] = rod
            return rod

    def get_all_rods(self) -> List[Rod]:
        with self._cache_lock:
            if self._all_rods_cached:
                return sorted(self._rod_cache.values(), key=lambda r: r.rarity, reverse=True)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM rods ORDER BY rarity DESC")
            rods = [self._row_to_rod(row) for row in cursor.fetchall()]
            with self._cache_lock:
                for rod in rods:
                    self._rod_cache[rod.rod_id] = rod
                self._all_rods_cached = True
            return rods

    # --- Bait Read Methods ---
    def get_bait_by_id(self, bait_id: int) -> Optional[Bait]:
        with self._cache_lock:
            if bait_id in self._bait_cache:
                return self._bait_cache[bait_id]
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM baits WHERE bait_id = ?", (bait_id,))
            bait = self._row_to_bait(cursor.fetchone())
            if bait:
                with self._cache_lock:
                    self._bait_cache[bait_id] = bait
            return bait

    def get_all_baits(self) -> List[Bait]:
        with self._cache_lock:
            if self._all_baits_cached:
                return sorted(self._bait_cache.values(), key=lambda b: b.rarity, reverse=True)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM baits ORDER BY rarity DESC")
            baits = [self._row_to_bait(row) for row in cursor.fetchall()]
            with self._cache_lock:
                for bait in baits:
                    self._bait_cache[bait.bait_id] = bait
                self._all_baits_cached = True
            return baits

    # --- Accessory Read Methods ---
    def get_accessory_by_id(self, accessory_id: int) -> Optional[Accessory]:
        with self._cache_lock:
            if accessory_id in self._accessory_cache:
                return self._accessory_cache[accessory_id]
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM accessories WHERE accessory_id = ?", (accessory_id,))
            accessory = self._row_to_accessory(cursor.fetchone())
            if accessory:
                with self._cache_lock:
                    self._accessory_cache[accessory_id] = accessory
            return accessory

    def get_all_accessories(self) -> List[Accessory]:
        with self._cache_lock:
            if self._all_accessories_cached:
                return sorted(self._accessory_cache.values(), key=lambda a: a.rarity, reverse=True)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM accessories ORDER BY rarity DESC")
            accessories = [self._row_to_accessory(row) for row in cursor.fetchall()]
            with self._cache_lock:
                for acc in accessories:
                    self._accessory_cache[acc.accessory_id] = acc
                self._all_accessories_cached = True
            return accessories

    # --- Title Read Methods ---
    def get_title_by_id(self, title_id: int) -> Optional[Title]:
        with self._cache_lock:
            if title_id in self._title_cache:
                return self._title_cache[title_id]
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM titles WHERE title_id = ?", (title_id,))
            title = self._row_to_title(cursor.fetchone())
            if title:
                with self._cache_lock:
                    self._title_cache[title_id] = title
            return title

    def get_all_titles(self) -> List[Title]:
        with self._cache_lock:
            if self._all_titles_cached:
                return sorted(self._title_cache.values(), key=lambda t: t.title_id)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM titles ORDER BY title_id")
            titles = [self._row_to_title(row) for row in cursor.fetchall()]
            with self._cache_lock:
                for t in titles:
                    self._title_cache[t.title_id] = t
                self._all_titles_cached = True
            return titles

    def get_title_by_name(self, name: str) -> Optional[Title]:
        with self._cache_lock:
            if name in self._title_by_name_cache:
                return self._title_by_name_cache[name]
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM titles WHERE name = ?", (name,))
            title = self._row_to_title(cursor.fetchone())
            if title:
                with self._cache_lock:
                    self._title_by_name_cache[name] = title
                    self._title_cache[title.title_id] = title
            return title

    # --- Item Read Methods ---
    def get_item_by_id(self, item_id: int) -> Optional[Item]:
        return self.get_by_id(item_id)

    def get_all_items(self) -> List[Item]:
        return self.get_all()

    # ==========================================================
    # Admin Panel CRUD Methods
    # ==========================================================

    # --- Fish Admin CRUD ---
    def add_fish_template(self, data: Dict[str, Any]) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO fish (name, description, rarity, base_value, min_weight, max_weight, icon_url)
                VALUES (:name, :description, :rarity, :base_value, :min_weight, :max_weight, :icon_url)
            """, {**data, "icon_url": data.get("icon_url")})
            conn.commit()
        with self._cache_lock:
            self._fish_cache.clear()
            self._all_fish_cached = False

    def update_fish_template(self, fish_id: int, data: Dict[str, Any]) -> None:
        data["fish_id"] = fish_id
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE fish SET
                    name = :name, description = :description, rarity = :rarity,
                    base_value = :base_value, min_weight = :min_weight,
                    max_weight = :max_weight, icon_url = :icon_url
                WHERE fish_id = :fish_id
            """, {**data, "icon_url": data.get("icon_url")})
            conn.commit()
        with self._cache_lock:
            self._fish_cache.clear()
            self._all_fish_cached = False

    def delete_fish_template(self, fish_id: int) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM fish WHERE fish_id = ?", (fish_id,))
            conn.commit()
        with self._cache_lock:
            self._fish_cache.clear()
            self._all_fish_cached = False

    # --- Rod Admin CRUD ---
    def add_rod_template(self, data: Dict[str, Any]) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # 注意：durability 允许为 0，不能用 "or None" 否则 0 会被当作 None
            durability_value = data.get("durability")
            if durability_value == "":
                durability_value = None
            cursor.execute("""
                INSERT INTO rods (name, description, rarity, source, purchase_cost,
                                  bonus_fish_quality_modifier, bonus_fish_quantity_modifier,
                                  bonus_rare_fish_chance, durability, icon_url)
                VALUES (:name, :description, :rarity, :source, :purchase_cost,
                        :bonus_fish_quality_modifier, :bonus_fish_quantity_modifier,
                        :bonus_rare_fish_chance, :durability, :icon_url)
            """, {**data, "purchase_cost": data.get("purchase_cost") or None, "durability": durability_value, "icon_url": data.get("icon_url")})
            conn.commit()
        with self._cache_lock:
            self._rod_cache.clear()
            self._all_rods_cached = False

    def update_rod_template(self, rod_id: int, data: Dict[str, Any]) -> None:
        data["rod_id"] = rod_id
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # 注意：durability 允许为 0，不能用 "or None"
            durability_value = data.get("durability")
            if durability_value == "":
                durability_value = None
            cursor.execute("""
                UPDATE rods SET
                    name = :name, description = :description, rarity = :rarity, source = :source,
                    purchase_cost = :purchase_cost, bonus_fish_quality_modifier = :bonus_fish_quality_modifier,
                    bonus_fish_quantity_modifier = :bonus_fish_quantity_modifier,
                    bonus_rare_fish_chance = :bonus_rare_fish_chance, durability = :durability,
                    icon_url = :icon_url
                WHERE rod_id = :rod_id
            """, {**data, "purchase_cost": data.get("purchase_cost") or None, "durability": durability_value, "icon_url": data.get("icon_url")})
            conn.commit()
        with self._cache_lock:
            self._rod_cache.clear()
            self._all_rods_cached = False

    def delete_rod_template(self, rod_id: int) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM rods WHERE rod_id = ?", (rod_id,))
            conn.commit()
        with self._cache_lock:
            self._rod_cache.clear()
            self._all_rods_cached = False

    # --- Bait Admin CRUD ---
    def add_bait_template(self, data: Dict[str, Any]) -> None:
        """后台添加一个新鱼饵，包含所有结构化效果字段"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # 从表单字典中准备数据，为数字字段提供默认值
            params = {
                "name": data.get("name"),
                "description": data.get("description"),
                "rarity": data.get("rarity", 1),
                "effect_description": data.get("effect_description"),
                "duration_minutes": data.get("duration_minutes", 0),
                "cost": data.get("cost", 0),
                "required_rod_rarity": data.get("required_rod_rarity", 0),
                "success_rate_modifier": data.get("success_rate_modifier", 0.0),
                "rare_chance_modifier": data.get("rare_chance_modifier", 0.0),
                "garbage_reduction_modifier": data.get("garbage_reduction_modifier", 0.0),
                "value_modifier": data.get("value_modifier", 1.0),
                "quantity_modifier": data.get("quantity_modifier", 1.0),
                "is_consumable": 1 if "is_consumable" in data else 0
            }
            cursor.execute("""
                INSERT INTO baits (
                    name, description, rarity, effect_description, duration_minutes, cost, required_rod_rarity,
                    success_rate_modifier, rare_chance_modifier, garbage_reduction_modifier,
                    value_modifier, quantity_modifier, is_consumable
                ) VALUES (
                    :name, :description, :rarity, :effect_description, :duration_minutes, :cost, :required_rod_rarity,
                    :success_rate_modifier, :rare_chance_modifier, :garbage_reduction_modifier,
                    :value_modifier, :quantity_modifier, :is_consumable
                )
            """, params)
            conn.commit()
        with self._cache_lock:
            self._bait_cache.clear()
            self._all_baits_cached = False

    def update_bait_template(self, bait_id: int, data: Dict[str, Any]) -> None:
        """后台更新一个鱼饵的信息，包含所有结构化效果字段"""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            params = {
                "bait_id": bait_id,
                "name": data.get("name"),
                "description": data.get("description"),
                "rarity": data.get("rarity", 1),
                "effect_description": data.get("effect_description"),
                "duration_minutes": data.get("duration_minutes", 0),
                "cost": data.get("cost", 0),
                "required_rod_rarity": data.get("required_rod_rarity", 0),
                "success_rate_modifier": data.get("success_rate_modifier", 0.0),
                "rare_chance_modifier": data.get("rare_chance_modifier", 0.0),
                "garbage_reduction_modifier": data.get("garbage_reduction_modifier", 0.0),
                "value_modifier": data.get("value_modifier", 1.0),
                "quantity_modifier": data.get("quantity_modifier", 1.0),
                "is_consumable": 1 if "is_consumable" in data else 0
            }
            cursor.execute("""
                UPDATE baits SET
                    name = :name, description = :description, rarity = :rarity,
                    effect_description = :effect_description, duration_minutes = :duration_minutes,
                    cost = :cost, required_rod_rarity = :required_rod_rarity,
                    success_rate_modifier = :success_rate_modifier, rare_chance_modifier = :rare_chance_modifier,
                    garbage_reduction_modifier = :garbage_reduction_modifier, value_modifier = :value_modifier,
                    quantity_modifier = :quantity_modifier, is_consumable = :is_consumable
                WHERE bait_id = :bait_id
            """, params)
            conn.commit()
        with self._cache_lock:
            self._bait_cache.clear()
            self._all_baits_cached = False

    def delete_bait_template(self, bait_id: int) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM baits WHERE bait_id = ?", (bait_id,))
            conn.commit()
        with self._cache_lock:
            self._bait_cache.clear()
            self._all_baits_cached = False

    # --- Accessory Admin CRUD ---
    def add_accessory_template(self, data: Dict[str, Any]) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO accessories (name, description, rarity, slot_type, bonus_fish_quality_modifier,
                                         bonus_fish_quantity_modifier, bonus_rare_fish_chance,
                                         bonus_coin_modifier, other_bonus_description, icon_url)
                VALUES (:name, :description, :rarity, :slot_type, :bonus_fish_quality_modifier,
                        :bonus_fish_quantity_modifier, :bonus_rare_fish_chance, :bonus_coin_modifier,
                        :other_bonus_description, :icon_url)
            """, {**data, "icon_url": data.get("icon_url")})
            conn.commit()
        with self._cache_lock:
            self._accessory_cache.clear()
            self._all_accessories_cached = False

    def update_accessory_template(self, accessory_id: int, data: Dict[str, Any]) -> None:
        data["accessory_id"] = accessory_id
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE accessories SET
                    name = :name, description = :description, rarity = :rarity, slot_type = :slot_type,
                    bonus_fish_quality_modifier = :bonus_fish_quality_modifier,
                    bonus_fish_quantity_modifier = :bonus_fish_quantity_modifier,
                    bonus_rare_fish_chance = :bonus_rare_fish_chance,
                    bonus_coin_modifier = :bonus_coin_modifier,
                    other_bonus_description = :other_bonus_description, icon_url = :icon_url
                WHERE accessory_id = :accessory_id
            """, {**data, "icon_url": data.get("icon_url")})
            conn.commit()
        with self._cache_lock:
            self._accessory_cache.clear()
            self._all_accessories_cached = False

    def delete_accessory_template(self, accessory_id: int) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM accessories WHERE accessory_id = ?", (accessory_id,))
            conn.commit()
        with self._cache_lock:
            self._accessory_cache.clear()
            self._all_accessories_cached = False

    # --- Item Admin CRUD ---
    def add_item_template(self, data: Dict[str, Any]) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO items (name, description, rarity, effect_description, cost, is_consumable, icon_url)
                VALUES (:name, :description, :rarity, :effect_description, :cost, :is_consumable, :icon_url)
            """, {
                **data,
                "is_consumable": 1 if "is_consumable" in data and data["is_consumable"] else 0,
                "icon_url": data.get("icon_url")
            })
            conn.commit()
        with self._cache_lock:
            self._item_cache.clear()
            self._item_by_name_cache.clear()
            self._all_items_cached = False

    def update_item_template(self, item_id: int, data: Dict[str, Any]) -> None:
        data["item_id"] = item_id
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE items SET
                    name = :name, description = :description, rarity = :rarity,
                    effect_description = :effect_description,
                    cost = :cost, is_consumable = :is_consumable, icon_url = :icon_url
                WHERE item_id = :item_id
            """, {
                **data,
                "is_consumable": 1 if "is_consumable" in data and data["is_consumable"] else 0,
                "icon_url": data.get("icon_url")
            })
            conn.commit()
        with self._cache_lock:
            self._item_cache.clear()
            self._item_by_name_cache.clear()
            self._all_items_cached = False

    def delete_item_template(self, item_id: int) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM items WHERE item_id = ?", (item_id,))
            conn.commit()
        with self._cache_lock:
            self._item_cache.clear()
            self._item_by_name_cache.clear()
            self._all_items_cached = False

    def add_title_template(self, data: Dict[str, Any]) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO titles (title_id, name, description, display_format)
                VALUES (:title_id, :name, :description, :display_format)
            """, data)
            conn.commit()
        with self._cache_lock:
            self._title_cache.clear()
            self._title_by_name_cache.clear()
            self._all_titles_cached = False

    def update_title_template(self, title_id: int, data: Dict[str, Any]) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE titles
                SET name = :name, description = :description, display_format = :display_format
                WHERE title_id = :title_id
            """, {**data, "title_id": title_id})
            conn.commit()
        with self._cache_lock:
            self._title_cache.clear()
            self._title_by_name_cache.clear()
            self._all_titles_cached = False

    def delete_title_template(self, title_id: int) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM titles WHERE title_id = ?", (title_id,))
            conn.commit()
        with self._cache_lock:
            self._title_cache.clear()
            self._title_by_name_cache.clear()
            self._all_titles_cached = False
