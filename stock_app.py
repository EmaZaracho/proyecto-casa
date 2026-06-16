from __future__ import annotations

import csv
from dataclasses import dataclass
import json
import logging
import shutil
import sqlite3
from datetime import date, datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "stock.db"
CONFIG_PATH = BASE_DIR / "config.json"

_DEFAULT_CONFIG: dict = {
    "nombre_negocio": "Sistema de Stock",
    "moneda": "$",
}

logger = logging.getLogger(__name__)


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            return {**_DEFAULT_CONFIG, **data}
        except Exception:
            logger.warning("No se pudo leer config.json, usando valores por defecto")
    return dict(_DEFAULT_CONFIG)


def save_config(config: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")


class StockError(Exception):
    pass


class DuplicateProductError(StockError):
    pass


class ProductNotFoundError(StockError):
    pass


class InsufficientStockError(StockError):
    pass


@dataclass
class BoletaRow:
    codigo: str
    nombre: str
    cantidad: int
    precio_costo: float | None = None
    precio_venta: float | None = None
    proveedor: str | None = None


@dataclass
class BoletaResult:
    rows_new: list
    rows_clean: list
    rows_conflict: list
    skipped: list


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


_SCHEMA_VERSION = 5


def initialize_database(conn: sqlite3.Connection) -> None:
    # schema_version table — must be first so migrations can reference it
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER NOT NULL
        )
        """
    )
    row = conn.execute("SELECT version FROM schema_version").fetchone()
    current_version = int(row["version"]) if row else 0

    # ── base tables (idempotent) ───────────────────────────────────────────────
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS productos (
            codigo TEXT PRIMARY KEY,
            nombre TEXT NOT NULL,
            precio REAL NOT NULL CHECK(precio >= 0),
            stock INTEGER NOT NULL,
            stock_minimo INTEGER NOT NULL CHECK(stock_minimo >= 0),
            foto TEXT,
            proveedor TEXT NOT NULL DEFAULT '',
            precio_costo REAL NOT NULL DEFAULT 0,
            notas TEXT NOT NULL DEFAULT ''
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS pendientes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            descripcion TEXT NOT NULL,
            estado TEXT NOT NULL DEFAULT 'Pendiente'
                CHECK(estado IN ('Pendiente', 'Completado')),
            creado_en TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS caja (
            fecha TEXT PRIMARY KEY,
            total REAL NOT NULL DEFAULT 0 CHECK(total >= 0)
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ventas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT NOT NULL,
            nombre TEXT NOT NULL,
            cantidad INTEGER NOT NULL,
            precio_unit REAL NOT NULL,
            total REAL NOT NULL,
            fecha TEXT NOT NULL,
            hora TEXT NOT NULL,
            forma_pago TEXT NOT NULL DEFAULT 'Efectivo',
            precio_costo REAL NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS historial_precios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT NOT NULL,
            nombre TEXT NOT NULL,
            precio_anterior REAL NOT NULL,
            precio_nuevo REAL NOT NULL,
            fecha TEXT NOT NULL,
            motivo TEXT NOT NULL DEFAULT ''
        )
        """
    )

    # ── versioned migrations ───────────────────────────────────────────────────
    def _col_exists(table: str, col: str) -> bool:
        cols = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        return col in cols

    # v0 → v1: add extra columns to productos (legacy migration kept as-is)
    if current_version < 1:
        for col, definition in [
            ("proveedor", "TEXT NOT NULL DEFAULT ''"),
            ("precio_costo", "REAL NOT NULL DEFAULT 0"),
            ("notas", "TEXT NOT NULL DEFAULT ''"),
        ]:
            if not _col_exists("productos", col):
                conn.execute(f"ALTER TABLE productos ADD COLUMN {col} {definition}")

    # v1 → v2: add forma_pago to ventas
    if current_version < 2:
        if not _col_exists("ventas", "forma_pago"):
            conn.execute("ALTER TABLE ventas ADD COLUMN forma_pago TEXT NOT NULL DEFAULT 'Efectivo'")

    # v2 → v3: add precio_costo to ventas (for profit tracking)
    if current_version < 3:
        if not _col_exists("ventas", "precio_costo"):
            conn.execute("ALTER TABLE ventas ADD COLUMN precio_costo REAL NOT NULL DEFAULT 0")

    # v3 -> v4: indexes for common searches and reports
    if current_version < 4:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ventas_fecha ON ventas(fecha)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_productos_nombre ON productos(nombre)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_productos_proveedor ON productos(proveedor)")

    # v4 -> v5: multiple suppliers per product, keeping productos as active supplier cache
    if current_version < 5:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS proveedores_producto (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo TEXT NOT NULL REFERENCES productos(codigo) ON DELETE CASCADE,
                proveedor TEXT NOT NULL,
                precio_costo REAL NOT NULL CHECK(precio_costo >= 0),
                es_principal INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        rows = conn.execute(
            """
            SELECT codigo, proveedor, precio_costo
            FROM productos
            WHERE proveedor != ''
            """
        ).fetchall()
        for row in rows:
            exists = conn.execute(
                """
                SELECT 1 FROM proveedores_producto
                WHERE codigo = ? AND proveedor = ? AND es_principal = 1
                """,
                (row["codigo"], row["proveedor"]),
            ).fetchone()
            if not exists:
                conn.execute(
                    """
                    INSERT INTO proveedores_producto
                        (codigo, proveedor, precio_costo, es_principal)
                    VALUES (?, ?, ?, 1)
                    """,
                    (row["codigo"], row["proveedor"], row["precio_costo"]),
                )

    # update stored version
    if current_version == 0:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (_SCHEMA_VERSION,))
    elif current_version < _SCHEMA_VERSION:
        conn.execute("UPDATE schema_version SET version = ?", (_SCHEMA_VERSION,))

    conn.commit()


def sanitize_path(raw_path: str) -> Path:
    cleaned = raw_path.strip().strip('"').strip("'")
    return Path(cleaned)


def add_product(
    conn: sqlite3.Connection,
    codigo: str,
    nombre: str,
    precio: float,
    stock: int,
    stock_minimo: int,
    proveedor: str = "",
    precio_costo: float = 0.0,
    notas: str = "",
) -> None:
    codigo = codigo.strip()
    nombre = nombre.strip()
    if conn.execute("SELECT 1 FROM productos WHERE codigo = ?", (codigo,)).fetchone():
        raise DuplicateProductError(f"Ya existe un producto con codigo {codigo}.")

    try:
        proveedor = proveedor.strip()
        with conn:
            conn.execute(
                """
                INSERT INTO productos
                    (codigo, nombre, precio, stock, stock_minimo, proveedor, precio_costo, notas)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (codigo, nombre, precio, stock, stock_minimo,
                 proveedor, precio_costo, notas.strip()),
            )
            if proveedor:
                conn.execute(
                    """
                    INSERT INTO proveedores_producto
                        (codigo, proveedor, precio_costo, es_principal)
                    VALUES (?, ?, ?, 1)
                    """,
                    (codigo, proveedor, float(precio_costo)),
                )
    except sqlite3.IntegrityError as exc:
        raise StockError(f"No se pudo registrar el producto: {exc}") from exc


def update_product(
    conn: sqlite3.Connection,
    codigo: str,
    nombre: str,
    precio: float,
    stock: int,
    stock_minimo: int,
    proveedor: str = "",
    precio_costo: float = 0.0,
    notas: str = "",
    motivo: str = "Edición manual",
) -> None:
    codigo = codigo.strip()
    nombre = nombre.strip()
    proveedor = proveedor.strip()
    precio_costo = float(precio_costo)
    row = conn.execute("SELECT precio FROM productos WHERE codigo = ?", (codigo,)).fetchone()
    if row is None:
        raise ProductNotFoundError(f"No existe un producto con codigo {codigo}.")

    try:
        with conn:
            conn.execute(
                """
                UPDATE productos
                SET nombre = ?, precio = ?, stock = ?, stock_minimo = ?,
                    proveedor = ?, precio_costo = ?, notas = ?
                WHERE codigo = ?
                """,
                (nombre, precio, stock, stock_minimo,
                 proveedor, precio_costo, notas.strip(), codigo),
            )
            primary = conn.execute(
                """
                SELECT id FROM proveedores_producto
                WHERE codigo = ? AND es_principal = 1
                """,
                (codigo,),
            ).fetchone()
            if proveedor:
                existing = conn.execute(
                    """
                    SELECT id FROM proveedores_producto
                    WHERE codigo = ? AND proveedor = ?
                    ORDER BY es_principal DESC, id ASC
                    LIMIT 1
                    """,
                    (codigo, proveedor),
                ).fetchone()
                if existing and (not primary or existing["id"] != primary["id"]):
                    conn.execute(
                        "UPDATE proveedores_producto SET es_principal = 0 WHERE codigo = ?",
                        (codigo,),
                    )
                    conn.execute(
                        """
                        UPDATE proveedores_producto
                        SET precio_costo = ?, es_principal = 1
                        WHERE id = ?
                        """,
                        (precio_costo, existing["id"]),
                    )
                    if primary:
                        conn.execute(
                            "DELETE FROM proveedores_producto WHERE id = ?",
                            (primary["id"],),
                        )
                    conn.execute(
                        """
                        DELETE FROM proveedores_producto
                        WHERE codigo = ? AND proveedor = ? AND id != ?
                        """,
                        (codigo, proveedor, existing["id"]),
                    )
                elif primary:
                    conn.execute(
                        """
                        UPDATE proveedores_producto
                        SET proveedor = ?, precio_costo = ?
                        WHERE id = ?
                        """,
                        (proveedor, precio_costo, primary["id"]),
                    )
                    conn.execute(
                        """
                        DELETE FROM proveedores_producto
                        WHERE codigo = ? AND proveedor = ? AND id != ?
                        """,
                        (codigo, proveedor, primary["id"]),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO proveedores_producto
                            (codigo, proveedor, precio_costo, es_principal)
                        VALUES (?, ?, ?, 1)
                        """,
                        (codigo, proveedor, precio_costo),
                    )
            elif primary:
                conn.execute(
                    "DELETE FROM proveedores_producto WHERE id = ?",
                    (primary["id"],),
                )
                remaining = conn.execute(
                    """
                    SELECT id, proveedor, precio_costo
                    FROM proveedores_producto
                    WHERE codigo = ?
                    ORDER BY proveedor ASC, id ASC
                    LIMIT 1
                    """,
                    (codigo,),
                ).fetchone()
                if remaining:
                    conn.execute(
                        "UPDATE proveedores_producto SET es_principal = 1 WHERE id = ?",
                        (remaining["id"],),
                    )
                    conn.execute(
                        "UPDATE productos SET proveedor = ?, precio_costo = ? WHERE codigo = ?",
                        (remaining["proveedor"], float(remaining["precio_costo"]), codigo),
                    )
            if float(row["precio"]) != precio:
                log_price_change(conn, codigo, nombre, float(row["precio"]), precio, motivo)
    except sqlite3.IntegrityError as exc:
        raise StockError(f"No se pudo actualizar el producto: {exc}") from exc


def _restore_product(conn: sqlite3.Connection, data: dict) -> None:
    """Re-inserts a previously deleted product row. Used by the undo system."""
    try:
        with conn:
            conn.execute(
                """
                INSERT INTO productos
                    (codigo, nombre, precio, stock, stock_minimo, foto, proveedor, precio_costo, notas)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    data["codigo"], data["nombre"], data["precio"],
                    data["stock"], data["stock_minimo"], data["foto"],
                    data["proveedor"], data.get("precio_costo", 0), data.get("notas", ""),
                ),
            )
            for supplier in data.get("suppliers", []):
                conn.execute(
                    """
                    INSERT INTO proveedores_producto
                        (codigo, proveedor, precio_costo, es_principal)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        data["codigo"],
                        supplier["proveedor"],
                        float(supplier["precio_costo"]),
                        int(supplier["es_principal"]),
                    ),
                )
    except sqlite3.IntegrityError as exc:
        raise DuplicateProductError(
            f"No se pudo restaurar el producto {data['codigo']}: el codigo ya existe."
        ) from exc


def delete_product(conn: sqlite3.Connection, codigo: str) -> None:
    row = conn.execute("SELECT foto FROM productos WHERE codigo = ?", (codigo.strip(),)).fetchone()
    if row is None:
        raise ProductNotFoundError(f"No existe un producto con codigo {codigo}.")
    # photo file is kept on disk intentionally so that undo can fully restore the product
    with conn:
        conn.execute("DELETE FROM productos WHERE codigo = ?", (codigo.strip(),))


def list_products(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT codigo, nombre, precio, stock, stock_minimo, foto, proveedor, precio_costo, notas
        FROM productos ORDER BY nombre
        """
    ).fetchall()


def search_products(conn: sqlite3.Connection, query: str = "") -> list[sqlite3.Row]:
    if not query:
        return list_products(conn)
    q = f"%{query.lower()}%"
    return conn.execute(
        """
        SELECT codigo, nombre, precio, stock, stock_minimo, foto, proveedor, precio_costo, notas
        FROM productos
        WHERE lower(codigo) LIKE ? OR lower(nombre) LIKE ? OR lower(proveedor) LIKE ?
        ORDER BY nombre
        """,
        (q, q, q),
    ).fetchall()


def get_products_preview(conn: sqlite3.Connection, codigos: list[str]) -> list[sqlite3.Row]:
    if not codigos:
        return []
    placeholders = ",".join("?" for _ in codigos)
    return conn.execute(
        f"""
        SELECT codigo, nombre, precio
        FROM productos
        WHERE codigo IN ({placeholders})
        ORDER BY nombre
        """,
        codigos,
    ).fetchall()


def adjust_stock(conn: sqlite3.Connection, codigo: str, nuevo_stock: int) -> int:
    """Sets the product stock to nuevo_stock. Returns the previous stock value."""
    row = conn.execute(
        "SELECT stock FROM productos WHERE codigo = ?", (codigo.strip(),)
    ).fetchone()
    if row is None:
        raise ProductNotFoundError(f"No existe un producto con codigo {codigo}.")
    stock_anterior = int(row["stock"])
    try:
        with conn:
            conn.execute(
                "UPDATE productos SET stock = ? WHERE codigo = ?", (nuevo_stock, codigo.strip())
            )
    except sqlite3.IntegrityError as exc:
        raise StockError(f"No se pudo ajustar el stock: {exc}") from exc
    return stock_anterior


def get_product(conn: sqlite3.Connection, codigo: str) -> sqlite3.Row:
    product = conn.execute("SELECT * FROM productos WHERE codigo = ?", (codigo.strip(),)).fetchone()
    if product is None:
        raise ProductNotFoundError(f"No existe un producto con codigo {codigo}.")
    return product


def get_all_proveedores(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT proveedor FROM proveedores_producto WHERE proveedor != '' ORDER BY proveedor"
    ).fetchall()
    return [row[0] for row in rows]


def get_product_suppliers(conn: sqlite3.Connection, codigo: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT id, codigo, proveedor, precio_costo, es_principal
        FROM proveedores_producto
        WHERE codigo = ?
        ORDER BY es_principal DESC, proveedor ASC, id ASC
        """,
        (codigo.strip(),),
    ).fetchall()


def add_product_supplier(
    conn: sqlite3.Connection,
    codigo: str,
    proveedor: str,
    precio_costo: float,
) -> None:
    codigo = codigo.strip()
    proveedor = proveedor.strip()
    if not proveedor:
        raise ValueError("El proveedor es obligatorio.")
    if precio_costo < 0:
        raise ValueError("El precio de costo no puede ser negativo.")
    if conn.execute("SELECT 1 FROM productos WHERE codigo = ?", (codigo,)).fetchone() is None:
        raise ProductNotFoundError(f"No existe un producto con codigo {codigo}.")
    with conn:
        existing = conn.execute(
            """
            SELECT id, es_principal FROM proveedores_producto
            WHERE codigo = ? AND proveedor = ?
            ORDER BY es_principal DESC, id ASC
            LIMIT 1
            """,
            (codigo, proveedor),
        ).fetchone()
        has_primary = conn.execute(
            """
            SELECT 1 FROM proveedores_producto
            WHERE codigo = ? AND es_principal = 1
            """,
            (codigo,),
        ).fetchone()
        if existing:
            is_primary = int(existing["es_principal"])
            conn.execute(
                """
                UPDATE proveedores_producto
                SET precio_costo = ?
                WHERE id = ?
                """,
                (float(precio_costo), existing["id"]),
            )
            conn.execute(
                """
                DELETE FROM proveedores_producto
                WHERE codigo = ? AND proveedor = ? AND id != ?
                """,
                (codigo, proveedor, existing["id"]),
            )
            if not has_primary:
                conn.execute(
                    "UPDATE proveedores_producto SET es_principal = 1 WHERE id = ?",
                    (existing["id"],),
                )
                is_primary = 1
            if is_primary:
                conn.execute(
                    "UPDATE productos SET proveedor = ?, precio_costo = ? WHERE codigo = ?",
                    (proveedor, float(precio_costo), codigo),
                )
            return
        is_primary = 0 if has_primary else 1
        conn.execute(
            """
            INSERT INTO proveedores_producto (codigo, proveedor, precio_costo, es_principal)
            VALUES (?, ?, ?, ?)
            """,
            (codigo, proveedor, float(precio_costo), is_primary),
        )
        if is_primary:
            conn.execute(
                "UPDATE productos SET proveedor = ?, precio_costo = ? WHERE codigo = ?",
                (proveedor, float(precio_costo), codigo),
            )


def set_primary_supplier(conn: sqlite3.Connection, supplier_id: int, codigo: str) -> None:
    codigo = codigo.strip()
    row = conn.execute(
        """
        SELECT id, proveedor, precio_costo
        FROM proveedores_producto
        WHERE id = ? AND codigo = ?
        """,
        (supplier_id, codigo),
    ).fetchone()
    if row is None:
        raise StockError("No existe ese proveedor para el producto.")
    with conn:
        conn.execute(
            "UPDATE proveedores_producto SET es_principal = 0 WHERE codigo = ?",
            (codigo,),
        )
        conn.execute(
            "UPDATE proveedores_producto SET es_principal = 1 WHERE id = ?",
            (supplier_id,),
        )
        conn.execute(
            "UPDATE productos SET proveedor = ?, precio_costo = ? WHERE codigo = ?",
            (row["proveedor"], float(row["precio_costo"]), codigo),
        )


def remove_product_supplier(conn: sqlite3.Connection, supplier_id: int) -> None:
    row = conn.execute(
        """
        SELECT id, codigo, es_principal
        FROM proveedores_producto
        WHERE id = ?
        """,
        (supplier_id,),
    ).fetchone()
    if row is None:
        raise StockError("No existe ese proveedor.")
    count = conn.execute(
        "SELECT COUNT(*) FROM proveedores_producto WHERE codigo = ?",
        (row["codigo"],),
    ).fetchone()[0]
    if count <= 1:
        raise StockError("No se puede eliminar el unico proveedor del producto.")
    if int(row["es_principal"]):
        raise StockError("No se puede eliminar el proveedor principal.")
    with conn:
        conn.execute("DELETE FROM proveedores_producto WHERE id = ?", (supplier_id,))


def low_stock_products(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT codigo, nombre, stock, stock_minimo
        FROM productos
        WHERE stock < stock_minimo
        ORDER BY stock ASC, nombre ASC
        """
    ).fetchall()


def log_price_change(
    conn: sqlite3.Connection,
    codigo: str,
    nombre: str,
    precio_anterior: float,
    precio_nuevo: float,
    motivo: str = "",
) -> None:
    conn.execute(
        """
        INSERT INTO historial_precios (codigo, nombre, precio_anterior, precio_nuevo, fecha, motivo)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (codigo, nombre, float(precio_anterior), float(precio_nuevo),
         datetime.now().strftime("%Y-%m-%d %H:%M:%S"), motivo),
    )


def get_price_history(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM historial_precios ORDER BY id DESC"
    ).fetchall()


def search_price_history(conn: sqlite3.Connection, query: str = "") -> list[sqlite3.Row]:
    q = query.strip().lower()
    if not q:
        return get_price_history(conn)
    like = f"%{q}%"
    return conn.execute(
        """
        SELECT *
        FROM historial_precios
        WHERE lower(codigo) LIKE ? OR lower(nombre) LIKE ?
        ORDER BY id DESC
        """,
        (like, like),
    ).fetchall()


def restore_prices(conn: sqlite3.Connection, changes: list[tuple[str, float, float]]) -> None:
    with conn:
        for codigo, old_price, _ in changes:
            conn.execute(
                "UPDATE productos SET precio = ? WHERE codigo = ?",
                (old_price, codigo),
            )


def bulk_price_increase(
    conn: sqlite3.Connection,
    codigos: list[str],
    pct: float,
) -> list[tuple[str, float, float]]:
    """Applies pct% increase rounded to the nearest ten. Returns (codigo, old, new) per product."""
    changes: list[tuple[str, float, float]] = []
    with conn:
        for codigo in codigos:
            row = conn.execute("SELECT precio, nombre FROM productos WHERE codigo = ?", (codigo,)).fetchone()
            if row:
                old_price = float(row["precio"])
                new_price = round(old_price * (1 + pct / 100) / 10) * 10
                conn.execute("UPDATE productos SET precio = ? WHERE codigo = ?", (new_price, codigo))
                log_price_change(conn, codigo, row["nombre"], old_price, new_price, f"Aumento masivo {pct}%")
                changes.append((codigo, old_price, new_price))
    return changes


def register_sale(
    conn: sqlite3.Connection,
    codigo: str,
    cantidad: int,
    allow_negative: bool = False,
    sale_date: date | None = None,
    forma_pago: str = "Efectivo",
) -> tuple[float, int]:
    if cantidad <= 0:
        raise ValueError("La cantidad debe ser mayor a cero.")

    sale_day = (sale_date or date.today()).isoformat()
    sale_hour = datetime.now().strftime("%H:%M:%S")
    with conn:
        product = conn.execute(
            "SELECT codigo, nombre, precio, stock, precio_costo FROM productos WHERE codigo = ?",
            (codigo.strip(),),
        ).fetchone()
        if product is None:
            raise ProductNotFoundError(f"No existe un producto con codigo {codigo}.")

        new_stock = int(product["stock"]) - cantidad
        if new_stock < 0 and not allow_negative:
            raise InsufficientStockError(
                f"Stock insuficiente. Stock actual: {product['stock']}, venta: {cantidad}."
            )

        total = float(product["precio"]) * cantidad
        conn.execute("UPDATE productos SET stock = ? WHERE codigo = ?", (new_stock, codigo.strip()))
        conn.execute(
            """
            INSERT INTO caja (fecha, total)
            VALUES (?, ?)
            ON CONFLICT(fecha) DO UPDATE SET total = total + excluded.total
            """,
            (sale_day, total),
        )
        cursor = conn.execute(
            """
            INSERT INTO ventas
                (codigo, nombre, cantidad, precio_unit, total, fecha, hora, forma_pago, precio_costo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (codigo.strip(), product["nombre"], cantidad, float(product["precio"]),
             total, sale_day, sale_hour, forma_pago, float(product["precio_costo"])),
        )
        sale_id = int(cursor.lastrowid)
    return total, sale_id


def reverse_sale(
    conn: sqlite3.Connection,
    codigo: str,
    cantidad: int,
    total: float,
    sale_date: str,
    sale_id: int | None = None,
) -> None:
    """Reverts a registered sale: restores stock, subtracts total from daily cash, removes venta row."""
    with conn:
        conn.execute(
            "UPDATE productos SET stock = stock + ? WHERE codigo = ?",
            (cantidad, codigo.strip()),
        )
        conn.execute(
            "UPDATE caja SET total = CASE WHEN total - ? < 0 THEN 0 ELSE total - ? END WHERE fecha = ?",
            (total, total, sale_date),
        )
        if sale_id is not None:
            conn.execute("DELETE FROM ventas WHERE id = ?", (sale_id,))
        else:
            conn.execute(
                """
                DELETE FROM ventas WHERE id = (
                    SELECT id FROM ventas
                    WHERE codigo = ? AND total = ? AND fecha = ?
                    ORDER BY id DESC LIMIT 1
                )
                """,
                (codigo.strip(), total, sale_date),
            )


def add_pending(conn: sqlite3.Connection, descripcion: str) -> None:
    with conn:
        conn.execute("INSERT INTO pendientes (descripcion) VALUES (?)", (descripcion.strip(),))


def list_pending(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, descripcion, estado, creado_en FROM pendientes ORDER BY estado DESC, id DESC"
    ).fetchall()


def complete_pending(conn: sqlite3.Connection, pending_id: int) -> bool:
    with conn:
        cursor = conn.execute(
            "UPDATE pendientes SET estado = 'Completado' WHERE id = ?", (pending_id,)
        )
    return cursor.rowcount > 0


def delete_pending(conn: sqlite3.Connection, pending_id: int) -> bool:
    with conn:
        cursor = conn.execute("DELETE FROM pendientes WHERE id = ?", (pending_id,))
    return cursor.rowcount > 0


def daily_cash(conn: sqlite3.Connection, cash_date: date | None = None) -> float:
    day = (cash_date or date.today()).isoformat()
    row = conn.execute("SELECT total FROM caja WHERE fecha = ?", (day,)).fetchone()
    return float(row["total"]) if row else 0.0


def get_ventas_hoy(conn: sqlite3.Connection, cash_date: date | None = None) -> list[sqlite3.Row]:
    day = (cash_date or date.today()).isoformat()
    return conn.execute(
        """
        SELECT id, hora, codigo, nombre, cantidad, precio_unit, total, forma_pago, fecha
        FROM ventas WHERE fecha = ? ORDER BY id DESC
        """,
        (day,),
    ).fetchall()


def get_ventas_rango(
    conn: sqlite3.Connection, fecha_desde: str, fecha_hasta: str
) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT id, hora, codigo, nombre, cantidad, precio_unit, total, forma_pago, fecha
        FROM ventas WHERE fecha >= ? AND fecha <= ? ORDER BY fecha DESC, id DESC
        """,
        (fecha_desde, fecha_hasta),
    ).fetchall()


def get_payment_breakdown(conn: sqlite3.Connection, cash_date: date | None = None) -> list[sqlite3.Row]:
    day = (cash_date or date.today()).isoformat()
    return conn.execute(
        """
        SELECT forma_pago, COUNT(*) AS cantidad, SUM(total) AS total
        FROM ventas WHERE fecha = ?
        GROUP BY forma_pago ORDER BY total DESC
        """,
        (day,),
    ).fetchall()


def get_daily_summary(conn: sqlite3.Connection, cash_date: date | None = None) -> dict:
    day = (cash_date or date.today()).isoformat()
    total = daily_cash(conn, cash_date)
    count = conn.execute(
        "SELECT COUNT(*) FROM ventas WHERE fecha = ?", (day,)
    ).fetchone()[0]
    top = conn.execute(
        """
        SELECT nombre, SUM(cantidad) AS total_cant, SUM(total) AS total_monto
        FROM ventas WHERE fecha = ?
        GROUP BY codigo ORDER BY total_monto DESC LIMIT 5
        """,
        (day,),
    ).fetchall()
    costo_row = conn.execute(
        "SELECT COALESCE(SUM(precio_costo * cantidad), 0) FROM ventas WHERE fecha = ?", (day,)
    ).fetchone()
    total_costo = float(costo_row[0])
    return {
        "fecha": day, "total": total, "count": count, "top_products": top,
        "total_costo": total_costo, "ganancia_bruta": total - total_costo,
    }


def get_range_summary(conn: sqlite3.Connection, fecha_desde: str, fecha_hasta: str) -> dict:
    total = float(conn.execute(
        "SELECT COALESCE(SUM(total), 0) FROM ventas WHERE fecha >= ? AND fecha <= ?",
        (fecha_desde, fecha_hasta),
    ).fetchone()[0])
    count = conn.execute(
        "SELECT COUNT(*) FROM ventas WHERE fecha >= ? AND fecha <= ?",
        (fecha_desde, fecha_hasta),
    ).fetchone()[0]
    breakdown = conn.execute(
        """
        SELECT forma_pago, COUNT(*) AS cantidad, SUM(total) AS total
        FROM ventas WHERE fecha >= ? AND fecha <= ?
        GROUP BY forma_pago ORDER BY total DESC
        """,
        (fecha_desde, fecha_hasta),
    ).fetchall()
    top = conn.execute(
        """
        SELECT nombre, SUM(cantidad) AS total_cant, SUM(total) AS total_monto
        FROM ventas WHERE fecha >= ? AND fecha <= ?
        GROUP BY codigo ORDER BY total_monto DESC LIMIT 5
        """,
        (fecha_desde, fecha_hasta),
    ).fetchall()
    total_costo = float(conn.execute(
        "SELECT COALESCE(SUM(precio_costo * cantidad), 0) FROM ventas WHERE fecha >= ? AND fecha <= ?",
        (fecha_desde, fecha_hasta),
    ).fetchone()[0])
    return {
        "desde": fecha_desde, "hasta": fecha_hasta,
        "total": total, "count": count, "breakdown": breakdown, "top_products": top,
        "total_costo": total_costo, "ganancia_bruta": total - total_costo,
    }


def backup_database() -> Path | None:
    """Creates one backup per day in backups/. Returns None if today's backup already exists."""
    backups_dir = BASE_DIR / "backups"
    backups_dir.mkdir(exist_ok=True)
    today = date.today().strftime("%Y%m%d")
    if list(backups_dir.glob(f"stock_{today}_*.db")):
        return None
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backups_dir / f"stock_{ts}.db"
    shutil.copy2(DB_PATH, dest)
    return dest


def export_products_csv(conn: sqlite3.Connection, dest_path: Path) -> int:
    rows = list_products(conn)
    fieldnames = ["codigo", "nombre", "precio", "precio_costo", "stock",
                  "stock_minimo", "proveedor", "notas"]
    with open(dest_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row[k] for k in fieldnames})
    return len(rows)


def export_ventas_csv(conn: sqlite3.Connection, dest_path: Path, cash_date: date | None = None) -> int:
    rows = get_ventas_hoy(conn, cash_date)
    with open(dest_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["Hora", "Codigo", "Nombre", "Cantidad", "Precio Unit.", "Total"])
        for row in rows:
            writer.writerow([row["hora"], row["codigo"], row["nombre"],
                             row["cantidad"], row["precio_unit"], row["total"]])
    return len(rows)


# ── Boleta CSV import ─────────────────────────────────────────────────────────

def parse_and_classify_boleta(
    conn: sqlite3.Connection,
    path: Path,
    default_proveedor: str | None = None,
) -> BoletaResult:
    """Parses a supplier boleta CSV and classifies rows as new, clean-update, or price-conflict."""
    result = BoletaResult(rows_new=[], rows_clean=[], rows_conflict=[], skipped=[])
    required_cols = {"codigo", "nombre", "cantidad"}
    default_proveedor = (default_proveedor or "").strip() or None

    try:
        with open(path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            fieldnames = set(reader.fieldnames or [])
            if not required_cols.issubset(fieldnames):
                missing = required_cols - fieldnames
                raise StockError(
                    f"CSV inválido: faltan columnas requeridas: {', '.join(sorted(missing))}"
                )

            for line_num, raw in enumerate(reader, start=2):
                codigo = raw.get("codigo", "").strip()
                nombre = raw.get("nombre", "").strip()

                if not codigo or not nombre:
                    result.skipped.append((line_num, "codigo o nombre vacío"))
                    continue

                try:
                    cantidad = int(raw.get("cantidad", "").strip())
                    if cantidad <= 0:
                        raise ValueError
                except (ValueError, AttributeError):
                    result.skipped.append((line_num, "cantidad inválida"))
                    continue

                skip_row = False
                precio_costo: float | None = None
                precio_venta: float | None = None

                for key in ("precio_costo", "precio_venta"):
                    raw_val = raw.get(key, "").strip()
                    if raw_val:
                        try:
                            val = float(raw_val.replace(",", "."))
                            if val < 0:
                                result.skipped.append((line_num, f"{key} no puede ser negativo"))
                                skip_row = True
                                break
                            if key == "precio_costo":
                                precio_costo = val
                            else:
                                precio_venta = val
                        except ValueError:
                            result.skipped.append((line_num, f"{key} inválido: '{raw_val}'"))
                            skip_row = True
                            break

                if skip_row:
                    continue

                proveedor = (raw.get("proveedor") or "").strip() or default_proveedor
                row = BoletaRow(
                    codigo=codigo, nombre=nombre, cantidad=cantidad,
                    precio_costo=precio_costo, precio_venta=precio_venta, proveedor=proveedor,
                )

                try:
                    db_row = get_product(conn, codigo)
                    has_conflict = (
                        (precio_costo is not None
                         and abs(precio_costo - float(db_row["precio_costo"])) > 0.001)
                        or (precio_venta is not None
                            and abs(precio_venta - float(db_row["precio"])) > 0.001)
                    )
                    if has_conflict:
                        result.rows_conflict.append((row, db_row))
                    else:
                        result.rows_clean.append(row)
                except ProductNotFoundError:
                    result.rows_new.append(row)

    except UnicodeDecodeError as exc:
        raise StockError(
            "El archivo no es UTF-8. Guardalo como UTF-8 desde Excel o el programa que lo genera."
        ) from exc

    return result


def apply_boleta_row(
    conn: sqlite3.Connection,
    row: BoletaRow,
    precio_venta_override: float | None = None,
    precio_costo_override: float | None = None,
) -> None:
    """Applies one boleta row: creates the product if new, or updates stock and prices if existing."""
    try:
        db_row = get_product(conn, row.codigo)
    except ProductNotFoundError:
        precio = precio_venta_override if precio_venta_override is not None else (row.precio_venta or 0.0)
        costo = precio_costo_override if precio_costo_override is not None else (row.precio_costo or 0.0)
        add_product(conn, row.codigo, row.nombre, precio, row.cantidad, 0, row.proveedor or "", costo, "")
        return

    nuevo_stock = int(db_row["stock"]) + row.cantidad

    if precio_venta_override is not None:
        final_precio = precio_venta_override
    elif row.precio_venta is not None:
        final_precio = row.precio_venta
    else:
        final_precio = float(db_row["precio"])

    if precio_costo_override is not None:
        final_costo = precio_costo_override
    elif row.precio_costo is not None:
        final_costo = row.precio_costo
    else:
        final_costo = float(db_row["precio_costo"])

    update_product(
        conn, row.codigo, db_row["nombre"], final_precio, nuevo_stock,
        int(db_row["stock_minimo"]), db_row["proveedor"] or "",
        final_costo, db_row["notas"] or "",
        motivo="Importación boleta",
    )

    if row.proveedor:
        try:
            add_product_supplier(conn, row.codigo, row.proveedor, row.precio_costo or final_costo)
        except (StockError, ValueError):
            pass


def apply_boleta_batch(
    conn: sqlite3.Connection,
    rows: list,
) -> tuple[int, list[str]]:
    """Applies a list of BoletaRow without conflict. Returns (count_ok, errors)."""
    count = 0
    errors: list[str] = []
    for row in rows:
        try:
            apply_boleta_row(conn, row)
            count += 1
        except StockError as exc:
            errors.append(f"{row.codigo}: {exc}")
    return count, errors


# ── Redo helpers ──────────────────────────────────────────────────────────────

def get_sale(conn: sqlite3.Connection, sale_id: int) -> sqlite3.Row:
    """Returns a single sale row by id. Needed to capture data before reverse_sale for redo."""
    row = conn.execute("SELECT * FROM ventas WHERE id = ?", (sale_id,)).fetchone()
    if row is None:
        raise StockError(f"No existe una venta con id {sale_id}.")
    return row


def restore_sale(conn: sqlite3.Connection, sale_data: dict) -> None:
    """Re-inserts a previously reversed sale and decrements stock (redo of a sale undo)."""
    with conn:
        conn.execute(
            """
            INSERT INTO ventas
                (id, codigo, nombre, cantidad, precio_unit, total, fecha, hora, forma_pago, precio_costo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                sale_data["id"], sale_data["codigo"], sale_data["nombre"],
                sale_data["cantidad"], sale_data["precio_unit"], sale_data["total"],
                sale_data["fecha"], sale_data["hora"], sale_data["forma_pago"],
                sale_data.get("precio_costo", 0),
            ),
        )
        conn.execute(
            "UPDATE productos SET stock = stock - ? WHERE codigo = ?",
            (sale_data["cantidad"], sale_data["codigo"]),
        )
        conn.execute(
            """
            INSERT INTO caja (fecha, total)
            VALUES (?, ?)
            ON CONFLICT(fecha) DO UPDATE SET total = total + excluded.total
            """,
            (sale_data["fecha"], sale_data["total"]),
        )


def re_apply_prices(conn: sqlite3.Connection, changes: list[tuple[str, float, float]]) -> None:
    """Re-applies the new_price for each (codigo, old_price, new_price). Complement of restore_prices."""
    with conn:
        for codigo, _, new_price in changes:
            conn.execute(
                "UPDATE productos SET precio = ? WHERE codigo = ?",
                (new_price, codigo),
            )


# ── CLI helpers ───────────────────────────────────────────────────────────────

def read_text(prompt: str, required: bool = True) -> str:
    while True:
        value = input(prompt).strip()
        if value or not required:
            return value
        print("El dato es obligatorio.")


def read_float(prompt: str) -> float:
    while True:
        try:
            return float(input(prompt).replace(",", "."))
        except ValueError:
            print("Ingrese un numero valido.")


def read_int(prompt: str) -> int:
    while True:
        try:
            return int(input(prompt))
        except ValueError:
            print("Ingrese un numero entero valido.")


def print_products(rows: list[sqlite3.Row]) -> None:
    if not rows:
        print("No hay productos cargados.")
        return
    for row in rows:
        print(
            f"{row['codigo']} | {row['nombre']} | ${row['precio']:.2f} | "
            f"costo ${row['precio_costo']:.2f} | "
            f"stock {row['stock']} | minimo {row['stock_minimo']} | "
            f"proveedor {row['proveedor'] or '-'} | foto {row['foto'] or '-'}"
        )


def create_product_flow(conn: sqlite3.Connection) -> None:
    codigo = read_text("Codigo de barras: ")
    nombre = read_text("Nombre: ")
    precio = read_float("Precio de venta: ")
    precio_costo = read_float("Precio de costo (0 si no aplica): ")
    stock = read_int("Stock inicial: ")
    stock_minimo = read_int("Stock minimo: ")
    proveedor = read_text("Proveedor (opcional): ", required=False)
    notas = read_text("Notas (opcional): ", required=False)
    try:
        add_product(conn, codigo, nombre, precio, stock, stock_minimo,
                    proveedor, precio_costo, notas)
        print("Producto registrado.")
    except DuplicateProductError as exc:
        print(exc)


def sale_flow(conn: sqlite3.Connection) -> None:
    codigo = read_text("Codigo de barras: ")
    cantidad = read_int("Cantidad vendida: ")
    try:
        total, _sale_id = register_sale(conn, codigo, cantidad)
        print(f"Venta registrada. Total: ${total:.2f}")
    except InsufficientStockError as exc:
        print(exc)
        answer = read_text("Autorizar stock negativo? (s/n): ").lower()
        if answer == "s":
            total, _sale_id = register_sale(conn, codigo, cantidad, allow_negative=True)
            print(f"Venta registrada con stock negativo. Total: ${total:.2f}")
    except (ProductNotFoundError, ValueError) as exc:
        print(exc)


def low_stock_flow(conn: sqlite3.Connection) -> None:
    rows = low_stock_products(conn)
    if not rows:
        print("No hay alertas de stock.")
        return
    for row in rows:
        print(f"{row['codigo']} | {row['nombre']} | stock {row['stock']} | minimo {row['stock_minimo']}")


def pending_menu(conn: sqlite3.Connection) -> None:
    while True:
        print("\n--- Pendientes ---")
        print("1. Ver pendientes")
        print("2. Agregar pendiente")
        print("3. Marcar como completado")
        print("4. Eliminar pendiente")
        print("0. Volver")
        option = input("Opcion: ").strip()

        if option == "1":
            rows = list_pending(conn)
            if not rows:
                print("No hay pendientes.")
            for row in rows:
                print(f"{row['id']} | {row['estado']} | {row['descripcion']}")
        elif option == "2":
            add_pending(conn, read_text("Descripcion: "))
            print("Pendiente agregado.")
        elif option == "3":
            pending_id = read_int("ID: ")
            print("Actualizado." if complete_pending(conn, pending_id) else "ID inexistente.")
        elif option == "4":
            pending_id = read_int("ID a eliminar: ")
            print("Eliminado." if delete_pending(conn, pending_id) else "ID inexistente.")
        elif option == "0":
            return
        else:
            print("Opcion invalida.")


def main() -> None:
    conn = get_connection()
    initialize_database(conn)
    try:
        while True:
            print("\n=== Sistema de Stock ===")
            print("1. Alta de producto")
            print("2. Listar productos")
            print("3. Venta rapida")
            print("4. Alertas de stock bajo")
            print("5. Caja del dia")
            print("6. Ventas de hoy")
            print("7. Pendientes")
            print("0. Salir")
            option = input("Opcion: ").strip()

            if option == "1":
                create_product_flow(conn)
            elif option == "2":
                print_products(list_products(conn))
            elif option == "3":
                sale_flow(conn)
            elif option == "4":
                low_stock_flow(conn)
            elif option == "5":
                print(f"Caja de hoy: ${daily_cash(conn):.2f}")
            elif option == "6":
                rows = get_ventas_hoy(conn)
                if not rows:
                    print("Sin ventas registradas hoy.")
                for row in rows:
                    print(f"{row['hora']} | {row['nombre']} | x{row['cantidad']} | ${row['total']:.2f}")
            elif option == "7":
                pending_menu(conn)
            elif option == "0":
                print("Sistema cerrado.")
                break
            else:
                print("Opcion invalida.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
