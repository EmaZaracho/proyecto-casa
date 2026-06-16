# Sistema de Stock - Contexto del Proyecto

Documento de referencia rapida: arquitectura, decisiones y estado actual.

## Que es

App de escritorio para gestion de inventario y punto de venta de un negocio pequeno. Corre localmente en Windows con Python, Tkinter y SQLite. Es una aplicacion monousuario, sin servidor y sin dependencia de internet para operar.

## Stack

| Capa | Tecnologia |
|---|---|
| GUI | Python 3.11 + Tkinter / ttk |
| Datos | SQLite 3 via `sqlite3` estandar |
| PDF | `fpdf2` |
| Tests | `unittest` estandar |
| Entorno | Windows, ejecutable con `iniciar_gui.bat` |

## Estado actual

- Rama de trabajo: `prueba-de-refactorizacion`.
- Schema actual: v5.
- Tests actuales: 89 con `python -m unittest -v`.
- `pytest` no esta instalado por defecto.
- Textos visibles de la GUI normalizados a ASCII para evitar mojibake en Windows.
- Refactor tecnico aplicado:
  - `UndoManager` encapsula pilas de undo/redo.
  - `ReportGenerator` encapsula generacion de PDF.
  - Variables Tkinter inicializadas en metodos privados.
  - Logging subido a nivel `INFO`.
  - Escrituras criticas en `stock_app.py` protegidas con `with conn:`.

## Archivos principales

```text
stock_app.py      - capa de datos: DB, migraciones, logica de negocio, CSV, backups
stock_gui.py      - GUI Tkinter, flujos de usuario, undo/redo, reportes
test_stock_app.py - tests de capa de datos, helpers y GUI
iniciar_gui.bat   - lanzador de la app
setup.bat         - crea entorno e instala dependencias
build.bat         - empaqueta con PyInstaller
stock.spec        - spec de PyInstaller
requirements.txt  - dependencias Python
config.json       - configuracion runtime, no versionada
stock.db          - SQLite runtime, no versionado
stock.log         - log runtime, no versionado
backups/          - backups automaticos diarios, no versionados
```

## Arquitectura

### Separacion de capas

`stock_app.py` concentra la capa de datos y negocio. No importa Tkinter. Expone funciones para productos, ventas, caja, proveedores, pendientes, historial, CSV, PDF data y backups.

`stock_gui.py` construye la interfaz Tkinter y llama a `stock_app.py`. No deberia hacer SQL directo salvo casos puntuales que convenga migrar despues.

### Clases estructurales nuevas

`UndoManager` vive en `stock_gui.py` y encapsula:

- pila de undo
- pila de redo
- limite maximo de 10 acciones
- invalidacion de redo cuando entra una accion nueva

`ReportGenerator` vive en `stock_gui.py` y encapsula:

- header de PDF
- tabla generica
- seccion productos
- seccion ventas
- seccion pendientes
- seccion stock bajo

La GUI queda como wrapper: recoge opciones, pide archivo destino y delega en `ReportGenerator.generate()`.

## Base de datos

### Conexion

`get_connection()` configura:

```sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
```

Decisiones:

- `foreign_keys=ON` es obligatorio para que `ON DELETE CASCADE` funcione en `proveedores_producto`.
- `journal_mode=WAL` mejora el comportamiento de lectura/escritura local sin cambiar el modelo monousuario.

### Versionado

`initialize_database()` usa tabla `schema_version` y aplica migraciones idempotentes.

Version actual: v5.

| Migracion | Cambio |
|---|---|
| v0 -> v1 | columnas extra en `productos`: proveedor, precio_costo, notas |
| v1 -> v2 | `forma_pago` en `ventas` |
| v2 -> v3 | `precio_costo` en `ventas` |
| v3 -> v4 | indices para ventas, nombre de producto y proveedor |
| v4 -> v5 | tabla `proveedores_producto` y migracion de proveedor existente |

### Tablas

```sql
productos
ventas
caja
historial_precios
pendientes
schema_version
proveedores_producto
```

`productos.proveedor` y `productos.precio_costo` se mantienen como cache del proveedor principal para no romper consultas existentes. La fuente normalizada de proveedores es `proveedores_producto`.

## Integridad y transacciones

Las operaciones criticas de negocio usan `with conn:` para commit/rollback atomico:

- `update_product`
- `_restore_product`
- `delete_product`
- `adjust_stock`
- `bulk_price_increase`
- `add_pending`
- `complete_pending`
- `delete_pending`

`log_price_change()` no hace commit propio. Se mantiene asi para que el cambio de precio y su auditoria queden en la misma transaccion.

## Proveedores

Decision actual: `get_all_proveedores()` lee desde `proveedores_producto`, no desde `productos.proveedor`.

Motivo:

- desde schema v5 los proveedores viven en la tabla normalizada;
- leer solo `productos.proveedor` omite proveedores secundarios;
- los combos de proveedor deben mostrar proveedores reales, no solo principales.

Al crear o actualizar productos, si hay proveedor se crea o actualiza el proveedor principal en `proveedores_producto`, incluso si el costo es `0`.

Si un producto se actualiza con proveedor vacio, se elimina el proveedor principal normalizado para evitar registros vacios en combos y listados. Si quedan proveedores secundarios, se promueve el primero como principal para que el producto no quede con proveedores pero sin principal.

`add_product_supplier()` es idempotente por `codigo + proveedor`: si el proveedor ya existe para el producto, actualiza su costo y no crea una fila duplicada.

Al borrar un producto:

- SQLite borra sus proveedores por cascade;
- la GUI captura `suppliers` antes de borrar;
- `_restore_product()` puede reinsertar esos proveedores al deshacer;
- si el codigo ya fue reutilizado, `_restore_product()` falla con `DuplicateProductError` y no mezcla proveedores del producto viejo con el nuevo.

## Importacion de boletas

La GUI pide el proveedor de la boleta antes de parsear el CSV. El usuario puede elegir un proveedor existente o ingresar uno nuevo.

Formato minimo:

```csv
codigo,nombre,cantidad
```

Columnas opcionales:

```csv
precio_costo,precio_venta,proveedor
```

Decision actual: `proveedor` en el CSV es opcional. Si no viene o esta vacio, `parse_and_classify_boleta(..., default_proveedor=...)` usa el proveedor elegido en la GUI. Si la columna existe y una fila trae valor, ese valor tiene prioridad sobre el proveedor del dialogo.

## Funcionalidades implementadas

### Principal

- Tabla de productos con busqueda en SQL.
- Alta y edicion de productos.
- Multi-proveedor por producto.
- Ajuste directo de stock.
- Importacion de boleta CSV con proveedor por dialogo.
- Venta individual y carrito.
- Alertas de stock bajo.
- Pendientes internos.

### Gestion de precios

- Tabla de productos con precio de venta, costo, margen y proveedor principal.
- Filtros por texto y proveedor.
- Aumento masivo con vista previa.
- Undo de aumento masivo.
- Exportacion de productos.

### Ventas del dia

- Navegacion por fecha.
- Filtro por rango `DD-MM-AAAA`.
- Tabla de ventas.
- Cierre de caja con desglose por pago, ganancia bruta y top productos.
- Exportacion CSV.

### Historial de precios

- Auditoria automatica de cambios.
- Motivos usados:
  - `Edicion manual`
  - `Aumento masivo X%`
  - `Importacion boleta`
- Busqueda SQL por codigo o nombre.

### Reportes

- PDF por secciones:
  - productos
  - ventas
  - pendientes
  - stock bajo
- Implementado por `ReportGenerator`.

## Logging

`stock_gui.py` configura logging a nivel `INFO` en `stock.log`.

Eventos de negocio registrados:

- venta individual
- carrito procesado
- producto eliminado
- aumento masivo de precios
- importacion de boleta

Los errores criticos siguen usando `logger.exception()`.

`load_config()` ya no silencia errores de lectura de `config.json`; registra warning y usa defaults.

## Decisiones de diseno

| Decision | Motivo |
|---|---|
| SQLite local, sin servidor | Instalacion simple para app monousuario. |
| `foreign_keys=ON` por conexion | Hace efectivo `ON DELETE CASCADE`. |
| `journal_mode=WAL` | Mejora robustez/performance local sin cambiar arquitectura. |
| Mutaciones con `with conn:` | Rollback automatico ante fallos intermedios. |
| `proveedores_producto` como fuente de proveedores | Evita perder proveedores secundarios. |
| `productos.proveedor/precio_costo` como cache | Mantiene compatibilidad con vistas y reportes existentes. |
| Proveedor vacio elimina proveedor principal y promueve secundario si existe | Evita registros vacios y mantiene un unico principal cuando quedan proveedores. |
| Proveedor repetido actualiza costo sin duplicar | Hace idempotente la importacion de boletas y la carga manual. |
| Undo de eliminacion captura proveedores | Necesario porque cascade borra `proveedores_producto`. |
| Restore no usa `INSERT OR IGNORE` | Evita mezclar proveedores si un codigo eliminado fue reutilizado antes del undo. |
| Proveedor de boleta por dialogo | Permite omitir `proveedor` en el CSV sin perder trazabilidad. |
| `UndoManager` | Reduce responsabilidad directa de `StockGui`. |
| `ReportGenerator` | Aisla generacion PDF de la GUI. |
| Textos visibles ASCII | Evita mojibake en Tkinter/Windows con archivos tocados por distintas herramientas. |
| `log_price_change()` sin commit propio | Auditoria y cambio quedan en la misma transaccion. |
| Margen sobre precio de venta | Convencion actual del negocio. |
| Fechas UI `DD-MM-AAAA`, DB ISO | UI amigable y DB ordenable. |
| Carrito activo por defecto | Flujo habitual del negocio. |

## Funciones clave en stock_app.py

| Funcion | Proposito |
|---|---|
| `get_connection()` | Abre SQLite, row factory, WAL y foreign keys. |
| `initialize_database()` | Crea tablas y aplica migraciones. |
| `add_product()` | Alta de producto y proveedor principal. |
| `update_product(..., motivo)` | Edita producto, proveedor principal e historial de precio. |
| `delete_product()` | Elimina producto; proveedores caen por cascade. |
| `_restore_product()` | Reinsert para undo, incluyendo proveedores capturados. |
| `register_sale()` | Venta, stock, caja y registro en `ventas`. |
| `reverse_sale()` | Undo de venta. |
| `restore_sale()` | Redo de venta. |
| `bulk_price_increase()` | Aumento masivo transaccional. |
| `restore_prices()` | Undo de aumento. |
| `re_apply_prices()` | Redo de aumento. |
| `get_all_proveedores()` | Lista proveedores desde `proveedores_producto`. |
| `get_product_suppliers()` | Lista proveedores de un producto. |
| `set_primary_supplier()` | Cambia proveedor principal y actualiza cache en `productos`. |
| `parse_and_classify_boleta(..., default_proveedor)` | Lee CSV, aplica proveedor por defecto y clasifica filas. |
| `apply_boleta_row()` | Aplica una fila de boleta. |
| `apply_boleta_batch()` | Aplica lote de boleta. |
| `get_range_summary()` | Resumen de ventas por rango. |
| `load_config()` / `save_config()` | Configuracion runtime. |

## Tests

Comando principal:

```powershell
python -m unittest -v
```

Estado actual:

- 89 tests pasan.
- Tests de GUI corren solo si hay display disponible.
- Cobertura nueva incluye cascade de proveedores, restore sin merge accidental, proveedores duplicados, promocion de secundario y proveedor por defecto en boleta.

## Pendientes / ideas

- El filtro por proveedor en la tabla de precios sigue mostrando el proveedor principal; podria extenderse para filtrar tambien por proveedores secundarios.
- Tests dependientes de `date.today()` pueden ser fragiles cerca de medianoche.
- Agregar ticket post-venta sin cambio de schema.
- Agregar notas por venta con schema v6 (`ventas.notas`).
- Comparacion de periodos en reportes PDF.
