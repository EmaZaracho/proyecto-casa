# Sistema de Stock

Aplicacion de escritorio en Python para gestion de inventario, ventas y caja de un negocio pequeno. Corre localmente en Windows con Python, Tkinter y SQLite. No requiere servidor ni conexion a internet para operar.

## Estado actual

- Rama principal: `main`. Refactorizacion tecnica completa mergeada.
- Base de datos local SQLite con migraciones hasta schema v6.
- GUI Tkinter con textos visibles en ASCII para evitar problemas de codificacion en Windows.
- Proveedores normalizados en `proveedores_producto`; `productos.proveedor` y `productos.precio_costo` quedan como cache del proveedor principal.
- SQLite abre con `PRAGMA foreign_keys=ON` y `PRAGMA journal_mode=WAL`.
- Operaciones criticas de escritura usan transacciones con `with conn:`.
- `StockService` centraliza operaciones de negocio usadas por la GUI.
- Undo/redo esta encapsulado en `UndoManager`.
- Generacion de PDF esta encapsulada en `ReportGenerator`, que lee config fresca al generar.
- Las acciones de la GUI usan refresh selectivo para evitar recargar vistas no afectadas.
- Suite actual: 102 tests con `unittest`.

## Requisitos

- Python 3.10 o superior.
- Modulos estandar: `sqlite3`, `tkinter`, `unittest`.
- Dependencia opcional: `fpdf2` para exportar PDF.

Instalacion:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

Tambien se puede ejecutar `setup.bat` con doble click para preparar el entorno.

## Uso

```powershell
python stock_gui.py
```

O con doble click en `iniciar_gui.bat`.

En la primera ejecucion la app crea automaticamente:

- `stock.db`
- `backups/`
- `config.json` cuando se guarda configuracion
- `stock.log` cuando hay eventos o errores registrados

## Funcionalidades principales

- Alta, edicion y eliminacion de productos por `codigo`.
- Multi-proveedor por producto, con proveedor principal y precio de costo propio.
- Busqueda de productos por codigo, nombre y proveedor.
- Alertas de stock bajo y sin stock.
- Registro de ventas individuales y ventas por carrito.
- Formas de pago: `Efectivo`, `Transferencia`, `Tarjeta de credito`, `Tarjeta de debito`, `Fiado`.
- Recargo del 15 % aplicado automaticamente en ventas con tarjeta (visible en carrito antes de cobrar).
- Fiado: las ventas marcadas como "Fiado" no entran a caja; se registran como deuda del cliente y descontancstock.
- Caja diaria con total, desglose por forma de pago y ganancia bruta.
- Historial de cambios de precio con motivo.
- Aumento masivo de precios con vista previa y undo.
- Importacion de boletas CSV con proveedor elegido desde la GUI. La columna
  `proveedor` es opcional y solo se usa si el archivo necesita sobrescribir el
  proveedor elegido para una fila puntual.

```csv
codigo,nombre,cantidad,precio_costo,precio_venta
```

- Resolucion manual de conflictos de precio al importar boletas.
- Pendientes internos con estado Pendiente / Completado.
- Filtro de ventas por fecha o rango de fechas en formato `DD-MM-AAAA`.
- Exportacion de productos y ventas a CSV.
- Reportes PDF por secciones: productos, ventas, pendientes y stock bajo.
- Modo oscuro.
- Backup automatico diario del archivo de base de datos.
- Deshacer y rehacer con `Ctrl+Z` / `Ctrl+Y`, hasta 10 pasos.

### Clientes Morosos

- Pestana "Clientes Morosos" con listado de clientes y total adeudado.
- Alta de cliente moroso desde la pestana o desde el flujo de venta.
- Registro de deuda (fiado): descuenta stock pero no registra en caja ni en ventas.
- Historial por deuda: pagos y recargos por fecha.
- Registro de pagos parciales o totales desde el popup de detalle.
- Recargo mensual del 20 % aplicado automaticamente el dia 10 de cada mes a todas las deudas activas anteriores al corte (idempotente: no se aplica dos veces el mismo dia).

## Pruebas

```powershell
python -m unittest -v
```

Estado actual: 102 tests pasan.

Nota: `pytest` no es requisito del proyecto. Si se quiere usar el comando del plan:

```powershell
python -m pytest test_stock_app.py -v
```

hay que instalar `pytest` aparte.

## Empaquetar como .exe

```powershell
setup.bat
build.bat
```

El ejecutable se genera en `dist\SistemaDeStock.exe`.

## Archivos principales

- `stock_app.py`: capa de datos, migraciones, logica de negocio y `StockService`.
- `stock_gui.py`: interfaz Tkinter, orquestacion de flujos, undo/redo y reportes.
- `test_stock_app.py`: tests unitarios y tests GUI cuando hay display disponible.
- `requirements.txt`: dependencias Python.
- `stock.spec`: configuracion de PyInstaller.
- `setup.bat`, `build.bat`, `iniciar_gui.bat`: scripts de Windows.

## Notas

- `stock.db`, `config.json`, `stock.log` y `backups/` son artefactos runtime y no deberian versionarse.
- La app usa fechas ISO en SQLite y `DD-MM-AAAA` en la interfaz.
- Al borrar un producto, SQLite elimina sus proveedores por cascade; el undo captura esos proveedores para poder restaurarlos.
- Reimportar la misma boleta no duplica proveedores: actualiza el costo del proveedor existente.
