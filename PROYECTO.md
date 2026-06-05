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
| Tests | `unittest` estándar |
| Entorno | Windows 11, ejecutable con `iniciar_gui.bat` |

---

## Archivos principales

```
stock_app.py      — capa de datos: DB, lógica de negocio, funciones puras
stock_gui.py      — GUI completa (Tkinter), consume stock_app
test_stock_app.py — tests unitarios de la capa de datos
iniciar_gui.bat   — lanzador de la app
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

Schema versioning con tabla `schema_version`. Al arrancar, `initialize_database()` detecta la versión actual y aplica las migraciones pendientes. Las migraciones son idempotentes (`_col_exists` previene ALTER TABLE duplicados).

**Versiones:**
- v0 → v1: columnas extra en `productos` (proveedor, precio_costo, notas)
- v1 → v2: `forma_pago` en `ventas`
- v2 → v3: `precio_costo` en `ventas` (para calcular ganancia bruta)

**Tablas:**

```sql
productos        — catálogo: codigo (PK), nombre, precio, stock, stock_minimo,
                   proveedor, precio_costo, notas, foto (columna legada, no usada)
ventas           — registros de venta: codigo, nombre, cantidad, precio_unit,
                   total, fecha, hora, forma_pago, precio_costo
caja             — total diario por fecha (PK)
historial_precios — auditoría de cambios de precio
pendientes       — lista de tareas interna
schema_version   — versión actual del schema
```

### Configuración persistente

`config.json` almacena `nombre_negocio` y `moneda`. Se carga al arrancar y se lee en el header de la app y en los PDFs exportados. Las funciones `load_config()` / `save_config()` están en `stock_app.py`.

### Logging

Errores se escriben en `stock.log` (BASE_DIR) con `logging.basicConfig`. Nivel ERROR. Los `except` críticos en la GUI llaman a `logger.exception()`.

---

## Funcionalidades implementadas

### Pestaña Principal

- **Tabla de productos**: búsqueda en tiempo real por código, nombre y proveedor (via `search_products()` SQL). Ordenamiento por columna (clic en encabezado, flecha ▲▼). Colores: rojo si stock ≤ 0, amarillo si stock < mínimo.
- **Formulario de producto**: alta y edición inline. Campos: código, nombre, precio, precio de costo, stock, mínimo, proveedor, notas. El código es readonly en edición.
- **Ajustar stock**: botón en la tabla que abre un diálogo para setear el stock actual directamente (usa `adjust_stock()`).
- **Venta rápida**: campo código + cantidad + forma de pago. Autocompletado: al tipear el código aparece nombre, precio y stock del producto. Botón 🔍 abre búsqueda por nombre.
- **Modo carrito**: activo por defecto al arrancar. Permite agregar múltiples productos antes de cobrar. El carrito muestra ítems, subtotales y total. Botón "Cobrar todo" registra todas las ventas con la forma de pago seleccionada.
- **Alertas de stock bajo**: tabla lateral con productos bajo el mínimo.
- **Lista de tareas**: pendientes con toggle Pendiente/Completado.

### Pestaña Gestión de Precios

- Tabla con precio de venta, precio de costo, margen, proveedor.
- Filtros: texto (SQL via `search_products`) + combo de proveedor.
- Aumentos masivos por porcentaje, aplicables a seleccionados o a todos los filtrados.
- El margen se calcula con `_calc_margen(precio, costo)` = `(precio - costo) / precio × 100`. Es margen sobre precio de venta, NO markup.
- **Exportar CSV** de productos. **Exportar PDF** con selector de contenido (lista completa / stock bajo).

### Pestaña Ventas del Día

- Navegación por fecha con botones ◀ ▶ y campo de fecha manual. Botón "Hoy".
- Filtro por rango de fechas (Desde / Hasta) con `get_ventas_rango()`.
- Tabla con hora, código, nombre, cantidad, precio unitario, subtotal y **forma de pago**.
- Label de total acumulado al pie.
- Resumen en header: N ventas | Total $X.
- **Cierre de caja**: popup con total del día, desglose por forma de pago y top 5 productos más vendidos. Desde schema v3 también muestra ganancia bruta del día.
- Exportar ventas del día a CSV.

### Pestaña Historial de Precios

- Registro automático de cambios de precio en `historial_precios`.
- Se loggea en: edición manual de producto (motivo "Edición manual") y aumentos masivos (motivo "Aumento masivo X%").
- Búsqueda en tiempo real por código o nombre.
- Se refresca al seleccionar la pestaña.

### Funciones de sistema

- **Undo** (Ctrl+Z, hasta 10 pasos): deshace ventas, altas y eliminaciones de producto.
- **Backup automático**: un .db por día en `backups/`, al iniciar la app.
- **Modo oscuro**: toggle en la barra superior, aplica tema a toda la interfaz.
- **Atajo F1**: foco en campo de código de venta.
- **Atajo F2**: abrir formulario de producto.
- **Atajo F3**: foco en campo de tarea pendiente.
- **Configuración** (botón ⚙): cambiar nombre del negocio y símbolo de moneda.

---

## Decisiones de diseño

| Decisión | Motivo |
|---|---|
| SQLite local, sin servidor | App monousuario de escritorio. Simplicidad de instalación. |
| `search_products()` en SQL | Más eficiente que traer todo y filtrar en Python, especialmente con catálogos grandes. |
| `_calc_margen()` como helper | Fórmula usada en 2 pestañas; centralizada para evitar divergencias. |
| `log_price_change()` sin commit propio | Siempre se llama dentro de una transacción más grande que hace commit. Intencional. |
| Columna `foto` en DB pero sin UI | Se eliminó la funcionalidad de fotos por no utilizarse. La columna queda en el schema para compatibilidad con datos existentes. |
| Margen = sobre precio de venta | Convención del negocio. No es markup (que sería sobre costo). |
| Carrito activo por defecto | El negocio siempre usa carrito; el toggle era un paso innecesario. |
| `forma_pago` DEFAULT 'Efectivo' | Retrocompatibilidad con ventas previas sin campo de pago. |

---

## Tests

`test_stock_app.py` cubre la capa de datos (36 tests). Prueba: alta de productos, ventas, stock, caja, reversiones, undo, precio histórico, ajuste de stock.

Los tests de GUI (`StockGuiTests`) requieren display disponible y están marcados con `@unittest.skipUnless`.

Ejecutar: `python -m unittest test_stock_app.StockAppTests`

---

## Cosas pendientes / ideas registradas

- Popup de alerta de stock bajo al iniciar (descartado temporalmente).
- Importar productos desde CSV (descartado temporalmente).
- Los tests de GUI actualmente no corren en CI (sin display).
