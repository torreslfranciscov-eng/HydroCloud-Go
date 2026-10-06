import datetime as dt
import inspect
import unittest

import repair_oracle_summaries as repair


class RepairOracleSummariesTests(unittest.TestCase):
    def test_rebuild_starts_before_every_invalidated_row(self):
        requested = dt.datetime(2026, 9, 29, tzinfo=dt.timezone.utc)
        corrupt = dt.datetime(2026, 9, 24, tzinfo=dt.timezone.utc)

        self.assertEqual(repair.repair_window_start(requested, corrupt), corrupt)
        self.assertEqual(repair.repair_window_start(corrupt, requested), corrupt)

    def test_destructive_statements_are_bounded_to_snapshot(self):
        source = inspect.getsource(repair.main)

        self.assertIn(
            "WHERE ts >= :corrupt_start AND ts < :end_ts AND valido = 1",
            source,
        )
        self.assertIn("WHERE ts >= :start_ts AND ts < :end_ts", source)
        self.assertIn(
            "WHERE fecha >= TRUNC(CAST(:start_ts AS DATE))", source
        )
        self.assertGreaterEqual(source.count("AND fecha < TRUNC(CAST(:end_ts AS DATE)) + 1"), 2)

    def test_apply_is_committed_as_one_transaction(self):
        source = inspect.getsource(repair.main)

        self.assertEqual(source.count("conn.commit()"), 1)

    def test_oracle_parallelism_is_disabled_before_large_merge(self):
        source = inspect.getsource(repair.main)

        disable_dml = source.index("ALTER SESSION DISABLE PARALLEL DML")
        disable_query = source.index("ALTER SESSION DISABLE PARALLEL QUERY")
        hourly_merge = source.index("cur.execute(HOURLY_MERGE")
        self.assertLess(disable_dml, hourly_merge)
        self.assertLess(disable_query, hourly_merge)


if __name__ == "__main__":
    unittest.main()
