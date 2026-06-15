# Sistema de Stock

Aplicación de escritorio en Python para gestión de inventario y punto de venta de un negocio pequeño. Corre localmente en Windows con Python + Tkinter + SQLite. Sin servidor, sin internet requerido.

**Requisitos**

- Python 3.10 o superior
- Módulos estándar: `sqlite3`, `tkinter` (incluidos en Python)
- Dependencia opcional: `fpdf2` — para exportar PDF (`pip install fpdf2`)

**Instalación**

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

También podés ejecutar `setup.bat` con doble click para hacer todo en un paso.

**Uso**

```powershell
python stock_gui.py
```

O con doble click en `iniciar_gui.bat` (Windows).

El programa crea automáticamente `stock.db`, `fotos_productos/` y `backups/` en la primera ejecución.

**Características principales**

- Alta, edición y eliminación de productos (clave: `codigo`).
- Multi-proveedor por producto: cada producto puede tener N proveedores con su propio precio de costo; el proveedor principal determina el margen.
- Importar productos y actualizar stock desde una **boleta CSV** (`codigo,nombre,cantidad,precio_costo,precio_venta,proveedor`). Los conflictos de precio se resuelven 1 a 1 con opciones: mantener, actualizar, o fijar porcentaje de ganancia.
- Registro de ventas y actualización de stock. Modo carrito para cobrar múltiples productos juntos.
- Control de ventas por forma de pago (Efectivo, Débito, Crédito, Transferencia).
- Registro de caja diaria con desglose por forma de pago y ganancia bruta.
- Aumentos masivos de precio por porcentaje con vista previa.
- Historial de cambios de precio con motivo (Edición manual / Aumento masivo / Importación boleta).
- Filtro de ventas por fecha o rango de fechas (formato DD-MM-AAAA).
- **Deshacer (Ctrl+Z) y Rehacer (Ctrl+Y)** — hasta 10 pasos.
- Exportar productos y ventas a CSV; exportar reportes a PDF.
- Pendientes (to-do) internos con estados Pendiente / Completado.
- Modo oscuro. Backup automático diario.

**Ejecutar pruebas**

```powershell
python -m unittest -v
```

79 tests. Las pruebas de GUI se omiten automáticamente si no hay display disponible.

**Empaquetar como .exe**

```powershell
setup.bat       # instala dependencias incluido PyInstaller
build.bat       # genera dist\SistemaDeStock.exe
```

**Notas**

- Exportación a PDF requiere `fpdf2`; la app sugiere instalarlo si falta.
- El formato de fecha en toda la interfaz es DD-MM-AAAA.
- `stock.db` y `config.json` están en `.gitignore`.
