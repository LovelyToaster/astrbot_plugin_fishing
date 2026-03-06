import sys
import os
import pytest

# 动态获取项目根目录并注入环境变量
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, project_root)

from core.services.fish_weight_service import FishWeightService
# 核心改动：直接导入初始配置文件中的 FISH_DATA 列表
from core.initial_data import FISH_DATA

class MockFish:
    def __init__(self, fish_id, name, base_value):
        self.fish_id = fish_id
        self.name = name
        self.base_value = base_value

@pytest.fixture(scope="module")
def service():
    return FishWeightService()

# 核心改动：写一个模拟的查询函数，代替 SqliteItemTemplateRepository
def get_mock_fishes_by_rarity(target_rarity):
    fish_list = []
    fish_id_counter = 1
    # 遍历配置表，格式为: (name, description, rarity, base_value, min_weight, max_weight, icon_url)
    for data in FISH_DATA:
        name = data[0]
        rarity = data[2]
        base_value = data[3]
        
        # 筛选出符合目标星级的鱼，封装成 MockFish 对象
        if rarity == target_rarity:
            fish_list.append(MockFish(fish_id_counter, name, base_value))
        fish_id_counter += 1
        
    return fish_list

# 矩阵化参数测试：组合不同的星级和加成倍率
@pytest.mark.parametrize("rarity", [1, 3, 5, 7])
@pytest.mark.parametrize("coins_chance", [0.0, 0.3, 0.5, 1.2, 2.0])
def test_real_fish_ev(service, rarity, coins_chance):
    print(f"\n========== 正在测试: {rarity}星鱼池 | 加成 {coins_chance*100}% ==========")
    
    # 核心改动：使用我们的内存模拟查询函数
    fish_list = get_mock_fishes_by_rarity(rarity)
    
    if not fish_list:
        pytest.skip(f"配置表中没有找到 {rarity} 星的鱼，跳过该项测试。")
        
    print(f"该星级共有 {len(fish_list)} 种鱼。最便宜: {min(f.base_value for f in fish_list)}, 最贵: {max(f.base_value for f in fish_list)}")

    # 计算基础期望 (0.0加成，基础权重全为1.0保证公平)
    base_weights = service.get_weights(fish_list, 0.0)
    base_ev = service._calculate_ev(fish_list, base_weights)
    
    # 计算当前测试加成下的期望
    weights = service.get_weights(fish_list, coins_chance)
    actual_ev = service._calculate_ev(fish_list, weights)
    
    # 理论目标期望 (带天花板保护)
    target_ev = base_ev * (1 + coins_chance)
    max_value = max(f.base_value for f in fish_list)
    expected_ev = min(target_ev, max_value)
    
    print(f"【无加成基础期望】: {base_ev:.2f}")
    print(f"【目标期望(物理极限)】: {expected_ev:.2f} (极限: {max_value})")
    print(f"【实际拟合期望】: {actual_ev:.2f}")
    print(f"【最终误差】: {abs(actual_ev - expected_ev):.4f}")
    
    # 打印前三贵和前三便宜的鱼的概率变化
    total_weight = sum(weights)
    sorted_fishes = sorted(zip(fish_list, weights), key=lambda x: x[0].base_value, reverse=True)
    
    print("\n【部分代表性鱼类概率】:")
    for f, w in sorted_fishes[:3]:  # 最贵的
        prob = (w / total_weight) * 100 if total_weight > 0 else 0
        print(f"  [高价] {f.name[:10]:<10} (价值:{f.base_value:<6}): {prob:5.2f}%")
    if len(sorted_fishes) > 6:
        print("  ...")
    for f, w in sorted_fishes[-3:]: # 最便宜的
        prob = (w / total_weight) * 100 if total_weight > 0 else 0
        print(f"  [低价] {f.name[:10]:<10} (价值:{f.base_value:<6}): {prob:5.2f}%")

    # 核心断言
    assert abs(actual_ev - expected_ev) < 0.1