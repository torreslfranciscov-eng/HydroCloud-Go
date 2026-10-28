import ast
import datetime
import re
import unittest
from pathlib import Path


def load_rewrite_scope():
    source = Path("mycloud_all_timescale.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {
        "_clean_oracle_bind_val",
        "_oracle_bind_sql",
        "_clean_merge_update_right",
        "_oracle_rewrite_upsert_to_merge",
    }
    nodes = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    scope = {"datetime": datetime, "re": re}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "oracle-upsert", "exec"), scope)
    return scope


class OracleSummaryUpsertTests(unittest.TestCase):
    def test_select_upsert_converts_every_postgres_placeholder(self):
        rewrite = load_rewrite_scope()["_oracle_rewrite_upsert_to_merge"]
        start = datetime.datetime(2026, 10, 5, tzinfo=datetime.timezone.utc)
        end = start + datetime.timedelta(hours=1)
        sql, binds = rewrite("""
            INSERT INTO resumen_horario
                (ts, dcp_id, sensor_id, promedio)
            SELECT TRUNC(ts, 'HH') AS ts, %s AS dcp_id, sensor_id, AVG(valor) AS promedio
            FROM dcp_datos
            WHERE dcp_id = %s AND sensor_id = %s
              AND ts > %s AND ts <= %s AND valido = 1
            GROUP BY TRUNC(ts, 'HH'), sensor_id
            ON CONFLICT (ts, dcp_id, sensor_id) DO UPDATE SET
                promedio = EXCLUDED.promedio
        """, ("DCP", "DCP", "0001", start, end))

        self.assertNotIn("%s", sql)
        self.assertIn("src.ts", sql)
        self.assertIn("src.dcp_id", sql)
        for position in range(1, 6):
            self.assertIn(f":{position}", sql)
        self.assertEqual(binds[:3], ("DCP", "DCP", "0001"))
        self.assertEqual(binds[3:], (start, end))


if __name__ == "__main__":
    unittest.main()
