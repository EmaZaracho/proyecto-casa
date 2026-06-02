import tempfile
import tkinter as tk
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import stock_app
import stock_gui


def _display_available() -> bool:
    try:
        root = tk.Tk()
        root.withdraw()
        root.destroy()
        return True
    except Exception:
        return False


# =============================================================================
# Business logic tests
# =============================================================================

class StockAppTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        self.conn = stock_app.get_connection(self.db_path)
        with patch.object(stock_app, "PHOTOS_DIR", Path(self.tmp.name) / "fotos_productos"):
            stock_app.initialize_database(self.conn)

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    # ── add / duplicate ───────────────────────────────────────────────────────

    def test_duplicate_product_is_controlled_error(self):
        stock_app.add_product(self.conn, "779001", "Yerba", 1500, 10, 2)
        with self.assertRaises(stock_app.DuplicateProductError):
            stock_app.add_product(self.conn, "779001", "Yerba repetida", 1600, 5, 1)

    def test_add_product_stores_proveedor(self):
        stock_app.add_product(self.conn, "P01", "Sal", 100, 5, 1, proveedor="DistNorte")
        product = stock_app.get_product(self.conn, "P01")
        self.assertEqual(product["proveedor"], "DistNorte")

    def test_add_product_proveedor_defaults_to_empty(self):
        stock_app.add_product(self.conn, "P02", "Azucar", 200, 3, 1)
        product = stock_app.get_product(self.conn, "P02")
        self.assertEqual(product["proveedor"], "")

    def test_add_product_stores_precio_costo_and_notas(self):
        stock_app.add_product(
            self.conn, "PC01", "Café", 1200, 5, 1,
            precio_costo=800.0, notas="Mantener en lugar fresco"
        )
        product = stock_app.get_product(self.conn, "PC01")
        self.assertEqual(product["precio_costo"], 800.0)
        self.assertEqual(product["notas"], "Mantener en lugar fresco")

    def test_add_product_precio_costo_defaults_to_zero(self):
        stock_app.add_product(self.conn, "PC02", "Pan", 300, 10, 2)
        product = stock_app.get_product(self.conn, "PC02")
        self.assertEqual(product["precio_costo"], 0.0)
        self.assertEqual(product["notas"], "")

    # ── input helpers ─────────────────────────────────────────────────────────

    def test_invalid_price_input_retries_until_valid_number(self):
        with patch("builtins.input", side_effect=["abc", "12,50"]):
            self.assertEqual(stock_app.read_float("Precio: "), 12.50)

    def test_missing_photo_path_is_ignored_and_product_is_created(self):
        stock_app.add_product(
            self.conn, "779002", "Fideos", 900, 4, 1,
            foto_path=str(Path(self.tmp.name) / "no_existe.jpg"),
        )
        product = stock_app.get_product(self.conn, "779002")
        self.assertIsNone(product["foto"])

    # ── sale ──────────────────────────────────────────────────────────────────

    def test_sale_updates_stock_and_daily_cash(self):
        stock_app.add_product(self.conn, "779003", "Arroz", 1000, 5, 1)
        total = stock_app.register_sale(self.conn, "779003", 2, sale_date=date(2026, 5, 23))
        product = stock_app.get_product(self.conn, "779003")
        cash = self.conn.execute(
            "SELECT total FROM caja WHERE fecha = '2026-05-23'"
        ).fetchone()
        self.assertEqual(total, 2000)
        self.assertEqual(product["stock"], 3)
        self.assertEqual(cash["total"], 2000)

    def test_sale_creates_venta_record(self):
        stock_app.add_product(self.conn, "VR01", "Leche", 500, 10, 1)
        stock_app.register_sale(self.conn, "VR01", 3, sale_date=date(2026, 5, 23))
        ventas = self.conn.execute(
            "SELECT * FROM ventas WHERE codigo = 'VR01'"
        ).fetchall()
        self.assertEqual(len(ventas), 1)
        self.assertEqual(ventas[0]["cantidad"], 3)
        self.assertEqual(ventas[0]["total"], 1500.0)
        self.assertEqual(ventas[0]["fecha"], "2026-05-23")

    def test_sale_without_stock_requires_authorization(self):
        stock_app.add_product(self.conn, "779004", "Aceite", 3000, 1, 1)
        with self.assertRaises(stock_app.InsufficientStockError):
            stock_app.register_sale(self.conn, "779004", 2)
        total = stock_app.register_sale(self.conn, "779004", 2, allow_negative=True)
        product = stock_app.get_product(self.conn, "779004")
        self.assertEqual(total, 6000)
        self.assertEqual(product["stock"], -1)

    # ── reverse_sale ──────────────────────────────────────────────────────────

    def test_reverse_sale_restores_stock_and_subtracts_from_caja(self):
        stock_app.add_product(self.conn, "REV01", "Yerba", 1000, 10, 1)
        stock_app.register_sale(self.conn, "REV01", 3, sale_date=date(2026, 5, 1))
        stock_app.reverse_sale(self.conn, "REV01", 3, 3000.0, "2026-05-01")
        product = stock_app.get_product(self.conn, "REV01")
        cash = self.conn.execute(
            "SELECT total FROM caja WHERE fecha = '2026-05-01'"
        ).fetchone()
        self.assertEqual(product["stock"], 10)
        self.assertEqual(cash["total"], 0.0)

    def test_reverse_sale_deletes_venta_record(self):
        stock_app.add_product(self.conn, "REV03", "Queso", 800, 5, 1)
        stock_app.register_sale(self.conn, "REV03", 2, sale_date=date(2026, 5, 5))
        total = 1600.0
        stock_app.reverse_sale(self.conn, "REV03", 2, total, "2026-05-05")
        ventas = self.conn.execute(
            "SELECT * FROM ventas WHERE codigo = 'REV03'"
        ).fetchall()
        self.assertEqual(ventas, [])

    def test_reverse_sale_caja_does_not_go_negative(self):
        stock_app.add_product(self.conn, "REV02", "Fideo", 500, 5, 1)
        stock_app.register_sale(self.conn, "REV02", 1, sale_date=date(2026, 5, 2))
        # try to reverse more than what's in caja
        stock_app.reverse_sale(self.conn, "REV02", 10, 99999.0, "2026-05-02")
        cash = self.conn.execute(
            "SELECT total FROM caja WHERE fecha = '2026-05-02'"
        ).fetchone()
        self.assertEqual(cash["total"], 0.0)

    # ── get_ventas_hoy / get_daily_summary ────────────────────────────────────

    def test_get_ventas_hoy_returns_todays_sales(self):
        stock_app.add_product(self.conn, "GVH01", "Aceite", 1000, 5, 0)
        stock_app.add_product(self.conn, "GVH02", "Sal", 200, 10, 0)
        today = date.today()
        stock_app.register_sale(self.conn, "GVH01", 2, sale_date=today)
        stock_app.register_sale(self.conn, "GVH02", 1, sale_date=today)
        ventas = stock_app.get_ventas_hoy(self.conn)
        self.assertEqual(len(ventas), 2)

    def test_get_ventas_hoy_excludes_other_dates(self):
        stock_app.add_product(self.conn, "GVH03", "Pan", 300, 5, 0)
        stock_app.register_sale(self.conn, "GVH03", 1, sale_date=date(2025, 1, 1))
        ventas = stock_app.get_ventas_hoy(self.conn)
        self.assertEqual(ventas, [])

    def test_get_daily_summary_totals(self):
        stock_app.add_product(self.conn, "GDS01", "Café", 500, 5, 0)
        today = date.today()
        stock_app.register_sale(self.conn, "GDS01", 2, sale_date=today)
        stock_app.register_sale(self.conn, "GDS01", 1, sale_date=today)
        summary = stock_app.get_daily_summary(self.conn)
        self.assertEqual(summary["count"], 2)
        self.assertEqual(summary["total"], 1500.0)

    # ── low stock ─────────────────────────────────────────────────────────────

    def test_low_stock_query(self):
        stock_app.add_product(self.conn, "779005", "Sal", 700, 1, 2)
        stock_app.add_product(self.conn, "779006", "Azucar", 1200, 5, 1)
        rows = stock_app.low_stock_products(self.conn)
        self.assertEqual([row["codigo"] for row in rows], ["779005"])

    def test_low_stock_at_minimum_does_not_alert(self):
        stock_app.add_product(self.conn, "779007", "Pimienta", 300, 2, 2)
        self.assertEqual(stock_app.low_stock_products(self.conn), [])

    def test_low_stock_minimo_zero_never_alerts(self):
        stock_app.add_product(self.conn, "779008", "Sal gruesa", 400, 0, 0)
        self.assertEqual(stock_app.low_stock_products(self.conn), [])

    # ── update_product ────────────────────────────────────────────────────────

    def test_update_product_changes_fields(self):
        stock_app.add_product(self.conn, "UP001", "Original", 1000, 5, 1)
        stock_app.update_product(
            self.conn, "UP001", "Actualizado", 1500, 10, 2,
            proveedor="ProvX", precio_costo=900.0, notas="Nueva nota"
        )
        product = stock_app.get_product(self.conn, "UP001")
        self.assertEqual(product["nombre"], "Actualizado")
        self.assertEqual(product["precio"], 1500)
        self.assertEqual(product["stock"], 10)
        self.assertEqual(product["stock_minimo"], 2)
        self.assertEqual(product["proveedor"], "ProvX")
        self.assertEqual(product["precio_costo"], 900.0)
        self.assertEqual(product["notas"], "Nueva nota")

    def test_update_preserves_foto_when_no_new_path(self):
        stock_app.add_product(self.conn, "UP002", "Sin foto", 100, 1, 0)
        stock_app.update_product(self.conn, "UP002", "Sin foto v2", 200, 2, 0)
        product = stock_app.get_product(self.conn, "UP002")
        self.assertIsNone(product["foto"])

    def test_update_nonexistent_product_raises(self):
        with self.assertRaises(stock_app.ProductNotFoundError):
            stock_app.update_product(self.conn, "NOPE", "X", 1.0, 1, 0)

    # ── delete_product ────────────────────────────────────────────────────────

    def test_delete_product_removes_from_db(self):
        stock_app.add_product(self.conn, "DEL001", "Borrar", 500, 3, 1)
        stock_app.delete_product(self.conn, "DEL001")
        with self.assertRaises(stock_app.ProductNotFoundError):
            stock_app.get_product(self.conn, "DEL001")

    def test_delete_nonexistent_product_raises(self):
        with self.assertRaises(stock_app.ProductNotFoundError):
            stock_app.delete_product(self.conn, "NOPE")

    def test_delete_does_not_affect_other_products(self):
        stock_app.add_product(self.conn, "KEEP", "Queda", 100, 1, 0)
        stock_app.add_product(self.conn, "GONE", "Borra", 100, 1, 0)
        stock_app.delete_product(self.conn, "GONE")
        rows = stock_app.list_products(self.conn)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["codigo"], "KEEP")

    def test_restore_product_reinserts_row(self):
        stock_app.add_product(
            self.conn, "REST01", "Restoreable", 300, 2, 0,
            proveedor="Prov", precio_costo=150.0, notas="Nota"
        )
        product = stock_app.get_product(self.conn, "REST01")
        data = {k: product[k] for k in product.keys()}
        stock_app.delete_product(self.conn, "REST01")
        stock_app._restore_product(self.conn, data)
        restored = stock_app.get_product(self.conn, "REST01")
        self.assertEqual(restored["nombre"], "Restoreable")
        self.assertEqual(restored["proveedor"], "Prov")
        self.assertEqual(restored["precio_costo"], 150.0)
        self.assertEqual(restored["notas"], "Nota")

    # ── bulk_price_increase ───────────────────────────────────────────────────

    def test_bulk_price_increase_applies_percentage(self):
        stock_app.add_product(self.conn, "BPI01", "Prod A", 1000, 1, 0)
        stock_app.add_product(self.conn, "BPI02", "Prod B", 2000, 1, 0)
        stock_app.bulk_price_increase(self.conn, ["BPI01", "BPI02"], 10.0)
        a = stock_app.get_product(self.conn, "BPI01")
        b = stock_app.get_product(self.conn, "BPI02")
        self.assertEqual(a["precio"], 1100.0)
        self.assertEqual(b["precio"], 2200.0)

    def test_bulk_price_increase_rounds_to_nearest_ten(self):
        stock_app.add_product(self.conn, "BPI03", "Prod C", 1234, 1, 0)
        stock_app.bulk_price_increase(self.conn, ["BPI03"], 15.0)
        product = stock_app.get_product(self.conn, "BPI03")
        # 1234 * 1.15 = 1419.1 → rounds to 1420
        self.assertEqual(product["precio"] % 10, 0)
        self.assertEqual(product["precio"], 1420.0)

    def test_bulk_price_increase_returns_changes(self):
        stock_app.add_product(self.conn, "BPI04", "Prod D", 1000, 1, 0)
        changes = stock_app.bulk_price_increase(self.conn, ["BPI04"], 20.0)
        self.assertEqual(len(changes), 1)
        codigo, old_price, new_price = changes[0]
        self.assertEqual(codigo, "BPI04")
        self.assertEqual(old_price, 1000.0)
        self.assertEqual(new_price, 1200.0)

    def test_bulk_price_increase_skips_unknown_codes(self):
        stock_app.add_product(self.conn, "BPI05", "Prod E", 500, 1, 0)
        changes = stock_app.bulk_price_increase(self.conn, ["BPI05", "UNKNOWN"], 10.0)
        self.assertEqual(len(changes), 1)

    # ── get_all_proveedores ───────────────────────────────────────────────────

    def test_get_all_proveedores_returns_unique_sorted(self):
        stock_app.add_product(self.conn, "GP01", "A", 100, 1, 0, proveedor="Zeta")
        stock_app.add_product(self.conn, "GP02", "B", 100, 1, 0, proveedor="Alfa")
        stock_app.add_product(self.conn, "GP03", "C", 100, 1, 0, proveedor="Zeta")
        proveedores = stock_app.get_all_proveedores(self.conn)
        self.assertEqual(proveedores, ["Alfa", "Zeta"])

    def test_get_all_proveedores_excludes_empty(self):
        stock_app.add_product(self.conn, "GP04", "D", 100, 1, 0)
        proveedores = stock_app.get_all_proveedores(self.conn)
        self.assertEqual(proveedores, [])

    # ── pending ───────────────────────────────────────────────────────────────

    def test_delete_pending_removes_item(self):
        stock_app.add_pending(self.conn, "Tarea de prueba")
        rows = stock_app.list_pending(self.conn)
        pending_id = rows[0]["id"]
        result = stock_app.delete_pending(self.conn, pending_id)
        self.assertTrue(result)
        self.assertEqual(stock_app.list_pending(self.conn), [])

    def test_delete_pending_nonexistent_returns_false(self):
        self.assertFalse(stock_app.delete_pending(self.conn, 9999))

    # ── backup_database ───────────────────────────────────────────────────────

    def test_backup_database_creates_file(self):
        with patch.object(stock_app, "BASE_DIR", Path(self.tmp.name)), \
             patch.object(stock_app, "DB_PATH", self.db_path):
            result = stock_app.backup_database()
        self.assertIsNotNone(result)
        self.assertTrue(result.exists())
        self.assertTrue(result.name.startswith("stock_"))

    def test_backup_database_skips_if_already_done_today(self):
        with patch.object(stock_app, "BASE_DIR", Path(self.tmp.name)), \
             patch.object(stock_app, "DB_PATH", self.db_path):
            first = stock_app.backup_database()
            second = stock_app.backup_database()
        self.assertIsNotNone(first)
        self.assertIsNone(second)

    # ── export CSV ────────────────────────────────────────────────────────────

    def test_export_products_csv_creates_file(self):
        stock_app.add_product(self.conn, "EXP01", "Exportable", 100, 5, 1)
        dest = Path(self.tmp.name) / "productos.csv"
        n = stock_app.export_products_csv(self.conn, dest)
        self.assertEqual(n, 1)
        self.assertTrue(dest.exists())
        content = dest.read_text(encoding="utf-8-sig")
        self.assertIn("EXP01", content)
        self.assertIn("Exportable", content)

    def test_export_ventas_csv_creates_file(self):
        stock_app.add_product(self.conn, "EXV01", "Vendible", 500, 10, 0)
        today = date.today()
        stock_app.register_sale(self.conn, "EXV01", 2, sale_date=today)
        dest = Path(self.tmp.name) / "ventas.csv"
        n = stock_app.export_ventas_csv(self.conn, dest)
        self.assertEqual(n, 1)
        content = dest.read_text(encoding="utf-8-sig")
        self.assertIn("EXV01", content)


# =============================================================================
# Parse helper tests
# =============================================================================

class ParseHelpersTests(unittest.TestCase):
    def test_parse_float_comma_separator(self):
        self.assertAlmostEqual(stock_gui.parse_float("3,14", "precio"), 3.14)

    def test_parse_float_integer_string(self):
        self.assertEqual(stock_gui.parse_float("100", "precio"), 100.0)

    def test_parse_float_zero_is_valid(self):
        self.assertEqual(stock_gui.parse_float("0", "precio"), 0.0)

    def test_parse_float_negative_raises(self):
        with self.assertRaises(ValueError):
            stock_gui.parse_float("-1", "precio")

    def test_parse_float_non_numeric_raises(self):
        with self.assertRaises(ValueError):
            stock_gui.parse_float("abc", "precio")

    def test_parse_int_valid(self):
        self.assertEqual(stock_gui.parse_int("5", "stock"), 5)

    def test_parse_int_zero_is_valid(self):
        self.assertEqual(stock_gui.parse_int("0", "stock"), 0)

    def test_parse_int_negative_raises(self):
        with self.assertRaises(ValueError):
            stock_gui.parse_int("-1", "stock")

    def test_parse_int_non_numeric_raises(self):
        with self.assertRaises(ValueError):
            stock_gui.parse_int("abc", "stock")


# =============================================================================
# GUI integration tests
# =============================================================================

@unittest.skipUnless(_display_available(), "No hay display disponible para tests de GUI")
class StockGuiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp_dir = Path(self.tmp.name)
        db_path = tmp_dir / "test_gui.db"
        photos_dir = tmp_dir / "fotos_productos"

        self.test_conn = stock_app.get_connection(db_path)
        self._photos_patch = patch.object(stock_app, "PHOTOS_DIR", photos_dir)
        self._conn_patch = patch.object(stock_app, "get_connection", return_value=self.test_conn)
        self._photos_patch.start()
        self._conn_patch.start()

        self.app = stock_gui.StockGui()
        self.app.withdraw()

    def tearDown(self):
        try:
            self.app.destroy()
        except Exception:
            pass
        self._conn_patch.stop()
        self._photos_patch.stop()
        self.test_conn.close()
        self.tmp.cleanup()

    # ── initial state ─────────────────────────────────────────────────────────

    def test_initial_caja_is_zero(self):
        self.assertIn("$0.00", self.app.caja_var.get())

    def test_initial_edit_mode_is_false(self):
        self.assertFalse(self.app._edit_mode)
        self.assertIsNone(self.app._edit_codigo)
        self.assertFalse(self.app._form_visible)
        self.assertFalse(self.app._product_form_frame.winfo_ismapped())

    def test_undo_button_starts_disabled(self):
        self.assertEqual(str(self.app._undo_btn.cget("state")), "disabled")

    def test_cart_mode_starts_inactive(self):
        self.assertTrue(self.app._cart_mode_active)
        self.assertEqual(self.app._cart, [])

    # ── create product ────────────────────────────────────────────────────────

    def test_create_product_via_gui_adds_to_db(self):
        self.app.codigo_var.set("GUI001")
        self.app.nombre_var.set("Producto GUI")
        self.app.precio_var.set("250")
        self.app.precio_costo_var.set("150")
        self.app.stock_var.set("10")
        self.app.stock_minimo_var.set("2")
        self.app.proveedor_var.set("Prov Test")
        self.app.notas_var.set("Nota de prueba")
        self.app.save_product()
        rows = stock_app.list_products(self.app.conn)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["codigo"], "GUI001")
        self.assertEqual(rows[0]["proveedor"], "Prov Test")
        self.assertEqual(rows[0]["precio_costo"], 150.0)
        self.assertEqual(rows[0]["notas"], "Nota de prueba")

    def test_create_product_clears_form_on_success(self):
        self.app.codigo_var.set("GUI002")
        self.app.nombre_var.set("Otro")
        self.app.precio_var.set("100")
        self.app.stock_var.set("5")
        self.app.stock_minimo_var.set("1")
        self.app.precio_costo_var.set("60")
        self.app.save_product()
        self.assertEqual(self.app.codigo_var.get(), "")
        self.assertEqual(self.app.nombre_var.get(), "")
        self.assertEqual(self.app.proveedor_var.get(), "")
        self.assertEqual(self.app.precio_costo_var.get(), "")
        self.assertEqual(self.app.notas_var.get(), "")

    # ── edit mode ─────────────────────────────────────────────────────────────

    def test_enter_edit_mode_populates_form(self):
        stock_app.add_product(
            self.test_conn, "ED001", "Editable", 500, 8, 2,
            proveedor="ProvX", precio_costo=300.0, notas="Fragil"
        )
        product = stock_app.get_product(self.test_conn, "ED001")
        self.app.enter_edit_mode(product)
        self.assertTrue(self.app._edit_mode)
        self.assertTrue(self.app._form_visible)
        self.assertEqual(self.app._edit_codigo, "ED001")
        self.assertEqual(self.app.codigo_var.get(), "ED001")
        self.assertEqual(self.app.nombre_var.get(), "Editable")
        self.assertEqual(self.app.proveedor_var.get(), "ProvX")
        self.assertEqual(self.app.notas_var.get(), "Fragil")
        self.assertEqual(self.app._save_btn.cget("text"), "Actualizar")

    def test_cancel_edit_resets_to_create_mode(self):
        stock_app.add_product(self.test_conn, "ED002", "Cancelar", 100, 3, 1)
        product = stock_app.get_product(self.test_conn, "ED002")
        self.app.enter_edit_mode(product)
        self.app.cancel_edit()
        self.assertFalse(self.app._edit_mode)
        self.assertIsNone(self.app._edit_codigo)
        self.assertEqual(self.app.codigo_var.get(), "")
        self.assertEqual(self.app._save_btn.cget("text"), "Guardar")
        self.assertTrue(self.app._form_visible)

    def test_update_product_via_gui(self):
        stock_app.add_product(self.test_conn, "UP_GUI", "Antes", 100, 5, 1)
        product = stock_app.get_product(self.test_conn, "UP_GUI")
        self.app.enter_edit_mode(product)
        self.app.nombre_var.set("Despues")
        self.app.precio_var.set("200")
        self.app.precio_costo_var.set("120")
        self.app.save_product()
        updated = stock_app.get_product(self.test_conn, "UP_GUI")
        self.assertEqual(updated["nombre"], "Despues")
        self.assertEqual(updated["precio"], 200.0)
        self.assertEqual(updated["precio_costo"], 120.0)
        self.assertFalse(self.app._edit_mode)

    # ── undo ──────────────────────────────────────────────────────────────────

    def test_undo_product_deletion(self):
        stock_app.add_product(self.test_conn, "UNDO01", "Undo Test", 100, 1, 0)
        self.app.refresh_products()
        iid = self.app.products_table.get_children()[0]
        self.app.products_table.selection_set(iid)
        with patch.object(stock_gui.messagebox, "askyesno", return_value=True):
            self.app.delete_selected_product()
        self.assertEqual(stock_app.list_products(self.test_conn), [])
        self.app._undo()
        rows = stock_app.list_products(self.test_conn)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["nombre"], "Undo Test")

    def test_undo_sale(self):
        stock_app.add_product(self.test_conn, "SALE01", "Venta Undo", 1000, 5, 0)
        self.app.venta_codigo_var.set("SALE01")
        self.app.venta_cantidad_var.set("2")
        self.app.register_sale()
        product_after = stock_app.get_product(self.test_conn, "SALE01")
        self.assertEqual(product_after["stock"], 3)
        self.app._undo()
        product_restored = stock_app.get_product(self.test_conn, "SALE01")
        self.assertEqual(product_restored["stock"], 5)

    def test_undo_price_increase(self):
        stock_app.add_product(self.test_conn, "PRICE01", "Precio Undo", 1000, 1, 0)
        self.app.refresh_price_table()
        iid = self.app.price_table.get_children()[0]
        self.app.price_table.selection_set(iid)
        self.app.aumento_var.set("10")
        with patch.object(stock_gui.messagebox, "askyesno", return_value=True):
            self.app._apply_to_selected()
        product_increased = stock_app.get_product(self.test_conn, "PRICE01")
        self.assertEqual(product_increased["precio"], 1100.0)
        self.app._undo()
        product_original = stock_app.get_product(self.test_conn, "PRICE01")
        self.assertEqual(product_original["precio"], 1000.0)

    # ── cart mode ─────────────────────────────────────────────────────────────

    def test_toggle_cart_mode_activates(self):
        self.app._toggle_cart_mode()
        self.assertFalse(self.app._cart_mode_active)

    def test_add_to_cart_accumulates_items(self):
        stock_app.add_product(self.test_conn, "CART01", "Producto Carrito", 500, 10, 0)
        self.app._toggle_cart_mode()
        self.app.venta_codigo_var.set("CART01")
        self.app.venta_cantidad_var.set("3")
        self.app._add_to_cart()
        self.assertEqual(len(self.app._cart), 1)
        self.assertEqual(self.app._cart[0]["cantidad"], 3)
        self.assertEqual(self.app._cart[0]["subtotal"], 1500.0)

    def test_add_to_cart_merges_same_product(self):
        stock_app.add_product(self.test_conn, "CART02", "Mergeble", 200, 10, 0)
        self.app._toggle_cart_mode()
        self.app.venta_codigo_var.set("CART02")
        self.app.venta_cantidad_var.set("2")
        self.app._add_to_cart()
        self.app.venta_codigo_var.set("CART02")
        self.app.venta_cantidad_var.set("3")
        self.app._add_to_cart()
        self.assertEqual(len(self.app._cart), 1)
        self.assertEqual(self.app._cart[0]["cantidad"], 5)

    def test_cobrar_carrito_registers_sales(self):
        stock_app.add_product(self.test_conn, "CART03", "Cobrable", 300, 5, 0)
        self.app._toggle_cart_mode()
        self.app.venta_codigo_var.set("CART03")
        self.app.venta_cantidad_var.set("2")
        self.app._add_to_cart()
        self.app._cobrar_carrito()
        product = stock_app.get_product(self.test_conn, "CART03")
        self.assertEqual(product["stock"], 3)
        self.assertEqual(self.app._cart, [])

    # ── search ────────────────────────────────────────────────────────────────

    def test_search_filters_products_table(self):
        stock_app.add_product(self.test_conn, "AAA", "Arroz", 100, 5, 1)
        stock_app.add_product(self.test_conn, "BBB", "Fideos", 80, 3, 1)
        self.app.refresh_products()
        self.app.search_var.set("fide")
        self.app.update_idletasks()
        visible = [
            self.app.products_table.item(iid, "values")[1]
            for iid in self.app.products_table.get_children()
        ]
        self.assertEqual(visible, ["Fideos"])

    def test_price_table_filters_by_proveedor(self):
        stock_app.add_product(self.test_conn, "CCC", "Cola", 50, 2, 0, proveedor="Bebidas SA")
        stock_app.add_product(self.test_conn, "DDD", "Pan", 30, 4, 0, proveedor="Panaderia")
        self.app.price_proveedor_var.set("Bebidas SA")
        self.app.refresh_price_table()
        visible = [
            self.app.price_table.item(iid, "values")[1]
            for iid in self.app.price_table.get_children()
        ]
        self.assertEqual(visible, ["Cola"])

    def test_price_table_shows_margen(self):
        stock_app.add_product(
            self.test_conn, "MAR01", "Con margen", 1000, 5, 0, precio_costo=600.0
        )
        self.app.refresh_price_table()
        iid = self.app.price_table.get_children()[0]
        values = self.app.price_table.item(iid, "values")
        margen_col = values[4]  # "margen" is col index 4
        self.assertIn("%", margen_col)
        self.assertNotEqual(margen_col, "-")

    # ── pending ───────────────────────────────────────────────────────────────

    def test_delete_pending_via_gui(self):
        stock_app.add_pending(self.test_conn, "Tarea GUI")
        self.app.refresh_pending()
        iid = self.app.pending_table.get_children()[0]
        self.app.pending_table.selection_set(iid)
        with patch.object(stock_gui.messagebox, "askyesno", return_value=True):
            self.app.delete_selected_pending()
        self.assertEqual(self.app.pending_table.get_children(), ())
        self.assertEqual(stock_app.list_pending(self.test_conn), [])


if __name__ == "__main__":
    unittest.main()
