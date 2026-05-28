from __future__ import annotations

import sqlite3
import tkinter as tk
from datetime import date
from tkinter import filedialog, messagebox, ttk
from typing import Any

import stock_app

_UNDO_MAX = 10


class StockGui(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Sistema de Stock")
        self.geometry("1080x700")
        self.minsize(920, 600)

        self.conn = stock_app.get_connection()
        stock_app.initialize_database(self.conn)

        # ── product form vars ──
        self.codigo_var = tk.StringVar()
        self.nombre_var = tk.StringVar()
        self.precio_var = tk.StringVar()
        self.stock_var = tk.StringVar()
        self.stock_minimo_var = tk.StringVar()
        self.foto_var = tk.StringVar()
        self.proveedor_var = tk.StringVar()

        # ── sale vars ──
        self.venta_codigo_var = tk.StringVar()
        self.venta_cantidad_var = tk.StringVar(value="1")

        # ── other vars ──
        self.pendiente_var = tk.StringVar()
        self.caja_var = tk.StringVar()
        self.search_var = tk.StringVar()

        # ── price tab vars ──
        self.price_search_var = tk.StringVar()
        self.price_proveedor_var = tk.StringVar()
        self.aumento_var = tk.StringVar()
        self._price_status_var = tk.StringVar(value="Seleccionados: 0")

        # ── edit mode state ──
        self._edit_mode = False
        self._edit_codigo: str | None = None

        # ── undo stack ──
        self._undo_stack: list[dict[str, Any]] = []

        self._build_layout()
        self.search_var.trace_add("write", lambda *_: self.refresh_products())
        self.refresh_all()
        self.bind("<Control-z>", lambda _: self._undo())
        self.protocol("WM_DELETE_WINDOW", self.on_close)

    # =========================================================================
    # Layout
    # =========================================================================

    def _build_layout(self) -> None:
        style = ttk.Style(self)
        style.configure("Title.TLabel", font=("Segoe UI", 13, "bold"))

        outer = ttk.Frame(self, padding=10)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(1, weight=1)

        # header row
        hdr = ttk.Frame(outer)
        hdr.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        hdr.columnconfigure(1, weight=1)
        ttk.Label(hdr, text="Sistema de Stock", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(hdr, textvariable=self.caja_var).grid(row=0, column=1, sticky="e", padx=(0, 10))
        self._undo_btn = ttk.Button(hdr, text="Deshacer ↩  (Ctrl+Z)", command=self._undo, state="disabled")
        self._undo_btn.grid(row=0, column=2)

        # notebook
        self._notebook = ttk.Notebook(outer)
        self._notebook.grid(row=1, column=0, sticky="nsew")

        tab1 = ttk.Frame(self._notebook, padding=6)
        tab2 = ttk.Frame(self._notebook, padding=6)
        self._notebook.add(tab1, text="  Principal  ")
        self._notebook.add(tab2, text="  Gestión de precios  ")

        self._build_tab_principal(tab1)
        self._build_tab_precios(tab2)

    # ── Tab 1 ─────────────────────────────────────────────────────────────────

    def _build_tab_principal(self, parent: ttk.Frame) -> None:
        parent.columnconfigure(0, weight=2)
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(0, weight=1)

        left = ttk.Frame(parent)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)

        right = ttk.Frame(parent)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        right.rowconfigure(2, weight=1)

        self._build_product_form(left)
        self._build_product_table(left)
        self._build_sale_box(right)
        self._build_alerts_box(right)
        self._build_pending_box(right)

    def _build_product_form(self, parent: ttk.Frame) -> None:
        self._product_form_frame = ttk.LabelFrame(parent, text="Alta de producto", padding=8)
        self._product_form_frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        for col in range(7):
            self._product_form_frame.columnconfigure(col, weight=1)

        # labels row
        for col, text in enumerate(("Codigo", "Nombre", "", "Precio", "Stock", "Minimo", "Proveedor")):
            if text:
                ttk.Label(self._product_form_frame, text=text).grid(row=0, column=col, sticky="w")

        # entries row
        self._codigo_entry = ttk.Entry(self._product_form_frame, textvariable=self.codigo_var)
        self._codigo_entry.grid(row=1, column=0, sticky="ew", padx=(0, 4))

        ttk.Entry(self._product_form_frame, textvariable=self.nombre_var).grid(
            row=1, column=1, columnspan=2, sticky="ew", padx=(0, 4)
        )
        ttk.Entry(self._product_form_frame, textvariable=self.precio_var).grid(
            row=1, column=3, sticky="ew", padx=(0, 4)
        )
        ttk.Entry(self._product_form_frame, textvariable=self.stock_var).grid(
            row=1, column=4, sticky="ew", padx=(0, 4)
        )
        ttk.Entry(self._product_form_frame, textvariable=self.stock_minimo_var).grid(
            row=1, column=5, sticky="ew", padx=(0, 4)
        )
        self._proveedor_combo = ttk.Combobox(
            self._product_form_frame, textvariable=self.proveedor_var
        )
        self._proveedor_combo.grid(row=1, column=6, sticky="ew")
        self._proveedor_combo.bind("<ButtonPress>", lambda _: self._refresh_form_proveedor())
        self._proveedor_combo.bind("<FocusIn>", lambda _: self._refresh_form_proveedor())

        # foto row
        ttk.Label(self._product_form_frame, text="Foto").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(self._product_form_frame, textvariable=self.foto_var).grid(
            row=3, column=0, columnspan=4, sticky="ew", padx=(0, 4)
        )
        ttk.Button(self._product_form_frame, text="Buscar", command=self.choose_photo).grid(
            row=3, column=4, sticky="ew", padx=(0, 4)
        )
        self._save_btn = ttk.Button(
            self._product_form_frame, text="Guardar", command=self.save_product
        )
        self._save_btn.grid(row=3, column=5, sticky="ew", padx=(0, 4))
        self._cancel_edit_btn = ttk.Button(
            self._product_form_frame, text="Cancelar", command=self.cancel_edit
        )
        self._cancel_edit_btn.grid(row=3, column=6, sticky="ew")
        self._cancel_edit_btn.grid_remove()

    def _build_product_table(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Productos", padding=8)
        frame.grid(row=1, column=0, sticky="nsew")
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)

        search_row = ttk.Frame(frame)
        search_row.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        search_row.columnconfigure(1, weight=1)
        ttk.Label(search_row, text="Buscar:").grid(row=0, column=0, padx=(0, 6))
        ttk.Entry(search_row, textvariable=self.search_var).grid(row=0, column=1, sticky="ew")

        cols = ("codigo", "nombre", "precio", "stock", "minimo", "proveedor", "foto")
        self.products_table = ttk.Treeview(frame, columns=cols, show="headings", height=11)
        for col, label, width in (
            ("codigo", "Codigo", 100),
            ("nombre", "Nombre", 155),
            ("precio", "Precio", 72),
            ("stock", "Stock", 55),
            ("minimo", "Minimo", 55),
            ("proveedor", "Proveedor", 105),
            ("foto", "Foto", 120),
        ):
            self.products_table.heading(col, text=label)
            self.products_table.column(col, width=width, minwidth=45)

        sb = ttk.Scrollbar(frame, orient="vertical", command=self.products_table.yview)
        self.products_table.configure(yscrollcommand=sb.set)
        self.products_table.grid(row=1, column=0, sticky="nsew")
        sb.grid(row=1, column=1, sticky="ns")
        self.products_table.bind("<Double-1>", lambda _: self.load_selected_for_edit())

        actions = ttk.Frame(frame)
        actions.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        actions.columnconfigure(0, weight=1)
        ttk.Button(actions, text="Cargar para editar", command=self.load_selected_for_edit).grid(
            row=0, column=1, padx=(0, 6)
        )
        ttk.Button(actions, text="Eliminar", command=self.delete_selected_product).grid(
            row=0, column=2, padx=(0, 6)
        )
        ttk.Button(actions, text="Actualizar lista", command=self.refresh_all).grid(row=0, column=3)

    def _build_sale_box(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="Venta rapida", padding=8)
        frame.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Codigo").grid(row=0, column=0, sticky="w", padx=(0, 6))
        ttk.Entry(frame, textvariable=self.venta_codigo_var).grid(row=0, column=1, sticky="ew")
        ttk.Label(frame, text="Cantidad").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=(6, 0))
        ttk.Entry(frame, textvariable=self.venta_cantidad_var).grid(
            row=1, column=1, sticky="ew", pady=(6, 0)
        )
        ttk.Button(frame, text="Registrar venta", command=self.register_sale).grid(
            row=2, column=0, columnspan=2, sticky="ew", pady=(8, 0)
        )

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
            ("minimo", "Minimo", 52),
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
        ttk.Entry(entry_row, textvariable=self.pendiente_var).grid(
            row=0, column=0, sticky="ew", padx=(0, 6)
        )
        ttk.Button(entry_row, text="Agregar", command=self.add_pending).grid(row=0, column=1)

        cols = ("id", "estado", "descripcion")
        self.pending_table = ttk.Treeview(frame, columns=cols, show="headings", height=5)
        for col, label, width in (
            ("id", "ID", 38),
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

        # filter bar
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

        # product table (extended multi-select)
        table_frame = ttk.LabelFrame(
            parent,
            text="Productos  —  Ctrl+Click o Shift+Click para seleccion multiple",
            padding=8,
        )
        table_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        table_frame.rowconfigure(0, weight=1)
        table_frame.columnconfigure(0, weight=1)

        price_cols = ("codigo", "nombre", "precio", "proveedor")
        self.price_table = ttk.Treeview(
            table_frame, columns=price_cols, show="headings",
            selectmode="extended", height=18,
        )
        for col, label, width in (
            ("codigo", "Codigo", 130),
            ("nombre", "Nombre", 310),
            ("precio", "Precio actual", 120),
            ("proveedor", "Proveedor", 170),
        ):
            self.price_table.heading(col, text=label)
            self.price_table.column(col, width=width, minwidth=60)

        psb = ttk.Scrollbar(table_frame, orient="vertical", command=self.price_table.yview)
        self.price_table.configure(yscrollcommand=psb.set)
        self.price_table.grid(row=0, column=0, sticky="nsew")
        psb.grid(row=0, column=1, sticky="ns")
        self.price_table.bind("<<TreeviewSelect>>", self._on_price_selection_change)
        self.price_table.bind("<Double-1>", lambda _: self._load_price_row_for_edit())

        # increase controls
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
        ttk.Label(inc_frame, textvariable=self._price_status_var).grid(row=0, column=5, sticky="e")

    # =========================================================================
    # Proveedor autocomplete helpers
    # =========================================================================

    def _refresh_form_proveedor(self) -> None:
        self._proveedor_combo["values"] = stock_app.get_all_proveedores(self.conn)

    def _refresh_price_proveedor(self) -> None:
        self._price_proveedor_combo["values"] = stock_app.get_all_proveedores(self.conn)

    def _clear_price_filters(self) -> None:
        self.price_proveedor_var.set("")
        self.price_search_var.set("")
        self.refresh_price_table()

    def _on_price_selection_change(self, *_) -> None:
        n = len(self.price_table.selection())
        total = len(self.price_table.get_children())
        self._price_status_var.set(f"Seleccionados: {n} / Total filtrados: {total}")

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
        if pct == 0.0:
            messagebox.showerror("Valor invalido", "El porcentaje debe ser mayor a 0.")
            return
        if not messagebox.askyesno(
            "Confirmar aumento",
            f"Aplicar {pct:.1f}% a {len(codigos)} producto(s)?\n"
            "El resultado se redondea a la decena mas cercana.",
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
        messagebox.showinfo("Aumento aplicado", f"Se actualizaron {len(changes)} precio(s).")

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
    # Undo
    # =========================================================================

    def _push_undo(self, action: dict[str, Any]) -> None:
        self._undo_stack.append(action)
        if len(self._undo_stack) > _UNDO_MAX:
            self._undo_stack.pop(0)
        self._undo_btn.configure(state="normal")

    def _undo(self) -> None:
        if not self._undo_stack:
            return
        action = self._undo_stack.pop()
        try:
            if action["type"] == "delete_product":
                stock_app._restore_product(self.conn, action["data"])
            elif action["type"] == "sale":
                stock_app.reverse_sale(
                    self.conn,
                    action["codigo"],
                    action["cantidad"],
                    action["total"],
                    action["sale_date"],
                )
            elif action["type"] == "price_increase":
                for codigo, old_price, _ in action["changes"]:
                    self.conn.execute(
                        "UPDATE productos SET precio = ? WHERE codigo = ?",
                        (old_price, codigo),
                    )
                self.conn.commit()
        except Exception as exc:
            messagebox.showerror("Error al deshacer", str(exc))
            return

        if not self._undo_stack:
            self._undo_btn.configure(state="disabled")
        self.refresh_all()
        messagebox.showinfo("Deshacer", f"Revertido: {action.get('description', '')}")

    # =========================================================================
    # Form helpers
    # =========================================================================

    def _clear_form(self) -> None:
        self.codigo_var.set("")
        self.nombre_var.set("")
        self.precio_var.set("")
        self.stock_var.set("")
        self.stock_minimo_var.set("")
        self.foto_var.set("")
        self.proveedor_var.set("")

    def choose_photo(self) -> None:
        filename = filedialog.askopenfilename(
            title="Seleccionar foto",
            filetypes=(
                ("Imagenes", "*.png *.jpg *.jpeg *.webp *.bmp *.gif"),
                ("Todos los archivos", "*.*"),
            ),
        )
        if filename:
            self.foto_var.set(filename)

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
            stock = parse_int(self.stock_var.get(), "stock")
            stock_minimo = parse_int(self.stock_minimo_var.get(), "stock minimo")
            proveedor = self.proveedor_var.get().strip()
            if not codigo or not nombre:
                raise ValueError("Codigo y nombre son obligatorios.")
            stock_app.add_product(
                self.conn, codigo, nombre, precio, stock, stock_minimo,
                self.foto_var.get() or None, proveedor,
            )
        except (ValueError, stock_app.StockError) as exc:
            messagebox.showerror("No se pudo guardar", str(exc))
            return

        self._clear_form()
        self.refresh_all()
        messagebox.showinfo("Producto guardado", "El producto fue registrado.")

    def _do_update_product(self) -> None:
        try:
            nombre = self.nombre_var.get().strip()
            precio = parse_float(self.precio_var.get(), "precio")
            stock = parse_int(self.stock_var.get(), "stock")
            stock_minimo = parse_int(self.stock_minimo_var.get(), "stock minimo")
            proveedor = self.proveedor_var.get().strip()
            if not nombre:
                raise ValueError("El nombre es obligatorio.")
            stock_app.update_product(
                self.conn,
                self._edit_codigo,  # type: ignore[arg-type]
                nombre, precio, stock, stock_minimo,
                self.foto_var.get() or None, proveedor,
            )
        except (ValueError, stock_app.StockError) as exc:
            messagebox.showerror("No se pudo actualizar", str(exc))
            return

        self.cancel_edit()
        self.refresh_all()
        messagebox.showinfo("Producto actualizado", "El producto fue actualizado.")

    def enter_edit_mode(self, product: sqlite3.Row) -> None:
        self._edit_mode = True
        self._edit_codigo = product["codigo"]
        self.codigo_var.set(product["codigo"])
        self.nombre_var.set(product["nombre"])
        self.precio_var.set(str(product["precio"]))
        self.stock_var.set(str(product["stock"]))
        self.stock_minimo_var.set(str(product["stock_minimo"]))
        self.proveedor_var.set(product["proveedor"] or "")
        self.foto_var.set("")
        self._codigo_entry.configure(state="readonly")
        self._save_btn.configure(text="Actualizar")
        self._product_form_frame.configure(text="Editar producto")
        self._cancel_edit_btn.grid()
        self._notebook.select(0)

    def cancel_edit(self) -> None:
        self._edit_mode = False
        self._edit_codigo = None
        self._clear_form()
        self._codigo_entry.configure(state="normal")
        self._save_btn.configure(text="Guardar")
        self._product_form_frame.configure(text="Alta de producto")
        self._cancel_edit_btn.grid_remove()

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
        try:
            cantidad = parse_int(self.venta_cantidad_var.get(), "cantidad")
            sale_date = date.today()
            total = stock_app.register_sale(self.conn, codigo, cantidad, sale_date=sale_date)
        except stock_app.InsufficientStockError as exc:
            allow = messagebox.askyesno(
                "Stock insuficiente",
                f"{exc}\n\n¿Autorizar venta con stock negativo?",
            )
            if not allow:
                return
            try:
                sale_date = date.today()
                cantidad = parse_int(self.venta_cantidad_var.get(), "cantidad")
                total = stock_app.register_sale(
                    self.conn, codigo, cantidad, allow_negative=True, sale_date=sale_date
                )
            except (ValueError, stock_app.StockError) as retry_exc:
                messagebox.showerror("No se pudo registrar", str(retry_exc))
                return
        except (ValueError, stock_app.StockError) as exc:
            messagebox.showerror("No se pudo registrar", str(exc))
            return

        self._push_undo({
            "type": "sale",
            "codigo": codigo,
            "cantidad": cantidad,
            "total": total,
            "sale_date": sale_date.isoformat(),
            "description": f"venta {cantidad}x '{codigo}' (${total:.2f})",
        })
        self.venta_codigo_var.set("")
        self.venta_cantidad_var.set("1")
        self.refresh_all()
        messagebox.showinfo("Venta registrada", f"Total: ${total:.2f}")

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

    def complete_selected_pending(self) -> None:
        selected = self.pending_table.selection()
        if not selected:
            messagebox.showerror("Seleccione un pendiente", "Elija un item de la lista.")
            return
        pending_id = int(self.pending_table.item(selected[0], "values")[0])
        stock_app.complete_pending(self.conn, pending_id)
        self.refresh_pending()

    def delete_selected_pending(self) -> None:
        selected = self.pending_table.selection()
        if not selected:
            messagebox.showerror("Seleccione un pendiente", "Elija un item de la lista.")
            return
        pending_id = int(self.pending_table.item(selected[0], "values")[0])
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
        self.refresh_price_table()
        self.caja_var.set(f"Caja de hoy: ${stock_app.daily_cash(self.conn):.2f}")

    def refresh_products(self) -> None:
        clear_table(self.products_table)
        query = self.search_var.get().lower()
        for row in stock_app.list_products(self.conn):
            if query and query not in row["codigo"].lower() and query not in row["nombre"].lower():
                continue
            self.products_table.insert(
                "", "end",
                values=(
                    row["codigo"],
                    row["nombre"],
                    f"${row['precio']:.2f}",
                    row["stock"],
                    row["stock_minimo"],
                    row["proveedor"] or "-",
                    row["foto"] or "-",
                ),
            )

    def refresh_alerts(self) -> None:
        clear_table(self.alerts_table)
        for row in stock_app.low_stock_products(self.conn):
            self.alerts_table.insert(
                "", "end",
                values=(row["codigo"], row["nombre"], row["stock"], row["stock_minimo"]),
            )

    def refresh_pending(self) -> None:
        clear_table(self.pending_table)
        for row in stock_app.list_pending(self.conn):
            self.pending_table.insert(
                "", "end",
                values=(row["id"], row["estado"], row["descripcion"]),
            )

    def refresh_price_table(self) -> None:
        clear_table(self.price_table)
        prov_filter = self.price_proveedor_var.get().strip().lower()
        text_filter = self.price_search_var.get().strip().lower()
        for row in stock_app.list_products(self.conn):
            if prov_filter and prov_filter not in (row["proveedor"] or "").lower():
                continue
            if text_filter and (
                text_filter not in row["codigo"].lower()
                and text_filter not in row["nombre"].lower()
            ):
                continue
            self.price_table.insert(
                "", "end",
                values=(
                    row["codigo"],
                    row["nombre"],
                    f"${row['precio']:.2f}",
                    row["proveedor"] or "-",
                ),
            )
        self._on_price_selection_change()

    def on_close(self) -> None:
        self.conn.close()
        self.destroy()


# =============================================================================
# Module-level helpers
# =============================================================================

def clear_table(table: ttk.Treeview) -> None:
    for item in table.get_children():
        table.delete(item)


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


def main() -> None:
    app = StockGui()
    app.mainloop()


if __name__ == "__main__":
    main()
