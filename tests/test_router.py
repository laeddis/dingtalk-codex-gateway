import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from src.executors.script_executor import build_ad_daily_markdown, build_ad_status_markdown, collect_ad_status_snapshots
from src.store_clients import DateWindow
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

    def test_missing_order_reconciliation_route(self):
        route = route_text("检查漏单 昨天")
        self.assertEqual(route.command, "reconcile_missing_orders_昨天")
        self.assertEqual(route.executor, "missing_order_reconciliation")
        self.assertEqual(route.args["day_word"], "昨天")

    def test_ad_status_route(self):
        route = route_text("广告状态")
        self.assertEqual(route.command, "ad_status")
        self.assertEqual(route.executor, "ad_status")

    def test_ad_daily_route(self):
        route = route_text("广告日报 昨天")
        self.assertEqual(route.command, "ad_daily_昨天")
        self.assertEqual(route.executor, "ad_daily")
        self.assertEqual(route.args["day_word"], "昨天")

    def test_ad_status_snapshot_from_csv(self):
        with TemporaryDirectory() as tmp:
            ad_tests = Path(tmp)
            (ad_tests / "dog_breed_shopline_meta_launch_results.csv").write_text(
                "campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_status,campaign_status,adset_status,title\n"
                "c1,Campaign One,s1,Adset One,a1,PAUSED,PAUSED,PAUSED,Ad One\n",
                encoding="utf-8",
            )
            snapshots = collect_ad_status_snapshots(ad_tests)
            markdown = build_ad_status_markdown(ad_tests, snapshots)
        self.assertEqual(len(snapshots), 1)
        self.assertIn("Campaign One", markdown)
        self.assertIn("PAUSED", markdown)

    def test_ad_status_snapshot_from_json_url_tags(self):
        with TemporaryDirectory() as tmp:
            ad_tests = Path(tmp)
            (ad_tests / "utm_update.json").write_text(
                """{
                  "updated": [{
                    "ad_id": "a1",
                    "ad_name": "Ad One",
                    "adset_id": "s1",
                    "url_tags": "utm_campaign=Campaign%20One&utm_id=c1&utm_adset=Adset%20One",
                    "status": "PAUSED"
                  }]
                }""",
                encoding="utf-8",
            )
            snapshots = collect_ad_status_snapshots(ad_tests)
        self.assertEqual(snapshots[0]["campaign_id"], "c1")
        self.assertEqual(snapshots[0]["campaign_name"], "Campaign One")
        self.assertEqual(snapshots[0]["adsets"]["s1"]["adset_name"], "Adset One")

    def test_ad_daily_markdown_totals(self):
        window = DateWindow("今天", "2026-06-06T00:00:00-04:00", "2026-06-07T00:00:00-04:00", "2026-06-06", "America/New_York")
        markdown = build_ad_daily_markdown(window, [{
            "campaign_name": "Campaign One",
            "status": "PAUSED",
            "effective_status": "PAUSED",
            "spend": "10.00",
            "impressions": "100.00",
            "clicks": "5.00",
            "link_clicks": "4.00",
            "purchases": "2.00",
            "purchase_value": "30.00",
            "cpa": "5.00",
            "roas": "3.00",
        }], [])
        self.assertIn("总花费：$10.00", markdown)
        self.assertIn("ROAS：3.00", markdown)


if __name__ == "__main__":
    unittest.main()
