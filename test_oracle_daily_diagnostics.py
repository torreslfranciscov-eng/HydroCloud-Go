import ast
import datetime
import unittest
from pathlib import Path


def load_diagnostic_scope():
    source = Path("mycloud_all_timescale.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function_names = {"_fechas_diagnostico_utc", "_filas_base_diagnostico"}
    constant_names = {
        "_DIAGNOSTICO_BASE_MERGE",
        "_DIAGNOSTICO_LIMPIAR_SQL",
        "_DIAGNOSTICO_HEADERS_MERGE",
        "_DIAGNOSTICO_VOLTAJE_MERGE",
        "_DIAGNOSTICO_CLASIFICAR_SQL",
    }
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in function_names:
            nodes.append(node)
        elif isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if any(name in constant_names for name in names):
                nodes.append(node)
    scope = {
        "datetime": datetime,
        "ESTACIONES": {
            "15F383A0": {
                "id_asignado": "TALIS07000",
                "nombre": "TALISMAN",
                "rango_transmision": 60,
            },
            "TEST10MIN": {
                "id_asignado": "TEST",
                "nombre": "PRUEBA",
                "rango_transmision": 10,
            },
        },
    }
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "diagnostic-functions", "exec"), scope)
    return scope


class OracleDailyDiagnosticsTests(unittest.TestCase):
    def test_base_rows_use_station_transmission_range(self):
        scope = load_diagnostic_scope()
        rows = scope["_filas_base_diagnostico"](datetime.date(2026, 10, 5))
        by_dcp = {row["diag_dcp"]: row for row in rows}
        self.assertEqual(by_dcp["15F383A0"]["diag_programadas"], 24)
        self.assertEqual(by_dcp["TEST10MIN"]["diag_programadas"], 144)

    def test_headers_are_aggregated_in_utc_day(self):
        sql = load_diagnostic_scope()["_DIAGNOSTICO_HEADERS_MERGE"]
        self.assertIn("SYS_EXTRACT_UTC(h.timestamp_msg) >= :diag_inicio", sql)
        self.assertIn("SYS_EXTRACT_UTC(h.timestamp_msg) < :diag_fin", sql)
        self.assertIn("COUNT(h.dcp_id) AS tx_recibidas", sql)
        self.assertIn("COUNT(DISTINCT h.channel)", sql)

    def test_cleanup_only_targets_completely_empty_stubs(self):
        sql = load_diagnostic_scope()["_DIAGNOSTICO_LIMPIAR_SQL"]
        self.assertIn("tx_programadas IS NULL", sql)
        self.assertIn("tx_recibidas IS NULL", sql)
        self.assertIn("porcentaje_eficiencia IS NULL", sql)
        self.assertIn("ultima_tx IS NULL", sql)

    def test_efficiency_signal_and_operational_thresholds_are_present(self):
        sql = load_diagnostic_scope()["_DIAGNOSTICO_CLASIFICAR_SQL"]
        self.assertIn("LEAST", sql)
        self.assertIn("d.potencia_prom >= 38 THEN 'EXCELENTE'", sql)
        self.assertIn(">= 0.80 THEN 'OPTIMO'", sql)
        self.assertIn(">= 0.50 THEN 'INTERMITENTE'", sql)

    def test_voltage_uses_only_valid_battery_measurements(self):
        sql = load_diagnostic_scope()["_DIAGNOSTICO_VOLTAJE_MERGE"]
        self.assertIn("NVL(x.valido, 1) = 1", sql)
        self.assertIn("LIKE '%VOLTAJE%BATER%'", sql)


if __name__ == "__main__":
    unittest.main()
