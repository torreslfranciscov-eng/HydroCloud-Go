import ast
import datetime as dt
import unittest
from pathlib import Path


class HourlyDailySummaryAlignmentTests(unittest.TestCase):
    def test_textual_daily_summary_uses_the_hourly_day_boundary(self):
        source = Path("mycloud_all_timescale.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "actualizar_resumenes_dcp"
        )
        function_source = ast.get_source_segment(source, function)
        self.assertIn(", 0, 1, 0, tzinfo=", function_source)
        daily_queries = [
            node.value for node in ast.walk(function)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and "INSERT INTO resumen_diario" in node.value
        ]
        self.assertEqual(len(daily_queries), 1)
        self.assertIn("AND ts >= %s AND ts < %s", daily_queries[0])

    def test_gs300_daily_summary_uses_the_same_day_boundary(self):
        source = Path("mycloud_all_timescale.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        function = next(
            node for node in tree.body
            if isinstance(node, ast.FunctionDef)
            and node.name == "insertar_datos_mapeados"
        )
        function_source = ast.get_source_segment(source, function)
        self.assertIn("datetime.time(0, 1)", function_source)
        self.assertIn(
            "fecha_inicio = (ts_inicio - datetime.timedelta(minutes=1)).date()",
            function_source,
        )
        self.assertIn(
            "fecha_fin = (ts_fin - datetime.timedelta(minutes=1)).date()",
            function_source,
        )
        self.assertIn("date_trunc('hour', ts - INTERVAL '1 minute')", function_source)

    def test_daily_bucket_sums_match_hourly_buckets_at_midnight(self):
        day = dt.datetime(2026, 10, 5, tzinfo=dt.timezone.utc)
        samples = [
            (day, 2.0),
            (day + dt.timedelta(minutes=1), 3.0),
            (day + dt.timedelta(hours=23), 5.0),
            (day + dt.timedelta(days=1), 7.0),
            (day + dt.timedelta(days=1, minutes=1), 11.0),
        ]

        hourly_totals = {}
        daily_totals = {}
        for timestamp, value in samples:
            bucket = timestamp - dt.timedelta(minutes=1)
            hour = bucket.replace(minute=0, second=0, microsecond=0)
            hourly_totals[hour] = hourly_totals.get(hour, 0.0) + value
            daily = bucket.date()
            daily_totals[daily] = daily_totals.get(daily, 0.0) + value

        for offset in range(3):
            date = (day + dt.timedelta(days=offset)).date()
            start = dt.datetime.combine(
                date, dt.time(0, 1), tzinfo=dt.timezone.utc
            )
            end = start + dt.timedelta(days=1)
            summary_total = sum(
                value for timestamp, value in samples
                if start <= timestamp < end
            )
            hourly_total = sum(
                value for hour, value in hourly_totals.items()
                if hour.date() == date
            )
            self.assertEqual(summary_total, hourly_total)

        self.assertEqual(
            daily_totals,
            {
                dt.date(2026, 10, 4): 2.0,
                dt.date(2026, 10, 5): 15.0,
                dt.date(2026, 10, 6): 11.0,
            },
        )
        self.assertEqual(
            sum(daily_totals.values()),
            sum(hourly_totals.values()),
        )


if __name__ == "__main__":
    unittest.main()
