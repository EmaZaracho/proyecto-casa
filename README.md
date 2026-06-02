# Sistema simple de stock

Aplicación de escritorio/console en Python que usa SQLite local para gestionar productos,
ventas, caja y reportes básicos.

**Requisitos**

- Python 3.10 o superior
- Módulos estándar: `sqlite3`, `tkinter` (para la interfaz gráfica)
- Dependencias opcionales:
	- `fpdf2` — para exportar PDF (instalable con `pip install fpdf2`)

**Instalación (recomendada)**

1. Crear y activar un entorno virtual:

```powershell
python -m venv .venv
.\.venv\Scripts\activate
```

2. (Opcional) Instalar dependencias necesarias para PDF:

```powershell
pip install fpdf2
```

**Uso**

- Interfaz gráfica:

```powershell
python stock_gui.py
```

También puedes ejecutar `iniciar_gui.bat` con doble click en Windows.

- Modo consola (CLI):

```powershell
python stock_app.py
```

El programa crea automáticamente:

- `stock.db` (base de datos SQLite)
- `fotos_productos/` (para fotografías de productos)
- `backups/` (copias de seguridad diarias)

**Características principales**

- Alta y edición de productos (clave primaria: `codigo`).
- Manejo opcional de fotos, guardadas como `[codigo]_[archivo_original]`.
- Registro de ventas y actualización de stock.
- Control de ventas con opción de permitir stock negativo.
- Registro de caja diaria y desglose por forma de pago.
- Historial de cambios de precio y deshacer (undo) en la interfaz.
- Pendientes (to‑do) con estados `Pendiente` / `Completado`.

**Ejecutar pruebas**

```powershell
python -m unittest -v
```

Las pruebas de GUI que requieren display se omiten automáticamente si no hay display disponible.

**Notas**

- Recomendado usar Python 3.10+ debido al uso de sintaxis de tipado moderno.
- La exportación a PDF requiere `fpdf2`; si no está instalada, la aplicación mostrará una sugerencia para instalarla.
- Si necesitás ayuda para ejecutar o empaquetar la aplicación, avisame y te guío.
