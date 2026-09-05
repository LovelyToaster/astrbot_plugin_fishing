import unittest
from draw.checkin import draw_sign_in_image, WIDTH


class TestCheckinDraw(unittest.TestCase):
    def test_dynamic_height_four_rows(self):
        """测试4行日历（如2021年2月，周一开始，28天）"""
        data = {
            "year": 2021,
            "month": 2,
            "days_in_month": 28,
            "signed_dates": [1, 2],
            "consecutive_days": 2,
            "today": 2,
            "reward": {
                "coins_base": 1000,
                "total_coins": 1000,
            }
        }
        img = draw_sign_in_image(data, "")
        self.assertEqual(img.width, WIDTH)
        self.assertEqual(img.height, 524)

    def test_dynamic_height_five_rows(self):
        """测试5行日历（如2026年9月，30天）"""
        data = {
            "year": 2026,
            "month": 9,
            "days_in_month": 30,
            "signed_dates": [1, 2, 3],
            "consecutive_days": 3,
            "today": 3,
            "reward": {
                "coins_base": 1000,
                "coins_linear": 300,
                "prem_base": 5,
                "total_coins": 1300,
                "total_premium": 5,
            }
        }
        img = draw_sign_in_image(data, "")
        self.assertEqual(img.width, WIDTH)
        self.assertEqual(img.height, 577)

    def test_dynamic_height_six_rows(self):
        """测试6行日历（如2026年8月，周六开始，31天），确保不会发生裁剪"""
        data = {
            "year": 2026,
            "month": 8,
            "days_in_month": 31,
            "signed_dates": [1, 5, 10, 15, 31],
            "consecutive_days": 5,
            "today": 15,
            "reward": {
                "coins_base": 1200,
                "coins_linear": 600,
                "coins_milestone": 2000,
                "prem_base": 1,
                "prem_linear": 1,
                "prem_milestone": 2,
                "total_coins": 3800,
                "total_premium": 4,
            }
        }
        img = draw_sign_in_image(data, "")
        self.assertEqual(img.width, WIDTH)
        self.assertEqual(img.height, 630)

    def test_no_reward_rendering(self):
        """测试未附带奖励详情时的渲染（紧凑自适应高度）"""
        data = {
            "year": 2026,
            "month": 8,
            "days_in_month": 31,
            "signed_dates": [15],
            "consecutive_days": 1,
            "today": 15,
            "reward": {}
        }
        img = draw_sign_in_image(data, "")
        self.assertEqual(img.width, WIDTH)
        self.assertEqual(img.height, 586)


if __name__ == "__main__":
    unittest.main()
