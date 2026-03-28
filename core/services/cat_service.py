from typing import Dict, Any, Optional, List, Tuple
from datetime import timedelta, datetime
import logging
import json
import random
import threading
import time

try:
    logger = __import__("astrbot.api", fromlist=["logger"]).logger
except Exception:
    logger = logging.getLogger(__name__)

from ..repositories.abstract_repository import (
    AbstractCatRepository,
    AbstractUserRepository,
    AbstractInventoryRepository,
    AbstractItemTemplateRepository,
    AbstractLogRepository,
    AbstractUserBuffRepository,
)
from ..domain.models import (
    CatTemplate,
    UserCatInstance,
    CatDisease,
    UserCatDisease,
    CatEvent,
    UserCatEventRecord,
    UserBuff,
)
from ..utils import get_now


class CatService:
    def __init__(
        self,
        cat_repo: AbstractCatRepository,
        user_repo: AbstractUserRepository,
        inventory_repo: AbstractInventoryRepository,
        item_template_repo: AbstractItemTemplateRepository,
        log_repo: AbstractLogRepository,
        buff_repo: AbstractUserBuffRepository,
        config: Dict[str, Any],
    ):
        self.cat_repo = cat_repo
        self.user_repo = user_repo
        self.inventory_repo = inventory_repo
        self.item_template_repo = item_template_repo
        self.log_repo = log_repo
        self.buff_repo = buff_repo
        self.config = config
        self.max_cats_per_user = config.get("cat", {}).get("max_cats_per_user", 5)
        self.adopt_cost = config.get("cat", {}).get("adopt_cost", 500)
        
        self._decay_thread: Optional[threading.Thread] = None
        self._decay_running = False
        self._decay_interval = config.get("cat", {}).get("decay_interval_minutes", 30)

    def adopt_cat(self, user_id: str, nickname: Optional[str] = None) -> Dict[str, Any]:
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}

        current_cats = self.cat_repo.get_user_cat_count(user_id)
        if current_cats >= self.max_cats_per_user:
            return {
                "success": False,
                "message": f"您已达到最大猫咪数量({self.max_cats_per_user}只)",
            }

        if user.coins < self.adopt_cost:
            return {"success": False, "message": f"金币不足，领养需要 {self.adopt_cost} 金币"}

        cats = self.cat_repo.get_all_cats()
        if not cats:
            return {"success": False, "message": "当前没有可领养的猫咪"}

        user.coins -= self.adopt_cost
        self.user_repo.update(user)

        selected_cat = random.choice(cats)

        final_nickname = nickname if nickname is not None else selected_cat.name
        
        rare_bonus_extra, coin_bonus_extra = self._generate_initial_bonus()
        
        cat_instance = UserCatInstance(
            cat_instance_id=0,
            user_id=user_id,
            cat_id=selected_cat.cat_id,
            nickname=final_nickname,
            obtained_at=get_now(),
            hunger=100,
            mood=100,
            health=100,
            level=1,
            exp=0,
            star=1,
            rare_bonus_extra=rare_bonus_extra,
            coin_bonus_extra=coin_bonus_extra,
            color=self._random_color(),
            pattern=self._random_pattern(),
        )

        try:
            created = self.cat_repo.add_cat_instance(cat_instance)
            if isinstance(created, UserCatInstance):
                cat_instance = created
            elif isinstance(created, int):
                fetched = self.cat_repo.get_cat_instance(created)
                if fetched:
                    cat_instance = fetched
                else:
                    user.coins += self.adopt_cost
                    self.user_repo.update(user)
                    return {"success": False, "message": "领养失败"}
        except Exception as e:
            user.coins += self.adopt_cost
            self.user_repo.update(user)
            logger.error(f"领养猫咪失败: {e}")
            return {"success": False, "message": "领养失败"}

        self._safe_log(user_id, "cat_adopt", f"领养猫咪: {selected_cat.name}({cat_instance.cat_instance_id})")
        logger.info(f"用户 {user_id} 领养猫咪成功: {selected_cat.name}#{cat_instance.cat_instance_id}")

        return {
            "success": True,
            "message": f"恭喜！您领养了一只 {selected_cat.name}！",
            "cat": cat_instance,
            "cat_template": selected_cat,
        }

    def feed_cat(self, user_id: str, cat_instance_id: int, fish_id: int, quality_level: int = 0) -> Dict[str, Any]:
        cat = self.cat_repo.get_cat_instance(cat_instance_id)
        if not cat or cat.user_id != user_id:
            return {"success": False, "message": "猫咪不存在"}

        last_feed = cat.last_feed_time or cat.obtained_at
        cooldown_remaining = max(0, 60 - int((get_now() - last_feed).total_seconds()))
        if cooldown_remaining > 0:
            return {"success": False, "message": f"喂食冷却中，请 {cooldown_remaining} 秒后再喂"}

        fish_template = self.item_template_repo.get_fish_by_id(fish_id)
        if not fish_template:
            return {"success": False, "message": "无效的鱼类ID"}

        fish_inv = self.inventory_repo.get_fish_inventory(user_id)
        user_fish = next((f for f in fish_inv if f.fish_id == fish_id and f.quality_level == quality_level), None)
        if not user_fish or user_fish.quantity < 1:
            quality_hint = " (高品质)" if quality_level else ""
            return {"success": False, "message": f"您的鱼塘中没有这条鱼 (ID:{fish_id}){quality_hint}"}

        rarity = fish_template.rarity
        hunger = 8 + rarity * 2
        exp = rarity
        mood = max(0, rarity - 3)

        old_hunger = cat.hunger
        old_mood = cat.mood
        cat.hunger = min(100, cat.hunger + hunger)
        cat.mood = min(100, cat.mood + mood)
        cat.last_feed_time = get_now()
        cat.exp += exp

        self.inventory_repo.update_fish_quantity(user_id, fish_id, -1, user_fish.quality_level)

        level_up, did_star_up_from_level, new_level = self._check_level_up(cat)
        if did_star_up_from_level or cat.star >= 10:
            star_up_result = None
        else:
            star_up_result = self._check_star_up(cat, rarity)
        
        self.cat_repo.update_cat_instance(cat)

        self._safe_log(
            user_id,
            "cat_feed",
            f"喂猫: cat={cat_instance_id}, fish={fish_id}(rarity={rarity}), hunger={old_hunger}->{cat.hunger}",
        )

        result: Dict[str, Any] = {
            "success": True,
            "fish_name": fish_template.name,
            "rarity": rarity,
            "old_hunger": old_hunger,
            "new_hunger": cat.hunger,
            "hunger_change": hunger,
            "old_mood": old_mood,
            "new_mood": cat.mood,
            "mood_change": mood,
            "exp_gain": exp,
            "level_up": level_up,
            "new_level": new_level if level_up else None,
            "star": cat.star,
        }

        if star_up_result:
            result["star_up"] = star_up_result

        event_result = self.trigger_random_event(user_id, cat_instance_id, "feed")
        if event_result:
            result["event"] = event_result

        disease_result = self.check_disease_onset(user_id, cat_instance_id)
        if disease_result:
            result["disease"] = disease_result

        return result

    def play_with_cat(self, user_id: str, cat_instance_id: int) -> Dict[str, Any]:
        cat = self.cat_repo.get_cat_instance(cat_instance_id)
        if not cat or cat.user_id != user_id:
            return {"success": False, "message": "猫咪不存在"}

        last_play = cat.last_play_time or cat.obtained_at
        cooldown_remaining = max(0, 60 - int((get_now() - last_play).total_seconds()))
        if cooldown_remaining > 0:
            return {"success": False, "message": f"逗猫冷却中，请 {cooldown_remaining} 秒后再逗"}

        old_mood = cat.mood
        mood_gain = random.randint(5, 15)
        cat.mood = min(100, cat.mood + mood_gain)
        cat.last_play_time = get_now()
        cat.exp += 10

        level_up, _, new_level = self._check_level_up(cat)
        self.cat_repo.update_cat_instance(cat)

        self._safe_log(
            user_id,
            "cat_play",
            f"逗猫: cat={cat_instance_id}, mood={old_mood}->{cat.mood}",
        )

        result: Dict[str, Any] = {
            "success": True,
            "old_mood": old_mood,
            "new_mood": cat.mood,
            "mood_change": mood_gain,
            "exp_gain": 10,
            "level_up": level_up,
            "new_level": new_level if level_up else None,
        }

        event_result = self.trigger_random_event(user_id, cat_instance_id, "play")
        if event_result:
            result["event"] = event_result

        return result

    def trigger_random_event(
        self, user_id: str, cat_instance_id: int, action: str
    ) -> Optional[Dict[str, Any]]:
        eligible_events = [
            e for e in self._get_cat_events() if action in e.get("trigger_actions", [])
        ]
        if not eligible_events:
            return None

        weights = [e.get("weight", 1) for e in eligible_events]
        selected = random.choices(eligible_events, weights=weights, k=1)[0]

        cat = self.cat_repo.get_cat_instance(cat_instance_id)
        if not cat:
            return None

        result_msg = f"【{selected['name']}】{selected['description']}"
        reward_info: Dict[str, Any] = {}

        reward_type = selected.get("reward_type")
        reward_value = selected.get("reward_value")
        if reward_type == "coins" and reward_value:
            user = self.user_repo.get_by_id(user_id)
            if user:
                user.coins = max(0, user.coins + int(reward_value))
                self.user_repo.update(user)
                reward_info["coins"] = int(reward_value)

        elif reward_type == "exp" and reward_value:
            cat.exp += int(reward_value)
            reward_info["exp"] = int(reward_value)

        elif reward_type == "item" and selected.get("reward_item_id"):
            reward_item_id = selected["reward_item_id"]
            try:
                item_id = int(reward_item_id)
            except (ValueError, TypeError):
                item = self.item_template_repo.get_by_name(reward_item_id)
                if item:
                    item_id = item.item_id
                else:
                    logger.warning(f"无法找到物品: {reward_item_id}")
                    reward_info["item"] = reward_item_id
                    reward_info["quantity"] = 0
                    item_id = None
            
            if item_id is not None:
                quantity = int(selected.get("reward_value", 1) or 1)
                self._add_item_to_user(user_id, item_id, quantity)
                reward_info["item"] = item_id
                reward_info["quantity"] = quantity

        elif reward_type == "buff" and selected.get("buff_type"):
            buff = UserBuff(
                id=0,
                user_id=user_id,
                buff_type=str(selected["buff_type"]),
                payload=json.dumps({"cat_instance_id": cat_instance_id}, ensure_ascii=False),
                started_at=get_now(),
                expires_at=get_now() + timedelta(minutes=int(selected.get("buff_duration_minutes", 60))),
            )
            self.buff_repo.add(buff)
            reward_info["buff"] = selected["buff_type"]

        penalty_type = selected.get("penalty_type")
        penalty_value = int(selected.get("penalty_value", 0) or 0)
        if penalty_type:
            if penalty_type in ("hunger", "mood", "health"):
                current_val = int(getattr(cat, penalty_type))
                if penalty_value > 0:
                    setattr(cat, penalty_type, min(100, current_val + penalty_value))
                else:
                    setattr(cat, penalty_type, max(0, current_val + penalty_value))
            elif penalty_type == "coins" and penalty_value < 0:
                user = self.user_repo.get_by_id(user_id)
                if user:
                    user.coins = max(0, user.coins + penalty_value)
                    self.user_repo.update(user)
                    reward_info["coins_penalty"] = abs(penalty_value)

        event_record = UserCatEventRecord(
            record_id=0,
            user_id=user_id,
            cat_instance_id=cat_instance_id,
            event_id=int(selected.get("event_id", 0)),
            event_name=str(selected.get("name", "未知事件")),
            event_type=str(selected.get("event_type", "normal")),
            description=str(selected.get("description", "")),
            reward_info=json.dumps(reward_info, ensure_ascii=False) if reward_info else None,
            triggered_at=get_now(),
        )
        self._add_cat_event_record(event_record)
        self.cat_repo.update_cat_instance(cat)

        self._safe_log(
            user_id,
            "cat_event",
            f"触发猫咪事件: cat={cat_instance_id}, event={selected.get('name', 'unknown')}",
        )

        return {**selected, "message": result_msg}

    def check_disease_onset(self, user_id: str, cat_instance_id: int) -> Optional[Dict[str, Any]]:
        cat = self.cat_repo.get_cat_instance(cat_instance_id)
        if not cat:
            return None

        existing = self._get_active_disease(cat_instance_id)
        if existing:
            return None

        diseases = self._get_cat_diseases()
        for disease in diseases:
            conditions_met = True
            if disease.get("min_health_threshold", 0) > 0 and cat.health >= int(disease["min_health_threshold"]):
                conditions_met = False
            if disease.get("min_hunger_threshold", 0) > 0 and cat.hunger >= int(disease["min_hunger_threshold"]):
                conditions_met = False
            if disease.get("min_mood_threshold", 0) > 0 and cat.mood >= int(disease["min_mood_threshold"]):
                conditions_met = False

            if conditions_met and random.random() < float(disease.get("onset_chance", 0.1)):
                user_disease = UserCatDisease(
                    id=0,
                    user_id=user_id,
                    cat_instance_id=cat_instance_id,
                    disease_id=int(disease["disease_id"]),
                    disease_name=str(disease["name"]),
                    started_at=get_now(),
                )
                self._add_cat_disease_record(user_disease)
                self._safe_log(
                    user_id,
                    "cat_disease_onset",
                    f"猫咪发病: cat={cat_instance_id}, disease={disease.get('name', 'unknown')}",
                )
                return disease

        return None

    def treat_cat(self, user_id: str, cat_instance_id: int) -> Dict[str, Any]:
        disease = self._get_active_disease(cat_instance_id)
        if not disease:
            return {"success": False, "message": "猫咪没有生病"}

        disease_info = next(
            (d for d in self._get_cat_diseases() if int(d["disease_id"]) == disease.disease_id),
            None,
        )
        cat = self.cat_repo.get_cat_instance(cat_instance_id)
        if not cat or cat.user_id != user_id:
            return {"success": False, "message": "猫咪不存在"}

        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}

        cost = int(disease_info.get("treatment_cost", 0)) if disease_info else 0
        if user.coins < cost:
            return {"success": False, "message": f"金币不足，治疗需要 {cost} 金币"}
        user.coins -= cost
        self.user_repo.update(user)

        disease.is_treated = True
        disease.treatment_start = get_now()
        self._update_cat_disease_record(disease)

        cat.health = min(100, cat.health + 20)
        self.cat_repo.update_cat_instance(cat)

        self._safe_log(
            user_id,
            "cat_treat",
            f"治疗猫咪: cat={cat_instance_id}, disease={disease.disease_name}",
        )

        return {
            "success": True,
            "message": f"您的猫咪「{cat.nickname}」接受了治疗，{disease.disease_name}已痊愈！健康恢复了20点",
        }

    def get_cat_status(self, user_id: str, cat_instance_id: int) -> Dict[str, Any]:
        cat = self.cat_repo.get_cat_instance(cat_instance_id)
        if not cat or cat.user_id != user_id:
            return {"success": False, "message": "猫咪不存在"}

        disease = self._get_active_disease(cat_instance_id)
        disease_info = None
        if disease:
            disease_info = next(
                (d for d in self._get_cat_diseases() if int(d["disease_id"]) == disease.disease_id),
                None,
            )

        cat_template = self.cat_repo.get_cat_by_id(cat.cat_id)
        events = self._get_recent_events(user_id, cat_instance_id, limit=4)

        base_rare_bonus = cat_template.rare_bonus if cat_template else 0.0
        base_coin_bonus = cat_template.coin_bonus if cat_template else 0.0
        
        rare_bonus = base_rare_bonus + cat.rare_bonus_extra
        coin_bonus = base_coin_bonus + cat.coin_bonus_extra
        
        if disease_info:
            rare_bonus += float(disease_info.get("fishing_bonus_modifier", 0.0))

        return {
            "success": True,
            "cat": cat,
            "cat_template": cat_template,
            "disease": disease_info,
            "is_sick": disease is not None,
            "fishing_bonus": rare_bonus,
            "coin_bonus": coin_bonus,
            "rare_bonus_extra": cat.rare_bonus_extra,
            "coin_bonus_extra": cat.coin_bonus_extra,
            "recent_events": events,
        }

    def list_user_cats(self, user_id: str) -> List[UserCatInstance]:
        return self.cat_repo.get_user_cats(user_id)

    def calculate_cat_fishing_bonus(self, user_id: str) -> Dict[str, float]:
        bonus = {
            "rare_bonus": 0.0,
            "coin_bonus": 0.0,
        }
        try:
            cats = self.list_user_cats(user_id)
            for cat in cats:
                status = self.get_cat_status(user_id, cat.cat_instance_id)
                if status.get("success"):
                    bonus["rare_bonus"] += status.get("fishing_bonus", 0.0)
                    bonus["coin_bonus"] += status.get("coin_bonus", 0.0)
        except Exception as e:
            logger.error(f"计算猫咪加成失败: {e}")
        return bonus

    def _check_level_up(self, cat: UserCatInstance) -> Tuple[bool, bool, int]:
        max_level = 10
        did_level_up = False
        did_star_up = False
        exp_needed = self._calc_exp_for_level(cat.level, cat.star)
        
        while cat.exp >= exp_needed and cat.level < max_level:
            cat.level += 1
            self._add_bonus_on_level_up(cat)
            did_level_up = True
            exp_needed = self._calc_exp_for_level(cat.level, cat.star)
        
        if cat.level >= max_level and cat.exp >= exp_needed and cat.star < 10:
            self._do_star_up(cat)
            did_star_up = True
            did_level_up = True
        
        return did_level_up, did_star_up, cat.level

    def _calc_exp_for_level(self, level: int, star: int) -> int:
        return int(100 * star * (1 + 0.5 * (level - 1)))

    def _check_star_up(self, cat: UserCatInstance, fish_rarity: int) -> Optional[Dict[str, Any]]:
        if fish_rarity > cat.star and cat.star < 10:
            if random.random() < 0.5:
                old_star = cat.star
                cat.star = min(10, cat.star + 1)
                self._add_bonus_on_star_up(cat)
                self._add_bonus_for_skipped_levels(cat, skipped_levels=10)
                return {"old_star": old_star, "new_star": cat.star}
        return None

    def _do_star_up(self, cat: UserCatInstance) -> None:
        if cat.star < 10:
            cat.star = min(10, cat.star + 1)
            cat.level = 1
            cat.exp = 0
            self._add_bonus_on_star_up(cat)

    def _generate_initial_bonus(self) -> Tuple[float, float]:
        rare_bonus_extra = round(random.uniform(0.015, 0.025), 4)
        coin_bonus_extra = round(random.uniform(0.01, 0.02), 4)
        return rare_bonus_extra, coin_bonus_extra

    def _add_bonus_on_level_up(self, cat: UserCatInstance) -> None:
        cat.rare_bonus_extra = round(cat.rare_bonus_extra + random.uniform(0.002, 0.005), 4)
        cat.coin_bonus_extra = round(cat.coin_bonus_extra + random.uniform(0.002, 0.004), 4)

    def _add_bonus_on_star_up(self, cat: UserCatInstance) -> None:
        cat.rare_bonus_extra = round(cat.rare_bonus_extra + random.uniform(0.015, 0.021), 4)
        cat.coin_bonus_extra = round(cat.coin_bonus_extra + random.uniform(0.011, 0.016), 4)

    def _add_bonus_for_skipped_levels(self, cat: UserCatInstance, skipped_levels: int = 10) -> None:
        cat.rare_bonus_extra = round(cat.rare_bonus_extra + random.uniform(0.002, 0.005) * skipped_levels, 4)
        cat.coin_bonus_extra = round(cat.coin_bonus_extra + random.uniform(0.002, 0.004) * skipped_levels, 4)

    def _random_color(self) -> str:
        return random.choice(["橙色", "黑色", "白色", "灰色", "黑白", "橘白", "三花"])

    def _random_pattern(self) -> str:
        return random.choice(["纯色", "虎斑", "奶牛斑", "橘斑", "龟甲"])

    def _safe_log(self, user_id: str, log_type: str, message: str) -> None:
        try:
            self.log_repo.add_log(user_id, log_type, message)
        except Exception as e:
            logger.warning(f"记录猫咪日志失败: {e}")

    def _get_cat_events(self) -> List[Dict[str, Any]]:
        try:
            from ..initial_data import CAT_EVENTS

            return list(CAT_EVENTS)
        except Exception:
            pass

        try:
            events = getattr(self.cat_repo, "get_all_events")()
            result: List[Dict[str, Any]] = []
            for e in events:
                if isinstance(e, CatEvent):
                    result.append(
                        {
                            "event_id": e.event_id,
                            "name": e.name,
                            "description": e.description,
                            "event_type": e.event_type,
                            "trigger_actions": e.trigger_actions,
                            "weight": e.weight,
                            "reward_type": e.reward_type,
                            "reward_value": e.reward_value,
                            "reward_item_id": e.reward_item_id,
                            "penalty_type": e.penalty_type,
                            "penalty_value": e.penalty_value,
                            "buff_type": e.buff_type,
                            "buff_duration_minutes": e.buff_duration_minutes,
                            "is_common": e.is_common,
                        }
                    )
            return result
        except Exception:
            return []

    def _get_cat_diseases(self) -> List[Dict[str, Any]]:
        try:
            from ..initial_data import CAT_DISEASES

            return list(CAT_DISEASES)
        except Exception:
            pass

        try:
            diseases = self.cat_repo.get_all_diseases()
            result: List[Dict[str, Any]] = []
            for d in diseases:
                if isinstance(d, CatDisease):
                    result.append(
                        {
                            "disease_id": d.disease_id,
                            "name": d.name,
                            "description": d.description,
                            "symptom": d.symptom,
                            "min_health_threshold": d.min_health_threshold,
                            "min_hunger_threshold": d.min_hunger_threshold,
                            "min_mood_threshold": d.min_mood_threshold,
                            "onset_chance": d.onset_chance,
                            "treatment_cost": d.treatment_cost,
                            "health_decay_per_hour": d.health_decay_per_hour,
                            "fishing_bonus_modifier": d.fishing_bonus_modifier,
                        }
                    )
            return result
        except Exception:
            return []

    def _get_active_disease(self, cat_instance_id: int) -> Optional[UserCatDisease]:
        if hasattr(self.cat_repo, "get_active_disease"):
            return getattr(self.cat_repo, "get_active_disease")(cat_instance_id)
        if hasattr(self.cat_repo, "get_cat_active_diseases"):
            diseases = getattr(self.cat_repo, "get_cat_active_diseases")(cat_instance_id)
            return diseases[0] if diseases else None
        return None

    def _add_cat_disease_record(self, disease: UserCatDisease) -> None:
        if hasattr(self.cat_repo, "add_cat_disease"):
            getattr(self.cat_repo, "add_cat_disease")(disease)
            return
        if hasattr(self.cat_repo, "add_user_disease"):
            getattr(self.cat_repo, "add_user_disease")(disease)

    def _update_cat_disease_record(self, disease: UserCatDisease) -> None:
        if hasattr(self.cat_repo, "update_cat_disease"):
            getattr(self.cat_repo, "update_cat_disease")(disease)
            return
        if hasattr(self.cat_repo, "update_user_disease"):
            getattr(self.cat_repo, "update_user_disease")(disease)

    def _add_cat_event_record(self, event: UserCatEventRecord) -> None:
        if hasattr(self.cat_repo, "add_cat_event"):
            getattr(self.cat_repo, "add_cat_event")(event)
            return
        if hasattr(self.cat_repo, "add_event_record"):
            getattr(self.cat_repo, "add_event_record")(event)

    def _get_recent_events(
        self, user_id: str, cat_instance_id: int, limit: int = 5
    ) -> List[UserCatEventRecord]:
        if hasattr(self.cat_repo, "get_recent_events"):
            return getattr(self.cat_repo, "get_recent_events")(user_id, cat_instance_id, limit)
        if hasattr(self.cat_repo, "get_cat_event_records"):
            return getattr(self.cat_repo, "get_cat_event_records")(cat_instance_id, limit)
        if hasattr(self.cat_repo, "get_user_event_records"):
            return getattr(self.cat_repo, "get_user_event_records")(user_id, limit)
        return []

    def _add_item_to_user(self, user_id: str, item_id: int, quantity: int) -> None:
        if hasattr(self.inventory_repo, "add_item_to_user"):
            getattr(self.inventory_repo, "add_item_to_user")(user_id, item_id, quantity)
            return
        if hasattr(self.inventory_repo, "update_item_quantity"):
            getattr(self.inventory_repo, "update_item_quantity")(user_id, item_id, quantity)

    def start_cat_decay_task(self):
        if self._decay_thread and self._decay_thread.is_alive():
            logger.info("猫咪属性衰减线程已在运行中")
            return
        self._decay_running = True
        self._decay_thread = threading.Thread(target=self._cat_decay_loop, daemon=True)
        self._decay_thread.start()
        logger.info("猫咪属性衰减线程已启动")

    def stop_cat_decay_task(self):
        self._decay_running = False
        if self._decay_thread:
            self._decay_thread.join(timeout=2.0)
            logger.info("猫咪属性衰减线程已停止")

    def _cat_decay_loop(self):
        while self._decay_running:
            try:
                self._process_cat_decay()
                self._process_cat_diseases()
            except Exception as e:
                logger.error(f"猫咪属性衰减处理出错: {e}")
            time.sleep(self._decay_interval * 60)

    def _process_cat_decay(self):
        all_cats = self.cat_repo.get_all_cat_instances()
        now = get_now()
        for cat in all_cats:
            try:
                changed = False
                last_feed = cat.last_feed_time or cat.obtained_at
                last_play = cat.last_play_time or cat.obtained_at
                
                hours_since_feed = (now - last_feed).total_seconds() / 3600
                hours_since_play = (now - last_play).total_seconds() / 3600
                
                if hours_since_feed >= 1:
                    hunger_decay = int(hours_since_feed) * 5
                    cat.hunger = max(0, cat.hunger - hunger_decay)
                    cat.last_feed_time = now
                    changed = True
                    
                if hours_since_play >= 2:
                    mood_decay = int(hours_since_play / 2) * 3
                    cat.mood = max(0, cat.mood - mood_decay)
                    cat.last_play_time = now
                    changed = True
                
                if changed:
                    self.cat_repo.update_cat_instance(cat)
            except Exception as e:
                logger.warning(f"处理猫咪 {cat.cat_instance_id} 衰减失败: {e}")

    def _process_cat_diseases(self):
        all_cats = self.cat_repo.get_all_cat_instances()
        decay_ratio = self._decay_interval / 60.0
        for cat in all_cats:
            try:
                disease = self._get_active_disease(cat.cat_instance_id)
                if not disease:
                    if cat.hunger < 30 or cat.mood < 30 or cat.health < 50:
                        self.check_disease_onset(cat.user_id, cat.cat_instance_id)
                    continue
                
                disease_info = next(
                    (d for d in self._get_cat_diseases() if int(d["disease_id"]) == disease.disease_id),
                    None,
                )
                if not disease_info:
                    continue
                
                decay_per_hour = disease_info.get("health_decay_per_hour", 0)
                if decay_per_hour > 0:
                    health_decay = int(decay_per_hour * decay_ratio)
                    if health_decay < 1 and decay_per_hour > 0:
                        health_decay = 1
                    cat.health = max(0, cat.health - health_decay)
                    self.cat_repo.update_cat_instance(cat)
                    
            except Exception as e:
                logger.warning(f"处理猫咪 {cat.cat_instance_id} 疾病失败: {e}")
