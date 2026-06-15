from __future__ import annotations

import logging
import sqlite3
import tkinter as tk
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any

import stock_app

_UNDO_MAX = 10
_FORMAS_PAGO = ("Efectivo", "Transferencia", "Tarjeta")

_COLORS_LIGHT = dict(
    bg="#f0f0f0", bg_widget="#ffffff", fg="#000000", fg_muted="gray",
    btn_bg="#e1e1e1", sel_bg="#0078d7", sel_fg="#ffffff",
    tree_bg="#ffffff", heading_bg="#dcdcdc", heading_fg="#000000",
    critical_bg="#ffcccc", critical_fg="#8b0000",
    warning_bg="#fff8e1", warning_fg="#000000",
)
_COLORS_DARK = dict(
    bg="#2b2b2b", bg_widget="#3c3f41", fg="#cccccc", fg_muted="#888888",
    btn_bg="#4c4c4c", sel_bg="#4b6eaf", sel_fg="#ffffff",
    tree_bg="#313335", heading_bg="#4c4f52", heading_fg="#cccccc",
    critical_bg="#5c1a1a", critical_fg="#ff9090",
    warning_bg="#4a3d00", warning_fg="#ffd54f",
)

logging.basicConfig(
    filename=stock_app.BASE_DIR / "stock.log",
    level=logging.ERROR,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    encoding="utf-8",
)
logger = logging.getLogger(__name__)


class StockGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Sistema de Stock")
        self.geometry("1100x720")
        self.minsize(960, 620)

        self.conn = stock_app.get_connection()
        stock_app.initialize_database(self.conn)
        self._config = stock_app.load_config()
        self._dark_mode: bool = bool(self._config.get("dark_mode", False))
        self._muted_labels: list[ttk.Label] = []

        # ── product form vars ──
        self.codigo_var = tk.StringVar()
        self.nombre_var = tk.StringVar()
        self.precio_var = tk.StringVar()
        self.precio_costo_var = tk.StringVar()
        self.stock_var = tk.StringVar()
        self.stock_minimo_var = tk.StringVar()
        self.proveedor_var = tk.StringVar()
        self.notas_var = tk.StringVar()

        # ── sale vars ──
        self.venta_codigo_var = tk.StringVar()
        self.venta_cantidad_var = tk.StringVar(value="1")
        self._venta_forma_pago_var = tk.StringVar(value="Efectivo")
        self._producto_preview_var = tk.StringVar()

        # ── other vars ──
        self.pendiente_var = tk.StringVar()
        self.caja_var = tk.StringVar()
        self.search_var = tk.StringVar()
        self._status_var = tk.StringVar()
        self._ventas_summary_var = tk.StringVar(value="Hoy: 0 ventas | Total: $0.00")
        self._cart_total_var = tk.StringVar(value="Total: $0.00")

        # ── price tab vars ──
        self.price_search_var = tk.StringVar()
        self.price_proveedor_var = tk.StringVar()
        self.aumento_var = tk.StringVar()
        self._price_status_var = tk.StringVar(value="Seleccionados: 0")

        # ── historial tab vars ──
        self._hist_search_var = tk.StringVar()

        # ── ventas tab vars ──
        self._ventas_date_var = tk.StringVar(value=_date_to_ui(date.today()))
        self._ventas_total_var = tk.StringVar(value="Total del día: $0.00")
        self._ventas_desde_var = tk.StringVar(value="")
        self._ventas_hasta_var = tk.StringVar(value="")
        self._ventas_range_active = False

        # ── reportes tab vars ──
        self._rep_productos_var = tk.BooleanVar(value=True)
        self._rep_ventas_var = tk.BooleanVar(value=True)
        self._rep_pendientes_var = tk.BooleanVar(value=False)
        self._rep_stock_bajo_var = tk.BooleanVar(value=True)
        self._rep_desde_var = tk.StringVar(value=_date_to_ui(date.today().replace(day=1)))
        self._rep_hasta_var = tk.StringVar(value=_date_to_ui(date.today()))

        # ── sorting state ──
        self._sort_col: str = ""
        self._sort_asc: bool = True

        # ── state ──
        self._edit_mode = False
        self._edit_codigo: str | None = None
        self._form_visible = False
        self._cart_mode_active = False
        self._cart: list[dict[str, Any]] = []
        self._undo_stack: list[dict[str, Any]] = []
        self._redo_stack: list[dict[str, Any]] = []

        self._build_layout()
        self.search_var.trace_add("write", lambda *_: self.refresh_products())
        self._hist_search_var.trace_add("write", lambda *_: self._refresh_price_history())
        self.venta_codigo_var.trace_add("write", lambda *_: self._update_producto_preview())
        self.refresh_all()
        self.bind("<Control-z>", lambda _: self._undo())
        self.bind("<Control-y>", lambda _: self._redo())
        # F-key shortcuts
        self.bind("<F1>", lambda _: self._venta_codigo_entry.focus_set())
        self.bind("<F2>", lambda _: self._toggle_form())
        self.bind("<F3>", lambda _: self._pendiente_entry.focus_set())
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # silent daily backup
        try:
            stock_app.backup_database()
        except Exception:
            pass

    # =========================================================================
    # Layout
    # =========================================================================

    def _build_layout(self) -> None:
        style = ttk.Style(self)
        style.configure("Title.TLabel", font=("Segoe UI", 13, "bold"))
        style.configure("Bold.TLabel", font=("Segoe UI", 10, "bold"))

        outer = ttk.Frame(self, padding=10)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        # header
        hdr = ttk.Frame(outer)
        hdr.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        hdr.columnconfigure(1, weight=1)
        self._title_label = ttk.Label(
            hdr, text=self._config.get("nombre_negocio", "Sistema de Stock"),
            style="Title.TLabel",
        )
        self._title_label.grid(row=0, column=0, sticky="w")
        ttk.Label(hdr, textvariable=self.caja_var).grid(row=0, column=1, sticky="e", padx=(0, 10))
        ttk.Button(hdr, text="⚙", width=3, command=self._show_configuracion).grid(
            row=0, column=2, padx=(0, 6)
        )
        self._undo_btn = ttk.Button(
            hdr, text="↩ Deshacer (Ctrl+Z)", command=self._undo, state="disabled"
        )
        self._undo_btn.grid(row=0, column=3, padx=(6, 0))
        self._redo_btn = ttk.Button(
            hdr, text="↪ Rehacer (Ctrl+Y)", command=self._redo, state="disabled"
        )
        self._redo_btn.grid(row=0, column=4, padx=(6, 0))
        self._dark_mode_btn = ttk.Button(
            hdr, text="🌙" if not self._dark_mode else "☀", width=3,
            command=self._toggle_dark_mode,
        )
        self._dark_mode_btn.grid(row=0, column=5, padx=(6, 0))

        # shortcuts hint
        _shortcuts_lbl = ttk.Label(hdr, text="F1=Venta  F2=Producto  F3=Pendiente",
                                   foreground="gray")
        _shortcuts_lbl.grid(row=1, column=0, columnspan=6, sticky="w", pady=(2, 0))
        self._muted_labels.append(_shortcuts_lbl)

        # notebook
        self._notebook = ttk.Notebook(outer)
        self._notebook.grid(row=1, column=0, sticky="nsew")
        self._notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        tab0 = ttk.Frame(self._notebook, padding=12)
        tab1 = ttk.Frame(self._notebook, padding=6)
        tab2 = ttk.Frame(self._notebook, padding=6)
        tab3 = ttk.Frame(self._notebook, padding=6)
        tab4 = ttk.Frame(self._notebook, padding=6)
        tab5 = ttk.Frame(self._notebook, padding=6)
        self._notebook.add(tab0, text="  Resumen  ")
        self._notebook.add(tab1, text="  Principal  ")
        self._notebook.add(tab2, text="  Gestión de precios  ")
        self._notebook.add(tab3, text="  Ventas del día  ")
        self._notebook.add(tab4, text="  Historial de precios  ")
        self._notebook.add(tab5, text="  Reportes  ")

        self._build_tab_dashboard(tab0)
        self._build_tab_principal(tab1)
        self._build_tab_precios(tab2)
        self._build_tab_ventas(tab3)
        self._build_tab_historial(tab4)
        self._build_tab_reportes(tab5)

        status_bar = ttk.Label(
            outer, textvariable=self._status_var,
            relief="sunken", anchor="w", padding=(6, 2),
        )
        status_bar.grid(row=2, column=0, sticky="ew", pady=(8, 0))

        self._apply_theme()

    # ── Tab 0 — Dashboard ─────────────────────────────────────────────────────

    def _build_tab_dashboard(self, frame: ttk.Frame) -> None:
        frame.columnconfigure(0, weight=1)

        # Ventas de hoy
        ventas_lf = ttk.LabelFrame(frame, text="  Ventas de hoy  ", padding=10)
        ventas_lf.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ventas_lf.columnconfigure(1, weight=1)

        self._dash_total_var = tk.StringVar(value="$0.00")
        self._dash_count_var = tk.StringVar(value="0 ventas")
        self._dash_pagos_var = tk.StringVar(value="Sin ventas registradas")

        ttk.Label(ventas_lf, textvariable=self._dash_total_var,
                  style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(ventas_lf, textvariable=self._dash_count_var).grid(row=0, column=1, sticky="e")
        lbl_pagos = ttk.Label(ventas_lf, textvariable=self._dash_pagos_var)
        lbl_pagos.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self._muted_labels.append(lbl_pagos)

        # Alertas de stock
        stock_lf = ttk.LabelFrame(frame, text="  Alertas de stock  ", padding=10)
        stock_lf.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        stock_lf.columnconfigure(0, weight=1)

        self._dash_alert_var = tk.StringVar(value="✅ Sin alertas")
        ttk.Label(stock_lf, textvariable=self._dash_alert_var).grid(
            row=0, column=0, sticky="w", pady=(0, 6)
        )

        self._dash_stock_list = ttk.Treeview(
            stock_lf,
            columns=("codigo", "nombre", "stock"),
            show="headings",
            height=6,
            selectmode="none",
        )
        self._dash_stock_list.heading("codigo", text="Código", anchor="center")
        self._dash_stock_list.heading("nombre", text="Nombre", anchor="center")
        self._dash_stock_list.heading("stock", text="Stock", anchor="center")
        self._dash_stock_list.column("codigo", width=110, anchor="center")
        self._dash_stock_list.column("nombre", width=280, anchor="center")
        self._dash_stock_list.column("stock", width=70, anchor="center")
        self._dash_stock_list.grid(row=1, column=0, sticky="ew")

        # Acceso rápido
        quick_lf = ttk.LabelFrame(frame, text="  Acceso rápido  ", padding=10)
        quick_lf.grid(row=2, column=0, sticky="ew")

        ttk.Button(
            quick_lf, text="🧾 Nueva venta  (F1)",
            command=lambda: (
                self._notebook.select(1),
                self.after(50, self._venta_codigo_entry.focus_set),
            ),
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            quick_lf, text="🔍 Buscar producto",
            command=lambda: (
                self._notebook.select(1),
                self.after(50, self._product_search_entry.focus_set),
            ),
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            quick_lf, text="📦 Nuevo producto  (F2)",
            command=lambda: (
                self._notebook.select(1),
                self.after(80, self._toggle_form),
            ),
        ).pack(side="left")

    def _refresh_dashboard(self) -> None:
        summary = stock_app.get_daily_summary(self.conn)
        breakdown = stock_app.get_payment_breakdown(self.conn)

        self._dash_total_var.set(f"${summary['total']:.2f}")
        count = summary["count"]
        self._dash_count_var.set(f"{count} venta{'s' if count != 1 else ''}")
        if breakdown:
            pagos = "  |  ".join(
                f"{r['forma_pago']}: ${float(r['total']):.2f}" for r in breakdown
            )
            self._dash_pagos_var.set(pagos)
        else:
            self._dash_pagos_var.set("Sin ventas registradas")

        productos = stock_app.search_products(self.conn)
        criticos = [p for p in productos if p["stock"] <= 0]
        bajos = [p for p in productos if 0 < p["stock"] < p["stock_minimo"]]

        if criticos or bajos:
            self._dash_alert_var.set(
                f"🔴 {len(criticos)} sin stock   |   🟡 {len(bajos)} bajo mínimo"
            )
        else:
            self._dash_alert_var.set("✅ Sin alertas de stock")

        clear_table(self._dash_stock_list)
        for p in (criticos + bajos)[:10]:
            self._dash_stock_list.insert(
                "", "end",
                values=(p["codigo"], p["nombre"], p["stock"]),
            )

    # ── Tab 1 ─────────────────────────────────────────────────────────────────

    def _build_tab_principal(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=2)
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(0, weight=1)

        left = ttk.Frame(parent)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.rowconfigure(2, weight=1)
        left.columnconfigure(0, weight=1)

        right = ttk.Frame(parent)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        right.rowconfigure(2, weight=1)

        toggle_row = ttk.Frame(left)
        toggle_row.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        self._toggle_form_btn = ttk.Button(
            toggle_row, text="＋ Nuevo producto", command=self._toggle_form
        )
        self._toggle_form_btn.pack(side="left")
        ttk.Button(
            toggle_row, text="Importar boleta CSV", command=self._import_boleta_csv
        ).pack(side="left", padx=(6, 0))

        self._build_product_form(left)
        self._build_product_table(left)
        self._build_sale_box(right)
        self._toggle_cart_mode()  # arranca en modo carrito (activo por defecto)
        self._build_alerts_box(right)
        self._build_pending_box(right)

    def _build_product_form(self, parent: ttk.Frame) -> None:
        self._product_form_frame = ttk.LabelFrame(parent, text="Alta de producto", padding=8)
        self._product_form_frame.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        for col in range(8):
            self._product_form_frame.columnconfigure(col, weight=1)

        # row 0 — labels
        for col, text in enumerate(
            ("Codigo", "Nombre", "", "Precio", "P.Costo", "Stock", "Minimo", "Proveedor")
        ):
            if text:
                ttk.Label(self._product_form_frame, text=text).grid(row=0, column=col, sticky="w")

        # row 1 — entries
        self._codigo_entry = ttk.Entry(self._product_form_frame, textvariable=self.codigo_var)
        self._codigo_entry.grid(row=1, column=0, sticky="ew", padx=(0, 4))

        self._nombre_entry = ttk.Entry(self._product_form_frame, textvariable=self.nombre_var)
        self._nombre_entry.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(0, 4))

        ttk.Entry(self._product_form_frame, textvariable=self.precio_var).grid(
            row=1, column=3, sticky="ew", padx=(0, 4)
        )
        ttk.Entry(self._product_form_frame, textvariable=self.precio_costo_var).grid(
            row=1, column=4, sticky="ew", padx=(0, 4)
        )
        ttk.Entry(self._product_form_frame, textvariable=self.stock_var).grid(
            row=1, column=5, sticky="ew", padx=(0, 4)
        )
        ttk.Entry(self._product_form_frame, textvariable=self.stock_minimo_var).grid(
            row=1, column=6, sticky="ew", padx=(0, 4)
        )
        self._proveedor_combo = ttk.Combobox(
            self._product_form_frame, textvariable=self.proveedor_var, state="readonly"
        )
        self._proveedor_combo.grid(row=1, column=7, sticky="ew")
        self._proveedor_combo.bind("<ButtonPress>", lambda _: self._refresh_form_proveedor())
        self._proveedor_combo.bind("<FocusIn>", lambda _: self._refresh_form_proveedor())

        # row 2 — second row labels
        ttk.Label(self._product_form_frame, text="Notas").grid(
            row=2, column=0, sticky="w", pady=(6, 0)
        )

        # row 3 — notas + actions
        ttk.Entry(self._product_form_frame, textvariable=self.notas_var).grid(
            row=3, column=0, columnspan=6, sticky="ew", padx=(0, 4)
        )
        self._save_btn = ttk.Button(
            self._product_form_frame, text="Guardar", command=self.save_product
        )
        self._save_btn.grid(row=3, column=6, sticky="ew", padx=(0, 4))
        self._cancel_edit_btn = ttk.Button(
            self._product_form_frame, text="Cancelar", command=self.cancel_edit
        )
        self._cancel_edit_btn.grid(row=3, column=7, sticky="ew")
        self._cancel_edit_btn.grid_remove()

        suppliers_frame = ttk.LabelFrame(
            self._product_form_frame, text="Proveedores del producto", padding=6
        )
        suppliers_frame.grid(row=4, column=0, columnspan=8, sticky="ew", pady=(8, 0))
        suppliers_frame.columnconfigure(0, weight=1)

        supplier_cols = ("proveedor", "precio_costo", "principal")
        self._suppliers_table = ttk.Treeview(
            suppliers_frame, columns=supplier_cols, show="headings", height=3
        )
        for col, label, width in (
            ("proveedor", "Proveedor", 220),
            ("precio_costo", "Precio costo", 110),
            ("principal", "Principal", 80),
        ):
            anchor = "e" if col == "precio_costo" else "w"
            self._suppliers_table.heading(col, text=label, anchor=anchor)
            self._suppliers_table.column(col, width=width, minwidth=60, anchor=anchor)
        self._suppliers_table.grid(row=0, column=0, sticky="ew")

        supplier_actions = ttk.Frame(suppliers_frame)
        supplier_actions.grid(row=0, column=1, sticky="ns", padx=(6, 0))
        self._supplier_add_btn = ttk.Button(
            supplier_actions, text="+ Agregar proveedor", command=self._add_product_supplier
        )
        self._supplier_add_btn.pack(fill="x", pady=(0, 4))
        self._supplier_primary_btn = ttk.Button(
            supplier_actions, text="Establecer principal", command=self._set_primary_supplier
        )
        self._supplier_primary_btn.pack(fill="x", pady=(0, 4))
        self._supplier_remove_btn = ttk.Button(
            supplier_actions, text="Eliminar", command=self._remove_product_supplier
        )
        self._supplier_remove_btn.pack(fill="x")
        self._set_supplier_controls_state("disabled")

        self._product_form_frame.grid_remove()

    def _build_product_table(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Productos", padding=8)
        frame.grid(row=2, column=0, sticky="nsew")
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)

        search_row = ttk.Frame(frame)
        search_row.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        search_row.columnconfigure(1, weight=1)
        ttk.Label(search_row, text="Buscar:").grid(row=0, column=0, padx=(0, 6))
        self._product_search_entry = ttk.Entry(search_row, textvariable=self.search_var)
        self._product_search_entry.grid(row=0, column=1, sticky="ew")

        cols = ("codigo", "nombre", "precio", "margen", "stock", "minimo", "proveedor")
        self.products_table = ttk.Treeview(frame, columns=cols, show="headings", height=11)
        for col, label, width in (
            ("codigo", "Codigo", 95),
            ("nombre", "Nombre", 165),
            ("precio", "Precio", 80),
            ("margen", "Margen", 70),
            ("stock", "Stock", 60),
            ("minimo", "Stock mín.", 70),
            ("proveedor", "Proveedor", 110),
        ):
            self.products_table.heading(
                col, text=label,
                command=lambda c=col: self._sort_products(c),
                anchor="e" if col in {"precio", "margen", "stock", "minimo"} else "w",
            )
            self.products_table.column(
                col,
                width=width,
                minwidth=38,
                anchor="e" if col in {"precio", "margen", "stock", "minimo"} else "w",
            )

        sb = ttk.Scrollbar(frame, orient="vertical", command=self.products_table.yview)
        self.products_table.configure(yscrollcommand=sb.set)
        self.products_table.grid(row=1, column=0, sticky="nsew")
        sb.grid(row=1, column=1, sticky="ns")
        self.products_table.bind("<Double-1>", lambda _: self.load_selected_for_edit())

        actions = ttk.Frame(frame)
        actions.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        actions.columnconfigure(4, weight=1)
        ttk.Button(actions, text="Agregar al carrito", command=self.add_selected_to_cart).grid(
            row=0, column=0, padx=(0, 6)
        )
        ttk.Button(actions, text="Cargar para editar", command=self.load_selected_for_edit).grid(
            row=0, column=1, padx=(0, 6)
        )
        ttk.Button(actions, text="Ajustar stock", command=self._show_ajuste_stock).grid(
            row=0, column=2, padx=(0, 6)
        )
        ttk.Button(actions, text="Eliminar", command=self.delete_selected_product).grid(
            row=0, column=3, padx=(0, 6)
        )
        ttk.Button(actions, text="Actualizar lista", command=self.refresh_all).grid(row=0, column=4)
        _consejo_lbl = ttk.Label(
            frame,
            text="Consejo: doble clic en una fila para editarla",
            foreground="gray",
        )
        _consejo_lbl.grid(row=3, column=0, columnspan=2, sticky="w", pady=(2, 0))
        self._muted_labels.append(_consejo_lbl)

    def _build_sale_box(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Venta", padding=8)
        frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        frame.columnconfigure(1, weight=1)

        # row 0: codigo + search button
        ttk.Label(frame, text="Codigo").grid(row=0, column=0, sticky="w", padx=(0, 6))
        code_row = ttk.Frame(frame)
        code_row.grid(row=0, column=1, sticky="ew")
        code_row.columnconfigure(0, weight=1)
        self._venta_codigo_entry = ttk.Entry(code_row, textvariable=self.venta_codigo_var)
        self._venta_codigo_entry.grid(row=0, column=0, sticky="ew")
        ttk.Button(code_row, text="🔍", width=3, command=self._buscar_producto_por_nombre).grid(
            row=0, column=1, padx=(4, 0)
        )

        # row 1: product name preview
        self._producto_preview_label = ttk.Label(
            frame, textvariable=self._producto_preview_var, foreground="gray",
            font=("Segoe UI", 8),
        )
        self._producto_preview_label.grid(row=1, column=0, columnspan=2, sticky="w", pady=(1, 0))
        self._muted_labels.append(self._producto_preview_label)

        # row 2: cantidad
        ttk.Label(frame, text="Cantidad").grid(row=2, column=0, sticky="w", padx=(0, 6), pady=(4, 0))
        self._venta_cantidad_entry = ttk.Entry(frame, textvariable=self.venta_cantidad_var)
        self._venta_cantidad_entry.grid(row=2, column=1, sticky="ew", pady=(4, 0))

        # row 3: forma de pago
        ttk.Label(frame, text="Pago").grid(row=3, column=0, sticky="w", padx=(0, 6), pady=(4, 0))
        ttk.Combobox(
            frame, textvariable=self._venta_forma_pago_var,
            values=_FORMAS_PAGO, state="readonly", width=14,
        ).grid(row=3, column=1, sticky="w", pady=(4, 0))

        # row 4: normal mode register button
        self._registrar_btn = ttk.Button(
            frame, text="Registrar venta", command=self.register_sale
        )
        self._registrar_btn.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        # cart mode: add-to-cart button (hidden by default)
        # cart mode: add-to-cart button (hidden by default)
        self._agregar_carrito_btn = ttk.Button(
            frame, text="＋ Agregar al carrito", command=self._add_to_cart
        )
        self._agregar_carrito_btn.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self._agregar_carrito_btn.grid_remove()

        ttk.Separator(frame, orient="horizontal").grid(
            row=5, column=0, columnspan=2, sticky="ew", pady=(8, 4)
        )

        # cart treeview (hidden by default)
        cart_cols = ("nombre", "cant", "precio", "subtotal")
        self._cart_table = ttk.Treeview(frame, columns=cart_cols, show="headings", height=5)
        for col, label, width in (
            ("nombre", "Producto", 115),
            ("cant", "Cant.", 38),
            ("precio", "P.Unit.", 60),
            ("subtotal", "Subtotal", 65),
        ):
            self._cart_table.heading(col, text=label)
            self._cart_table.column(col, width=width, minwidth=30)
        self._cart_table.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(0, 4))
        self._cart_table.grid_remove()
        self._cart_table.bind("<Double-1>", lambda _: self.load_selected_cart_for_edit())

        self._cart_total_label = ttk.Label(
            frame, textvariable=self._cart_total_var, style="Bold.TLabel"
        )
        self._cart_total_label.grid(row=7, column=0, columnspan=2, sticky="e", pady=(0, 4))
        self._cart_total_label.grid_remove()

        cart_btns = ttk.Frame(frame)
        cart_btns.grid(row=8, column=0, columnspan=2, sticky="ew")
        cart_btns.columnconfigure(0, weight=1)
        ttk.Button(cart_btns, text="Cobrar todo", command=self._cobrar_carrito).grid(
            row=0, column=0, sticky="ew", padx=(0, 4)
        )
        ttk.Button(cart_btns, text="Quitar", command=self._remove_from_cart).grid(
            row=0, column=1, padx=(0, 4)
        )
        ttk.Button(cart_btns, text="Vaciar", command=self._clear_cart).grid(row=0, column=2)
        cart_btns.grid_remove()
        self._cart_btns_frame = cart_btns

        self._toggle_cart_btn = ttk.Button(
            frame, text="🛒 Activar modo carrito", command=self._toggle_cart_mode
        )
        self._toggle_cart_btn.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(4, 0))

        # key bindings
        self._venta_codigo_entry.bind("<Return>", lambda _: self._venta_cantidad_entry.focus())
        self._venta_cantidad_entry.bind("<Return>", lambda _: self._handle_venta_return())

    def _build_alerts_box(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Stock bajo", padding=8)
        frame.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        cols = ("codigo", "nombre", "stock", "minimo")
        self.alerts_table = ttk.Treeview(frame, columns=cols, show="headings", height=5)
        for col, label, width in (
            ("codigo", "Codigo", 82),
            ("nombre", "Nombre", 115),
            ("stock", "Stock", 52),
            ("minimo", "Stock mín.", 60),
        ):
            self.alerts_table.heading(col, text=label)
            self.alerts_table.column(col, width=width, minwidth=40)
        self.alerts_table.grid(row=0, column=0, sticky="nsew")

    def _build_pending_box(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Pendientes", padding=8)
        frame.grid(row=2, column=0, sticky="nsew")
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)

        entry_row = ttk.Frame(frame)
        entry_row.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        entry_row.columnconfigure(0, weight=1)
        self._pendiente_entry = ttk.Entry(entry_row, textvariable=self.pendiente_var)
        self._pendiente_entry.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(entry_row, text="Agregar", command=self.add_pending).grid(row=0, column=1)

        cols = ("estado", "descripcion")
        self.pending_table = ttk.Treeview(frame, columns=cols, show="headings", height=5)
        for col, label, width in (
            ("estado", "Estado", 80),
            ("descripcion", "Descripcion", 185),
        ):
            self.pending_table.heading(col, text=label)
            self.pending_table.column(col, width=width, minwidth=30)
        self.pending_table.grid(row=1, column=0, sticky="nsew")

        btn_row = ttk.Frame(frame)
        btn_row.grid(row=2, column=0, sticky="ew", pady=(6, 0))
        btn_row.columnconfigure(0, weight=1)
        ttk.Button(btn_row, text="Marcar completado", command=self.complete_selected_pending).grid(
            row=0, column=1, padx=(0, 6)
        )
        ttk.Button(btn_row, text="Eliminar", command=self.delete_selected_pending).grid(
            row=0, column=2, padx=(0, 6)
        )
        ttk.Button(btn_row, text="Refrescar", command=self.refresh_pending).grid(row=0, column=3)

    # ── Tab 2: price management ───────────────────────────────────────────────

    def _build_tab_precios(self, parent: ttk.Frame) -> None:
        parent.rowconfigure(1, weight=1)
        parent.columnconfigure(0, weight=1)

        filter_frame = ttk.LabelFrame(parent, text="Filtros", padding=8)
        filter_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        filter_frame.columnconfigure(1, weight=1)
        filter_frame.columnconfigure(3, weight=2)

        ttk.Label(filter_frame, text="Proveedor:").grid(row=0, column=0, padx=(0, 6))
        self._price_proveedor_combo = ttk.Combobox(
            filter_frame, textvariable=self.price_proveedor_var, width=22
        )
        self._price_proveedor_combo.grid(row=0, column=1, sticky="ew", padx=(0, 14))
        self._price_proveedor_combo.bind("<ButtonPress>", lambda _: self._refresh_price_proveedor())
        self._price_proveedor_combo.bind("<FocusIn>", lambda _: self._refresh_price_proveedor())

        ttk.Label(filter_frame, text="Buscar:").grid(row=0, column=2, padx=(0, 6))
        ttk.Entry(filter_frame, textvariable=self.price_search_var).grid(
            row=0, column=3, sticky="ew", padx=(0, 14)
        )
        ttk.Button(filter_frame, text="Filtrar", command=self.refresh_price_table).grid(
            row=0, column=4, padx=(0, 6)
        )
        ttk.Button(filter_frame, text="Limpiar", command=self._clear_price_filters).grid(
            row=0, column=5
        )

        table_frame = ttk.LabelFrame(
            parent,
            text="Productos  —  Ctrl+Click o Shift+Click para seleccion multiple",
            padding=8,
        )
        table_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        price_cols = ("codigo", "nombre", "precio", "precio_costo", "margen", "proveedor")
        self.price_table = ttk.Treeview(
            table_frame, columns=price_cols, show="headings",
            selectmode="extended", height=16,
        )
        for col, label, width in (
            ("codigo", "Codigo", 115),
            ("nombre", "Nombre", 260),
            ("precio", "Precio venta", 100),
            ("precio_costo", "Precio costo", 100),
            ("margen", "Margen %", 80),
            ("proveedor", "Proveedor", 150),
        ):
            anchor = "e" if col in {"precio", "precio_costo", "margen"} else "w"
            self.price_table.heading(col, text=label, anchor=anchor)
            self.price_table.column(col, width=width, minwidth=55, anchor=anchor)

        psb = ttk.Scrollbar(table_frame, orient="vertical", command=self.price_table.yview)
        self.price_table.configure(yscrollcommand=psb.set)
        self.price_table.grid(row=0, column=0, sticky="nsew")
        psb.grid(row=0, column=1, sticky="ns")
        self.price_table.bind("<<TreeviewSelect>>", self._on_price_selection_change)
        self.price_table.bind("<Double-1>", lambda _: self._load_price_row_for_edit())

        inc_frame = ttk.LabelFrame(parent, text="Aplicar aumento de precio", padding=8)
        inc_frame.grid(row=2, column=0, sticky="ew")
        inc_frame.columnconfigure(5, weight=1)

        ttk.Label(inc_frame, text="Porcentaje:").grid(row=0, column=0, padx=(0, 4))
        ttk.Entry(inc_frame, textvariable=self.aumento_var, width=8).grid(row=0, column=1, padx=(0, 2))
        ttk.Label(inc_frame, text="%").grid(row=0, column=2, padx=(0, 14))
        ttk.Button(
            inc_frame, text="Aplicar a seleccionados",
            command=self._apply_to_selected,
        ).grid(row=0, column=3, padx=(0, 8))
        ttk.Button(
            inc_frame, text="Aplicar a todos los filtrados",
            command=self._apply_to_filtered,
        ).grid(row=0, column=4, padx=(0, 14))
        ttk.Button(
            inc_frame, text="Exportar productos CSV",
            command=self._export_products_csv,
        ).grid(row=0, column=5, padx=(0, 8))
        ttk.Label(inc_frame, textvariable=self._price_status_var).grid(row=0, column=6, sticky="e")

    # ── Tab 4: price history ──────────────────────────────────────────────────

    def _build_tab_historial(self, parent: ttk.Frame) -> None:
        parent.rowconfigure(1, weight=1)
        parent.columnconfigure(0, weight=1)

        filter_row = ttk.Frame(parent)
        filter_row.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        filter_row.columnconfigure(1, weight=1)
        ttk.Label(filter_row, text="Buscar:").grid(row=0, column=0, padx=(0, 6))
        ttk.Entry(filter_row, textvariable=self._hist_search_var).grid(row=0, column=1, sticky="ew")
        ttk.Button(filter_row, text="Refrescar", command=self._refresh_price_history).grid(
            row=0, column=2, padx=(8, 0)
        )

        table_frame = ttk.LabelFrame(parent, text="Cambios de precio", padding=8)
        table_frame.grid(row=1, column=0, sticky="nsew")
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        hist_cols = ("fecha", "codigo", "nombre", "anterior", "nuevo", "cambio", "motivo")
        self._hist_table = ttk.Treeview(table_frame, columns=hist_cols, show="headings", height=20)
        for col, label, width in (
            ("fecha", "Fecha y hora", 140),
            ("codigo", "Codigo", 80),
            ("nombre", "Nombre", 150),
            ("anterior", "Precio ant.", 80),
            ("nuevo", "Precio nuevo", 85),
            ("cambio", "Cambio", 70),
            ("motivo", "Motivo", 160),
        ):
            self._hist_table.heading(col, text=label)
            self._hist_table.column(col, width=width, minwidth=40)

        vsb = ttk.Scrollbar(table_frame, orient="vertical", command=self._hist_table.yview)
        self._hist_table.configure(yscrollcommand=vsb.set)
        self._hist_table.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

    def _refresh_price_history(self) -> None:
        clear_table(self._hist_table)
        query = self._hist_search_var.get()
        for row in stock_app.search_price_history(self.conn, query):
            ant = float(row["precio_anterior"])
            nvo = float(row["precio_nuevo"])
            if ant > 0:
                pct = ((nvo - ant) / ant) * 100
                cambio = f"+{pct:.1f}%" if pct >= 0 else f"{pct:.1f}%"
            else:
                cambio = "-"
            self._hist_table.insert("", "end", values=(
                row["fecha"], row["codigo"], row["nombre"],
                f"${ant:.2f}", f"${nvo:.2f}", cambio, row["motivo"],
            ))

    # ── Tab 3: sales of the day ───────────────────────────────────────────────

    def _build_tab_ventas(self, parent: ttk.Frame) -> None:
        parent.rowconfigure(2, weight=1)
        parent.columnconfigure(0, weight=1)

        # ── date navigation + summary ─────────────────────────────────────────
        nav_frame = ttk.Frame(parent)
        nav_frame.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        nav_frame.columnconfigure(4, weight=1)

        self._nav_prev_btn = ttk.Button(nav_frame, text="◀", width=3, command=self._ventas_prev_day)
        self._nav_prev_btn.grid(row=0, column=0, padx=(0, 2))
        self._nav_date_entry = ttk.Entry(nav_frame, textvariable=self._ventas_date_var, width=12)
        self._nav_date_entry.grid(row=0, column=1, padx=(0, 2))
        self._nav_next_btn = ttk.Button(nav_frame, text="▶", width=3, command=self._ventas_next_day)
        self._nav_next_btn.grid(row=0, column=2, padx=(0, 10))
        self._nav_today_btn = ttk.Button(nav_frame, text="Hoy", command=self._ventas_go_today)
        self._nav_today_btn.grid(row=0, column=3, padx=(0, 14))
        ttk.Label(
            nav_frame, textvariable=self._ventas_summary_var,
            font=("Segoe UI", 11, "bold"),
        ).grid(row=0, column=4, sticky="e")

        # ── date range filter ─────────────────────────────────────────────────
        range_frame = ttk.Frame(parent)
        range_frame.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(range_frame, text="Rango — Desde:").grid(row=0, column=0, padx=(0, 4))
        ttk.Entry(range_frame, textvariable=self._ventas_desde_var, width=12).grid(
            row=0, column=1, padx=(0, 8)
        )
        ttk.Label(range_frame, text="Hasta:").grid(row=0, column=2, padx=(0, 4))
        ttk.Entry(range_frame, textvariable=self._ventas_hasta_var, width=12).grid(
            row=0, column=3, padx=(0, 8)
        )
        ttk.Button(range_frame, text="Filtrar rango", command=self._ventas_filtrar_rango).grid(
            row=0, column=4, padx=(0, 4)
        )
        ttk.Button(range_frame, text="Limpiar", command=self._ventas_limpiar_rango).grid(
            row=0, column=5
        )

        # ── ventas table ─────────────────────────────────────────────────────
        self._ventas_table_frame = ttk.LabelFrame(parent, text="Ventas", padding=8)
        self._ventas_table_frame.grid(row=2, column=0, sticky="nsew", pady=(0, 4))
        self._ventas_table_frame.rowconfigure(0, weight=1)
        self._ventas_table_frame.columnconfigure(0, weight=1)

        cols = ("hora", "codigo", "nombre", "cantidad", "precio_unit", "total", "forma_pago")
        self.ventas_table = ttk.Treeview(self._ventas_table_frame, columns=cols, show="headings", height=16)
        for col, label, width in (
            ("hora", "Hora", 72),
            ("codigo", "Codigo", 90),
            ("nombre", "Nombre", 200),
            ("cantidad", "Cant.", 50),
            ("precio_unit", "P.Unit.", 80),
            ("total", "Subtotal", 80),
            ("forma_pago", "Pago", 90),
        ):
            anchor = "e" if col in {"cantidad", "precio_unit", "total"} else "w"
            self.ventas_table.heading(col, text=label, anchor=anchor)
            self.ventas_table.column(col, width=width, minwidth=40, anchor=anchor)

        vsb = ttk.Scrollbar(self._ventas_table_frame, orient="vertical", command=self.ventas_table.yview)
        self.ventas_table.configure(yscrollcommand=vsb.set)
        self.ventas_table.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        # ── total footer ──────────────────────────────────────────────────────
        ttk.Label(parent, textvariable=self._ventas_total_var,
                  font=("Segoe UI", 10, "bold")).grid(
            row=3, column=0, sticky="e", pady=(0, 4)
        )

        # ── buttons ───────────────────────────────────────────────────────────
        btn_row = ttk.Frame(parent)
        btn_row.grid(row=4, column=0, sticky="ew")
        btn_row.columnconfigure(0, weight=1)
        ttk.Button(btn_row, text="Refrescar", command=self.refresh_ventas).grid(
            row=0, column=1, padx=(0, 6)
        )
        ttk.Button(btn_row, text="Exportar ventas CSV", command=self._export_ventas_csv).grid(
            row=0, column=2, padx=(0, 6)
        )
        ttk.Button(btn_row, text="Cierre de caja", command=self._show_cierre_caja).grid(
            row=0, column=3
        )

    # =========================================================================
    # Status bar
    # =========================================================================

    def _set_status(self, msg: str, ms: int = 3000) -> None:
        self._status_var.set(msg)
        self.after(ms, lambda: self._status_var.set(""))

    # =========================================================================
    # Form toggle
    # =========================================================================

    def _toggle_form(self) -> None:
        self._form_visible = not self._form_visible
        if self._form_visible:
            self._product_form_frame.grid()
            self._toggle_form_btn.configure(text="✕ Cerrar formulario")
        else:
            self._product_form_frame.grid_remove()
            self._toggle_form_btn.configure(text="＋ Nuevo producto")

    # =========================================================================
    # Tab change
    # =========================================================================

    def _on_tab_changed(self, _=None) -> None:
        idx = self._notebook.index("current")
        if idx == 0:
            self._refresh_dashboard()
        elif idx == 1:
            self.after(50, self._venta_codigo_entry.focus_set)
        elif idx == 2:
            self.refresh_price_table()
        elif idx == 3:
            self.refresh_ventas()
        elif idx == 4:
            self._refresh_price_history()

    # =========================================================================
    # Ventas por fecha
    # =========================================================================

    def _ventas_go_today(self) -> None:
        self._ventas_date_var.set(_date_to_ui(date.today()))
        self.refresh_ventas()

    def _ventas_prev_day(self) -> None:
        try:
            d = _date_from_ui(self._ventas_date_var.get()) - timedelta(days=1)
        except ValueError:
            d = date.today()
        self._ventas_date_var.set(_date_to_ui(d))
        self.refresh_ventas()

    def _ventas_next_day(self) -> None:
        try:
            d = _date_from_ui(self._ventas_date_var.get()) + timedelta(days=1)
        except ValueError:
            d = date.today()
        self._ventas_date_var.set(_date_to_ui(d))
        self.refresh_ventas()

    def _selected_ventas_date(self) -> date | None:
        try:
            return _date_from_ui(self._ventas_date_var.get())
        except ValueError:
            return None

    def _center_dialog(self, dialog: tk.Toplevel) -> None:
        dialog.update_idletasks()
        width = dialog.winfo_width()
        height = dialog.winfo_height()
        if width <= 1:
            width = dialog.winfo_reqwidth()
        if height <= 1:
            height = dialog.winfo_reqheight()
        x = self.winfo_rootx() + (self.winfo_width() - width) // 2
        y = self.winfo_rooty() + (self.winfo_height() - height) // 2
        dialog.geometry(f"{width}x{height}+{x}+{y}")

    # =========================================================================
    # Autocompletado de producto en venta
    # =========================================================================

    def _update_producto_preview(self) -> None:
        codigo = self.venta_codigo_var.get().strip()
        if not codigo:
            self._producto_preview_var.set("")
            return
        try:
            row = stock_app.get_product(self.conn, codigo)
            if row:
                self._producto_preview_var.set(
                    f"{row['nombre']}  —  ${float(row['precio']):.2f}  |  Stock: {row['stock']}"
                )
            else:
                self._producto_preview_var.set("")
        except Exception:
            self._producto_preview_var.set("")

    def _buscar_producto_por_nombre(self) -> None:
        query = self.venta_codigo_var.get().strip()

        dialog = tk.Toplevel(self)
        dialog.title("Buscar producto")
        dialog.geometry("420x320")
        dialog.transient(self)
        dialog.grab_set()

        ttk.Label(dialog, text="Buscar por nombre o código:").pack(padx=12, pady=(12, 4), anchor="w")

        search_var = tk.StringVar(value=query)
        search_entry = ttk.Entry(dialog, textvariable=search_var)
        search_entry.pack(fill="x", padx=12)

        listbox = tk.Listbox(dialog, height=10, font=("Segoe UI", 9))
        listbox.pack(fill="both", expand=True, padx=12, pady=8)

        _all_products: list = []

        def _populate(q: str = "") -> None:
            listbox.delete(0, "end")
            _all_products.clear()
            q = q.lower()
            for p in stock_app.list_products(self.conn):
                if not q or q in p["codigo"].lower() or q in p["nombre"].lower():
                    display = f"{p['codigo']}  —  {p['nombre']}  (${float(p['precio']):.2f})"
                    listbox.insert("end", display)
                    _all_products.append(p["codigo"])

        search_var.trace_add("write", lambda *_: _populate(search_var.get()))
        _populate(query)
        search_entry.focus_set()

        def _select(*_) -> None:
            sel = listbox.curselection()
            if not sel:
                return
            self.venta_codigo_var.set(_all_products[sel[0]])
            self._venta_codigo_entry.focus_set()
            dialog.destroy()

        listbox.bind("<Double-1>", _select)
        listbox.bind("<Return>", _select)
        ttk.Button(dialog, text="Seleccionar", command=_select).pack(pady=(0, 10))
        self._center_dialog(dialog)

    # =========================================================================
    # Ordenamiento de tabla de productos
    # =========================================================================

    def _sort_products(self, col: str) -> None:
        if self._sort_col == col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = col
            self._sort_asc = True
        self.refresh_products()

    # =========================================================================
    # Configuración del negocio
    # =========================================================================

    def _show_configuracion(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Configuración")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="Nombre del negocio:").grid(row=0, column=0, sticky="w", pady=(0, 4))
        nombre_var = tk.StringVar(value=self._config.get("nombre_negocio", ""))
        ttk.Entry(frame, textvariable=nombre_var, width=32).grid(row=0, column=1, padx=(8, 0))

        ttk.Label(frame, text="Símbolo de moneda:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        moneda_var = tk.StringVar(value=self._config.get("moneda", "$"))
        ttk.Entry(frame, textvariable=moneda_var, width=6).grid(row=1, column=1, sticky="w", padx=(8, 0), pady=(8, 0))

        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(16, 0))

        def _guardar() -> None:
            self._config["nombre_negocio"] = nombre_var.get().strip() or "Sistema de Stock"
            self._config["moneda"] = moneda_var.get().strip() or "$"
            stock_app.save_config(self._config)
            self._title_label.configure(text=self._config["nombre_negocio"])
            dialog.destroy()
            self._set_status("✓ Configuración guardada")

        ttk.Button(btn_frame, text="Guardar", command=_guardar).pack(side="right", padx=(8, 0))
        ttk.Button(btn_frame, text="Cancelar", command=dialog.destroy).pack(side="right")
        self._center_dialog(dialog)

    # =========================================================================
    # Proveedor autocomplete
    # =========================================================================

    def _refresh_form_proveedor(self) -> None:
        self._proveedor_combo["values"] = stock_app.get_all_proveedores(self.conn)

    def _refresh_price_proveedor(self) -> None:
        self._price_proveedor_combo["values"] = stock_app.get_all_proveedores(self.conn)

    def _set_supplier_controls_state(self, state: str) -> None:
        for btn in (
            self._supplier_add_btn,
            self._supplier_primary_btn,
            self._supplier_remove_btn,
        ):
            btn.configure(state=state)

    def _refresh_product_suppliers(self) -> None:
        clear_table(self._suppliers_table)
        if not self._edit_mode or not self._edit_codigo:
            self._set_supplier_controls_state("disabled")
            return
        self._set_supplier_controls_state("normal")
        for row in stock_app.get_product_suppliers(self.conn, self._edit_codigo):
            self._suppliers_table.insert(
                "",
                "end",
                iid=str(row["id"]),
                values=(
                    row["proveedor"],
                    f"${float(row['precio_costo']):.2f}",
                    "Si" if int(row["es_principal"]) else "",
                ),
            )

    def _sync_primary_supplier_fields(self) -> None:
        if not self._edit_codigo:
            return
        product = stock_app.get_product(self.conn, self._edit_codigo)
        self.proveedor_var.set(product["proveedor"] or "")
        self.precio_costo_var.set(str(product["precio_costo"]))

    def _add_product_supplier(self) -> None:
        if not self._edit_mode or not self._edit_codigo:
            messagebox.showerror("Guardar primero", "Guarda el producto antes de agregar proveedores.")
            return
        proveedor = simpledialog.askstring(
            "Agregar proveedor", "Proveedor:", parent=self
        )
        if proveedor is None:
            return
        proveedor = proveedor.strip()
        if not proveedor:
            messagebox.showerror("Proveedor requerido", "El proveedor es obligatorio.")
            return
        costo_raw = simpledialog.askstring(
            "Agregar proveedor", "Precio de costo:", parent=self
        )
        if costo_raw is None:
            return
        try:
            precio_costo = parse_float(costo_raw, "precio costo")
            stock_app.add_product_supplier(self.conn, self._edit_codigo, proveedor, precio_costo)
        except (ValueError, stock_app.StockError) as exc:
            messagebox.showerror("No se pudo agregar", str(exc))
            return
        self._sync_primary_supplier_fields()
        self._refresh_product_suppliers()
        self.refresh_products()
        self.refresh_price_table()
        self._set_status(f"Proveedor '{proveedor}' agregado.")

    def _selected_supplier_id(self) -> int | None:
        selected = self._suppliers_table.selection()
        if not selected:
            messagebox.showerror("Seleccione un proveedor", "Elija un proveedor de la lista.")
            return None
        return int(selected[0])

    def _set_primary_supplier(self) -> None:
        if not self._edit_codigo:
            return
        supplier_id = self._selected_supplier_id()
        if supplier_id is None:
            return
        try:
            stock_app.set_primary_supplier(self.conn, supplier_id, self._edit_codigo)
        except stock_app.StockError as exc:
            messagebox.showerror("No se pudo actualizar", str(exc))
            return
        self._sync_primary_supplier_fields()
        self._refresh_product_suppliers()
        self.refresh_all()
        self._set_status("Proveedor principal actualizado.")

    def _remove_product_supplier(self) -> None:
        supplier_id = self._selected_supplier_id()
        if supplier_id is None:
            return
        if not messagebox.askyesno("Eliminar proveedor", "Eliminar el proveedor seleccionado?"):
            return
        try:
            stock_app.remove_product_supplier(self.conn, supplier_id)
        except stock_app.StockError as exc:
            messagebox.showerror("No se pudo eliminar", str(exc))
            return
        self._refresh_product_suppliers()
        self.refresh_all()
        self._set_status("Proveedor eliminado.")

    def _clear_price_filters(self) -> None:
        self.price_proveedor_var.set("")
        self.price_search_var.set("")
        self.refresh_price_table()

    def _on_price_selection_change(self, *_) -> None:
        n = len(self.price_table.selection())
        total = len(self.price_table.get_children())
        self._price_status_var.set(f"Seleccionados: {n} / Total filtrados: {total}")

    # =========================================================================
    # Cart mode
    # =========================================================================

    def _toggle_cart_mode(self) -> None:
        self._cart_mode_active = not self._cart_mode_active
        if self._cart_mode_active:
            self._registrar_btn.grid_remove()
            self._agregar_carrito_btn.grid()
            self._cart_table.grid()
            self._cart_total_label.grid()
            self._cart_btns_frame.grid()
            self._toggle_cart_btn.configure(text="✕ Desactivar modo carrito")
        else:
            self._agregar_carrito_btn.grid_remove()
            self._cart_table.grid_remove()
            self._cart_total_label.grid_remove()
            self._cart_btns_frame.grid_remove()
            self._registrar_btn.grid()
            self._toggle_cart_btn.configure(text="🛒 Activar modo carrito")
            self._clear_cart()

    def _handle_venta_return(self) -> None:
        if self._cart_mode_active:
            self._add_to_cart()
        else:
            self.register_sale()

    def _add_to_cart(self) -> None:
        codigo = self.venta_codigo_var.get().strip()
        if not codigo:
            return
        try:
            cantidad = parse_int(self.venta_cantidad_var.get(), "cantidad")
        except ValueError as exc:
            messagebox.showerror("Valor invalido", str(exc))
            return
        try:
            product = stock_app.get_product(self.conn, codigo)
        except stock_app.ProductNotFoundError:
            if messagebox.askyesno(
                "Producto no encontrado",
                f"No existe ningún producto con código '{codigo}'.\n\n¿Querés agregarlo ahora?",
            ):
                self._start_add_product_with_code(codigo)
            return

        previous_quantity = 0
        previous_item: dict[str, Any] | None = None
        # merge if already in cart
        for item in self._cart:
            if item["codigo"] == codigo:
                previous_quantity = int(item["cantidad"])
                previous_item = dict(item)
                item["cantidad"] += cantidad
                item["subtotal"] = item["cantidad"] * item["precio_unit"]
                break
        else:
            self._cart.append({
                "codigo": codigo,
                "nombre": product["nombre"],
                "cantidad": cantidad,
                "precio_unit": float(product["precio"]),
                "subtotal": cantidad * float(product["precio"]),
            })

        self._push_undo({
            "type": "cart_change",
            "codigo": codigo,
            "previous_quantity": previous_quantity,
            "new_quantity": previous_quantity + cantidad,
            "previous_item": previous_item,
            "description": f"carrito {cantidad}x '{codigo}'",
        })
        self.venta_codigo_var.set("")
        self.venta_cantidad_var.set("1")
        self._refresh_cart_display()
        self._venta_codigo_entry.focus_set()

    def _find_cart_item_index(self, codigo: str) -> int:
        for index, item in enumerate(self._cart):
            if item["codigo"] == codigo:
                return index
        return -1

    def add_selected_to_cart(self) -> None:
        selected = self.products_table.selection()
        if not selected:
            messagebox.showerror("Seleccione un producto", "Elija un producto de la lista.")
            return

        codigo = self.products_table.item(selected[0], "values")[0]
        self.venta_codigo_var.set(codigo)
        if not self._cart_mode_active:
            self._toggle_cart_mode()
        self._add_to_cart()

    def load_selected_cart_for_edit(self) -> None:
        selected = self._cart_table.selection()
        if not selected:
            return

        idx = self._cart_table.index(selected[0])
        if not (0 <= idx < len(self._cart)):
            return

        self._edit_cart_item_dialog(idx)

    def _edit_cart_item_dialog(self, idx: int) -> None:
        item = self._cart[idx]

        dialog = tk.Toplevel(self)
        dialog.title("Editar producto del carrito")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=16)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Producto:").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 6))
        ttk.Label(frame, text=item["nombre"]).grid(row=0, column=1, sticky="w", pady=(0, 6))

        ttk.Label(frame, text="Código:").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(0, 6))
        ttk.Label(frame, text=item["codigo"]).grid(row=1, column=1, sticky="w", pady=(0, 6))

        qty_var = tk.StringVar(value=str(item["cantidad"]))
        ttk.Label(frame, text="Cantidad:").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(0, 10))
        qty_entry = ttk.Entry(frame, textvariable=qty_var, width=12)
        qty_entry.grid(row=2, column=1, sticky="w", pady=(0, 10))

        btn_row = ttk.Frame(frame)
        btn_row.grid(row=3, column=0, columnspan=2, sticky="e")

        def _save() -> None:
            try:
                new_quantity = parse_int(qty_var.get(), "cantidad")
            except ValueError as exc:
                messagebox.showerror("Valor invalido", str(exc), parent=dialog)
                return
            if new_quantity <= 0:
                messagebox.showerror(
                    "Valor invalido",
                    "La cantidad debe ser mayor a 0.",
                    parent=dialog,
                )
                return

            previous_quantity = int(item["cantidad"])
            if new_quantity == previous_quantity:
                dialog.destroy()
                return

            self._cart[idx]["cantidad"] = new_quantity
            self._cart[idx]["subtotal"] = new_quantity * float(self._cart[idx]["precio_unit"])
            self._push_undo({
                "type": "cart_change",
                "codigo": item["codigo"],
                "previous_quantity": previous_quantity,
                "new_quantity": new_quantity,
                "description": f"editar carrito '{item['codigo']}'",
            })
            self._refresh_cart_display()
            dialog.destroy()

        ttk.Button(btn_row, text="Guardar", command=_save).pack(side="right", padx=(8, 0))
        ttk.Button(btn_row, text="Cancelar", command=dialog.destroy).pack(side="right")

        self._center_dialog(dialog)

        qty_entry.focus_set()
        qty_entry.selection_range(0, tk.END)

    def _refresh_cart_display(self) -> None:
        clear_table(self._cart_table)
        total = 0.0
        for item in self._cart:
            self._cart_table.insert(
                "", "end",
                values=(
                    item["nombre"][:22],
                    item["cantidad"],
                    f"${item['precio_unit']:.2f}",
                    f"${item['subtotal']:.2f}",
                ),
            )
            total += item["subtotal"]
        self._cart_total_var.set(f"Total: ${total:.2f}")

    def _remove_from_cart(self) -> None:
        selected = self._cart_table.selection()
        if not selected:
            return
        idx = self._cart_table.index(selected[0])
        if 0 <= idx < len(self._cart):
            item = dict(self._cart.pop(idx))
            self._push_undo({
                "type": "cart_remove",
                "item": item,
                "index": idx,
                "description": f"quitar carrito '{item['codigo']}'",
            })
        self._refresh_cart_display()

    def _clear_cart(self) -> None:
        if self._cart:
            if not messagebox.askyesno(
                "Vaciar carrito",
                f"Eliminar {len(self._cart)} producto(s)?",
            ):
                return
            self._push_undo({
                "type": "cart_clear",
                "items": [dict(item) for item in self._cart],
                "description": f"vaciar carrito ({len(self._cart)})",
            })
        self._cart.clear()
        self._refresh_cart_display()

    def _cobrar_carrito(self) -> None:
        if not self._cart:
            messagebox.showerror("Carrito vacío", "No hay productos en el carrito.")
            return

        forma_pago = self._venta_forma_pago_var.get() or "Efectivo"
        errors: list[str] = []
        processed: list[dict] = []
        sale_date = date.today()

        for item in self._cart:
            try:
                total, sale_id = stock_app.register_sale(
                    self.conn, item["codigo"], item["cantidad"],
                    sale_date=sale_date, forma_pago=forma_pago,
                )
                processed.append({
                    **item,
                    "total": total,
                    "sale_id": sale_id,
                    "sale_date": sale_date.isoformat(),
                })
            except stock_app.InsufficientStockError as exc:
                errors.append(f"• {item['nombre']}: {exc}")
            except stock_app.StockError as exc:
                errors.append(f"• {item['nombre']}: {exc}")

        for item in reversed(processed):
            self._push_undo({
                "type": "sale",
                "codigo": item["codigo"],
                "cantidad": item["cantidad"],
                "total": item["total"],
                "sale_id": item["sale_id"],
                "sale_date": item["sale_date"],
                "description": f"venta {item['cantidad']}x '{item['codigo']}' (${item['total']:.2f})",
            })

        processed_codes = {p["codigo"] for p in processed}
        self._cart = [i for i in self._cart if i["codigo"] not in processed_codes]
        self._refresh_cart_display()
        self.refresh_all()

        total_cobrado = sum(p["total"] for p in processed)
        if errors:
            messagebox.showwarning(
                "Venta parcial",
                f"Procesados: {len(processed)} | Total: ${total_cobrado:.2f}\n\nErrores:\n"
                + "\n".join(errors),
            )
        else:
            self._set_status(
                f"✓ Carrito cobrado [{forma_pago}] — {len(processed)} prod. — Total: ${total_cobrado:.2f}"
            )
            self._cart.clear()
            self._refresh_cart_display()

    # =========================================================================
    # Price increase
    # =========================================================================

    def _apply_to_selected(self) -> None:
        selected = self.price_table.selection()
        if not selected:
            messagebox.showerror(
                "Sin seleccion",
                "Use Ctrl+Click o Shift+Click para seleccionar productos.",
            )
            return
        codigos = [self.price_table.item(iid, "values")[0] for iid in selected]
        self._apply_price_increase(codigos)

    def _apply_to_filtered(self) -> None:
        codigos = [
            self.price_table.item(iid, "values")[0]
            for iid in self.price_table.get_children()
        ]
        if not codigos:
            messagebox.showerror("Sin productos", "No hay productos visibles en la tabla.")
            return
        self._apply_price_increase(codigos)

    def _apply_price_increase(self, codigos: list[str]) -> None:
        try:
            pct = parse_float(self.aumento_var.get(), "porcentaje")
        except ValueError as exc:
            messagebox.showerror("Valor invalido", str(exc))
            return
        if pct <= 0.0:
            messagebox.showerror("Valor invalido", "El porcentaje debe ser mayor a 0.")
            return

        sample_rows = stock_app.get_products_preview(self.conn, codigos[:3])
        preview_lines = "\n".join(
            f"  {row['nombre'][:25]}: ${row['precio']:.0f} -> "
            f"${round(row['precio'] * (1 + pct / 100) / 10) * 10:.0f}"
            for row in sample_rows
        )
        preview = f"\n\nVista previa:\n{preview_lines}" if preview_lines else ""
        if not messagebox.askyesno(
            "Confirmar aumento",
            f"Aplicar {pct:.1f}% a {len(codigos)} producto(s)?\n"
            "El resultado se redondea a la decena mas cercana."
            f"{preview}",
        ):
            return

        changes = stock_app.bulk_price_increase(self.conn, codigos, pct)
        if changes:
            self._push_undo({
                "type": "price_increase",
                "changes": changes,
                "description": f"aumento {pct:.1f}% a {len(changes)} producto(s)",
            })
        self.refresh_all()
        self.aumento_var.set("")
        self._set_status(f"✓ Aumento {pct:.1f}% aplicado a {len(changes)} producto(s).")

    def _load_price_row_for_edit(self) -> None:
        selected = self.price_table.selection()
        if not selected:
            return
        codigo = self.price_table.item(selected[0], "values")[0]
        try:
            product = stock_app.get_product(self.conn, codigo)
        except stock_app.StockError:
            return
        self.enter_edit_mode(product)

    # =========================================================================
    # Ventas del día
    # =========================================================================

    def refresh_ventas(self) -> None:
        clear_table(self.ventas_table)
        running_total = 0.0
        if self._ventas_range_active:
            ventas = stock_app.get_ventas_rango(
                self.conn,
                _date_from_ui(self._ventas_desde_var.get()).isoformat(),
                _date_from_ui(self._ventas_hasta_var.get()).isoformat(),
            )
            for row in ventas:
                running_total += float(row["total"])
                self.ventas_table.insert(
                    "", "end",
                    values=(
                        f"{row['fecha']} {row['hora']}",
                        row["codigo"],
                        row["nombre"],
                        row["cantidad"],
                        f"${row['precio_unit']:.2f}",
                        f"${row['total']:.2f}",
                        row["forma_pago"],
                    ),
                )
            self._ventas_total_var.set(f"Total del rango: ${running_total:.2f}")
            self._ventas_summary_var.set(
                f"Rango {self._ventas_desde_var.get()} → {self._ventas_hasta_var.get()}: "
                f"{len(ventas)} ventas  |  ${running_total:.2f}"
            )
        else:
            selected_date = self._selected_ventas_date()
            for row in stock_app.get_ventas_hoy(self.conn, cash_date=selected_date):
                running_total += float(row["total"])
                self.ventas_table.insert(
                    "", "end",
                    values=(
                        row["hora"],
                        row["codigo"],
                        row["nombre"],
                        row["cantidad"],
                        f"${row['precio_unit']:.2f}",
                        f"${row['total']:.2f}",
                        row["forma_pago"],
                    ),
                )
            self._ventas_total_var.set(f"Total del día: ${running_total:.2f}")
            self._update_ventas_summary()

    def _update_ventas_summary(self) -> None:
        selected_date = self._selected_ventas_date()
        summary = stock_app.get_daily_summary(self.conn, cash_date=selected_date)
        label_date = _date_to_ui(selected_date) if selected_date else _date_to_ui(date.today())
        is_today = (selected_date is None or selected_date == date.today())
        prefix = "Hoy" if is_today else label_date
        self._ventas_summary_var.set(
            f"{prefix}: {summary['count']} ventas  |  Total: ${summary['total']:.2f}"
        )

    def _show_cierre_caja(self) -> None:
        top = tk.Toplevel(self)
        top.title("Cierre de caja")
        top.geometry("460x520")
        top.resizable(False, False)
        top.transient(self)
        top.grab_set()

        frame = ttk.Frame(top, padding=20)
        frame.pack(fill="both", expand=True)

        if self._ventas_range_active:
            desde = self._ventas_desde_var.get()
            hasta = self._ventas_hasta_var.get()
            summary = stock_app.get_range_summary(
                self.conn,
                _date_from_ui(desde).isoformat(),
                _date_from_ui(hasta).isoformat(),
            )
            breakdown = summary["breakdown"]
            ttk.Label(frame, text="Cierre de rango", font=("Segoe UI", 14, "bold")).pack(anchor="w")
            ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=8)
            ttk.Label(frame, text=f"Desde: {desde}  —  Hasta: {hasta}").pack(anchor="w")
        else:
            selected_date = self._selected_ventas_date()
            summary = stock_app.get_daily_summary(self.conn, cash_date=selected_date)
            breakdown = stock_app.get_payment_breakdown(self.conn, cash_date=selected_date)
            ttk.Label(frame, text="Cierre de caja", font=("Segoe UI", 14, "bold")).pack(anchor="w")
            ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=8)
            ttk.Label(frame, text=f"Fecha: {summary['fecha']}").pack(anchor="w")

        ttk.Label(
            frame, text=f"Ventas realizadas: {summary['count']}"
        ).pack(anchor="w", pady=(4, 0))
        ttk.Label(
            frame,
            text=f"Total recaudado: ${summary['total']:.2f}",
            font=("Segoe UI", 13, "bold"),
        ).pack(anchor="w", pady=(6, 0))

        if summary.get("total_costo", 0) > 0:
            ttk.Label(
                frame, text=f"Costo total: ${summary['total_costo']:.2f}"
            ).pack(anchor="w", pady=(2, 0))
            ganancia = summary.get("ganancia_bruta", 0)
            ttk.Label(
                frame,
                text=f"Ganancia bruta: ${ganancia:.2f}",
                font=("Segoe UI", 11, "bold"),
                foreground="#2a7a2a" if ganancia >= 0 else "#cc0000",
            ).pack(anchor="w", pady=(2, 0))

        if breakdown:
            ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=8)
            ttk.Label(frame, text="Por forma de pago:", font=("Segoe UI", 10, "bold")).pack(anchor="w")
            for row in breakdown:
                ttk.Label(
                    frame,
                    text=f"  • {row['forma_pago']}: {row['cantidad']} venta(s) — ${row['total']:.2f}",
                ).pack(anchor="w", pady=(2, 0))

        if summary.get("top_products"):
            ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=8)
            ttk.Label(
                frame, text="Productos más vendidos:", font=("Segoe UI", 10, "bold")
            ).pack(anchor="w")
            for p in summary["top_products"]:
                ttk.Label(
                    frame,
                    text=f"  • {p['nombre'][:32]} — {p['total_cant']} unid. — ${p['total_monto']:.2f}",
                ).pack(anchor="w", pady=(2, 0))

        ttk.Separator(frame, orient="horizontal").pack(fill="x", pady=8)
        ttk.Button(frame, text="Cerrar", command=top.destroy).pack(anchor="e")
        self._center_dialog(top)

    def _export_ventas_csv(self) -> None:
        filepath = filedialog.asksaveasfilename(
            defaultextension=".csv",
            initialfile=f"ventas_{date.today().isoformat()}.csv",
            filetypes=[("CSV", "*.csv"), ("Todos los archivos", "*.*")],
        )
        if not filepath:
            return
        n = stock_app.export_ventas_csv(self.conn, Path(filepath))
        self._set_status(f"✓ Exportadas {n} ventas a {Path(filepath).name}")

    def _export_products_csv(self) -> None:
        filepath = filedialog.asksaveasfilename(
            defaultextension=".csv",
            initialfile="productos.csv",
            filetypes=[("CSV", "*.csv"), ("Todos los archivos", "*.*")],
        )
        if not filepath:
            return
        n = stock_app.export_products_csv(self.conn, Path(filepath))
        self._set_status(f"✓ Exportados {n} productos a {Path(filepath).name}")

    # ── Tab 5: reportes ───────────────────────────────────────────────────────

    def _build_tab_reportes(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=1)

        ttk.Label(
            parent, text="Generador de reportes PDF",
            style="Title.TLabel",
        ).grid(row=0, column=0, sticky="w", pady=(0, 14))

        sec_frame = ttk.LabelFrame(parent, text="Secciones a incluir", padding=14)
        sec_frame.grid(row=1, column=0, sticky="ew")
        sec_frame.columnconfigure(1, weight=1)

        # ── Productos ─────────────────────────────────────────────────────────
        ttk.Checkbutton(
            sec_frame, text="Todos los productos",
            variable=self._rep_productos_var,
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 10))

        # ── Ventas ────────────────────────────────────────────────────────────
        ventas_cb = ttk.Checkbutton(
            sec_frame, text="Ventas",
            variable=self._rep_ventas_var,
            command=self._rep_toggle_ventas_dates,
        )
        ventas_cb.grid(row=1, column=0, sticky="w")

        dates_frame = ttk.Frame(sec_frame)
        dates_frame.grid(row=1, column=1, sticky="w", padx=(16, 0))
        ttk.Label(dates_frame, text="Desde:").grid(row=0, column=0, padx=(0, 4))
        self._rep_desde_entry = ttk.Entry(dates_frame, textvariable=self._rep_desde_var, width=12)
        self._rep_desde_entry.grid(row=0, column=1, padx=(0, 12))
        ttk.Label(dates_frame, text="Hasta:").grid(row=0, column=2, padx=(0, 4))
        self._rep_hasta_entry = ttk.Entry(dates_frame, textvariable=self._rep_hasta_var, width=12)
        self._rep_hasta_entry.grid(row=0, column=3)

        hint_lbl = ttk.Label(
            sec_frame, text="Formato DD-MM-AAAA. Dejá vacío para usar solo la fecha de hoy.",
            foreground="gray", font=("Segoe UI", 8),
        )
        hint_lbl.grid(row=2, column=1, sticky="w", padx=(16, 0), pady=(2, 10))
        self._muted_labels.append(hint_lbl)

        # ── Pendientes ────────────────────────────────────────────────────────
        ttk.Checkbutton(
            sec_frame, text="Pendientes",
            variable=self._rep_pendientes_var,
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(0, 10))

        # ── Stock bajo ────────────────────────────────────────────────────────
        ttk.Checkbutton(
            sec_frame, text="Stock bajo",
            variable=self._rep_stock_bajo_var,
        ).grid(row=4, column=0, columnspan=2, sticky="w")

        # ── Botón generar ─────────────────────────────────────────────────────
        btn_row = ttk.Frame(parent)
        btn_row.grid(row=2, column=0, sticky="e", pady=(18, 0))
        ttk.Button(
            btn_row, text="  Generar PDF  ", command=self._generar_reporte_pdf,
        ).pack()

    def _rep_toggle_ventas_dates(self) -> None:
        state = "normal" if self._rep_ventas_var.get() else "disabled"
        self._rep_desde_entry.configure(state=state)
        self._rep_hasta_entry.configure(state=state)

    def _generar_reporte_pdf(self) -> None:
        if not any([
            self._rep_productos_var.get(),
            self._rep_ventas_var.get(),
            self._rep_pendientes_var.get(),
            self._rep_stock_bajo_var.get(),
        ]):
            messagebox.showwarning("Aviso", "Seleccioná al menos una sección.")
            return

        try:
            from fpdf import FPDF  # type: ignore
        except ImportError:
            messagebox.showerror("Error", "Falta la librería fpdf2.\nEjecutá: pip install fpdf2")
            return

        filepath = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            initialfile=f"reporte_{date.today().isoformat()}.pdf",
            filetypes=[("PDF", "*.pdf"), ("Todos los archivos", "*.*")],
        )
        if not filepath:
            return

        moneda = self._config.get("moneda", "$")
        negocio = self._config.get("nombre_negocio", "Reporte")

        pdf = FPDF()
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        # ── Encabezado ────────────────────────────────────────────────────────
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, negocio, ln=True, align="C")
        pdf.set_font("Helvetica", "", 9)
        pdf.cell(0, 6, f"Generado: {datetime.now().strftime('%Y-%m-%d %H:%M')}", ln=True, align="C")
        pdf.ln(8)

        # ── Sección: todos los productos ──────────────────────────────────────
        if self._rep_productos_var.get():
            productos = stock_app.list_products(self.conn)
            pdf.set_font("Helvetica", "B", 12)
            pdf.set_fill_color(220, 220, 220)
            pdf.cell(0, 8, f"Productos ({len(productos)})", ln=True, fill=True)
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", 8)
            for h, w in [("Código", 25), ("Nombre", 65), ("Precio", 25),
                         ("Costo", 25), ("Stock", 18), ("Mín.", 18), ("Proveedor", 14)]:
                pdf.cell(w, 7, h, border=1, align="C")
            pdf.ln()
            pdf.set_font("Helvetica", "", 8)
            for p in productos:
                precio = float(p["precio"])
                costo = float(p["precio_costo"])
                pdf.cell(25, 6, str(p["codigo"]), border=1)
                pdf.cell(65, 6, str(p["nombre"])[:38], border=1)
                pdf.cell(25, 6, f"{moneda}{precio:.2f}", border=1, align="R")
                pdf.cell(25, 6, f"{moneda}{costo:.2f}" if costo > 0 else "-", border=1, align="R")
                pdf.cell(18, 6, str(p["stock"]), border=1, align="C")
                pdf.cell(18, 6, str(p["stock_minimo"]), border=1, align="C")
                pdf.cell(14, 6, str(p["proveedor"] or "-")[:8], border=1)
                pdf.ln()
            pdf.ln(6)

        # ── Sección: ventas ───────────────────────────────────────────────────
        if self._rep_ventas_var.get():
            desde_raw = self._rep_desde_var.get().strip()
            hasta_raw = self._rep_hasta_var.get().strip()
            hoy = date.today().isoformat()
            try:
                desde = _date_from_ui(desde_raw).isoformat() if desde_raw else hoy
                hasta = _date_from_ui(hasta_raw).isoformat() if hasta_raw else hoy
            except ValueError:
                messagebox.showerror("Error", "Fechas inválidas en la sección Ventas.\nUsá el formato DD-MM-AAAA.")
                return

            ventas = stock_app.get_ventas_rango(self.conn, desde, hasta)
            resumen = stock_app.get_range_summary(self.conn, desde, hasta)

            titulo_ventas = (
                f"Ventas del {desde}"
                if desde == hasta
                else f"Ventas del {desde} al {hasta}"
            )
            pdf.set_font("Helvetica", "B", 12)
            pdf.set_fill_color(220, 220, 220)
            pdf.cell(0, 8, titulo_ventas, ln=True, fill=True)
            pdf.ln(2)

            # Resumen financiero
            pdf.set_font("Helvetica", "B", 9)
            pdf.cell(60, 6, f"Total: {moneda}{resumen['total']:.2f}", border=0)
            pdf.cell(60, 6, f"Transacciones: {resumen['count']}", border=0)
            ganancia = resumen.get("ganancia_bruta", 0)
            pdf.cell(0, 6, f"Ganancia bruta: {moneda}{ganancia:.2f}", ln=True, border=0)

            # Desglose por forma de pago
            if resumen["breakdown"]:
                pdf.set_font("Helvetica", "", 8)
                for row in resumen["breakdown"]:
                    pdf.cell(0, 5,
                             f"  {row['forma_pago']}: {row['cantidad']} ventas — {moneda}{float(row['total']):.2f}",
                             ln=True)
            pdf.ln(3)

            # Tabla de ventas
            pdf.set_font("Helvetica", "B", 8)
            for h, w in [("Fecha", 22), ("Hora", 18), ("Nombre", 70),
                         ("Cant.", 14), ("P.Unit.", 24), ("Total", 24), ("Pago", 18)]:
                pdf.cell(w, 7, h, border=1, align="C")
            pdf.ln()
            pdf.set_font("Helvetica", "", 8)
            for v in ventas:
                pdf.cell(22, 6, str(v["fecha"]), border=1)
                pdf.cell(18, 6, str(v["hora"])[:5], border=1, align="C")
                pdf.cell(70, 6, str(v["nombre"])[:42], border=1)
                pdf.cell(14, 6, str(v["cantidad"]), border=1, align="C")
                pdf.cell(24, 6, f"{moneda}{float(v['precio_unit']):.2f}", border=1, align="R")
                pdf.cell(24, 6, f"{moneda}{float(v['total']):.2f}", border=1, align="R")
                pdf.cell(18, 6, str(v["forma_pago"])[:10], border=1)
                pdf.ln()

            # Top 5 productos
            if resumen["top_products"]:
                pdf.ln(3)
                pdf.set_font("Helvetica", "B", 9)
                pdf.cell(0, 6, "Top 5 productos más vendidos:", ln=True)
                pdf.set_font("Helvetica", "", 8)
                for i, row in enumerate(resumen["top_products"], 1):
                    pdf.cell(0, 5,
                             f"  {i}. {row['nombre']} — {row['total_cant']} unid. — {moneda}{float(row['total_monto']):.2f}",
                             ln=True)
            pdf.ln(6)

        # ── Sección: pendientes ───────────────────────────────────────────────
        if self._rep_pendientes_var.get():
            pendientes = stock_app.list_pending(self.conn)
            pdf.set_font("Helvetica", "B", 12)
            pdf.set_fill_color(220, 220, 220)
            pdf.cell(0, 8, f"Pendientes ({len(pendientes)})", ln=True, fill=True)
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", 8)
            for h, w in [("Estado", 30), ("Descripción", 120), ("Creado", 40)]:
                pdf.cell(w, 7, h, border=1, align="C")
            pdf.ln()
            pdf.set_font("Helvetica", "", 8)
            for p in pendientes:
                pdf.cell(30, 6, str(p["estado"]), border=1, align="C")
                pdf.cell(120, 6, str(p["descripcion"])[:65], border=1)
                pdf.cell(40, 6, str(p["creado_en"])[:16], border=1, align="C")
                pdf.ln()
            pdf.ln(6)

        # ── Sección: stock bajo ───────────────────────────────────────────────
        if self._rep_stock_bajo_var.get():
            bajo = stock_app.low_stock_products(self.conn)
            pdf.set_font("Helvetica", "B", 12)
            pdf.set_fill_color(220, 220, 220)
            pdf.cell(0, 8, f"Stock bajo ({len(bajo)} productos)", ln=True, fill=True)
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", 8)
            for h, w in [("Código", 30), ("Nombre", 100), ("Stock actual", 30), ("Stock mín.", 30)]:
                pdf.cell(w, 7, h, border=1, align="C")
            pdf.ln()
            pdf.set_font("Helvetica", "", 8)
            for p in bajo:
                pdf.cell(30, 6, str(p["codigo"]), border=1)
                pdf.cell(100, 6, str(p["nombre"])[:55], border=1)
                pdf.cell(30, 6, str(p["stock"]), border=1, align="C")
                pdf.cell(30, 6, str(p["stock_minimo"]), border=1, align="C")
                pdf.ln()

        pdf.output(filepath)
        self._set_status(f"✓ PDF exportado: {Path(filepath).name}")

    # =========================================================================
    # Undo
    # =========================================================================

    def _push_undo(self, action: dict[str, Any]) -> None:
        self._undo_stack.append(action)
        if len(self._undo_stack) > _UNDO_MAX:
            self._undo_stack.pop(0)
        self._redo_stack.clear()
        self._update_undo_redo_btns()

    def _update_undo_redo_btns(self) -> None:
        if self._undo_stack:
            self._undo_btn.configure(
                state="normal",
                text=f"↩ Deshacer: {self._undo_stack[-1]['description'][:35]}",
            )
        else:
            self._undo_btn.configure(state="disabled", text="↩ Deshacer (Ctrl+Z)")
        if self._redo_stack:
            self._redo_btn.configure(
                state="normal",
                text=f"↪ Rehacer: {self._redo_stack[-1]['description'][:35]}",
            )
        else:
            self._redo_btn.configure(state="disabled", text="↪ Rehacer (Ctrl+Y)")

    def _undo(self) -> None:
        if not self._undo_stack:
            return
        action = self._undo_stack.pop()
        cart_action_handled = False
        redo_entry: dict[str, Any] | None = None

        try:
            if action["type"] == "delete_product":
                stock_app._restore_product(self.conn, action["data"])
                redo_entry = {
                    "type": "redo_delete",
                    "codigo": action["data"]["codigo"],
                    "nombre": action["data"]["nombre"],
                    "description": f"eliminar '{action['data']['nombre']}'",
                }

            elif action["type"] == "sale":
                sale_id = action.get("sale_id")
                sale_data: dict | None = None
                if sale_id is not None:
                    try:
                        row = stock_app.get_sale(self.conn, sale_id)
                        sale_data = dict(row)
                    except stock_app.StockError:
                        pass
                stock_app.reverse_sale(
                    self.conn,
                    action["codigo"],
                    action["cantidad"],
                    action["total"],
                    action["sale_date"],
                    sale_id=sale_id,
                )
                if sale_data:
                    redo_entry = {
                        "type": "redo_sale",
                        "sale_data": sale_data,
                        "description": action["description"],
                    }

            elif action["type"] == "price_increase":
                stock_app.restore_prices(self.conn, action["changes"])
                redo_entry = {
                    "type": "redo_price_increase",
                    "changes": action["changes"],
                    "description": action["description"],
                }

            elif action["type"] == "cart_change":
                idx = self._find_cart_item_index(action["codigo"])
                previous_quantity = int(action.get("previous_quantity", 0))
                new_quantity = int(action.get("new_quantity", 0))
                if previous_quantity <= 0:
                    if idx != -1:
                        self._cart.pop(idx)
                elif idx != -1:
                    self._cart[idx]["cantidad"] = previous_quantity
                    self._cart[idx]["subtotal"] = previous_quantity * self._cart[idx]["precio_unit"]
                cart_action_handled = True
                redo_entry = {
                    "type": "cart_change",
                    "codigo": action["codigo"],
                    "previous_quantity": new_quantity,
                    "new_quantity": previous_quantity,
                    "previous_item": action.get("previous_item"),
                    "description": f"rehacer {action['description']}",
                }

            elif action["type"] == "cart_remove":
                item = dict(action["item"])
                index = int(action.get("index", len(self._cart)))
                if index < 0 or index > len(self._cart):
                    index = len(self._cart)
                self._cart.insert(index, item)
                cart_action_handled = True
                redo_entry = {
                    "type": "redo_cart_remove",
                    "codigo": item["codigo"],
                    "description": f"rehacer quitar '{item['codigo']}'",
                }

            elif action["type"] == "cart_clear":
                self._cart = [dict(item) for item in action.get("items", [])]
                cart_action_handled = True
                redo_entry = {
                    "type": "redo_cart_clear",
                    "description": "rehacer vaciar carrito",
                }

        except Exception as exc:
            messagebox.showerror("Error al deshacer", str(exc))
            return

        if redo_entry:
            self._redo_stack.append(redo_entry)

        if cart_action_handled:
            self._refresh_cart_display()

        self._update_undo_redo_btns()
        self.refresh_all()
        self._set_status(f"↩ Revertido: {action.get('description', '')}")

    def _redo(self) -> None:
        if not self._redo_stack:
            return
        action = self._redo_stack.pop()
        cart_action_handled = False
        undo_entry: dict[str, Any] | None = None

        try:
            if action["type"] == "redo_delete":
                codigo = action["codigo"]
                try:
                    product = stock_app.get_product(self.conn, codigo)
                    undo_data = {k: product[k] for k in product.keys()}
                    stock_app.delete_product(self.conn, codigo)
                    undo_entry = {
                        "type": "delete_product",
                        "data": undo_data,
                        "description": f"eliminacion de '{undo_data['nombre']}'",
                    }
                except stock_app.ProductNotFoundError as exc:
                    messagebox.showerror("Error al rehacer", str(exc))
                    self._redo_stack.clear()
                    self._update_undo_redo_btns()
                    return

            elif action["type"] == "redo_sale":
                sale_data = action["sale_data"]
                stock_app.restore_sale(self.conn, sale_data)
                undo_entry = {
                    "type": "sale",
                    "codigo": sale_data["codigo"],
                    "cantidad": sale_data["cantidad"],
                    "total": sale_data["total"],
                    "sale_id": sale_data["id"],
                    "sale_date": sale_data["fecha"],
                    "description": action["description"],
                }

            elif action["type"] == "redo_price_increase":
                stock_app.re_apply_prices(self.conn, action["changes"])
                undo_entry = {
                    "type": "price_increase",
                    "changes": action["changes"],
                    "description": action["description"],
                }

            elif action["type"] == "cart_change":
                codigo = action["codigo"]
                new_quantity = int(action.get("new_quantity", 0))
                previous_quantity = int(action.get("previous_quantity", 0))
                idx = self._find_cart_item_index(codigo)
                if previous_quantity <= 0:
                    if idx != -1:
                        self._cart.pop(idx)
                elif idx == -1:
                    prev_item = action.get("previous_item")
                    if prev_item:
                        self._cart.append(dict(prev_item))
                else:
                    self._cart[idx]["cantidad"] = previous_quantity
                    self._cart[idx]["subtotal"] = previous_quantity * self._cart[idx]["precio_unit"]
                cart_action_handled = True
                undo_entry = {
                    "type": "cart_change",
                    "codigo": codigo,
                    "previous_quantity": new_quantity,
                    "new_quantity": previous_quantity,
                    "description": action["description"],
                }

            elif action["type"] == "redo_cart_remove":
                codigo = action["codigo"]
                idx = self._find_cart_item_index(codigo)
                if idx != -1:
                    item = dict(self._cart.pop(idx))
                    undo_entry = {
                        "type": "cart_remove",
                        "item": item,
                        "index": idx,
                        "description": f"quitar carrito '{codigo}'",
                    }
                cart_action_handled = True

            elif action["type"] == "redo_cart_clear":
                if self._cart:
                    undo_entry = {
                        "type": "cart_clear",
                        "items": [dict(item) for item in self._cart],
                        "description": f"vaciar carrito ({len(self._cart)})",
                    }
                self._cart.clear()
                cart_action_handled = True

        except Exception as exc:
            messagebox.showerror("Error al rehacer", str(exc))
            return

        if undo_entry:
            self._undo_stack.append(undo_entry)
            if len(self._undo_stack) > _UNDO_MAX:
                self._undo_stack.pop(0)

        if cart_action_handled:
            self._refresh_cart_display()

        self._update_undo_redo_btns()
        self.refresh_all()
        self._set_status(f"↪ Rehecho: {action.get('description', '')}")

    # =========================================================================
    # Form helpers
    # =========================================================================

    def _clear_form(self) -> None:
        self.codigo_var.set("")
        self.nombre_var.set("")
        self.precio_var.set("")
        self.precio_costo_var.set("")
        self.stock_var.set("")
        self.stock_minimo_var.set("")
        self.proveedor_var.set("")
        self.notas_var.set("")
        if hasattr(self, "_suppliers_table"):
            clear_table(self._suppliers_table)
            self._set_supplier_controls_state("disabled")

    def _show_ajuste_stock(self) -> None:
        selected = self.products_table.selection()
        if not selected:
            messagebox.showerror("Seleccione un producto", "Elija un producto de la lista.")
            return
        codigo = self.products_table.item(selected[0], "values")[0]
        try:
            product = stock_app.get_product(self.conn, codigo)
        except stock_app.StockError as exc:
            messagebox.showerror("Error", str(exc))
            return

        dialog = tk.Toplevel(self)
        dialog.title("Ajustar stock")
        dialog.resizable(False, False)
        dialog.transient(self)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=20)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Producto:").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 4))
        ttk.Label(frame, text=product["nombre"], style="Bold.TLabel").grid(
            row=0, column=1, sticky="w", pady=(0, 4)
        )
        ttk.Label(frame, text="Código:").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=(0, 4))
        ttk.Label(frame, text=product["codigo"]).grid(row=1, column=1, sticky="w", pady=(0, 4))
        ttk.Label(frame, text="Stock actual:").grid(row=2, column=0, sticky="w", padx=(0, 8), pady=(0, 10))
        ttk.Label(frame, text=str(product["stock"]), style="Bold.TLabel").grid(
            row=2, column=1, sticky="w", pady=(0, 10)
        )

        ttk.Separator(frame, orient="horizontal").grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(0, 10)
        )
        ttk.Label(frame, text="Nuevo stock:").grid(row=4, column=0, sticky="w", padx=(0, 8), pady=(0, 10))
        nuevo_var = tk.StringVar(value=str(product["stock"]))
        nuevo_entry = ttk.Entry(frame, textvariable=nuevo_var, width=12)
        nuevo_entry.grid(row=4, column=1, sticky="w", pady=(0, 10))

        btn_row = ttk.Frame(frame)
        btn_row.grid(row=5, column=0, columnspan=2, sticky="e")

        def _guardar() -> None:
            try:
                nuevo = parse_int(nuevo_var.get(), "stock")
            except ValueError as exc:
                messagebox.showerror("Valor inválido", str(exc), parent=dialog)
                return
            try:
                anterior = stock_app.adjust_stock(self.conn, codigo, nuevo)
            except stock_app.StockError as exc:
                messagebox.showerror("Error", str(exc), parent=dialog)
                return
            dialog.destroy()
            self.refresh_all()
            self._set_status(
                f"✓ Stock de '{product['nombre']}' ajustado: {anterior} → {nuevo}"
            )

        ttk.Button(btn_row, text="Guardar", command=_guardar).pack(side="right", padx=(8, 0))
        ttk.Button(btn_row, text="Cancelar", command=dialog.destroy).pack(side="right")
        self._center_dialog(dialog)
        nuevo_entry.focus_set()
        nuevo_entry.selection_range(0, tk.END)

    def _ventas_filtrar_rango(self) -> None:
        desde = self._ventas_desde_var.get().strip()
        hasta = self._ventas_hasta_var.get().strip()
        if not desde or not hasta:
            messagebox.showerror(
                "Fechas requeridas",
                "Ingresá ambas fechas en formato DD-MM-AAAA.",
            )
            return
        try:
            d_desde = _date_from_ui(desde)
            d_hasta = _date_from_ui(hasta)
        except ValueError:
            messagebox.showerror("Formato inválido", "Usá el formato DD-MM-AAAA.")
            return
        if d_desde > d_hasta:
            messagebox.showerror("Rango inválido", "La fecha 'Desde' debe ser anterior a 'Hasta'.")
            return
        self._ventas_range_active = True
        for btn in (self._nav_prev_btn, self._nav_next_btn, self._nav_today_btn):
            btn.configure(state="disabled")
        self._nav_date_entry.configure(state="disabled")
        self.refresh_ventas()

    def _ventas_limpiar_rango(self) -> None:
        self._ventas_range_active = False
        for btn in (self._nav_prev_btn, self._nav_next_btn, self._nav_today_btn):
            btn.configure(state="normal")
        self._nav_date_entry.configure(state="normal")
        self._ventas_desde_var.set("")
        self._ventas_hasta_var.set("")
        self.refresh_ventas()

    # =========================================================================
    # Create / edit product
    # =========================================================================

    def save_product(self) -> None:
        if self._edit_mode:
            self._do_update_product()
        else:
            self._do_create_product()

    def _do_create_product(self) -> None:
        try:
            codigo = self.codigo_var.get().strip()
            nombre = self.nombre_var.get().strip()
            precio = parse_float(self.precio_var.get(), "precio")
            precio_costo = parse_float(self.precio_costo_var.get() or "0", "precio costo")
            stock = parse_int(self.stock_var.get(), "stock")
            stock_minimo = parse_int(self.stock_minimo_var.get(), "stock minimo")
            proveedor = self.proveedor_var.get().strip()
            notas = self.notas_var.get().strip()
            if not codigo or not nombre:
                raise ValueError("Codigo y nombre son obligatorios.")
            stock_app.add_product(
                self.conn, codigo, nombre, precio, stock, stock_minimo,
                proveedor, precio_costo, notas,
            )
        except (ValueError, stock_app.StockError) as exc:
            messagebox.showerror("No se pudo guardar", str(exc))
            return

        saved_name = nombre
        self._clear_form()
        self.refresh_all()
        self._set_status(f"✓ Producto '{saved_name}' registrado.")

    def _do_update_product(self) -> None:
        try:
            nombre = self.nombre_var.get().strip()
            precio = parse_float(self.precio_var.get(), "precio")
            precio_costo = parse_float(self.precio_costo_var.get() or "0", "precio costo")
            stock = parse_int(self.stock_var.get(), "stock")
            stock_minimo = parse_int(self.stock_minimo_var.get(), "stock minimo")
            proveedor = self.proveedor_var.get().strip()
            notas = self.notas_var.get().strip()
            if not nombre:
                raise ValueError("El nombre es obligatorio.")
            stock_app.update_product(
                self.conn,
                self._edit_codigo,  # type: ignore[arg-type]
                nombre, precio, stock, stock_minimo,
                proveedor, precio_costo, notas,
            )
        except (ValueError, stock_app.StockError) as exc:
            messagebox.showerror("No se pudo actualizar", str(exc))
            return

        saved_name = nombre
        self.cancel_edit()
        self.refresh_all()
        self._set_status(f"✓ Producto '{saved_name}' actualizado.")

    def enter_edit_mode(self, product: sqlite3.Row) -> None:
        if not self._form_visible:
            self._toggle_form()
        self._edit_mode = True
        self._edit_codigo = product["codigo"]
        self.codigo_var.set(product["codigo"])
        self.nombre_var.set(product["nombre"])
        self.precio_var.set(str(product["precio"]))
        self.precio_costo_var.set(str(product["precio_costo"]))
        self.stock_var.set(str(product["stock"]))
        self.stock_minimo_var.set(str(product["stock_minimo"]))
        self.proveedor_var.set(product["proveedor"] or "")
        self.notas_var.set(product["notas"] or "")
        self._codigo_entry.configure(state="readonly")
        self._save_btn.configure(text="Actualizar")
        self._product_form_frame.configure(text="Editar producto")
        self._cancel_edit_btn.grid()
        self._refresh_product_suppliers()
        self._notebook.select(0)

    def cancel_edit(self) -> None:
        self._edit_mode = False
        self._edit_codigo = None
        self._clear_form()
        self._codigo_entry.configure(state="normal")
        self._save_btn.configure(text="Guardar")
        self._product_form_frame.configure(text="Alta de producto")
        self._cancel_edit_btn.grid_remove()

    def _start_add_product_with_code(self, codigo: str) -> None:
        self._notebook.select(0)
        if self._edit_mode:
            self.cancel_edit()
        if not self._form_visible:
            self._toggle_form()
        self.codigo_var.set(codigo)
        self._nombre_entry.focus_set()

    def load_selected_for_edit(self) -> None:
        selected = self.products_table.selection()
        if not selected:
            messagebox.showerror("Seleccione un producto", "Elija un producto de la lista.")
            return
        codigo = self.products_table.item(selected[0], "values")[0]
        try:
            product = stock_app.get_product(self.conn, codigo)
        except stock_app.StockError as exc:
            messagebox.showerror("Error", str(exc))
            return
        self.enter_edit_mode(product)

    def delete_selected_product(self) -> None:
        selected = self.products_table.selection()
        if not selected:
            messagebox.showerror("Seleccione un producto", "Elija un producto de la lista.")
            return
        codigo = self.products_table.item(selected[0], "values")[0]
        if not messagebox.askyesno(
            "Confirmar eliminacion",
            f"Eliminar el producto '{codigo}'?\nPodras deshacerlo con Ctrl+Z.",
        ):
            return
        try:
            product = stock_app.get_product(self.conn, codigo)
            undo_data = {k: product[k] for k in product.keys()}
            stock_app.delete_product(self.conn, codigo)
        except stock_app.StockError as exc:
            messagebox.showerror("Error", str(exc))
            return

        self._push_undo({
            "type": "delete_product",
            "data": undo_data,
            "description": f"eliminacion de '{undo_data['nombre']}'",
        })
        if self._edit_mode and self._edit_codigo == codigo:
            self.cancel_edit()
        self.refresh_all()

    # =========================================================================
    # Sale
    # =========================================================================

    def register_sale(self) -> None:
        codigo = self.venta_codigo_var.get().strip()
        forma_pago = self._venta_forma_pago_var.get() or "Efectivo"
        try:
            cantidad = parse_int(self.venta_cantidad_var.get(), "cantidad")
            sale_date = date.today()
            total, sale_id = stock_app.register_sale(
                self.conn, codigo, cantidad, sale_date=sale_date, forma_pago=forma_pago
            )
        except stock_app.ProductNotFoundError:
            if messagebox.askyesno(
                "Producto no encontrado",
                f"No existe ningún producto con código '{codigo}'.\n\n¿Querés agregarlo ahora?",
            ):
                self._start_add_product_with_code(codigo)
            return
        except stock_app.InsufficientStockError as exc:
            allow = messagebox.askyesno(
                "Stock insuficiente",
                f"{exc}\n\n¿Autorizar venta con stock negativo?",
            )
            if not allow:
                return
            try:
                total, sale_id = stock_app.register_sale(
                    self.conn, codigo, cantidad, allow_negative=True,
                    sale_date=sale_date, forma_pago=forma_pago,
                )
            except (ValueError, stock_app.StockError) as retry_exc:
                logger.exception("Error en venta con stock negativo")
                messagebox.showerror("No se pudo registrar", str(retry_exc))
                return
        except (ValueError, stock_app.StockError) as exc:
            logger.exception("Error registrando venta")
            messagebox.showerror("No se pudo registrar", str(exc))
            return

        self._push_undo({
            "type": "sale",
            "codigo": codigo,
            "cantidad": cantidad,
            "total": total,
            "sale_id": sale_id,
            "sale_date": sale_date.isoformat(),
            "description": f"venta {cantidad}x '{codigo}' (${total:.2f})",
        })
        self.venta_codigo_var.set("")
        self.venta_cantidad_var.set("1")
        self.refresh_all()
        self._set_status(f"✓ Venta registrada [{forma_pago}] - Total: ${total:.2f}")
        self._venta_codigo_entry.focus_set()

    # =========================================================================
    # Pending
    # =========================================================================

    def add_pending(self) -> None:
        descripcion = self.pendiente_var.get().strip()
        if not descripcion:
            messagebox.showerror("Dato obligatorio", "Ingrese una descripcion.")
            return
        stock_app.add_pending(self.conn, descripcion)
        self.pendiente_var.set("")
        self.refresh_pending()
        self._set_status("✓ Pendiente agregado.")

    def complete_selected_pending(self) -> None:
        selected = self.pending_table.selection()
        if not selected:
            messagebox.showerror("Seleccione un pendiente", "Elija un item de la lista.")
            return
        pending_id = int(selected[0])
        stock_app.complete_pending(self.conn, pending_id)
        self.refresh_pending()

    def delete_selected_pending(self) -> None:
        selected = self.pending_table.selection()
        if not selected:
            messagebox.showerror("Seleccione un pendiente", "Elija un item de la lista.")
            return
        pending_id = int(selected[0])
        if not messagebox.askyesno("Confirmar", "¿Eliminar este pendiente definitivamente?"):
            return
        stock_app.delete_pending(self.conn, pending_id)
        self.refresh_pending()

    # =========================================================================
    # Refresh
    # =========================================================================

    def refresh_all(self) -> None:
        self.refresh_products()
        self.refresh_alerts()
        self.refresh_pending()
        self.caja_var.set(f"Caja de hoy: ${stock_app.daily_cash(self.conn):.2f}")
        self._update_ventas_summary()
        self._refresh_dashboard()
        idx = self._notebook.index("current")
        if idx == 2:
            self.refresh_price_table()
        elif idx == 3:
            self.refresh_ventas()

    def refresh_products(self) -> None:
        clear_table(self.products_table)
        query = self.search_var.get().strip()

        rows_data = []
        for row in stock_app.search_products(self.conn, query):
            precio = float(row["precio"])
            costo = float(row["precio_costo"])
            margen = _calc_margen(precio, costo)
            if row["stock"] <= 0:
                tag = "stock_critical"
            elif row["stock"] < row["stock_minimo"]:
                tag = "stock_warning"
            else:
                tag = ""
            rows_data.append((
                row["codigo"], row["nombre"], precio, margen,
                row["stock"], row["stock_minimo"],
                row["proveedor"] or "-",
                tag,
            ))

        # apply column sort
        col_idx = {"codigo": 0, "nombre": 1, "precio": 2, "margen": 3,
                   "stock": 4, "minimo": 5, "proveedor": 6}
        label_map = {"codigo": "Codigo", "nombre": "Nombre", "precio": "Precio",
                     "margen": "Margen", "stock": "Stock", "minimo": "Stock mín.",
                     "proveedor": "Proveedor"}
        if self._sort_col in col_idx:
            idx = col_idx[self._sort_col]
            def _key(r: tuple) -> Any:
                v = r[idx]
                if isinstance(v, str):
                    try:
                        return float(v.strip("$%").replace(",", "."))
                    except ValueError:
                        return v.lower()
                return v
            rows_data.sort(key=_key, reverse=not self._sort_asc)
            for c in col_idx:
                arrow = (" ▲" if self._sort_asc else " ▼") if c == self._sort_col else ""
                self.products_table.heading(c, text=label_map[c] + arrow)

        for row in rows_data:
            self.products_table.insert(
                "", "end",
                values=row[:7],
                tags=(row[7],) if row[7] else (),
            )

    def refresh_alerts(self) -> None:
        clear_table(self.alerts_table)
        for row in stock_app.low_stock_products(self.conn):
            tag = "critical" if row["stock"] <= 0 else "warning"
            self.alerts_table.insert(
                "", "end",
                values=(row["codigo"], row["nombre"], row["stock"], row["stock_minimo"]),
                tags=(tag,),
            )

    def refresh_pending(self) -> None:
        clear_table(self.pending_table)
        for row in stock_app.list_pending(self.conn):
            self.pending_table.insert(
                "", "end",
                iid=str(row["id"]),
                values=(row["estado"], row["descripcion"]),
            )

    def refresh_price_table(self) -> None:
        clear_table(self.price_table)
        text_filter = self.price_search_var.get().strip()
        prov_filter = self.price_proveedor_var.get().strip().lower()
        for row in stock_app.search_products(self.conn, text_filter):
            if prov_filter and prov_filter not in (row["proveedor"] or "").lower():
                continue
            precio = float(row["precio"])
            costo = float(row["precio_costo"])
            self.price_table.insert(
                "", "end",
                values=(
                    row["codigo"],
                    row["nombre"],
                    f"${precio:.2f}",
                    f"${costo:.2f}" if costo > 0 else "-",
                    _calc_margen(precio, costo),
                    row["proveedor"] or "-",
                ),
            )
        self._on_price_selection_change()

    # =========================================================================
    # Tema / Modo oscuro
    # =========================================================================

    def _apply_theme(self) -> None:
        c = _COLORS_DARK if self._dark_mode else _COLORS_LIGHT
        style = ttk.Style(self)
        style.theme_use("clam")

        self.configure(bg=c["bg"])

        style.configure(".", background=c["bg"], foreground=c["fg"])
        style.configure("TFrame", background=c["bg"])
        style.configure("TLabelframe", background=c["bg"], bordercolor=c["fg_muted"])
        style.configure("TLabelframe.Label", background=c["bg"], foreground=c["fg"])
        style.configure("TLabel", background=c["bg"], foreground=c["fg"])
        style.configure("Title.TLabel", background=c["bg"], foreground=c["fg"],
                        font=("Segoe UI", 13, "bold"))
        style.configure("Bold.TLabel", background=c["bg"], foreground=c["fg"],
                        font=("Segoe UI", 10, "bold"))
        style.configure("TButton", background=c["btn_bg"], foreground=c["fg"], borderwidth=1)
        style.map("TButton",
                  background=[("active", c["sel_bg"]), ("pressed", c["sel_bg"])],
                  foreground=[("active", c["sel_fg"]), ("pressed", c["sel_fg"])])
        style.configure("TEntry", fieldbackground=c["bg_widget"], foreground=c["fg"],
                        insertcolor=c["fg"])
        style.configure("TCombobox", fieldbackground=c["bg_widget"], foreground=c["fg"])
        style.map("TCombobox",
                  fieldbackground=[("readonly", c["bg_widget"])],
                  foreground=[("readonly", c["fg"])],
                  selectbackground=[("readonly", c["sel_bg"])],
                  selectforeground=[("readonly", c["sel_fg"])])
        style.configure("Treeview", background=c["tree_bg"], foreground=c["fg"],
                        fieldbackground=c["tree_bg"])
        style.configure("Treeview.Heading", background=c["heading_bg"],
                        foreground=c["heading_fg"], relief="flat")
        style.map("Treeview",
                  background=[("selected", c["sel_bg"])],
                  foreground=[("selected", c["sel_fg"])])
        style.configure("TNotebook", background=c["bg"])
        style.configure("TNotebook.Tab", background=c["bg"], foreground=c["fg"],
                        padding=(8, 4))
        style.map("TNotebook.Tab",
                  background=[("selected", c["bg_widget"])],
                  foreground=[("selected", c["fg"])])
        style.configure("TScrollbar", background=c["bg"], troughcolor=c["bg_widget"],
                        arrowcolor=c["fg"])
        style.configure("TSeparator", background=c["fg_muted"])

        for lbl in self._muted_labels:
            try:
                lbl.configure(foreground=c["fg_muted"])
            except tk.TclError:
                pass

        for tree, tag in (
            (self.products_table, "stock_critical"),
            (self.products_table, "stock_warning"),
            (self.alerts_table, "critical"),
            (self.alerts_table, "warning"),
        ):
            if "critical" in tag:
                tree.tag_configure(tag, background=c["critical_bg"], foreground=c["critical_fg"])
            else:
                tree.tag_configure(tag, background=c["warning_bg"], foreground=c["warning_fg"])

    def _toggle_dark_mode(self) -> None:
        self._dark_mode = not self._dark_mode
        self._config["dark_mode"] = self._dark_mode
        stock_app.save_config(self._config)
        self._dark_mode_btn.configure(text="☀" if self._dark_mode else "🌙")
        self._apply_theme()

    def on_close(self) -> None:
        self.conn.close()
        self.destroy()

    # =========================================================================
    # Importar boleta CSV
    # =========================================================================

    def _import_boleta_csv(self) -> None:
        filepath = filedialog.askopenfilename(
            title="Seleccionar boleta CSV",
            filetypes=[("CSV", "*.csv"), ("Todos los archivos", "*.*")],
        )
        if not filepath:
            return

        try:
            result = stock_app.parse_and_classify_boleta(self.conn, Path(filepath))
        except stock_app.StockError as exc:
            messagebox.showerror("Error al leer CSV", str(exc))
            return

        total_valid = len(result.rows_new) + len(result.rows_clean) + len(result.rows_conflict)
        if total_valid == 0:
            self._set_status("Sin datos: el CSV no contiene filas válidas.")
            return

        # Apply rows without price conflict immediately
        n_new = len(result.rows_new)
        n_clean = len(result.rows_clean)
        errors: list[str] = []
        if result.rows_new or result.rows_clean:
            _, errors = stock_app.apply_boleta_batch(self.conn, result.rows_new + result.rows_clean)

        def _skipped_detail() -> str:
            if not result.skipped:
                return ""
            lines = [f"  Línea {ln}: {reason}" for ln, reason in result.skipped[:5]]
            if len(result.skipped) > 5:
                lines.append(f"  ... y {len(result.skipped) - 5} más")
            return "\n\nFilas ignoradas:\n" + "\n".join(lines)

        def _build_summary(with_conflicts: bool) -> tuple[str, bool]:
            """Devuelve (texto_resumen, tiene_detalles_largos)."""
            parts = []
            if n_new > 0:
                parts.append(f"{n_new} nuevo(s)")
            if n_clean > 0:
                parts.append(f"{n_clean} actualizado(s)")
            if with_conflicts and result.rows_conflict:
                parts.append(f"{len(result.rows_conflict)} conflicto(s) resuelto(s)")
            if errors:
                parts.append(f"{len(errors)} error(es)")
            text = ", ".join(parts) if parts else "Sin cambios"
            return text, bool(errors or result.skipped)

        def _on_conflicts_done() -> None:
            self.refresh_all()
            summary, has_detail = _build_summary(with_conflicts=True)
            if has_detail:
                parts_full = []
                if n_new > 0:
                    parts_full.append(f"{n_new} producto(s) nuevo(s)")
                if n_clean > 0:
                    parts_full.append(f"{n_clean} producto(s) con stock actualizado")
                if result.rows_conflict:
                    parts_full.append(f"{len(result.rows_conflict)} conflicto(s) resuelto(s)")
                if errors:
                    parts_full.append(f"{len(errors)} error(es)")
                messagebox.showinfo(
                    "Importación completada",
                    "\n".join(parts_full) + _skipped_detail(),
                )
            else:
                self._set_status(f"✓ Importación completada — {summary}")

        if not result.rows_conflict:
            self.refresh_all()
            summary, has_detail = _build_summary(with_conflicts=False)
            if has_detail:
                parts_full = []
                if n_new > 0:
                    parts_full.append(f"{n_new} producto(s) nuevo(s)")
                if n_clean > 0:
                    parts_full.append(f"{n_clean} producto(s) con stock actualizado")
                if errors:
                    parts_full.append(f"{len(errors)} error(es)")
                messagebox.showinfo(
                    "Importación completada",
                    "\n".join(parts_full) + _skipped_detail(),
                )
            else:
                self._set_status(f"✓ Importación completada — {summary}")
            return

        ConflictoDialog(self, result.rows_conflict, self.conn, _on_conflicts_done)


# =============================================================================
# Conflict resolution dialog
# =============================================================================

class ConflictoDialog:
    def __init__(
        self,
        parent: StockGui,
        conflicts: list,
        conn: sqlite3.Connection,
        on_complete: object,
    ) -> None:
        self._parent = parent
        self._conflicts = conflicts
        self._conn = conn
        self._on_complete = on_complete
        self._current_idx = 0

        self._dialog = tk.Toplevel(parent)
        self._dialog.title("Conflicto de precios")
        self._dialog.resizable(False, False)
        self._dialog.transient(parent)
        self._dialog.grab_set()
        self._dialog.protocol("WM_DELETE_WINDOW", lambda: self._dialog.destroy())

        self._title_var = tk.StringVar()
        self._nombre_var = tk.StringVar()
        self._proveedor_var = tk.StringVar()
        self._pc_actual_var = tk.StringVar()
        self._pc_nuevo_var = tk.StringVar()
        self._pv_actual_var = tk.StringVar()
        self._pv_nuevo_var = tk.StringVar()
        self._opcion_var = tk.StringVar(value="keep")
        self._pct_var = tk.StringVar()
        self._preview_var = tk.StringVar()

        self._build_layout()
        self._load_conflict(0)
        parent._center_dialog(self._dialog)

    def _build_layout(self) -> None:
        outer = ttk.Frame(self._dialog, padding=16)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, textvariable=self._title_var, style="Bold.TLabel").pack(
            anchor="w", pady=(0, 10)
        )

        info = ttk.LabelFrame(outer, text="Datos del producto", padding=10)
        info.pack(fill="x", pady=(0, 10))
        info.columnconfigure(1, weight=1)
        info.columnconfigure(3, weight=1)

        ttk.Label(info, text="Producto:").grid(row=0, column=0, sticky="w", padx=(0, 8))
        ttk.Label(info, textvariable=self._nombre_var, style="Bold.TLabel").grid(
            row=0, column=1, columnspan=3, sticky="w", pady=(0, 4)
        )
        ttk.Label(info, text="Proveedor boleta:").grid(row=1, column=0, sticky="w", padx=(0, 8))
        ttk.Label(info, textvariable=self._proveedor_var).grid(
            row=1, column=1, columnspan=3, sticky="w", pady=(0, 8)
        )
        ttk.Label(info, text="").grid(row=2, column=0)
        ttk.Label(info, text="Actual", style="Bold.TLabel").grid(row=2, column=1, sticky="w")
        ttk.Label(info, text="En la boleta", style="Bold.TLabel").grid(
            row=2, column=2, sticky="w", padx=(24, 0)
        )
        ttk.Label(info, text="Precio costo:").grid(row=3, column=0, sticky="w", padx=(0, 8))
        ttk.Label(info, textvariable=self._pc_actual_var).grid(row=3, column=1, sticky="w")
        ttk.Label(info, textvariable=self._pc_nuevo_var).grid(
            row=3, column=2, sticky="w", padx=(24, 0)
        )
        ttk.Label(info, text="Precio venta:").grid(
            row=4, column=0, sticky="w", padx=(0, 8), pady=(4, 0)
        )
        ttk.Label(info, textvariable=self._pv_actual_var).grid(
            row=4, column=1, sticky="w", pady=(4, 0)
        )
        ttk.Label(info, textvariable=self._pv_nuevo_var).grid(
            row=4, column=2, sticky="w", padx=(24, 0), pady=(4, 0)
        )

        opt = ttk.LabelFrame(outer, text="Decisión para este producto", padding=10)
        opt.pack(fill="x", pady=(0, 10))

        ttk.Radiobutton(
            opt, text="Mantener precio actual",
            variable=self._opcion_var, value="keep",
            command=self._on_opcion_changed,
        ).pack(anchor="w")
        ttk.Radiobutton(
            opt, text="Actualizar precio (usar precio de la boleta)",
            variable=self._opcion_var, value="update",
            command=self._on_opcion_changed,
        ).pack(anchor="w", pady=(4, 0))
        ttk.Radiobutton(
            opt, text="Modificar % del precio de venta:",
            variable=self._opcion_var, value="porcentaje",
            command=self._on_opcion_changed,
        ).pack(anchor="w", pady=(4, 0))

        pct_row = ttk.Frame(opt)
        pct_row.pack(fill="x", padx=(20, 0), pady=(2, 0))
        ttk.Label(pct_row, text="Porcentaje:").pack(side="left", padx=(0, 4))
        self._pct_entry = ttk.Entry(pct_row, textvariable=self._pct_var, width=10, state="disabled")
        self._pct_entry.pack(side="left", padx=(0, 4))
        ttk.Label(pct_row, text="%").pack(side="left", padx=(0, 12))
        ttk.Label(pct_row, textvariable=self._preview_var, foreground="gray").pack(side="left")

        self._pct_var.trace_add("write", self._on_pct_changed)

        btn_row = ttk.Frame(outer)
        btn_row.pack(fill="x", pady=(4, 0))
        self._confirmar_btn = ttk.Button(btn_row, text="Confirmar", command=self._confirmar)
        self._confirmar_btn.pack(side="right", padx=(8, 0))
        ttk.Button(
            btn_row, text="Aplicar a todos los restantes igual",
            command=self._aplicar_a_todos,
        ).pack(side="right")

    def _load_conflict(self, idx: int) -> None:
        row, db_row = self._conflicts[idx]
        total = len(self._conflicts)
        self._title_var.set(f"Conflicto de precios ({idx + 1} de {total})")
        self._nombre_var.set(db_row["nombre"])
        self._proveedor_var.set(row.proveedor or "(no especificado)")
        self._pc_actual_var.set(f"${float(db_row['precio_costo']):.2f}")
        self._pc_nuevo_var.set(
            f"${row.precio_costo:.2f}" if row.precio_costo is not None else "—"
        )
        self._pv_actual_var.set(f"${float(db_row['precio']):.2f}")
        self._pv_nuevo_var.set(
            f"${row.precio_venta:.2f}" if row.precio_venta is not None else "—"
        )
        self._opcion_var.set("keep")
        self._pct_var.set("")
        self._preview_var.set("")
        self._pct_entry.configure(state="disabled")
        self._confirmar_btn.configure(state="normal")

    def _on_opcion_changed(self) -> None:
        if self._opcion_var.get() == "porcentaje":
            self._pct_entry.configure(state="normal")
            self._pct_entry.focus_set()
        else:
            self._pct_entry.configure(state="disabled")
            self._preview_var.set("")
            self._confirmar_btn.configure(state="normal")

    def _on_pct_changed(self, *_: Any) -> None:
        if self._opcion_var.get() != "porcentaje":
            return
        idx = self._current_idx
        if idx >= len(self._conflicts):
            return
        _, db_row = self._conflicts[idx]
        pct_raw = self._pct_var.get().strip()
        if not pct_raw:
            self._preview_var.set("")
            self._confirmar_btn.configure(state="normal")
            return
        try:
            pct = float(pct_raw.replace(",", "."))
            nuevo = float(db_row["precio"]) * (1 + pct / 100)
            if nuevo <= 0:
                self._preview_var.set("⚠ Precio resultante ≤ 0")
                self._confirmar_btn.configure(state="disabled")
            else:
                self._preview_var.set(f"→ ${nuevo:.2f}")
                self._confirmar_btn.configure(state="normal")
        except ValueError:
            self._preview_var.set("⚠ Ingrese un número")
            self._confirmar_btn.configure(state="disabled")

    def _resolve_overrides(
        self, row: Any, db_row: sqlite3.Row
    ) -> tuple[float | None, float | None] | None:
        """Returns (pv_override, pc_override) for the current option, or None on validation error."""
        opcion = self._opcion_var.get()
        if opcion == "keep":
            return float(db_row["precio"]), float(db_row["precio_costo"])
        elif opcion == "update":
            return None, None
        else:
            pct_raw = self._pct_var.get().strip().replace(",", ".")
            try:
                pct = float(pct_raw)
                nuevo_pv = float(db_row["precio"]) * (1 + pct / 100)
                if nuevo_pv <= 0:
                    messagebox.showerror(
                        "Precio inválido",
                        "El porcentaje resulta en un precio ≤ 0.",
                        parent=self._dialog,
                    )
                    return None
                return nuevo_pv, None
            except ValueError:
                messagebox.showerror(
                    "Valor inválido",
                    "Ingrese un porcentaje numérico válido.",
                    parent=self._dialog,
                )
                return None

    def _confirmar(self) -> None:
        idx = self._current_idx
        row, db_row = self._conflicts[idx]
        overrides = self._resolve_overrides(row, db_row)
        if overrides is None:
            return
        pv_override, pc_override = overrides
        try:
            stock_app.apply_boleta_row(
                self._conn, row,
                precio_venta_override=pv_override,
                precio_costo_override=pc_override,
            )
        except stock_app.StockError as exc:
            messagebox.showerror("Error", str(exc), parent=self._dialog)
            return
        self._current_idx += 1
        if self._current_idx < len(self._conflicts):
            self._load_conflict(self._current_idx)
        else:
            self._finish()

    def _aplicar_a_todos(self) -> None:
        opcion = self._opcion_var.get()
        pct = 0.0
        if opcion == "porcentaje":
            try:
                pct = float(self._pct_var.get().strip().replace(",", "."))
            except ValueError:
                messagebox.showerror(
                    "Valor inválido",
                    "Ingrese un porcentaje numérico válido.",
                    parent=self._dialog,
                )
                return

        for idx in range(self._current_idx, len(self._conflicts)):
            row, db_row = self._conflicts[idx]
            if opcion == "keep":
                pv_override: float | None = float(db_row["precio"])
                pc_override: float | None = float(db_row["precio_costo"])
            elif opcion == "update":
                pv_override = None
                pc_override = None
            else:
                nuevo_pv = float(db_row["precio"]) * (1 + pct / 100)
                pv_override = max(nuevo_pv, 0.01)
                pc_override = None
            try:
                stock_app.apply_boleta_row(
                    self._conn, row,
                    precio_venta_override=pv_override,
                    precio_costo_override=pc_override,
                )
            except stock_app.StockError:
                pass

        self._finish()

    def _finish(self) -> None:
        self._dialog.destroy()
        self._on_complete()


# =============================================================================
# Module-level helpers
# =============================================================================

def clear_table(table: ttk.Treeview) -> None:
    for item in table.get_children():
        table.delete(item)


def _calc_margen(precio: float, costo: float) -> str:
    if costo > 0 and precio > 0:
        return f"{((precio - costo) / precio * 100):.0f}%"
    return "-"


def parse_float(value: str, field_name: str) -> float:
    try:
        number = float(value.strip().replace(",", "."))
    except ValueError as exc:
        raise ValueError(f"Ingrese un numero valido en {field_name}.") from exc
    if number < 0:
        raise ValueError(f"{field_name.capitalize()} no puede ser negativo.")
    return number


def parse_int(value: str, field_name: str) -> int:
    try:
        number = int(value.strip())
    except ValueError as exc:
        raise ValueError(f"Ingrese un entero valido en {field_name}.") from exc
    if number < 0:
        raise ValueError(f"{field_name.capitalize()} no puede ser negativo.")
    return number


def _date_to_ui(d: date) -> str:
    return d.strftime("%d-%m-%Y")


def _date_from_ui(s: str) -> date:
    return datetime.strptime(s.strip(), "%d-%m-%Y").date()


def main() -> None:
    app = StockGui()
    app.mainloop()


if __name__ == "__main__":
    main()
