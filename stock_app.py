from __future__ import annotations

import csv
import json
import logging
import shutil
import sqlite3
from datetime import date, datetime
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "stock.db"
PHOTOS_DIR = BASE_DIR / "fotos_productos"
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
            pass
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


def get_connection(db_path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


_SCHEMA_VERSION = 2


def initialize_database(conn: sqlite3.Connection) -> None:
    PHOTOS_DIR.mkdir(exist_ok=True)

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
            hora TEXT NOT NULL
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

    # update stored version
    if current_version == 0:
        conn.execute("INSERT INTO schema_version (version) VALUES (?)", (_SCHEMA_VERSION,))
    elif current_version < _SCHEMA_VERSION:
        conn.execute("UPDATE schema_version SET version = ?", (_SCHEMA_VERSION,))

    conn.commit()


def sanitize_path(raw_path: str) -> Path:
    cleaned = raw_path.strip().strip('"').strip("'")
    return Path(cleaned)


def save_product_photo(codigo: str, raw_path: str | None, photos_dir: Path = PHOTOS_DIR) -> str | None:
    if not raw_path or not raw_path.strip():
        return None

    source = sanitize_path(raw_path)
    if not source.is_file():
        return None

    photos_dir.mkdir(exist_ok=True)
    safe_code = "".join(ch for ch in codigo if ch.isalnum() or ch in ("-", "_")).strip()
    target_name = f"{safe_code}_{source.name}"
    target = photos_dir / target_name
    shutil.copy2(source, target)
    return str(target.relative_to(BASE_DIR))


def add_product(
    conn: sqlite3.Connection,
    codigo: str,
    nombre: str,
    precio: float,
    stock: int,
    stock_minimo: int,
    foto_path: str | None = None,
    proveedor: str = "",
    precio_costo: float = 0.0,
    notas: str = "",
) -> None:
    codigo = codigo.strip()
    nombre = nombre.strip()
    if conn.execute("SELECT 1 FROM productos WHERE codigo = ?", (codigo,)).fetchone():
        raise DuplicateProductError(f"Ya existe un producto con codigo {codigo}.")

    foto = save_product_photo(codigo, foto_path)
    try:
        conn.execute(
            """
            INSERT INTO productos
                (codigo, nombre, precio, stock, stock_minimo, foto, proveedor, precio_costo, notas)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (codigo, nombre, precio, stock, stock_minimo, foto,
             proveedor.strip(), precio_costo, notas.strip()),
        )
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise StockError(f"No se pudo registrar el producto: {exc}") from exc


def update_product(
    conn: sqlite3.Connection,
    codigo: str,
    nombre: str,
    precio: float,
    stock: int,
    stock_minimo: int,
    foto_path: str | None = None,
    proveedor: str = "",
    precio_costo: float = 0.0,
    notas: str = "",
) -> None:
    codigo = codigo.strip()
    nombre = nombre.strip()
    row = conn.execute("SELECT foto, precio FROM productos WHERE codigo = ?", (codigo,)).fetchone()
    if row is None:
        raise ProductNotFoundError(f"No existe un producto con codigo {codigo}.")

    new_foto = save_product_photo(codigo, foto_path)
    foto = new_foto if new_foto is not None else row["foto"]

    try:
        conn.execute(
            """
            UPDATE productos
            SET nombre = ?, precio = ?, stock = ?, stock_minimo = ?,
                foto = ?, proveedor = ?, precio_costo = ?, notas = ?
            WHERE codigo = ?
            """,
            (nombre, precio, stock, stock_minimo, foto,
             proveedor.strip(), precio_costo, notas.strip(), codigo),
        )
        if float(row["precio"]) != precio:
            log_price_change(conn, codigo, nombre, float(row["precio"]), precio, "Edición manual")
        conn.commit()
    except sqlite3.IntegrityError as exc:
        raise StockError(f"No se pudo actualizar el producto: {exc}") from exc


def _restore_product(conn: sqlite3.Connection, data: dict) -> None:
    """Re-inserts a previously deleted product row. Used by the undo system."""
    conn.execute(
        """
        INSERT OR IGNORE INTO productos
            (codigo, nombre, precio, stock, stock_minimo, foto, proveedor, precio_costo, notas)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["codigo"], data["nombre"], data["precio"],
            data["stock"], data["stock_minimo"], data["foto"],
            data["proveedor"], data.get("precio_costo", 0), data.get("notas", ""),
        ),
    )
    conn.commit()


def delete_product(conn: sqlite3.Connection, codigo: str) -> None:
    row = conn.execute("SELECT foto FROM productos WHERE codigo = ?", (codigo.strip(),)).fetchone()
    if row is None:
        raise ProductNotFoundError(f"No existe un producto con codigo {codigo}.")
    # photo file is kept on disk intentionally so that undo can fully restore the product
    conn.execute("DELETE FROM productos WHERE codigo = ?", (codigo.strip(),))
    conn.commit()


def list_products(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT codigo, nombre, precio, stock, stock_minimo, foto, proveedor, precio_costo, notas
        FROM productos ORDER BY nombre
        """
    ).fetchall()


def get_product(conn: sqlite3.Connection, codigo: str) -> sqlite3.Row:
    product = conn.execute("SELECT * FROM productos WHERE codigo = ?", (codigo.strip(),)).fetchone()
    if product is None:
        raise ProductNotFoundError(f"No existe un producto con codigo {codigo}.")
    return product


def get_all_proveedores(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT proveedor FROM productos WHERE proveedor != '' ORDER BY proveedor"
    ).fetchall()
    return [row[0] for row in rows]


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


def bulk_price_increase(
    conn: sqlite3.Connection,
    codigos: list[str],
    pct: float,
) -> list[tuple[str, float, float]]:
    """Applies pct% increase rounded to the nearest ten. Returns (codigo, old, new) per product."""
    changes: list[tuple[str, float, float]] = []
    for codigo in codigos:
        row = conn.execute("SELECT precio, nombre FROM productos WHERE codigo = ?", (codigo,)).fetchone()
        if row:
            old_price = float(row["precio"])
            new_price = round(old_price * (1 + pct / 100) / 10) * 10
            conn.execute("UPDATE productos SET precio = ? WHERE codigo = ?", (new_price, codigo))
            log_price_change(conn, codigo, row["nombre"], old_price, new_price, f"Aumento masivo {pct}%")
            changes.append((codigo, old_price, new_price))
    conn.commit()
    return changes


def register_sale(
    conn: sqlite3.Connection,
    codigo: str,
    cantidad: int,
    allow_negative: bool = False,
    sale_date: date | None = None,
    forma_pago: str = "Efectivo",
) -> float:
    if cantidad <= 0:
        raise ValueError("La cantidad debe ser mayor a cero.")

    sale_day = (sale_date or date.today()).isoformat()
    sale_hour = datetime.now().strftime("%H:%M:%S")
    with conn:
        product = conn.execute(
            "SELECT codigo, nombre, precio, stock FROM productos WHERE codigo = ?", (codigo.strip(),)
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
        conn.execute(
            """
            INSERT INTO ventas (codigo, nombre, cantidad, precio_unit, total, fecha, hora, forma_pago)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (codigo.strip(), product["nombre"], cantidad, float(product["precio"]),
             total, sale_day, sale_hour, forma_pago),
        )
    return total


def reverse_sale(
    conn: sqlite3.Connection,
    codigo: str,
    cantidad: int,
    total: float,
    sale_date: str,
) -> None:
    """Reverts a registered sale: restores stock, subtracts total from daily cash, removes venta row."""
    with conn:
        conn.execute(
            "UPDATE productos SET stock = stock + ? WHERE codigo = ?",
            (cantidad, codigo.strip()),
        )
        conn.execute(
            "UPDATE caja SET total = MAX(0, total - ?) WHERE fecha = ?",
            (total, sale_date),
        )
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
    conn.execute("INSERT INTO pendientes (descripcion) VALUES (?)", (descripcion.strip(),))
    conn.commit()


def list_pending(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, descripcion, estado, creado_en FROM pendientes ORDER BY estado DESC, id DESC"
    ).fetchall()


def complete_pending(conn: sqlite3.Connection, pending_id: int) -> bool:
    cursor = conn.execute(
        "UPDATE pendientes SET estado = 'Completado' WHERE id = ?", (pending_id,)
    )
    conn.commit()
    return cursor.rowcount > 0


def delete_pending(conn: sqlite3.Connection, pending_id: int) -> bool:
    cursor = conn.execute("DELETE FROM pendientes WHERE id = ?", (pending_id,))
    conn.commit()
    return cursor.rowcount > 0


def daily_cash(conn: sqlite3.Connection, cash_date: date | None = None) -> float:
    day = (cash_date or date.today()).isoformat()
    row = conn.execute("SELECT total FROM caja WHERE fecha = ?", (day,)).fetchone()
    return float(row["total"]) if row else 0.0


def get_ventas_hoy(conn: sqlite3.Connection, cash_date: date | None = None) -> list[sqlite3.Row]:
    day = (cash_date or date.today()).isoformat()
    return conn.execute(
        """
        SELECT id, hora, codigo, nombre, cantidad, precio_unit, total, forma_pago
        FROM ventas WHERE fecha = ? ORDER BY id DESC
        """,
        (day,),
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
    return {"fecha": day, "total": total, "count": count, "top_products": top}


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
    foto_path = read_text("Ruta de foto (opcional): ", required=False)
    try:
        add_product(conn, codigo, nombre, precio, stock, stock_minimo,
                    foto_path, proveedor, precio_costo, notas)
        print("Producto registrado.")
    except DuplicateProductError as exc:
        print(exc)


def sale_flow(conn: sqlite3.Connection) -> None:
    codigo = read_text("Codigo de barras: ")
    cantidad = read_int("Cantidad vendida: ")
    try:
        total = register_sale(conn, codigo, cantidad)
        print(f"Venta registrada. Total: ${total:.2f}")
    except InsufficientStockError as exc:
        print(exc)
        answer = read_text("Autorizar stock negativo? (s/n): ").lower()
        if answer == "s":
            total = register_sale(conn, codigo, cantidad, allow_negative=True)
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
