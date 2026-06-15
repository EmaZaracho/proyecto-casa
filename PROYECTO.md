# Sistema de Stock — Contexto del Proyecto

Documento de referencia rápida: arquitectura, decisiones y estado actual.

---

## Qué es

App de escritorio para gestión de inventario y punto de venta de un negocio pequeño. Corre localmente en Windows con Python + Tkinter + SQLite. Sin servidor, sin internet requerido.

---

## Stack

| Capa | Tecnología |
|---|---|
| GUI | Python 3.11 + Tkinter / ttk |
| Datos | SQLite 3 vía `sqlite3` estándar |
| PDF | `fpdf2` (instalado via pip) |
| Tests | `unittest` estándar (79 tests) |
| Entorno | Windows 11, ejecutable con `iniciar_gui.bat` |

---

## Archivos principales

```
stock_app.py      — capa de datos: DB, lógica de negocio, funciones puras
stock_gui.py      — GUI completa (Tkinter), consume stock_app
test_stock_app.py — tests unitarios de la capa de datos
iniciar_gui.bat   — lanzador de la app con manejo de errores
setup.bat         — instala dependencias (.venv + requirements.txt)
build.bat         — empaqueta con PyInstaller → dist/SistemaDeStock.exe
stock.spec        — spec de PyInstaller
requirements.txt  — dependencias (fpdf2)
config.json       — configuración del negocio (generado en runtime, en .gitignore)
stock.db          — base de datos SQLite (en .gitignore)
stock.log         — log de errores (en .gitignore)
backups/          — backups automáticos diarios del .db (en .gitignore)
```

---

## Arquitectura

### Separación de capas

`stock_app.py` es la capa de datos: todas las operaciones de DB, sin Tkinter. La GUI en `stock_gui.py` llama a esas funciones y no hace SQL directamente. Esta separación permite testear la lógica sin levantar la interfaz.

### Base de datos

Schema versioning con tabla `schema_version`. Al arrancar, `initialize_database()` detecta la versión actual y aplica migraciones pendientes. Las migraciones son idempotentes.

**Versión actual: v5**

| Migración | Cambio |
|---|---|
| v0 → v1 | Columnas extra en `productos`: proveedor, precio_costo, notas |
| v1 → v2 | `forma_pago` en `ventas` |
| v2 → v3 | `precio_costo` en `ventas` (para calcular ganancia bruta) |
| v3 → v4 | Índices: `idx_ventas_fecha`, `idx_productos_nombre`, `idx_productos_proveedor` |
| v4 → v5 | Tabla `proveedores_producto` + migración de datos existentes |

**Tablas:**

```sql
productos            — catálogo: codigo (PK), nombre, precio, stock, stock_minimo,
                       proveedor, precio_costo, notas, foto (legada)
ventas               — registros de venta: codigo, nombre, cantidad, precio_unit,
                       total, fecha, hora, forma_pago, precio_costo
caja                 — total diario por fecha (PK)
historial_precios    — auditoría de cambios de precio (con motivo)
pendientes           — lista de tareas interna
schema_version       — versión actual del schema
proveedores_producto — N proveedores por producto con precio_costo propio;
                       es_principal=1 indica el activo
```

### Dataclasses para importación

`BoletaRow` — fila parseada de un CSV de boleta:
- `codigo`, `nombre`, `cantidad` (requeridos)
- `precio_costo`, `precio_venta`, `proveedor` (opcionales)

`BoletaResult` — resultado de clasificar la boleta:
- `rows_new` — productos nuevos (no existen en DB)
- `rows_clean` — existentes sin conflicto de precio
- `rows_conflict` — pares `(BoletaRow, db_row)` donde el precio difiere > 0.001
- `skipped` — pares `(nro_línea, motivo)` de filas ignoradas

### Configuración persistente

`config.json` almacena `nombre_negocio` y `moneda`. Se lee en el header y en los PDFs. Funciones `load_config()` / `save_config()` en `stock_app.py`.

### Logging

Errores en `stock.log` con `logging.basicConfig` nivel ERROR. Los `except` críticos en la GUI llaman a `logger.exception()`.

---

## Funcionalidades implementadas

### Pestaña Principal

- **Tabla de productos**: búsqueda en tiempo real por código, nombre y proveedor (SQL `LIKE`). Ordenamiento por columna. Colores: rojo si stock ≤ 0, amarillo si stock < mínimo.
- **Formulario de producto**: alta y edición inline. Campos: código, nombre, precio de venta, precio de costo, stock, mínimo, proveedor, notas.
- **Multi-proveedor**: cada producto puede tener N proveedores con su propio precio_costo. Mini-tabla en el formulario para agregar, eliminar y cambiar el proveedor principal (`set_primary_supplier` actualiza `productos.proveedor` y `productos.precio_costo`).
- **Ajustar stock**: diálogo para setear el stock directamente (`adjust_stock()`).
- **Importar boleta CSV**: carga un archivo `codigo,nombre,cantidad,precio_costo,precio_venta,proveedor`. Los productos nuevos y los sin conflicto se aplican de inmediato. Los conflictos de precio abren `ConflictoDialog` para resolverlos 1 a 1 (ver más abajo).
- **Venta rápida / carrito**: campo código + cantidad + forma de pago. Autocompletado por código. Búsqueda por nombre con 🔍. Carrito acumulativo con botón "Cobrar todo".
- **Alertas de stock bajo**: tabla lateral con productos bajo el mínimo.
- **Lista de tareas**: pendientes con toggle Pendiente/Completado.

### ConflictoDialog (importación de boleta)

Modal que aparece cuando la boleta trae un precio distinto al de la DB. Muestra los datos del producto y tres opciones por ítem:
- **Mantener precio**: usa el precio actual de la DB (no lo pisa).
- **Actualizar precio**: aplica el precio de la boleta.
- **Modificar % de ganancia**: calcula precio de venta como `costo_boleta × (1 + pct/100)` con preview en tiempo real.

Botón "Aplicar a todos los restantes igual" aplica la decisión actual a todos los conflictos pendientes de una vez.

### Pestaña Gestión de Precios

- Tabla con precio de venta, precio de costo, margen, proveedor.
- Filtros: texto (SQL `LIKE`) + combo de proveedor.
- Aumentos masivos por porcentaje, aplicables a seleccionados o a todos los filtrados.
- Margen = `(precio - costo) / precio × 100` (sobre precio de venta, no markup).
- Exportar CSV de productos. Exportar PDF con selector de contenido.

### Pestaña Ventas del Día

- Navegación por fecha con botones ◀ ▶ y entrada manual. Botón "Hoy". Formato: **DD-MM-AAAA**.
- Filtro por rango de fechas (Desde / Hasta). La comparación de rango se hace sobre objetos `date`, no strings.
- Tabla con hora, código, nombre, cantidad, precio unitario, subtotal y forma de pago.
- Resumen en header: N ventas | Total $X.
- **Cierre de caja**: popup con total, desglose por forma de pago y top 5 productos más vendidos. Incluye ganancia bruta del día (schema v3+).
- Exportar ventas a CSV.

### Pestaña Historial de Precios

- Registro automático en `historial_precios` con motivo:
  - `"Edición manual"` — edición desde formulario
  - `"Aumento masivo X%"` — desde Gestión de Precios
  - `"Importación boleta"` — desde importación CSV
- Búsqueda en tiempo real por código o nombre (SQL via `search_price_history()`).

### Pestaña Reportes

- Generación de PDF por secciones: lista de productos, ventas de rango, pendientes, stock bajo.
- Rango de fechas configurable en formato DD-MM-AAAA (se convierte a ISO para la DB).

### Funciones de sistema

- **Undo (Ctrl+Z)** y **Redo (Ctrl+Y)**, hasta 10 pasos. Tipos soportados: venta, eliminación de producto, aumento de precios, cambios en carrito.
  - `_undo()` captura el estado antes de ejecutar y lo guarda en `_redo_stack`.
  - `_redo()` re-aplica la acción y la remueve del stack. Una nueva acción vacía `_redo_stack`.
  - Para ventas: `get_sale()` captura la fila antes de `reverse_sale()`; `restore_sale()` la re-inserta en redo.
- **Backup automático**: un `.db` por día en `backups/`, al iniciar la app.
- **Modo oscuro**: toggle en la barra superior.
- **Configuración** (botón ⚙): nombre del negocio y símbolo de moneda.
- **Atajos**: F1 → foco en código de venta; F2 → formulario de producto; F3 → tarea pendiente.

---

## Funciones clave en stock_app.py

| Función | Propósito |
|---|---|
| `initialize_database()` | Crea tablas y aplica migraciones |
| `get_connection()` | Devuelve conexión con `row_factory = sqlite3.Row` |
| `add_product()` | Alta de producto, lanza `DuplicateProductError` si ya existe |
| `update_product(..., motivo)` | Edita producto y loggea cambio de precio con motivo |
| `delete_product()` / `restore_product()` | Baja y restauración para undo |
| `adjust_stock()` | Setea stock directamente |
| `register_sale()` | Registra venta, actualiza stock y caja, devuelve `(total, sale_id)` |
| `reverse_sale(..., sale_id)` | Revierte venta por ID; fallback por campos si no hay ID |
| `restore_sale()` | Re-inserta venta revertida (para redo) |
| `get_sale()` | Lee una venta por ID antes de revertirla |
| `bulk_price_increase()` | Aumento masivo, devuelve lista de `(codigo, old, new)` |
| `restore_prices()` | Restaura precios anteriores (undo de aumento) |
| `re_apply_prices()` | Re-aplica precios nuevos (redo de aumento) |
| `get_product_suppliers()` | Lista proveedores de un producto, principal primero |
| `add_product_supplier()` | Agrega proveedor (evita duplicados) |
| `set_primary_supplier()` | Cambia principal y actualiza `productos.proveedor/precio_costo` |
| `remove_product_supplier()` | Elimina proveedor (no el único) |
| `parse_and_classify_boleta()` | Parsea CSV y clasifica filas en new/clean/conflict/skipped |
| `apply_boleta_row()` | Aplica una fila de boleta con override de precio opcional |
| `apply_boleta_batch()` | Aplica lista de filas, devuelve `(count_ok, errores)` |
| `get_products_preview()` | Fetch de muestra de productos por código (sin SQL en GUI) |
| `search_price_history()` | Historial de precios filtrado en SQL |
| `get_ventas_rango()` | Ventas entre dos fechas ISO |
| `get_range_summary()` | Resumen de rango (total, desglose por pago) |
| `load_config()` / `save_config()` | Configuración del negocio en JSON |

---

## Decisiones de diseño

| Decisión | Motivo |
|---|---|
| SQLite local, sin servidor | App monousuario de escritorio. Simplicidad de instalación. |
| `search_products()` en SQL | Más eficiente que traer todo y filtrar en Python. |
| `_calc_margen()` como helper | Fórmula usada en 2 pestañas; centralizada para evitar divergencias. |
| `log_price_change()` sin commit propio | Siempre se llama dentro de una transacción más grande. Intencional. |
| `motivo` opcional en `update_product` | Backward-compatible; por defecto `"Edición manual"`. |
| Margen = sobre precio de venta | Convención del negocio. No es markup (sobre costo). |
| Carrito activo por defecto | El negocio siempre usa carrito. |
| `forma_pago` DEFAULT 'Efectivo' | Retrocompatibilidad con ventas previas sin campo de pago. |
| `proveedores_producto` separada | Relación N a N entre productos y proveedores sin romper el contrato de `register_sale()`. |
| `_push_undo` limpia `_redo_stack` | Una nueva acción invalida el historial de redo (comportamiento estándar). |
| `_redo` no llama `_push_undo` | Para no limpiar `_redo_stack` durante la misma operación de redo. |
| Fechas en UI como DD-MM-AAAA | La DB siempre almacena ISO; la conversión ocurre en `_date_from_ui()` antes de cada query. `_ventas_filtrar_rango` compara objetos `date`, no strings, porque DD-MM-AAAA no es ordenable lexicográficamente. |
| Boleta "keep": override explícito | Pasar `None` como override dejaría que `row.precio_venta` pisara el precio de DB. Se pasan los precios actuales de la DB explícitamente. |

---

## Tests

`test_stock_app.py` — **79 tests** (36 `StockAppTests` + `StockGuiTests`). Cubre: alta de productos, ventas, stock, caja, reversiones, undo, precio histórico, ajuste de stock, multi-proveedor, aumento masivo.

Los tests de GUI (`StockGuiTests`) requieren display y están marcados con `@unittest.skipUnless`.

```powershell
python -m unittest -v
```

---

## Pendientes / ideas registradas

- Tests de GUI no corren en CI (sin display).
- El filtro por proveedor en la tabla de precios muestra solo el proveedor principal; podría extenderse a buscar en `proveedores_producto`.
- Los tests de `date.today()` pueden ser frágiles cerca de la medianoche.

**Feat 1 — Ticket post-venta:** popup con detalle itemizado después de cobrar (artículos, subtotales, total, forma de pago, fecha), con opción de imprimir o copiar como texto. No requiere cambio de schema.

**Feat 5 — Notas por venta:** campo de texto libre opcional al cobrar, guardado en `ventas` y visible en el historial. Requiere schema v6 (columna `notas` en `ventas`).

**Feat 8 — Comparación de períodos en reportes PDF:** en la sección de ventas del PDF, incluir fila comparativa con el período anterior equivalente. Solo requiere una segunda llamada a `get_ventas_rango` con fechas desplazadas.
