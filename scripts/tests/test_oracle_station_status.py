import ast
import unittest
from pathlib import Path


def load_status_scope():
    source = Path("mycloud_all_timescale.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    names = {
        "_oracle_estatus_merge_sql",
        "_actualizar_estatus_estacion_oracle",
    }
    nodes = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    scope = {"DB_BACKEND": "oracle"}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "status-functions", "exec"), scope)
    return scope


class Cursor:
    def __init__(self):
        self.calls = []

    def execute(self, sql, binds=None):
        self.calls.append((sql, binds))


class OracleStationStatusTests(unittest.TestCase):
    def test_global_merge_recalculates_current_windows(self):
        sql = load_status_scope()["_oracle_estatus_merge_sql"]()
        self.assertIn("INTERVAL '2' DAY", sql)
        self.assertIn("INTERVAL '1' DAY", sql)
        self.assertIn("e.fecha_calculo = SYSTIMESTAMP", sql)
        self.assertIn("e.mensajes_recibidos_48h", sql)
        self.assertIn("e.transmitiendo", sql)
        self.assertNotIn(":status_dcp_id", sql)

    def test_incremental_merge_is_limited_to_one_station(self):
        scope = load_status_scope()
        cursor = Cursor()
        scope["_actualizar_estatus_estacion_oracle"](cursor, "15F383A0")
        self.assertEqual(len(cursor.calls), 1)
        sql, binds = cursor.calls[0]
        self.assertIn("WHERE e2.dcp_id = :status_dcp_id", sql)
        self.assertEqual(binds, {"status_dcp_id": "15F383A0"})

    def test_incremental_merge_is_skipped_outside_oracle(self):
        scope = load_status_scope()
        scope["DB_BACKEND"] = "postgres"
        cursor = Cursor()
        scope["_actualizar_estatus_estacion_oracle"](cursor, "15F383A0")
        self.assertEqual(cursor.calls, [])


if __name__ == "__main__":
    unittest.main()
