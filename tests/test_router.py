import unittest

from src.router import route_text
from src.security import find_dangerous_pattern


class RouterTest(unittest.TestCase):
    def test_order_daily_defaults_to_all_today(self):
        route = route_text("订单日报 今天")
        self.assertEqual(route.command, "order_daily_今天_all")
        self.assertEqual(route.executor, "order_daily")
        self.assertEqual(route.args["store"], "all")

    def test_order_daily_store(self):
        route = route_text("订单日报 昨天 store=shoplazza")
        self.assertEqual(route.command, "order_daily_昨天_shoplazza")
        self.assertEqual(route.args["day_word"], "昨天")
        self.assertEqual(route.args["store"], "shoplazza")

    def test_dangerous_command_rejected(self):
        self.assertEqual(find_dangerous_pattern("帮我暂停广告"), "暂停广告")
        route = route_text("帮我暂停广告")
        self.assertEqual(route.executor, "reject")


if __name__ == "__main__":
    unittest.main()
