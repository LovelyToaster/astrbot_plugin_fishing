"""
AI 决策特征提取器 (FeatureExtractor)

一次 SQL 查询批量拉取所有候选真人目标的特征，供模型推理使用。
候选筛选：is_ai=0 AND is_system=0，可通过 exclude_ids 排除额外 ID。

特征列表（8 维）：
- target_fish_count       目标鱼塘鱼数
- target_coins            目标金币
- target_has_shield       目标是否有护盾类 buff
- target_has_protection   目标是否有守护海灵/保护类 buff
- target_rod_rarity       目标装备鱼竿稀有度（0 表示未装备）
- target_accessory_rarity 目标装备饰品稀有度（0 表示未装备）
- attacker_rod_rarity     AI 自己装备鱼竿稀有度
- attacker_accessory_rarity AI 自己装备饰品稀有度

设计约束：训练脚本必须使用相同的特征名和 SQL 逻辑，保证训练/推理特征对齐。
"""

import sqlite3
import threading
from typing import Dict, List, Optional, Tuple

from astrbot.api import logger

from ...domain.models import User


class FeatureExtractor:
    """批量特征提取器：单次 JOIN SQL 拉取全部候选特征"""

    # 特征名列表（固定顺序，训练脚本必须一致）
    FEATURE_NAMES = [
        "target_fish_count",
        "target_coins",
        "target_has_shield",
        "target_has_protection",
        "target_rod_rarity",
        "target_accessory_rarity",
        "attacker_rod_rarity",
        "attacker_accessory_rarity",
    ]

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._local = threading.local()

    def _get_connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "connection", None)
        if conn is None:
            conn = sqlite3.connect(
                self.db_path,
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
            )
            conn.row_factory = sqlite3.Row
            self._local.connection = conn
        return conn

    def _get_attacker_equipment_rarity(self, attacker_user_id: str) -> Tuple[int, int]:
        """
        获取攻击者当前装备的鱼竿和饰品稀有度。

        Returns:
            (rod_rarity, accessory_rarity)，未装备返回 0
        """
        conn = self._get_connection()
        cursor = conn.cursor()

        rod_rarity = 0
        acc_rarity = 0

        try:
            cursor.execute(
                """
                SELECT MAX(r.rarity) AS m
                FROM user_rods ur
                JOIN rods r ON ur.rod_id = r.rod_id
                WHERE ur.user_id = ? AND ur.is_equipped = 1
                """,
                (attacker_user_id,),
            )
            row = cursor.fetchone()
            if row and row["m"] is not None:
                rod_rarity = int(row["m"])
        except Exception as e:
            logger.debug(f"[FeatureExtractor] 查询攻击者鱼竿稀有度失败: {e}")

        try:
            cursor.execute(
                """
                SELECT MAX(a.rarity) AS m
                FROM user_accessories ua
                JOIN accessories a ON ua.accessory_id = a.accessory_id
                WHERE ua.user_id = ? AND ua.is_equipped = 1
                """,
                (attacker_user_id,),
            )
            row = cursor.fetchone()
            if row and row["m"] is not None:
                acc_rarity = int(row["m"])
        except Exception as e:
            logger.debug(f"[FeatureExtractor] 查询攻击者饰品稀有度失败: {e}")

        return rod_rarity, acc_rarity

    def batch_extract(
        self,
        attacker_user: User,
        exclude_ids: Optional[List[str]] = None,
    ) -> List[Tuple[str, Dict[str, float]]]:
        """
        批量提取所有候选真人目标的特征。

        Args:
            attacker_user: AI 用户对象（用于填 attacker_* 特征）
            exclude_ids: 需要排除的 user_id 列表（通常含 AI 自己）

        Returns:
            [(target_user_id, features_dict), ...]
            features_dict 包含所有 FEATURE_NAMES 中的字段
        """
        # 1. 攻击者装备稀有度（一次算好）
        attacker_rod_r, attacker_acc_r = self._get_attacker_equipment_rarity(
            attacker_user.user_id
        )

        # 2. 构造 exclude 条件
        exclude_ids = exclude_ids or []
        # AI 自己必须排除，若调用方没传就补上
        if attacker_user.user_id not in exclude_ids:
            exclude_ids = list(exclude_ids) + [attacker_user.user_id]

        placeholders = ", ".join(["?"] * len(exclude_ids))

        sql = f"""
            SELECT
                u.user_id AS target_user_id,
                COALESCE(u.coins, 0) AS target_coins,
                (SELECT COALESCE(SUM(quantity), 0) FROM user_fish_inventory ufi
                 WHERE ufi.user_id = u.user_id) AS target_fish_count,
                (SELECT MAX(r.rarity) FROM user_rods ur
                 JOIN rods r ON ur.rod_id = r.rod_id
                 WHERE ur.user_id = u.user_id AND ur.is_equipped = 1) AS target_rod_rarity,
                (SELECT MAX(a.rarity) FROM user_accessories ua
                 JOIN accessories a ON ua.accessory_id = a.accessory_id
                 WHERE ua.user_id = u.user_id AND ua.is_equipped = 1) AS target_accessory_rarity,
                EXISTS(
                    SELECT 1 FROM user_buffs ub
                    WHERE ub.user_id = u.user_id
                      AND ub.buff_type LIKE '%shield%'
                      AND (ub.expires_at IS NULL OR ub.expires_at > datetime('now'))
                ) AS target_has_shield,
                EXISTS(
                    SELECT 1 FROM user_buffs ub
                    WHERE ub.user_id = u.user_id
                      AND ub.buff_type LIKE '%protection%'
                      AND (ub.expires_at IS NULL OR ub.expires_at > datetime('now'))
                ) AS target_has_protection
            FROM users u
            WHERE u.is_ai = 0
              AND u.is_system = 0
              AND u.user_id NOT IN ({placeholders})
        """

        candidates = []
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(sql, exclude_ids)
            rows = cursor.fetchall()

            for row in rows:
                try:
                    features = {
                        "target_fish_count": float(row["target_fish_count"] or 0),
                        "target_coins": float(row["target_coins"] or 0),
                        "target_has_shield": float(row["target_has_shield"] or 0),
                        "target_has_protection": float(row["target_has_protection"] or 0),
                        "target_rod_rarity": float(row["target_rod_rarity"] or 0),
                        "target_accessory_rarity": float(row["target_accessory_rarity"] or 0),
                        "attacker_rod_rarity": float(attacker_rod_r),
                        "attacker_accessory_rarity": float(attacker_acc_r),
                    }
                    candidates.append((row["target_user_id"], features))
                except Exception as e:
                    logger.debug(f"[FeatureExtractor] 解析候选行失败，跳过: {e}")
        except Exception as e:
            logger.warning(f"[FeatureExtractor] 批量提取特征失败: {e}")
            return []

        return candidates
