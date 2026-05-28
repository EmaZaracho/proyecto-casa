# Sistema simple de stock

Aplicacion de consola en Python con SQLite local.

## Uso

Interfaz grafica:

```powershell
python stock_gui.py
```

Tambien podes abrir `iniciar_gui.bat` con doble click.

Modo consola:

```powershell
python stock_app.py
```

El programa crea automaticamente:

- `stock.db`
- `fotos_productos/`

## Funciones

- Alta de productos con `codigo` como clave primaria.
- Copia opcional de fotos con nombre `[codigo]_[archivo_original]`.
- Venta rapida con control de stock negativo.
- Caja diaria acumulada por fecha `YYYY-MM-DD`.
- Alertas de stock bajo.
- Lista de pendientes con estados `Pendiente` y `Completado`.

## Pruebas

```powershell
python -m unittest -v
```
