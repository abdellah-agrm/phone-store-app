import tkinter as tk
from tkinter import messagebox, filedialog, scrolledtext
import sqlite3
import os
import datetime
import random
import string
from PIL import Image, ImageTk, ImageDraw, ImageFont
import barcode
from barcode.writer import ImageWriter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
import pandas as pd
import tempfile
import shutil
import urllib.parse
import subprocess
import hashlib
import hmac

from pathlib import Path
import sys
from ttkbootstrap import Style
import ttkbootstrap as ttk

from ttkbootstrap.widgets import DateEntry

# --- FIXED PATHS FOR PYINSTALLER ---
def get_app_directory():
    """Get the directory where the app should store its data"""
    if getattr(sys, 'frozen', False):
        # Running as compiled executable
        app_dir = os.path.dirname(sys.executable)
    else:
        # Running as script
        app_dir = os.path.dirname(os.path.abspath(__file__))
    return app_dir

def get_resource_path(relative_path):
    """Get absolute path to resource, works for dev and PyInstaller"""
    if getattr(sys, 'frozen', False):
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    else:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

# Runtime data is stored in a writable, stable user folder.
# Windows: %APPDATA%\PhoneShopManager
# Other systems: ~/PhoneShopManager
APP_NAME = "PhoneShopManager"
DB_DIR = os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"), APP_NAME)
os.makedirs(DB_DIR, exist_ok=True)

DB_PATH = os.path.join(DB_DIR, "phone_shop.db")
BARCODES_DIR = os.path.join(DB_DIR, "codes_barres")
os.makedirs(BARCODES_DIR, exist_ok=True)


def _same_path(a, b):
    try:
        return os.path.samefile(a, b)
    except Exception:
        return os.path.abspath(a) == os.path.abspath(b)


def migrate_legacy_runtime_data():
    """Copy old local DB/barcodes into the stable data folder once.

    Older builds commonly kept phone_shop.db beside main.py/main.exe. The new
    build uses DB_DIR so updates installed under Program Files do not lose data
    or crash because of write permissions. This function copies old data only
    when the new DB does not already exist, so it never overwrites live data.
    """
    if os.path.exists(DB_PATH):
        return

    candidates = []
    for base in (get_app_directory(), os.getcwd()):
        if base and base not in candidates:
            candidates.append(base)

    for base in candidates:
        legacy_db = os.path.join(base, "phone_shop.db")
        if os.path.exists(legacy_db) and not _same_path(legacy_db, DB_PATH):
            try:
                shutil.copy2(legacy_db, DB_PATH)

                legacy_barcodes = os.path.join(base, "codes_barres")
                if os.path.isdir(legacy_barcodes):
                    os.makedirs(BARCODES_DIR, exist_ok=True)
                    for name in os.listdir(legacy_barcodes):
                        src = os.path.join(legacy_barcodes, name)
                        dst = os.path.join(BARCODES_DIR, name)
                        if os.path.isfile(src) and not os.path.exists(dst):
                            shutil.copy2(src, dst)
                break
            except Exception as exc:
                print(f"Legacy data migration skipped: {exc}")


def hash_password(password):
    """Return a PBKDF2 hash. Plain old passwords are still accepted by verify_password."""
    salt = os.urandom(16).hex()
    rounds = 120000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), rounds).hex()
    return f"pbkdf2_sha256${rounds}${salt}${digest}"


def verify_password(stored_password, entered_password):
    if not stored_password:
        return False
    if stored_password.startswith("pbkdf2_sha256$"):
        try:
            _, rounds, salt, digest = stored_password.split("$", 3)
            check = hashlib.pbkdf2_hmac("sha256", entered_password.encode("utf-8"), bytes.fromhex(salt), int(rounds)).hex()
            return hmac.compare_digest(check, digest)
        except Exception:
            return False
    # Backward compatibility for existing plain-text users in old databases.
    return hmac.compare_digest(stored_password, entered_password)


migrate_legacy_runtime_data()

class PhoneShopApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Système de Gestion de Magasin de Téléphones")
        self.root.geometry("1180x720")
        self.root.minsize(1050, 650)

        # Use the global BARCODES_DIR
        self.barcode_folder = BARCODES_DIR
        if not os.path.exists(self.barcode_folder):
            os.makedirs(self.barcode_folder)

        # initialize ttkbootstrap style (light modern theme)
        self.style = Style(theme="litera")  # try 'litera', 'flatly', 'cosmo', etc.
        # pull some palette values for consistent background usage
        try:
            # ttkbootstrap exposes colors via style.colors (best-effort)
            palette = self.style.colors
            # Try to get icon from resources or skip
            try:
                icon_path = get_resource_path("app.ico")
                if os.path.exists(icon_path):
                    self.root.iconbitmap(icon_path)
            except:
                pass  # Skip icon if not found
            
            self.bg_color = palette.get("bg", "#f6f8fb")
            self.surface_color = palette.get("secondary", "#ffffff")
            self.accent_color = palette.get("primary", "#0d6efd")
            self.muted_text = palette.get("muted", "#6c757d")
        except Exception:
            self.bg_color = "#f6f8fb"
            self.surface_color = "#ffffff"
            self.accent_color = "#0d6efd"
            self.muted_text = "#6c757d"

        # configure a couple of custom styles on top of the bootstrap theme
        self._configure_styles()

        # reusable PIL-based line icons for a cleaner UI (no emoji glyphs)
        self._init_icon_library()

        # database + user state
        self.init_database()
        self.current_user = None

        # main frame
        self.main_frame = ttk.Frame(self.root, style="Main.TFrame")
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=18, pady=18)

        # show login screen
        self.show_login_screen()

    def _configure_styles(self):
        s = ttk.Style()
        # Main container
        s.configure("Main.TFrame", background=self.bg_color)
        # Headings and labels
        s.configure("TLabel", background=self.bg_color, foreground="#222222", font=("Segoe UI", 10))
        s.configure("Heading.TLabel", background=self.bg_color, foreground="#111111", font=("Segoe UI", 16, "bold"))
        s.configure("Title.TLabel", background=self.bg_color, foreground=self.accent_color, font=("Segoe UI", 20, "bold"))
        # Buttons
        s.configure("TButton", font=("Segoe UI", 10))
        s.configure("Primary.TButton", font=("Segoe UI", 10, "bold"))
        # Entries / Combobox
        s.configure("TEntry", fieldbackground=self.surface_color, background=self.surface_color, foreground="#111111", font=("Segoe UI", 10))
        s.configure("TCombobox", fieldbackground=self.surface_color, background=self.surface_color, foreground="#111111", font=("Segoe UI", 10))
        # Treeview
        s.configure("Treeview", background=self.surface_color, foreground="#111111", fieldbackground=self.surface_color, font=("Segoe UI", 10), rowheight=28)
        s.configure("Treeview.Heading", font=("Segoe UI", 10, "bold"))
        # Labelframes
        s.configure("TLabelframe", background=self.bg_color, foreground="#222222")
        s.configure("TLabelframe.Label", background=self.bg_color, foreground=self.accent_color, font=("Segoe UI", 12, "bold"))
        # Notebook
        s.configure("TNotebook", background=self.bg_color)
        s.configure("TNotebook.Tab", padding=[12, 6], font=("Segoe UI", 10))
        # root bg
        self.root.configure(bg=self.bg_color)


    def _init_icon_library(self):
        """Create small, reusable line icons as Tk images.

        The icons are drawn with Pillow so the app does not depend on emoji
        rendering or Windows-specific symbol fonts. Each image is stored on
        self.icons so Tkinter keeps a live reference.
        """
        self.icons = {}
        for name in (
            "phone", "sales", "reports", "accessory", "settings", "logout",
            "scan", "search", "plus", "clear", "save", "sell", "edit",
            "delete", "view", "print", "user", "database", "refresh", "calendar",
            "close"
        ):
            self.icons[name] = self._draw_icon(name)

    def _draw_icon(self, name, size=18):
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        c = "#4b5563"
        w = 2
        s = size
        try:
            rr = draw.rounded_rectangle
        except AttributeError:
            rr = draw.rectangle

        def line(points, width=w):
            draw.line(points, fill=c, width=width, joint="curve")

        if name == "phone":
            rr([5, 2, s - 5, s - 2], radius=3, outline=c, width=w)
            line([(7, s - 5), (s - 7, s - 5)], 1)
        elif name == "sales":
            line([(3, 5), (5, 5), (7, 12), (14, 12), (16, 7), (7, 7)])
            draw.ellipse([7, 13, 10, 16], outline=c, width=w)
            draw.ellipse([13, 13, 16, 16], outline=c, width=w)
        elif name == "reports":
            line([(3, 15), (15, 15)], 1)
            draw.rectangle([4, 9, 6, 14], outline=c, width=w)
            draw.rectangle([8, 5, 10, 14], outline=c, width=w)
            draw.rectangle([12, 7, 14, 14], outline=c, width=w)
        elif name == "accessory":
            draw.arc([3, 3, 15, 15], start=190, end=350, fill=c, width=w)
            rr([2, 9, 5, 15], radius=1, outline=c, width=w)
            rr([13, 9, 16, 15], radius=1, outline=c, width=w)
        elif name == "settings":
            draw.ellipse([5, 5, 13, 13], outline=c, width=w)
            draw.ellipse([8, 8, 10, 10], fill=c)
            for p1, p2 in [((9,1),(9,4)), ((9,14),(9,17)), ((1,9),(4,9)), ((14,9),(17,9)), ((3,3),(5,5)), ((13,13),(15,15)), ((15,3),(13,5)), ((5,13),(3,15))]:
                line([p1, p2], 1)
        elif name == "logout":
            rr([3, 3, 10, 15], radius=1, outline=c, width=w)
            line([(9, 9), (16, 9)])
            line([(13, 6), (16, 9), (13, 12)])
        elif name == "scan":
            for x in [3, 6, 8, 12, 15]:
                line([(x, 4), (x, 14)], 1 if x in (6, 12) else 2)
            line([(2, 2), (6, 2)], 1); line([(2, 2), (2, 6)], 1)
            line([(12, 2), (16, 2)], 1); line([(16, 2), (16, 6)], 1)
            line([(2, 12), (2, 16)], 1); line([(2, 16), (6, 16)], 1)
            line([(12, 16), (16, 16)], 1); line([(16, 12), (16, 16)], 1)
        elif name == "search":
            draw.ellipse([3, 3, 11, 11], outline=c, width=w)
            line([(10, 10), (15, 15)])
        elif name == "plus":
            line([(9, 3), (9, 15)])
            line([(3, 9), (15, 9)])
        elif name == "clear" or name == "close":
            line([(4, 4), (14, 14)])
            line([(14, 4), (4, 14)])
        elif name == "save":
            rr([3, 3, 15, 15], radius=1, outline=c, width=w)
            draw.rectangle([6, 3, 12, 7], outline=c, width=1)
            draw.rectangle([6, 11, 12, 15], outline=c, width=1)
        elif name == "sell":
            draw.ellipse([4, 3, 14, 13], outline=c, width=w)
            line([(9, 5), (9, 11)], 1)
            draw.arc([6, 5, 12, 9], start=210, end=30, fill=c, width=1)
            draw.arc([6, 8, 12, 12], start=30, end=210, fill=c, width=1)
        elif name == "edit":
            line([(4, 13), (12, 5)])
            line([(10, 3), (15, 8)])
            line([(3, 15), (7, 14)])
        elif name == "delete":
            line([(4, 5), (14, 5)])
            rr([5, 6, 13, 16], radius=1, outline=c, width=w)
            line([(7, 3), (11, 3)], 1)
            line([(8, 8), (8, 14)], 1); line([(11, 8), (11, 14)], 1)
        elif name == "view":
            line([(2, 9), (5, 5), (9, 4), (13, 5), (16, 9), (13, 13), (9, 14), (5, 13), (2, 9)], 1)
            draw.ellipse([7, 7, 11, 11], outline=c, width=w)
        elif name == "print":
            rr([4, 7, 14, 14], radius=1, outline=c, width=w)
            draw.rectangle([6, 3, 12, 7], outline=c, width=1)
            draw.rectangle([6, 12, 12, 16], outline=c, width=1)
        elif name == "user":
            draw.ellipse([6, 3, 12, 9], outline=c, width=w)
            draw.arc([3, 9, 15, 18], start=200, end=340, fill=c, width=w)
        elif name == "database":
            draw.ellipse([3, 2, 15, 7], outline=c, width=w)
            line([(3, 5), (3, 13)], 1); line([(15, 5), (15, 13)], 1)
            draw.arc([3, 10, 15, 16], start=0, end=180, fill=c, width=w)
            draw.arc([3, 6, 15, 12], start=0, end=180, fill=c, width=1)
        elif name == "refresh":
            draw.arc([3, 3, 15, 15], start=35, end=320, fill=c, width=w)
            line([(13, 3), (15, 7), (11, 7)])
        elif name == "calendar":
            rr([3, 4, 15, 16], radius=1, outline=c, width=w)
            line([(3, 8), (15, 8)], 1)
            line([(6, 2), (6, 6)], 1); line([(12, 2), (12, 6)], 1)
        else:
            draw.rectangle([4, 4, 14, 14], outline=c, width=w)
        return ImageTk.PhotoImage(img)

    def icon(self, name):
        return getattr(self, "icons", {}).get(name)

    def icon_button(self, parent, text, icon_name=None, **kwargs):
        image = self.icon(icon_name)
        if image is not None:
            kwargs.setdefault("image", image)
            kwargs.setdefault("compound", tk.LEFT)
            text = "  " + text
        return ttk.Button(parent, text=text, **kwargs)

    def add_tab(self, frame, text, icon_name=None):
        image = self.icon(icon_name)
        if image is not None:
            self.notebook.add(frame, text="  " + text, image=image, compound=tk.LEFT)
        else:
            self.notebook.add(frame, text=text)

    def center_window(self, window):
        window.update_idletasks()
        x = (window.winfo_screenwidth() // 2) - (window.winfo_width() // 2)
        y = (window.winfo_screenheight() // 2) - (window.winfo_height() // 2)
        window.geometry(f"+{x}+{y}")

    def barcode_conflict(self, code, ignore_accessory_id=None, ignore_phone_id=None):
        """Return a user-readable conflict message if a barcode is already used."""
        code = (code or "").strip()
        if not code:
            return None
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        params = [code, code, code]
        q = "SELECT id, ID_phone, brand, model FROM phones WHERE (ID_phone = ? OR imei = ? OR barcode = ?)"
        if ignore_phone_id is not None:
            q += " AND id <> ?"
            params.append(ignore_phone_id)
        q += " LIMIT 1"
        cursor.execute(q, params)
        phone = cursor.fetchone()
        if phone:
            conn.close()
            return f"Ce code est déjà utilisé par le téléphone {phone[1]} ({phone[2] or ''} {phone[3] or ''})."
        params = [code, code]
        q = "SELECT id, SKU, name FROM accessories WHERE (SKU = ? OR barcode = ?)"
        if ignore_accessory_id is not None:
            q += " AND id <> ?"
            params.append(ignore_accessory_id)
        q += " LIMIT 1"
        cursor.execute(q, params)
        accessory = cursor.fetchone()
        conn.close()
        if accessory:
            return f"Ce code est déjà utilisé par l'accessoire {accessory[1] or accessory[0]} ({accessory[2] or ''})."
        return None

    def init_database(self):
        """Initialize database and safely migrate old database files in place.

        The app may be updated while an older phone_shop.db already exists on the
        PC. SQLite keeps old tables exactly as they were, so every new column used
        by the code must be added with ALTER TABLE before the UI loads.
        """
        conn = None
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()

            cursor.execute('''CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL CHECK(role IN ('admin', 'vendor'))
            )''')

            cursor.execute('''CREATE TABLE IF NOT EXISTS phones (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ID_phone TEXT UNIQUE NOT NULL,
                brand TEXT NOT NULL,
                model TEXT NOT NULL,
                imei TEXT UNIQUE NOT NULL,
                color TEXT,
                storage TEXT,
                ram TEXT,
                battery_state TEXT DEFAULT '100',
                price REAL NOT NULL,
                description TEXT,
                barcode TEXT NOT NULL,
                barcode_file_path TEXT,
                image_path TEXT,
                available BOOLEAN DEFAULT 1,
                seller_name TEXT,
                seller_price REAL,
                seller_contact TEXT,
                seller_description TEXT,
                date_added TEXT DEFAULT (datetime('now'))
            )''')

            cursor.execute('''CREATE TABLE IF NOT EXISTS accessories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                SKU TEXT UNIQUE,
                name TEXT NOT NULL,
                brand TEXT,
                model TEXT,
                price REAL NOT NULL,
                quantity INTEGER DEFAULT 1,
                description TEXT,
                barcode TEXT,
                barcode_file_path TEXT,
                image_path TEXT,
                available BOOLEAN DEFAULT 1,
                seller_name TEXT,
                seller_price REAL,
                seller_contact TEXT,
                seller_description TEXT,
                seller_total_price REAL,
                date_added TEXT DEFAULT (datetime('now'))
            )''')

            cursor.execute('''CREATE TABLE IF NOT EXISTS buyers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                contact_info TEXT NOT NULL,
                description TEXT
            )''')

            cursor.execute('''CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_id INTEGER,
                buyer_id INTEGER NOT NULL,
                sale_date TEXT NOT NULL,
                sale_price REAL NOT NULL,
                product_type TEXT DEFAULT 'phone',
                product_id INTEGER,
                sale_qty INTEGER DEFAULT 1,
                sale_unit_price REAL,
                sale_total REAL,
                product_ref TEXT,
                product_name_snapshot TEXT,
                product_brand_snapshot TEXT,
                product_model_snapshot TEXT,
                product_imei_snapshot TEXT,
                buyer_name_snapshot TEXT,
                buyer_contact_snapshot TEXT,
                FOREIGN KEY(buyer_id) REFERENCES buyers(id)
            )''')

            migration_backup_done = False

            def backup_before_migration():
                nonlocal migration_backup_done
                if migration_backup_done:
                    return
                migration_backup_done = True
                try:
                    if os.path.exists(DB_PATH) and os.path.getsize(DB_PATH) > 0:
                        backups_dir = os.path.join(DB_DIR, "backups")
                        os.makedirs(backups_dir, exist_ok=True)
                        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                        shutil.copy2(DB_PATH, os.path.join(backups_dir, f"pre_migration_{timestamp}.db"))
                except Exception as exc:
                    print(f"Pre-migration backup skipped: {exc}")

            def ensure_column(table, column, col_def):
                cursor.execute(f"PRAGMA table_info({table})")
                cols = [r[1] for r in cursor.fetchall()]
                if column not in cols:
                    backup_before_migration()
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {col_def}")

            # Users
            ensure_column("users", "username", "username TEXT")
            ensure_column("users", "password", "password TEXT")
            ensure_column("users", "role", "role TEXT DEFAULT 'vendor'")

            # Phones: all columns used by the UI/reports. Added columns are nullable
            # when migrating old DB files so existing rows remain valid.
            for column, col_def in (
                ("ID_phone", "ID_phone TEXT"),
                ("brand", "brand TEXT"),
                ("model", "model TEXT"),
                ("imei", "imei TEXT"),
                ("color", "color TEXT"),
                ("storage", "storage TEXT"),
                ("ram", "ram TEXT"),
                ("battery_state", "battery_state TEXT DEFAULT '100'"),
                ("price", "price REAL DEFAULT 0"),
                ("description", "description TEXT"),
                ("barcode", "barcode TEXT"),
                ("barcode_file_path", "barcode_file_path TEXT"),
                ("image_path", "image_path TEXT"),
                ("available", "available BOOLEAN DEFAULT 1"),
                ("seller_name", "seller_name TEXT"),
                ("seller_price", "seller_price REAL"),
                ("seller_contact", "seller_contact TEXT"),
                ("seller_description", "seller_description TEXT"),
                ("date_added", "date_added TEXT"),
            ):
                ensure_column("phones", column, col_def)

            # Accessories
            for column, col_def in (
                ("SKU", "SKU TEXT"),
                ("name", "name TEXT"),
                ("brand", "brand TEXT"),
                ("model", "model TEXT"),
                ("price", "price REAL DEFAULT 0"),
                ("quantity", "quantity INTEGER DEFAULT 1"),
                ("description", "description TEXT"),
                ("barcode", "barcode TEXT"),
                ("barcode_file_path", "barcode_file_path TEXT"),
                ("image_path", "image_path TEXT"),
                ("available", "available BOOLEAN DEFAULT 1"),
                ("seller_name", "seller_name TEXT"),
                ("seller_price", "seller_price REAL"),
                ("seller_contact", "seller_contact TEXT"),
                ("seller_description", "seller_description TEXT"),
                ("seller_total_price", "seller_total_price REAL"),
                ("date_added", "date_added TEXT"),
            ):
                ensure_column("accessories", column, col_def)

            # Buyers
            ensure_column("buyers", "name", "name TEXT")
            ensure_column("buyers", "contact_info", "contact_info TEXT")
            ensure_column("buyers", "description", "description TEXT")

            # Sales and report snapshots. Snapshots preserve old sale history even
            # if the related phone/accessory/buyer is deleted later.
            for column, col_def in (
                ("phone_id", "phone_id INTEGER"),
                ("buyer_id", "buyer_id INTEGER"),
                ("sale_date", "sale_date TEXT"),
                ("sale_price", "sale_price REAL DEFAULT 0"),
                ("product_type", "product_type TEXT DEFAULT 'phone'"),
                ("product_id", "product_id INTEGER"),
                ("sale_qty", "sale_qty INTEGER DEFAULT 1"),
                ("sale_unit_price", "sale_unit_price REAL"),
                ("sale_total", "sale_total REAL"),
                ("product_ref", "product_ref TEXT"),
                ("product_name_snapshot", "product_name_snapshot TEXT"),
                ("product_brand_snapshot", "product_brand_snapshot TEXT"),
                ("product_model_snapshot", "product_model_snapshot TEXT"),
                ("product_imei_snapshot", "product_imei_snapshot TEXT"),
                ("buyer_name_snapshot", "buyer_name_snapshot TEXT"),
                ("buyer_contact_snapshot", "buyer_contact_snapshot TEXT"),
            ):
                ensure_column("sales", column, col_def)

            # Repair/fill values needed by current code for older rows.
            cursor.execute("UPDATE phones SET battery_state = '100' WHERE battery_state IS NULL OR TRIM(COALESCE(battery_state,'')) = ''")
            cursor.execute("UPDATE phones SET price = 0 WHERE price IS NULL")
            cursor.execute("UPDATE phones SET available = 1 WHERE available IS NULL")
            cursor.execute("UPDATE phones SET date_added = datetime('now') WHERE date_added IS NULL OR TRIM(COALESCE(date_added,'')) = ''")
            cursor.execute("SELECT id FROM phones WHERE ID_phone IS NULL OR TRIM(COALESCE(ID_phone,'')) = ''")
            for (row_id,) in cursor.fetchall():
                cursor.execute("UPDATE phones SET ID_phone = ? WHERE id = ?", (f"{row_id:05d}", row_id))
            cursor.execute("UPDATE phones SET barcode = ID_phone WHERE barcode IS NULL OR TRIM(COALESCE(barcode,'')) = ''")

            cursor.execute("UPDATE accessories SET quantity = 1 WHERE quantity IS NULL")
            cursor.execute("UPDATE accessories SET price = 0 WHERE price IS NULL")
            cursor.execute("UPDATE accessories SET available = CASE WHEN COALESCE(quantity,0) <= 0 THEN 0 ELSE 1 END WHERE available IS NULL")
            cursor.execute("UPDATE accessories SET date_added = datetime('now') WHERE date_added IS NULL OR TRIM(COALESCE(date_added,'')) = ''")
            cursor.execute("SELECT id FROM accessories WHERE SKU IS NULL OR TRIM(COALESCE(SKU,'')) = ''")
            for (row_id,) in cursor.fetchall():
                cursor.execute("UPDATE accessories SET SKU = ? WHERE id = ?", (f"ACC{row_id:05d}", row_id))
            cursor.execute("UPDATE accessories SET barcode = SKU WHERE barcode IS NULL OR TRIM(COALESCE(barcode,'')) = ''")

            cursor.execute("UPDATE sales SET product_type = 'phone' WHERE product_type IS NULL OR TRIM(COALESCE(product_type,'')) = ''")
            cursor.execute("UPDATE sales SET product_id = phone_id WHERE product_id IS NULL AND phone_id IS NOT NULL")
            cursor.execute("UPDATE sales SET sale_qty = 1 WHERE sale_qty IS NULL OR sale_qty <= 0")
            cursor.execute("UPDATE sales SET sale_unit_price = sale_price WHERE sale_unit_price IS NULL")
            cursor.execute("UPDATE sales SET sale_total = sale_price WHERE sale_total IS NULL")
            cursor.execute("UPDATE sales SET sale_price = sale_total WHERE sale_price IS NULL")
            cursor.execute("UPDATE sales SET sale_date = datetime('now') WHERE sale_date IS NULL OR TRIM(COALESCE(sale_date,'')) = ''")

            # Backfill snapshots for existing sales where possible.
            cursor.execute("""
                UPDATE sales
                SET product_ref = (SELECT ID_phone FROM phones p WHERE p.id = sales.product_id),
                    product_brand_snapshot = (SELECT brand FROM phones p WHERE p.id = sales.product_id),
                    product_model_snapshot = (SELECT model FROM phones p WHERE p.id = sales.product_id),
                    product_imei_snapshot = (SELECT imei FROM phones p WHERE p.id = sales.product_id),
                    product_name_snapshot = (SELECT COALESCE(brand,'') || ' ' || COALESCE(model,'') FROM phones p WHERE p.id = sales.product_id)
                WHERE product_type = 'phone' AND product_id IS NOT NULL AND product_name_snapshot IS NULL
            """)
            cursor.execute("""
                UPDATE sales
                SET product_ref = (SELECT SKU FROM accessories a WHERE a.id = sales.product_id),
                    product_brand_snapshot = (SELECT brand FROM accessories a WHERE a.id = sales.product_id),
                    product_model_snapshot = (SELECT COALESCE(model, name) FROM accessories a WHERE a.id = sales.product_id),
                    product_name_snapshot = (SELECT name FROM accessories a WHERE a.id = sales.product_id)
                WHERE product_type = 'accessory' AND product_id IS NOT NULL AND product_name_snapshot IS NULL
            """)
            cursor.execute("""
                UPDATE sales
                SET buyer_name_snapshot = (SELECT name FROM buyers b WHERE b.id = sales.buyer_id),
                    buyer_contact_snapshot = (SELECT contact_info FROM buyers b WHERE b.id = sales.buyer_id)
                WHERE buyer_id IS NOT NULL AND buyer_name_snapshot IS NULL
            """)

            # Create default users if missing. New installs use hashed passwords;
            # old plain-text rows remain login-compatible and are upgraded on login.
            cursor.execute("SELECT * FROM users WHERE username = ?", ("admin",))
            if not cursor.fetchone():
                cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                            ("admin", hash_password("admin123"), "admin"))
            cursor.execute("SELECT * FROM users WHERE username = ?", ("vendeur",))
            if not cursor.fetchone():
                cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                            ("vendeur", hash_password("vendeur123"), "vendor"))

            conn.commit()
        except Exception as e:
            messagebox.showerror("Database Error", f"Failed to initialize database: {e}")
        finally:
            if conn:
                conn.close()


    def generate_phone_id(self):
        """Générer un ID de téléphone unique avec seulement des chiffres"""
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()

            # Obtenir le nombre de téléphones existants
            cursor.execute("SELECT COUNT(*) FROM phones")
            count = cursor.fetchone()[0]
            conn.close()

            # Générer l'ID avec seulement des chiffres (5 chiffres minimum)
            next_id = count + 1
            phone_id = f"{next_id:05d}"  # Format: 00001, 00002, etc.

            # Vérifier que l'ID n'existe pas déjà (peu probable mais possible)
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM phones WHERE ID_phone = ?", (phone_id,))
            existing = cursor.fetchone()
            conn.close()

            # Si par hasard il existe, essayer un nombre aléatoire
            if existing:
                import random
                while True:
                    random_num = random.randint(1, 99999)
                    phone_id = f"{random_num:05d}"
                    conn = sqlite3.connect(DB_PATH)
                    cursor = conn.cursor()
                    cursor.execute("SELECT id FROM phones WHERE ID_phone = ?", (phone_id,))
                    if not cursor.fetchone():
                        conn.close()
                        break
                    conn.close()

            return phone_id
        except Exception as e:
            print(f"Error generating phone ID: {e}")
            return "00001"  # Fallback
        

    def generate_accessory_sku(self):
        """Generate a unique accessory SKU used for barcode/scanner lookup."""
        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM accessories")
            next_num = (cursor.fetchone()[0] or 0) + 1
            while True:
                sku = f"ACC{next_num:05d}"
                cursor.execute("SELECT id FROM accessories WHERE SKU = ?", (sku,))
                if not cursor.fetchone():
                    conn.close()
                    return sku
                next_num += 1
        except Exception as e:
            print(f"Error generating accessory SKU: {e}")
            return "ACC00001"


    def show_login_screen(self):
        for widget in self.main_frame.winfo_children():
            widget.destroy()

        container = ttk.Frame(self.main_frame, style="Main.TFrame")
        container.place(relx=0.5, rely=0.5, anchor="center")

        title_label = ttk.Label(container, text="Gestionnaire de Magasin de Téléphones", style="Title.TLabel")
        title_label.pack(pady=(0, 24))

        login_card = ttk.Labelframe(container, text="Connexion", padding=28, style="TLabelframe")
        login_card.pack(pady=12)

        ttk.Label(login_card, text="Nom d'utilisateur", style="TLabel").pack(anchor="w", pady=(0, 6))
        self.username_entry = ttk.Entry(login_card, width=36)
        self.username_entry.pack(pady=(0, 12), ipady=8)

        ttk.Label(login_card, text="Mot de passe", style="TLabel").pack(anchor="w", pady=(0, 6))
        self.password_entry = ttk.Entry(login_card, show="*", width=36)
        self.password_entry.pack(pady=(0, 16), ipady=8)

        login_btn = ttk.Button(login_card, text="CONNEXION", command=self.login, bootstyle="primary")
        login_btn.pack(fill="x", ipady=8)

        info_label = ttk.Label(login_card, text="Par défaut: admin / admin123", foreground=self.muted_text, font=("Segoe UI", 9))
        info_label.pack(pady=(12, 0))

        self.username_entry.focus()
        self.root.bind('<Return>', lambda event: self.login())

    def login(self):
        username = self.username_entry.get().strip()
        password = self.password_entry.get().strip()
        if not username or not password:
            messagebox.showerror("Erreur", "Veuillez entrer le nom d'utilisateur et le mot de passe.")
            return
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id, username, password, role FROM users WHERE username = ?", (username,))
        user = cursor.fetchone()
        if user and verify_password(user[2], password):
            if not str(user[2]).startswith("pbkdf2_sha256$"):
                cursor.execute("UPDATE users SET password = ? WHERE id = ?", (hash_password(password), user[0]))
                conn.commit()
            conn.close()
            self.current_user = {'id': user[0], 'username': user[1], 'role': user[3]}
            try:
                self.root.unbind('<Return>')
            except Exception:
                pass
            self.show_main_dashboard()
        else:
            conn.close()
            messagebox.showerror("Erreur", "Nom d'utilisateur ou mot de passe invalide.")

    def show_main_dashboard(self):
        for widget in self.main_frame.winfo_children():
            widget.destroy()

        header_frame = ttk.Frame(self.main_frame, style="Main.TFrame")
        header_frame.pack(fill=tk.X, pady=(0, 18))

        welcome_label = ttk.Label(header_frame, text=f"Bienvenue, {self.current_user['username']}!", style="Heading.TLabel")
        welcome_label.pack(side=tk.LEFT)

        user_frame = ttk.Frame(header_frame, style="Main.TFrame")
        user_frame.pack(side=tk.RIGHT)

        role_label = ttk.Label(user_frame, text=f"Rôle: {self.current_user['role'].title()}", style="TLabel")
        role_label.pack(side=tk.LEFT, padx=(0, 14))

        logout_btn = ttk.Button(user_frame, text="Déconnexion", command=self.show_login_screen)
        logout_btn.pack(side=tk.LEFT)

        scan_btn = self.icon_button(user_frame, "Scanner Code-Barres", "scan", command=self.scan_barcode_dialog, bootstyle="primary-outline")
        scan_btn.pack(side=tk.LEFT, padx=(8, 0))

        # Notebook
        self.notebook = ttk.Notebook(self.main_frame)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Create all frames first
        self.phones_frame = ttk.Frame(self.notebook, style="Main.TFrame", padding=6)
        self.sales_frame = ttk.Frame(self.notebook, style="Main.TFrame", padding=6)
        self.reports_frame = ttk.Frame(self.notebook, style="Main.TFrame", padding=6)
        self.accessories_frame = ttk.Frame(self.notebook, style="Main.TFrame", padding=6)
        self.settings_frame = ttk.Frame(self.notebook, style="Main.TFrame", padding=6)

        # Add tabs in the desired order
        self.add_tab(self.phones_frame, "Inventaire", "phone")
        self.add_tab(self.sales_frame, "Ventes", "sales")
        self.add_tab(self.reports_frame, "Rapports", "reports")
        self.add_tab(self.accessories_frame, "Accessoires", "accessory")
        self.add_tab(self.settings_frame, "Paramètres", "settings")

        # Populate the frames
        self.setup_phones_section()
        self.setup_sales_section()
        self.setup_reports_section()
        self.setup_accessories_section()
        self.setup_settings_section()
        

    def setup_phones_section(self):
        toolbar = ttk.Frame(self.phones_frame, style="Main.TFrame")
        toolbar.pack(fill=tk.X, pady=(0, 16))

        search_frame = ttk.Labelframe(toolbar, text="Recherche & Filtre", padding=12, style="TLabelframe")
        search_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 12))

        search_inner = ttk.Frame(search_frame, style="Main.TFrame")
        search_inner.pack(fill=tk.X)

        self.phone_search_var = tk.StringVar()
        search_entry = ttk.Entry(search_inner, textvariable=self.phone_search_var, width=36)
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8), ipady=6)
        search_entry.bind("<Return>", lambda _e: self.search_phones())

        search_btn = self.icon_button(search_inner, "Rechercher", "search", command=self.search_phones)
        search_btn.pack(side=tk.LEFT, padx=(0, 8))

        clear_btn = ttk.Button(search_inner, text="Effacer", command=self.clear_search)
        clear_btn.pack(side=tk.LEFT)

        # availability filter
        self.available_filter = tk.StringVar(value="all")
        available_frame = ttk.Frame(search_inner, style="Main.TFrame")
        available_frame.pack(side=tk.LEFT, padx=(16, 0))
        ttk.Radiobutton(available_frame, text="Tous", variable=self.available_filter, value="all",
                        command=self.load_phones_data).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Radiobutton(available_frame, text="Disponibles", variable=self.available_filter, value="available",
                        command=self.load_phones_data).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Radiobutton(available_frame, text="Vendus", variable=self.available_filter, value="sold",
                        command=self.load_phones_data).pack(side=tk.LEFT)

        if self.current_user['role'] == 'admin':
            actions_frame = ttk.Labelframe(toolbar, text="Actions", padding=12, style="TLabelframe")
            actions_frame.pack(side=tk.RIGHT)
            add_btn = self.icon_button(actions_frame, "Ajouter Téléphone", "plus", command=self.add_phone_dialog, bootstyle="primary")
            add_btn.pack()

        list_frame = ttk.Labelframe(self.phones_frame, text="Inventaire des Téléphones", padding=12, style="TLabelframe")
        list_frame.pack(fill=tk.BOTH, expand=True)

        # add 'Batterie' column before price
        columns = ("ID", "ID Téléphone", "Marque", "Modèle", "IMEI", "Batterie", "Prix", "Statut", "Actions")
        self.phones_tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=18)
        self.phones_tree.column("ID", width=50, anchor="center")
        self.phones_tree.column("ID Téléphone", width=100)
        self.phones_tree.column("Marque", width=120)
        self.phones_tree.column("Modèle", width=180)
        self.phones_tree.column("IMEI", width=150)
        self.phones_tree.column("Batterie", width=90, anchor="center")
        self.phones_tree.column("Prix", width=100, anchor="e")
        self.phones_tree.column("Statut", width=90, anchor="center")
        self.phones_tree.column("Actions", width=160, anchor="center")
        for col in columns:
            self.phones_tree.heading(col, text=col)

        v_scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.phones_tree.yview)
        h_scrollbar = ttk.Scrollbar(list_frame, orient=tk.HORIZONTAL, command=self.phones_tree.xview)
        self.phones_tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)
        self.phones_tree.grid(row=0, column=0, sticky="nsew")
        v_scrollbar.grid(row=0, column=1, sticky="ns")
        h_scrollbar.grid(row=1, column=0, sticky="ew")
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)

        # bindings
        self.phones_tree.bind("<Button-3>", self.show_phone_context_menu)
        self.phones_tree.bind("<ButtonRelease-1>", self.on_phone_click)
        self.phones_tree.bind("<Double-1>", self.show_phone_details)

        self.load_phones_data()


    def setup_accessories_section(self):
        # Clear any existing widgets from the frame before drawing
        for widget in self.accessories_frame.winfo_children():
            widget.destroy()

        toolbar = ttk.Frame(self.accessories_frame, style="Main.TFrame")
        toolbar.pack(fill=tk.X, pady=(0, 14))

        search_frame = ttk.Labelframe(toolbar, text="Recherche & Filtre", padding=12, style="TLabelframe")
        search_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 12))

        search_inner = ttk.Frame(search_frame, style="Main.TFrame")
        search_inner.pack(fill=tk.X)

        self.accessory_search_var = tk.StringVar()
        search_entry = ttk.Entry(search_inner, textvariable=self.accessory_search_var, width=36)
        search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8), ipady=6)
        search_entry.bind("<Return>", lambda _e: self.search_accessories())

        self.icon_button(search_inner, "Rechercher", "search", command=self.search_accessories).pack(side=tk.LEFT, padx=(0, 8))
        self.icon_button(search_inner, "Effacer", "clear", command=self.clear_accessory_search).pack(side=tk.LEFT)

        self.accessory_filter = tk.StringVar(value="all")
        available_frame = ttk.Frame(search_inner, style="Main.TFrame")
        available_frame.pack(side=tk.LEFT, padx=(16, 0))
        ttk.Radiobutton(available_frame, text="Tous", variable=self.accessory_filter, value="all", command=self.load_accessories_data).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Radiobutton(available_frame, text="Disponible", variable=self.accessory_filter, value="available", command=self.load_accessories_data).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Radiobutton(available_frame, text="Rupture", variable=self.accessory_filter, value="sold", command=self.load_accessories_data).pack(side=tk.LEFT)

        actions = ttk.Labelframe(toolbar, text="Actions", padding=12, style="TLabelframe")
        actions.pack(side=tk.RIGHT)
        add_btn = self.icon_button(actions, "Ajouter Accessoire", "plus", command=self.add_accessory_dialog, bootstyle="primary")
        add_btn.pack()
        if not (self.current_user and self.current_user.get('role') == 'admin'):
            try:
                add_btn.state(['disabled'])
            except Exception:
                pass

        list_frame = ttk.Labelframe(self.accessories_frame, text="Liste des Accessoires", padding=12, style="TLabelframe")
        list_frame.pack(fill=tk.BOTH, expand=True)
        columns = ("ID", "Code", "Type", "Marque", "Modèle", "Quantité", "Prix", "Prix Achat Unité", "Prix Achat Total", "Statut", "Actions")
        self.accessories_tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=18)
        widths = {"ID":55, "Code":120, "Type":150, "Marque":120, "Modèle":140, "Quantité":85, "Prix":100, "Prix Achat Unité":125, "Prix Achat Total":125, "Statut":100, "Actions":95}
        for col in columns:
            self.accessories_tree.heading(col, text=col)
            anchor = "center" if col in ("ID", "Quantité", "Statut", "Actions") else ("e" if col in ("Prix", "Prix Achat Unité", "Prix Achat Total") else "w")
            self.accessories_tree.column(col, width=widths.get(col, 100), anchor=anchor, stretch=col not in ("ID", "Actions"))
        v_scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.accessories_tree.yview)
        h_scrollbar = ttk.Scrollbar(list_frame, orient=tk.HORIZONTAL, command=self.accessories_tree.xview)
        self.accessories_tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)
        self.accessories_tree.grid(row=0, column=0, sticky="nsew")
        v_scrollbar.grid(row=0, column=1, sticky="ns")
        h_scrollbar.grid(row=1, column=0, sticky="ew")
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)
        self.accessories_tree.bind("<Double-1>", self.show_accessory_from_tree)
        self.load_accessories_data()

    def load_accessories_data(self):
        for item in self.accessories_tree.get_children():
            self.accessories_tree.delete(item)
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        base_q = """
            SELECT id, COALESCE(NULLIF(TRIM(barcode), ''), SKU) AS code, name, brand, model,
                   COALESCE(quantity,0), price, seller_price, seller_total_price
            FROM accessories
        """
        params = []
        conditions = []
        if self.accessory_search_var.get().strip():
            q = f"%{self.accessory_search_var.get().strip().lower()}%"
            conditions.append("(LOWER(COALESCE(SKU,'')) LIKE ? OR LOWER(COALESCE(barcode,'')) LIKE ? OR LOWER(COALESCE(name,'')) LIKE ? OR LOWER(COALESCE(brand,'')) LIKE ? OR LOWER(COALESCE(model,'')) LIKE ?)")
            params.extend([q, q, q, q, q])
        if self.accessory_filter.get() == "available":
            conditions.append("COALESCE(quantity,0) > 0")
        elif self.accessory_filter.get() == "sold":
            conditions.append("COALESCE(quantity,0) <= 0")
        if conditions:
            base_q += " WHERE " + " AND ".join(conditions)
        base_q += " ORDER BY id DESC"
        cursor.execute(base_q, params)
        rows = cursor.fetchall()
        conn.close()
        for r in rows:
            qty = r[5] or 0
            status = "Disponible" if qty > 0 else "Rupture"
            seller_unit = f"{(r[7] or 0):.2f} MAD" if r[7] is not None else "-"
            seller_total = f"{(r[8] or 0):.2f} MAD" if r[8] is not None else "-"
            self.accessories_tree.insert("", tk.END, values=(r[0], r[1] or "-", r[2] or "-", r[3] or "-", r[4] or "-", qty, f"{(r[6] or 0):.2f} MAD", seller_unit, seller_total, status, "Voir"))
        if not rows:
            self.accessories_tree.insert("", tk.END, values=("", "", "Aucun accessoire trouvé", "", "", "", "", "", "", "", ""))

    def add_accessory_dialog(self):
        if not (self.current_user and self.current_user.get('role') == 'admin'):
            messagebox.showwarning("Accès Refusé", "Seuls les administrateurs peuvent ajouter des accessoires.")
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Ajouter un Accessoire")
        dialog.geometry("660x650")
        dialog.transient(self.root)
        dialog.grab_set()
        self.center_window(dialog)

        container = ttk.Frame(dialog, style="Main.TFrame")
        container.pack(fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(container, bg=self.bg_color, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient=tk.VERTICAL, command=canvas.yview)
        scrollable = ttk.Frame(canvas, style="Main.TFrame")
        scrollable.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable, anchor="nw", width=630)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        title = ttk.Label(scrollable, text="Ajouter un Accessoire", style="Heading.TLabel")
        title.pack(anchor="w", pady=(14, 12), padx=18)

        form = ttk.Labelframe(scrollable, text="Informations Accessoire", padding=14, style="TLabelframe")
        form.pack(fill=tk.X, padx=18, pady=(0, 12))
        form.columnconfigure(1, weight=1)

        def add_entry(row, label, required=False):
            ttk.Label(form, text=f"{label}{' *' if required else ''}").grid(row=row, column=0, sticky="w", pady=6, padx=(0, 12))
            entry = ttk.Entry(form)
            entry.grid(row=row, column=1, sticky="ew", pady=6)
            return entry

        type_entry = add_entry(0, "Type", True)
        brand_entry = add_entry(1, "Marque")
        model_entry = add_entry(2, "Modèle")

        ttk.Label(form, text="Code-Barres / SKU").grid(row=3, column=0, sticky="w", pady=6, padx=(0, 12))
        barcode_container = ttk.Frame(form)
        barcode_container.grid(row=3, column=1, sticky="ew", pady=6)
        barcode_container.columnconfigure(0, weight=1)
        barcode_entry = ttk.Entry(barcode_container)
        barcode_entry.grid(row=0, column=0, sticky="ew")
        self.icon_button(barcode_container, "Scan", "scan", command=barcode_entry.focus_set).grid(row=0, column=1, padx=(8, 0))
        ttk.Label(form, text="Scannez le code dans ce champ. Si vide, un SKU automatique sera utilisé.", foreground=self.muted_text, font=("Segoe UI", 9)).grid(row=4, column=1, sticky="w", pady=(0, 6))

        price_entry = add_entry(5, "Prix de Vente", True)
        qty_entry = add_entry(6, "Quantité")
        qty_entry.insert(0, "1")

        ttk.Label(form, text="Description").grid(row=7, column=0, sticky="nw", pady=6, padx=(0, 12))
        desc_text = scrolledtext.ScrolledText(form, width=40, height=4, font=("Segoe UI", 10), bg=self.surface_color, fg="#111111", wrap=tk.WORD)
        desc_text.grid(row=7, column=1, sticky="ew", pady=6)

        seller_form = ttk.Labelframe(scrollable, text="Informations Vendeur", padding=14, style="TLabelframe")
        seller_form.pack(fill=tk.X, padx=18, pady=(0, 12))
        seller_form.columnconfigure(1, weight=1)

        def add_seller(row, label):
            ttk.Label(seller_form, text=label).grid(row=row, column=0, sticky="w", pady=6, padx=(0, 12))
            entry = ttk.Entry(seller_form)
            entry.grid(row=row, column=1, sticky="ew", pady=6)
            return entry

        seller_name = add_seller(0, "Nom Vendeur")
        seller_contact = add_seller(1, "Contact Vendeur")
        seller_unit_price = add_seller(2, "Prix d'achat (unité)")
        seller_total_price_entry = add_seller(3, "Prix d'achat (total)")

        def compute_total(_=None):
            try:
                unit = float(seller_unit_price.get().strip() or 0)
                qty = int(qty_entry.get().strip() or 1)
                seller_total_price_entry.delete(0, tk.END)
                seller_total_price_entry.insert(0, f"{unit * qty:.2f}")
            except Exception:
                seller_total_price_entry.delete(0, tk.END)
        seller_unit_price.bind("<KeyRelease>", compute_total)
        qty_entry.bind("<KeyRelease>", compute_total)

        btn_frame = ttk.Frame(scrollable, style="Main.TFrame")
        btn_frame.pack(fill=tk.X, pady=(4, 18), padx=18)
        ttk.Button(btn_frame, text="Annuler", command=dialog.destroy).pack(side=tk.RIGHT, padx=(8, 0))

        def on_save():
            t = type_entry.get().strip()
            price = price_entry.get().strip()
            scanned_barcode = barcode_entry.get().strip()
            if not t or not price:
                messagebox.showwarning("Avertissement", "Type et prix sont requis.")
                return
            try:
                price_val = float(price)
            except Exception:
                messagebox.showwarning("Avertissement", "Le prix doit être un nombre.")
                return
            try:
                qty_val = int(qty_entry.get().strip() or 1)
            except Exception:
                qty_val = 1
            if qty_val < 0:
                messagebox.showwarning("Avertissement", "La quantité ne peut pas être négative.")
                return
            try:
                seller_unit = float(seller_unit_price.get().strip()) if seller_unit_price.get().strip() else None
            except Exception:
                seller_unit = None
            try:
                seller_total = float(seller_total_price_entry.get().strip()) if seller_total_price_entry.get().strip() else (seller_unit * qty_val if seller_unit is not None else None)
            except Exception:
                seller_total = None

            sku = self.generate_accessory_sku()
            barcode_data = scanned_barcode or sku
            conflict = self.barcode_conflict(barcode_data)
            if conflict:
                messagebox.showerror("Code-Barres déjà utilisé", conflict)
                return

            barcode_filepath = None
            try:
                barcode_img = self.create_barcode_with_text(barcode_data, t)
                safe_name = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in f"{barcode_data}_{t}")
                barcode_filepath = os.path.join(self.barcode_folder, f"{safe_name}.png")
                barcode_img.save(barcode_filepath)
            except Exception as e:
                print(f"Accessory barcode generation skipped: {e}")

            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO accessories (SKU, name, brand, model, price, quantity, description, barcode, barcode_file_path, seller_name, seller_contact, seller_price, seller_total_price, available)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (sku, t, brand_entry.get().strip(), model_entry.get().strip(), price_val, qty_val, desc_text.get("1.0", tk.END).strip(), barcode_data, barcode_filepath, seller_name.get().strip(), seller_contact.get().strip(), seller_unit, seller_total, 1 if qty_val > 0 else 0))
            conn.commit()
            conn.close()
            messagebox.showinfo("Succès", "Accessoire ajouté.")
            dialog.destroy()
            self.load_accessories_data()

        self.icon_button(btn_frame, "Enregistrer", "save", command=on_save, bootstyle="primary").pack(side=tk.RIGHT)
        type_entry.focus()

    def show_accessory_from_tree(self, event):
        sel = self.accessories_tree.selection()
        if not sel:
            return
        item = self.accessories_tree.item(sel[0])
        accessory_id = item['values'][0]
        if not accessory_id:
            return
        self.show_accessory_details(accessory_id)


    def show_accessory_details(self, accessory_id):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, SKU, COALESCE(NULLIF(TRIM(barcode), ''), SKU) AS code, name, brand, model,
                   price, COALESCE(quantity,0), description, COALESCE(seller_name,''),
                   COALESCE(seller_contact,''), seller_price, seller_total_price,
                   COALESCE(available,1), barcode_file_path
            FROM accessories WHERE id = ? LIMIT 1
        """, (accessory_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            messagebox.showerror("Erreur", "Accessoire introuvable.")
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Détails Accessoire")
        dialog.geometry("760x520")
        dialog.transient(self.root)
        dialog.grab_set()
        self.center_window(dialog)

        main = ttk.Frame(dialog, padding=18, style="Main.TFrame")
        main.pack(fill=tk.BOTH, expand=True)
        ttk.Label(main, text=row[3] or "Accessoire", style="Heading.TLabel").pack(anchor="w", pady=(0, 12))

        content = ttk.Frame(main, style="Main.TFrame")
        content.pack(fill=tk.BOTH, expand=True)

        left = ttk.Labelframe(content, text="Code-Barres", padding=12, style="TLabelframe")
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 16))
        left.configure(width=250)
        left.pack_propagate(False)

        barcode_path = row[14]
        if barcode_path and os.path.exists(barcode_path):
            try:
                barcode_image = Image.open(barcode_path)
                barcode_image.thumbnail((220, 150))
                barcode_photo = ImageTk.PhotoImage(barcode_image)
                barcode_label = tk.Label(left, image=barcode_photo, bg=self.bg_color)
                barcode_label.image = barcode_photo
                barcode_label.pack(pady=(0, 10))
            except Exception:
                ttk.Label(left, text="Image non disponible").pack(pady=(0, 10))
        ttk.Label(left, text=f"Code: {row[2] or '-'}", wraplength=220).pack(anchor="w", pady=(0, 6))
        ttk.Label(left, text=f"SKU: {row[1] or '-'}", wraplength=220, foreground=self.muted_text).pack(anchor="w")
        self.icon_button(left, "Voir / Imprimer", "view", command=lambda: self.show_barcode_modal(barcode_path), bootstyle="primary-outline").pack(fill=tk.X, pady=(14, 0))

        right = ttk.Frame(content, style="Main.TFrame")
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        details = ttk.Labelframe(right, text="Informations Accessoire", padding=12, style="TLabelframe")
        details.pack(fill=tk.X, pady=(0, 12))
        detail_rows = [
            ("Type", row[3] or "-"),
            ("Marque", row[4] or "-"),
            ("Modèle", row[5] or "-"),
            ("Prix de vente", f"{(row[6] or 0):.2f} MAD"),
            ("Quantité", str(row[7] or 0)),
            ("Statut", "Disponible" if (row[7] or 0) > 0 and (row[13] or 0) else "Rupture"),
        ]
        for i, (label, value) in enumerate(detail_rows):
            ttk.Label(details, text=f"{label}:", width=18, font=("Segoe UI", 10, "bold")).grid(row=i, column=0, sticky="w", pady=3)
            ttk.Label(details, text=value).grid(row=i, column=1, sticky="w", pady=3)
        details.columnconfigure(1, weight=1)

        seller = ttk.Labelframe(right, text="Informations Vendeur", padding=12, style="TLabelframe")
        seller.pack(fill=tk.X, pady=(0, 12))
        seller_rows = [
            ("Nom", row[9] or "-"),
            ("Contact", row[10] or "-"),
            ("Prix achat unité", f"{row[11]:.2f} MAD" if row[11] is not None else "-"),
            ("Prix achat total", f"{row[12]:.2f} MAD" if row[12] is not None else "-"),
        ]
        for i, (label, value) in enumerate(seller_rows):
            ttk.Label(seller, text=f"{label}:", width=18, font=("Segoe UI", 10, "bold")).grid(row=i, column=0, sticky="w", pady=3)
            ttk.Label(seller, text=value).grid(row=i, column=1, sticky="w", pady=3)
        seller.columnconfigure(1, weight=1)

        if row[8]:
            desc_box = ttk.Labelframe(right, text="Description", padding=8, style="TLabelframe")
            desc_box.pack(fill=tk.BOTH, expand=True)
            desc = tk.Text(desc_box, height=4, wrap=tk.WORD, bg=self.surface_color, relief=tk.FLAT, font=("Segoe UI", 10))
            desc.insert("1.0", row[8] or "")
            desc.config(state=tk.DISABLED)
            desc.pack(fill=tk.BOTH, expand=True)

        btn_frame = ttk.Frame(main, style="Main.TFrame")
        btn_frame.pack(fill=tk.X, pady=(14, 0))
        if (row[7] or 0) > 0 and (row[13] or 0):
            self.icon_button(btn_frame, "Vendre", "sell", command=lambda: self.sell_accessory_dialog(accessory_id, dialog), bootstyle="success").pack(side=tk.LEFT, padx=(0, 8))
        if self.current_user and self.current_user.get('role') == 'admin':
            self.icon_button(btn_frame, "Modifier", "edit", command=lambda: self.edit_accessory_dialog(accessory_id, dialog), bootstyle="warning").pack(side=tk.LEFT, padx=(0, 8))
            self.icon_button(btn_frame, "Supprimer", "delete", command=lambda: self.delete_accessory(accessory_id, dialog), bootstyle="danger").pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="Fermer", command=dialog.destroy).pack(side=tk.RIGHT)

    def delete_accessory(self, accessory_id, parent_dialog=None):
        """Delete an accessory safely. Sale snapshots remain in the sales table."""
        if not (self.current_user and self.current_user.get('role') == 'admin'):
            messagebox.showwarning("Accès Refusé", "Seuls les administrateurs peuvent supprimer des accessoires.")
            return

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT name, barcode_file_path FROM accessories WHERE id = ?", (accessory_id,))
        row = cursor.fetchone()
        if not row:
            conn.close()
            messagebox.showerror("Erreur", "Accessoire introuvable.")
            return

        name, barcode_path = row
        if not messagebox.askyesno("Confirmer la Suppression", f"Supprimer l'accessoire '{name or accessory_id}' ?"):
            conn.close()
            return

        try:
            cursor.execute("DELETE FROM accessories WHERE id = ?", (accessory_id,))
            conn.commit()
        finally:
            conn.close()

        if barcode_path and os.path.exists(barcode_path):
            try:
                os.remove(barcode_path)
            except Exception:
                pass

        if parent_dialog:
            try:
                parent_dialog.destroy()
            except Exception:
                pass
        self.load_accessories_data()
        try:
            self.load_recent_sales()
        except Exception:
            pass
        messagebox.showinfo("Succès", "Accessoire supprimé.")


    def edit_accessory_dialog(self, accessory_id, parent_dialog=None):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name, brand, model, price, COALESCE(quantity,0), description, seller_name,
                   seller_contact, seller_price, seller_total_price, SKU,
                   COALESCE(NULLIF(TRIM(barcode), ''), SKU), barcode_file_path
            FROM accessories WHERE id = ?
        """, (accessory_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            messagebox.showerror("Erreur", "Accessoire introuvable.")
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Modifier Accessoire")
        dialog.geometry("660x650")
        dialog.transient(self.root)
        dialog.grab_set()
        self.center_window(dialog)

        container = ttk.Frame(dialog, style="Main.TFrame")
        container.pack(fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(container, bg=self.bg_color, highlightthickness=0)
        scrollbar = ttk.Scrollbar(container, orient=tk.VERTICAL, command=canvas.yview)
        scrollable = ttk.Frame(canvas, style="Main.TFrame")
        scrollable.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=scrollable, anchor="nw", width=630)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        ttk.Label(scrollable, text="Modifier Accessoire", style="Heading.TLabel").pack(anchor="w", pady=(14, 12), padx=18)

        form = ttk.Labelframe(scrollable, text="Informations Accessoire", padding=14, style="TLabelframe")
        form.pack(fill=tk.X, padx=18, pady=(0, 12))
        form.columnconfigure(1, weight=1)

        def add_entry(row_index, label, value="", required=False):
            ttk.Label(form, text=f"{label}{' *' if required else ''}").grid(row=row_index, column=0, sticky="w", pady=6, padx=(0, 12))
            entry = ttk.Entry(form)
            entry.insert(0, value or "")
            entry.grid(row=row_index, column=1, sticky="ew", pady=6)
            return entry

        type_entry = add_entry(0, "Type", row[0], True)
        brand_entry = add_entry(1, "Marque", row[1])
        model_entry = add_entry(2, "Modèle", row[2])

        ttk.Label(form, text="Code-Barres / SKU").grid(row=3, column=0, sticky="w", pady=6, padx=(0, 12))
        barcode_container = ttk.Frame(form)
        barcode_container.grid(row=3, column=1, sticky="ew", pady=6)
        barcode_container.columnconfigure(0, weight=1)
        barcode_entry = ttk.Entry(barcode_container)
        barcode_entry.insert(0, row[11] or "")
        barcode_entry.grid(row=0, column=0, sticky="ew")
        self.icon_button(barcode_container, "Scan", "scan", command=barcode_entry.focus_set).grid(row=0, column=1, padx=(8, 0))
        ttk.Label(form, text=f"SKU interne: {row[10] or '-'}", foreground=self.muted_text, font=("Segoe UI", 9)).grid(row=4, column=1, sticky="w", pady=(0, 6))

        price_entry = add_entry(5, "Prix de Vente", str(row[3] or ""), True)
        qty_entry = add_entry(6, "Quantité", str(row[4] or 0))

        ttk.Label(form, text="Description").grid(row=7, column=0, sticky="nw", pady=6, padx=(0, 12))
        desc_text = scrolledtext.ScrolledText(form, width=40, height=4, font=("Segoe UI", 10), bg=self.surface_color, fg="#111111", wrap=tk.WORD)
        desc_text.insert("1.0", row[5] or "")
        desc_text.grid(row=7, column=1, sticky="ew", pady=6)

        seller_form = ttk.Labelframe(scrollable, text="Informations Vendeur", padding=14, style="TLabelframe")
        seller_form.pack(fill=tk.X, padx=18, pady=(0, 12))
        seller_form.columnconfigure(1, weight=1)

        def add_seller(row_index, label, value=""):
            ttk.Label(seller_form, text=label).grid(row=row_index, column=0, sticky="w", pady=6, padx=(0, 12))
            entry = ttk.Entry(seller_form)
            entry.insert(0, value or "")
            entry.grid(row=row_index, column=1, sticky="ew", pady=6)
            return entry

        seller_name = add_seller(0, "Nom Vendeur", row[6])
        seller_contact = add_seller(1, "Contact Vendeur", row[7])
        seller_unit_price = add_seller(2, "Prix d'achat (unité)", str(row[8] or ""))
        seller_total_price_entry = add_seller(3, "Prix d'achat (total)", str(row[9] or ""))

        def compute_total(_=None):
            try:
                unit = float(seller_unit_price.get().strip() or 0)
                qty = int(qty_entry.get().strip() or 1)
                seller_total_price_entry.delete(0, tk.END)
                seller_total_price_entry.insert(0, f"{unit * qty:.2f}")
            except Exception:
                seller_total_price_entry.delete(0, tk.END)
        seller_unit_price.bind("<KeyRelease>", compute_total)
        qty_entry.bind("<KeyRelease>", compute_total)

        btn_frame = ttk.Frame(scrollable, style="Main.TFrame")
        btn_frame.pack(fill=tk.X, pady=(4, 18), padx=18)
        ttk.Button(btn_frame, text="Annuler", command=dialog.destroy).pack(side=tk.RIGHT, padx=(8, 0))

        def on_update():
            t = type_entry.get().strip()
            price = price_entry.get().strip()
            barcode_data = barcode_entry.get().strip() or row[10] or self.generate_accessory_sku()
            if not t or not price:
                messagebox.showwarning("Avertissement", "Type et prix sont requis.")
                return
            try:
                price_val = float(price)
            except Exception:
                messagebox.showwarning("Avertissement", "Le prix doit être un nombre.")
                return
            try:
                qty_val = int(qty_entry.get().strip() or 0)
            except Exception:
                qty_val = 0
            if qty_val < 0:
                messagebox.showwarning("Avertissement", "La quantité ne peut pas être négative.")
                return
            conflict = self.barcode_conflict(barcode_data, ignore_accessory_id=accessory_id)
            if conflict:
                messagebox.showerror("Code-Barres déjà utilisé", conflict)
                return
            try:
                seller_unit = float(seller_unit_price.get().strip()) if seller_unit_price.get().strip() else None
            except Exception:
                seller_unit = None
            try:
                seller_total = float(seller_total_price_entry.get().strip()) if seller_total_price_entry.get().strip() else (seller_unit * qty_val if seller_unit is not None else None)
            except Exception:
                seller_total = None

            barcode_filepath = row[12]
            if barcode_data != (row[11] or "") or not barcode_filepath or not os.path.exists(barcode_filepath):
                try:
                    barcode_img = self.create_barcode_with_text(barcode_data, t)
                    safe_name = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in f"{barcode_data}_{t}")
                    barcode_filepath = os.path.join(self.barcode_folder, f"{safe_name}.png")
                    barcode_img.save(barcode_filepath)
                except Exception as e:
                    print(f"Accessory barcode update skipped: {e}")

            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE accessories SET name = ?, brand = ?, model = ?, price = ?, quantity = ?,
                    description = ?, seller_name = ?, seller_contact = ?, seller_price = ?,
                    seller_total_price = ?, barcode = ?, barcode_file_path = ?, available = ?
                WHERE id = ?
            """, (t, brand_entry.get().strip(), model_entry.get().strip(), price_val, qty_val, desc_text.get("1.0", tk.END).strip(), seller_name.get().strip(), seller_contact.get().strip(), seller_unit, seller_total, barcode_data, barcode_filepath, 1 if qty_val > 0 else 0, accessory_id))
            conn.commit()
            conn.close()
            messagebox.showinfo("Succès", "Accessoire mis à jour.")
            dialog.destroy()
            if parent_dialog:
                try:
                    parent_dialog.destroy()
                except Exception:
                    pass
            self.load_accessories_data()

        self.icon_button(btn_frame, "Enregistrer les modifications", "save", command=on_update, bootstyle="primary").pack(side=tk.RIGHT)
        type_entry.focus()

    def sell_accessory_dialog(self, accessory_id, parent_dialog=None):
        dialog = tk.Toplevel(self.root)
        dialog.title("Vendre l'Accessoire")
        dialog.geometry("520x600")
        dialog.transient(self.root)
        dialog.grab_set()
        main_frame = ttk.Frame(dialog, style="Main.TFrame", padding=12)
        main_frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(main_frame, text="Vendre l'Accessoire", style="Heading.TLabel").pack(anchor="w", pady=(0,10))
        buyer_frame = ttk.Labelframe(main_frame, text="Informations de l'Acheteur", padding=12, style="TLabelframe")
        buyer_frame.pack(fill=tk.X, pady=(0, 12))
        ttk.Label(buyer_frame, text="Sélectionner l'Acheteur:").pack(anchor="w")
        self.buyer_combo = ttk.Combobox(buyer_frame, width=40)
        self.buyer_combo.pack(fill=tk.X, pady=6)
        new_buyer_btn = ttk.Button(buyer_frame, text="+ Ajouter Nouvel Acheteur", command=lambda: self.add_buyer_dialog(self.buyer_combo))
        new_buyer_btn.pack(pady=6)
        sale_frame = ttk.Labelframe(main_frame, text="Détails de la Vente", padding=12, style="TLabelframe")
        sale_frame.pack(fill=tk.X, pady=(0,12))
        ttk.Label(sale_frame, text="Prix de Vente (unité):").pack(anchor="w")
        self.sale_price_entry = ttk.Entry(sale_frame, width=20)
        self.sale_price_entry.pack(fill=tk.X, pady=6)
        ttk.Label(sale_frame, text="Quantité à vendre:").pack(anchor="w")
        self.sale_qty_entry = ttk.Entry(sale_frame, width=20)
        self.sale_qty_entry.pack(fill=tk.X, pady=6)
        self.sale_qty_entry.insert(0, "1")
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT price, quantity FROM accessories WHERE id = ?", (accessory_id,))
        row = cursor.fetchone()
        conn.close()
        if row:
            unit_price = float(row[0] or 0)
            available_qty = int(row[1] or 0)
        else:
            unit_price = 0
            available_qty = 0
        if available_qty <= 0:
            messagebox.showerror("Erreur", "Cet accessoire est en rupture de stock.")
            dialog.destroy()
            return
        self.sale_price_entry.insert(0, f"{unit_price:.2f}")
        info_lbl = ttk.Label(sale_frame, text=f"Stock disponible: {available_qty}")
        info_lbl.pack(anchor="w", pady=(4,0))
        def update_price(_=None):
            # Keep the sale price field as the UNIT price. process_sale multiplies by quantity.
            try:
                qty = int(self.sale_qty_entry.get().strip() or 1)
                if qty < 1:
                    self.sale_qty_entry.delete(0, tk.END)
                    self.sale_qty_entry.insert(0, "1")
            except Exception:
                pass
        self.sale_qty_entry.bind("<KeyRelease>", update_price)
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill=tk.X, pady=12)
        ttk.Button(btn_frame, text="Annuler", command=dialog.destroy).pack(side=tk.RIGHT, padx=(8,0))
        self.icon_button(btn_frame, "Confirmer la Vente", "sell", command=lambda: self.process_sale(accessory_id, dialog, product_type="accessory", quantity_entry=self.sale_qty_entry), bootstyle="success").pack(side=tk.RIGHT)
        self.load_buyers()


    def load_phones_data(self):
        for item in self.phones_tree.get_children():
            self.phones_tree.delete(item)
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        query = "SELECT id, ID_phone, brand, model, imei, COALESCE(battery_state, 'Unknown'), price, available FROM phones"
        params = []

        if self.available_filter.get() == "available":
            query += " WHERE available = 1"
        elif self.available_filter.get() == "sold":
            query += " WHERE available = 0"

        query += " ORDER BY id DESC"
        cursor.execute(query, params)
        phones = cursor.fetchall()
        conn.close()
        for phone in phones:
            status = "Disponible" if phone[7] else "Vendu"
            actions = "Voir Détails"
            # values order must match Treeview columns:
            # ("ID", "ID Téléphone", "Marque", "Modèle", "IMEI", "Batterie", "Prix", "Statut", "Actions")
            self.phones_tree.insert("", tk.END, values=(phone[0], phone[1], phone[2], phone[3], phone[4], phone[5], f"{phone[6]:.2f}MAD", status, actions))

    def on_phone_click(self, event):
        """Open details when user clicks a row (not header)."""
        try:
            row_id = self.phones_tree.identify_row(event.y)
            if not row_id:
                return
            values = self.phones_tree.item(row_id).get('values', [])
            if not values:
                return
            phone_db_id = values[0]  # tree stores DB id at index 0
            # Select that item (so other functions expecting selection keep working)
            self.phones_tree.selection_set(row_id)
            self.phones_tree.focus(row_id)
            # Open details window for this DB id
            self.show_phone_details(phone_id=phone_db_id)
        except Exception as e:
            # defensive: don't crash the UI on unexpected click handling errors
            print("on_phone_click error:", e)

    def show_phone_context_menu(self, event):
        item = self.phones_tree.selection()[0] if self.phones_tree.selection() else None
        if not item:
            return
        context_menu = tk.Menu(self.root, tearoff=0)
        context_menu.add_command(label="Voir Détails", command=self.show_phone_details)
        if self.current_user['role'] == 'admin':
            context_menu.add_separator()
            context_menu.add_command(label="Modifier Téléphone", command=lambda: self.edit_phone_dialog(event))
            context_menu.add_command(label="Supprimer Téléphone", command=self.delete_phone)
        try:
            context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            context_menu.grab_release()

    def clear_search(self):
        self.phone_search_var.set("")
        self.load_phones_data()

    def search_phones(self):
        query = self.phone_search_var.get().lower()
        if not query:
            self.load_phones_data()
            return
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id, ID_phone, brand, model, imei, COALESCE(battery_state, 'Unknown'), price, available FROM phones WHERE LOWER(COALESCE(brand,'')) LIKE ? OR LOWER(COALESCE(model,'')) LIKE ? OR imei LIKE ? OR ID_phone LIKE ?",
                       (f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%"))
        phones = cursor.fetchall()
        conn.close()
        for item in self.phones_tree.get_children():
            self.phones_tree.delete(item)
        for phone in phones:
            status = "Disponible" if phone[7] else "Vendu"
            actions = "Voir Détails"
            self.phones_tree.insert("", tk.END, values=(phone[0], phone[1], phone[2], phone[3], phone[4], phone[5], f"{(phone[6] or 0):.2f}MAD", status, actions))

    def clear_accessory_search(self):
        self.accessory_search_var.set("")
        self.load_accessories_data()

    def search_accessories(self):
        self.load_accessories_data()

    def clear_sales_search(self):
        self.sales_search_var.set("")
        if hasattr(self, 'sales_date_entry'):
            self.sales_date_entry.entry.delete(0, tk.END)
        self.load_recent_sales()

    def search_sales(self):
        self.load_recent_sales()


    def add_phone_dialog(self):
        if self.current_user['role'] != 'admin':
            messagebox.showwarning("Accès Refusé", "Seuls les administrateurs peuvent ajouter de nouveaux téléphones.")
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Ajouter un Téléphone d'Occasion")
        dialog.geometry("600x700")
        dialog.transient(self.root)
        dialog.grab_set()

        # center window
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (dialog.winfo_width() // 2)
        y = (dialog.winfo_screenheight() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")

        main_frame = ttk.Frame(dialog, style="Main.TFrame", padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)

        title_label = ttk.Label(main_frame, text="Ajouter un Téléphone d'Occasion", style="Heading.TLabel")
        title_label.pack(pady=(0, 12))

        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True)

        phone_frame = ttk.Frame(notebook, style="Main.TFrame")
        notebook.add(phone_frame, text="  Info Téléphone", image=self.icon("phone"), compound=tk.LEFT)

        form_frame = ttk.Frame(phone_frame, style="Main.TFrame")
        form_frame.pack(fill=tk.X, pady=(0, 12), padx=10)

        new_phone_id = self.generate_phone_id()

        # Store widgets in this dictionary for later access
        form_fields = {}

        # Define the order and labels for the form
        field_labels = [
            "ID Téléphone", "Marque *", "Modèle *", "IMEI *", "Couleur",
            "Stockage", "RAM", "Etat Batterie", "Prix *", "Description"
        ]

        row = 0
        for label_text in field_labels:
            # Create and grid the label for each field
            ttk.Label(form_frame, text=label_text, style="TLabel").grid(row=row, column=0, sticky="w", pady=6)

            # Create the appropriate widget for each field
            if label_text == "ID Téléphone":
                widget = ttk.Label(form_frame, text=new_phone_id, font=("Segoe UI", 11, "bold"))
                widget.grid(row=row, column=1, padx=(10, 0), pady=6, sticky="ew")
            elif label_text == "IMEI *":
                # Create a special container for the IMEI entry and button
                imei_container = ttk.Frame(form_frame)
                imei_container.grid(row=row, column=1, padx=(10, 0), pady=6, sticky="ew")

                # **FIX**: Create the Entry with `imei_container` as its parent
                widget = ttk.Entry(imei_container, width=40)
                widget.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)

                scan_btn = ttk.Button(imei_container, text="Scan", command=widget.focus_set)
                scan_btn.pack(side=tk.LEFT, padx=(5, 0))
            elif label_text == "Description":
                widget = scrolledtext.ScrolledText(form_frame, width=30, height=4, font=("Segoe UI", 10), bg=self.surface_color, fg="#111111", wrap=tk.WORD)
                widget.grid(row=row, column=1, padx=(10, 0), pady=6, sticky="ew")
            else: # For all other standard text entries
                widget = ttk.Entry(form_frame, width=40)
                widget.grid(row=row, column=1, padx=(10, 0), pady=6, ipady=4, sticky="ew")
            
            # Store the widget for the save function
            form_fields[label_text] = widget
            row += 1
            
        form_frame.grid_columnconfigure(1, weight=1)

        # seller tab
        seller_frame = ttk.Frame(notebook, style="Main.TFrame")
        notebook.add(seller_frame, text="  Info Vendeur", image=self.icon("user"), compound=tk.LEFT)

        seller_form_frame = ttk.Frame(seller_frame, style="Main.TFrame")
        seller_form_frame.pack(fill=tk.X, pady=(0, 12), padx=10)

        seller_fields = {
            "Nom du Vendeur *": ttk.Entry(seller_form_frame, width=40),
            "Contact du Vendeur *": ttk.Entry(seller_form_frame, width=40),
            "Prix d'Achat du Vendeur": ttk.Entry(seller_form_frame, width=40),
            "Description du Vendeur": scrolledtext.ScrolledText(seller_form_frame, width=30, height=4, font=("Segoe UI", 10), bg=self.surface_color, fg="#111111", wrap=tk.WORD)
        }

        row = 0
        for label_text, widget in seller_fields.items():
            ttk.Label(seller_form_frame, text=label_text, style="TLabel").grid(row=row, column=0, sticky="w", pady=6)
            widget.grid(row=row, column=1, padx=(10, 0), pady=6, ipady=4 if not isinstance(widget, scrolledtext.ScrolledText) else 0, sticky="ew")
            row += 1
        seller_form_frame.grid_columnconfigure(1, weight=1)

        button_frame = ttk.Frame(main_frame, style="Main.TFrame")
        button_frame.pack(fill=tk.X, pady=(8, 0))

        cancel_btn = ttk.Button(button_frame, text="Annuler", command=dialog.destroy)
        cancel_btn.pack(side=tk.RIGHT, padx=(10, 0))

        save_btn = self.icon_button(button_frame, "Enregistrer le Téléphone", "save", command=lambda: self.save_new_phone(form_fields, seller_fields, dialog), bootstyle="primary")
        save_btn.pack(side=tk.RIGHT)

        form_fields["Marque *"].focus()


    def create_barcode_with_text(self, barcode_data, model_text):
        """Fixed barcode creation that works with PyInstaller"""
        try:
            # Générer un code-barres Code128 (supporte l'alphanumÉrique)
            CODE128 = barcode.get_barcode_class('code128')
            
            # Create barcode with options that work in PyInstaller
            barcode_obj = CODE128(barcode_data, writer=ImageWriter())
            
            # Use a temporary file approach
            temp_dir = tempfile.gettempdir()
            temp_name = f"temp_barcode_{random.randint(1000, 9999)}"
            temp_path = os.path.join(temp_dir, temp_name)
            
            # Generate the barcode image without extension first
            try:
                full_path = barcode_obj.save(temp_path)
            except Exception as e:
                print(f"Barcode generation error: {e}")
                # Fallback: create a simple text-based image
                return self.create_fallback_barcode_image(barcode_data, model_text)
            
            # Open the generated barcode image
            try:
                barcode_img = Image.open(full_path)
            except Exception as e:
                print(f"Error opening barcode image: {e}")
                return self.create_fallback_barcode_image(barcode_data, model_text)
            
            # Add text under the barcode
            img_width, img_height = barcode_img.size
            text_height = 60
            new_img = Image.new('RGB', (img_width, img_height + text_height), 'white')
            new_img.paste(barcode_img, (0, 0))

            draw = ImageDraw.Draw(new_img)
            
            # Try to load font, with multiple fallbacks
            font = self.get_available_font(20)
            
            # Calculate text position
            try:
                # For newer Pillow versions
                bbox = draw.textbbox((0, 0), model_text, font=font)
                text_width = bbox[2] - bbox[0]
            except AttributeError:
                # For older Pillow versions
                text_width, _ = draw.textsize(model_text, font=font)
            
            text_x = (img_width - text_width) // 2
            text_y = img_height + 10
            draw.text((text_x, text_y), model_text, fill="black", font=font)

            # Clean up temporary file
            try:
                if os.path.exists(full_path):
                    os.remove(full_path)
            except:
                pass

            return new_img
            
        except Exception as e:
            print(f"Complete barcode creation failed: {e}")
            return self.create_fallback_barcode_image(barcode_data, model_text)

        
    def get_available_font(self, size):
        """Get the best available font for the system"""
        fonts_to_try = [
            # Windows fonts
            "arial.ttf",
            "calibri.ttf", 
            "tahoma.ttf",
            "segoeui.ttf",
            # System paths for Windows
            "C:/Windows/Fonts/arial.ttf",
            "C:/Windows/Fonts/calibri.ttf",
            "C:/Windows/Fonts/tahoma.ttf",
            # Linux fonts
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            # Mac fonts
            "/System/Library/Fonts/Arial.ttf",
            "/System/Library/Fonts/Helvetica.ttc"
        ]
        
        for font_path in fonts_to_try:
            try:
                return ImageFont.truetype(font_path, size)
            except (IOError, OSError):
                continue
        
        # If all else fails, use default font
        try:
            return ImageFont.load_default()
        except:
            # Ultimate fallback - create a dummy font object
            return None

    def create_fallback_barcode_image(self, barcode_data, model_text):
        """Create a fallback barcode image when normal generation fails"""
        try:
            # Create a simple white image with text
            img_width = 400
            img_height = 200
            img = Image.new('RGB', (img_width, img_height), 'white')
            draw = ImageDraw.Draw(img)
            
            # Draw a simple rectangle to simulate barcode
            draw.rectangle([50, 50, 350, 100], outline='black', width=2)
            
            # Add the barcode data as text
            font = self.get_available_font(16)
            if font:
                draw.text((50, 110), f"ID: {barcode_data}", fill="black", font=font)
                draw.text((50, 140), model_text, fill="black", font=font)
            else:
                # Even more basic fallback
                draw.text((50, 110), f"ID: {barcode_data}", fill="black")
                draw.text((50, 140), model_text, fill="black")
            
            return img
        except Exception as e:
            print(f"Even fallback image creation failed: {e}")
            # Return a minimal white image
            return Image.new('RGB', (400, 200), 'white')

    def save_new_phone(self, fields, seller_fields, dialog):
        try:
            print("Starting save_new_phone...")  # Debug
            
            # Extraire l'ID généré automatiquement du label
            id_phone = fields["ID Téléphone"].cget("text")

            phone_details = {
                "ID_phone": id_phone,
                "brand": fields["Marque *"].get().strip(),
                "model": fields["Modèle *"].get().strip(),
                "imei": fields["IMEI *"].get().strip(),
                "color": fields["Couleur"].get().strip(),
                "storage": fields["Stockage"].get().strip(),
                "ram": fields["RAM"].get().strip(),
                "battery_state": fields["Etat Batterie"].get().strip(),
                "price": fields["Prix *"].get().strip(),
                "description": fields["Description"].get("1.0", tk.END).strip(),
            }

            seller_details = {
                "seller_name": seller_fields["Nom du Vendeur *"].get().strip(),
                "seller_contact": seller_fields["Contact du Vendeur *"].get().strip(),
                "seller_price": seller_fields["Prix d'Achat du Vendeur"].get().strip(),
                "seller_description": seller_fields["Description du Vendeur"].get("1.0", tk.END).strip(),
            }

            print(f"Phone details: {phone_details}")  # Debug
            print(f"Seller details: {seller_details}")  # Debug

            if not all([phone_details["brand"], phone_details["model"], phone_details["imei"], phone_details["price"]]):
                messagebox.showwarning("Avertissement", "Les champs marqués avec * sont requis.")
                return

            if not all([seller_details["seller_name"], seller_details["seller_contact"]]):
                messagebox.showwarning("Avertissement", "Le nom et le contact du vendeur sont requis.")
                return

            try:
                price_val = float(phone_details["price"])
            except ValueError:
                messagebox.showerror("Erreur", "Le prix doit être un nombre.")
                return

            # Générer le code-barres uniquement à partir de l'ID du téléphone
            barcode_data_url = id_phone
            if not barcode_data_url:
                return

            print(f"Generating barcode for: {barcode_data_url}")  # Debug
            barcode_img = self.create_barcode_with_text(barcode_data_url, f"{phone_details['brand']} {phone_details['model']}")
            barcode_filename = f"{phone_details['ID_phone']}_{phone_details['brand']}_{phone_details['model']}.png".replace(" ", "_")
            barcode_filepath = os.path.join(self.barcode_folder, barcode_filename)
            barcode_img.save(barcode_filepath)
            print(f"Barcode saved to: {barcode_filepath}")  # Debug

            # Convert seller_price to float if provided
            try:
                seller_price_val = float(seller_details["seller_price"]) if seller_details["seller_price"] else None
            except ValueError:
                seller_price_val = None

            print("Connecting to database...")  # Debug
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            
            insert_query = """INSERT INTO phones (ID_phone, brand, model, imei, color, storage, ram, battery_state, price, description, barcode, barcode_file_path, available, seller_name, seller_contact, seller_description, seller_price)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
            
            values = (phone_details["ID_phone"], phone_details["brand"], phone_details["model"], phone_details["imei"], 
                     phone_details["color"], phone_details["storage"], phone_details["ram"], phone_details["battery_state"],
                     price_val, phone_details["description"], barcode_data_url, barcode_filepath, 1, 
                     seller_details["seller_name"], seller_details["seller_contact"], seller_details["seller_description"], seller_price_val)
            
            print(f"Executing query with values: {values}")  # Debug
            cursor.execute(insert_query, values)
            conn.commit()
            conn.close()
            
            print("Phone saved successfully!")  # Debug
            messagebox.showinfo("Succès", f"Téléphone ajouté avec succès!")
            dialog.destroy()
            self.load_phones_data()
            
        except sqlite3.IntegrityError as e:
            print(f"Integrity error: {e}")  # Debug
            messagebox.showerror("Erreur", f"Un téléphone avec cet ID ou IMEI existe déjà : {e}")
        except Exception as e:
            print(f"General error in save_new_phone: {e}")  # Debug
            messagebox.showerror("Erreur de Base de Données", f"Une erreur est survenue: {e}")


    def show_phone_details(self, event=None, phone_id=None):
        """
        Show details window.
        Accepts either:
        - phone_id (DB integer), OR
        - uses current selection in self.phones_tree.
        """
        # Determine phone_id if not explicitly provided
        if phone_id is None:
            selection = self.phones_tree.selection()
            if not selection:
                messagebox.showwarning("Avertissement", "Veuillez sélectionner un téléphone pour voir les détails.")
                return
            item = self.phones_tree.item(selection[0])
            phone_id = item['values'][0]

        # Ensure the tree selection matches the phone being viewed
        for item in self.phones_tree.get_children():
            vals = self.phones_tree.item(item).get('values', [])
            if vals and vals[0] == phone_id:
                self.phones_tree.selection_set(item)
                self.phones_tree.focus(item)
                break

        # Create details window
        details_window = tk.Toplevel(self.root)
        details_window.title("Détails du Téléphone")
        details_window.geometry("800x600")
        details_window.transient(self.root)
        details_window.grab_set()
        details_window.configure(bg='white')
        
        # Apply ttkbootstrap style
        style = ttk.Style()
        style.configure('Custom.TFrame', background='white')
        style.configure('Header.TLabel', background='white', font=('Segoe UI', 12, 'bold'))
        style.configure('Title.TLabel', background='#f8f9fa', font=('Segoe UI', 10, 'bold'))
        style.configure('Value.TLabel', background='white', font=('Segoe UI', 10))
        style.configure('Section.TLabelframe', background='white', bordercolor='#dee2e6')
        style.configure('Section.TLabelframe.Label', background='white', font=('Segoe UI', 11, 'bold'))

        # Main container with scrollbar
        main_container = ttk.Frame(details_window, style='Custom.TFrame')
        main_container.pack(fill=tk.BOTH, expand=True, padx=15, pady=15)

        # Create scrollable frame
        canvas = tk.Canvas(main_container, bg='white', highlightthickness=0)
        scrollbar = ttk.Scrollbar(main_container, orient=tk.VERTICAL, command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas, style='Custom.TFrame')

        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )

        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Load phone details from DB (explicit columns so indexes are stable)
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, ID_phone, brand, model, imei, color, storage, ram, price,
                description, barcode, barcode_file_path, image_path, available,
                seller_name, seller_contact, seller_description, seller_price, COALESCE(battery_state, 'Unknown')
            FROM phones WHERE id = ?
        """, (phone_id,))
        phone = cursor.fetchone()
        conn.close()

        if not phone:
            messagebox.showerror("Erreur", "Téléphone introuvable.")
            details_window.destroy()
            return

        # Map indexes (for readability)
        # 0:id 1:ID_phone 2:brand 3:model 4:imei 5:color 6:storage 7:ram 8:price
        # 9:description 10:barcode 11:barcode_file_path 12:image_path 13:available
        # 14:seller_name 15:seller_contact 16:seller_description 17:seller_price 18:battery_state

        # Header with phone model
        header_frame = ttk.Frame(scrollable_frame, style='Custom.TFrame')
        header_frame.pack(fill=tk.X, pady=(0, 15))
        
        ttk.Label(
            header_frame, 
            text=f"{phone[2]} {phone[3]}", 
            style='Header.TLabel'
        ).pack(anchor=tk.W)
        
        ttk.Separator(header_frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=5)

        # Main content (image and details)
        content_frame = ttk.Frame(scrollable_frame, style='Custom.TFrame')
        content_frame.pack(fill=tk.X, pady=5)

        # Left: barcode / image
        left_frame = ttk.Frame(content_frame, style='Custom.TFrame', width=250)
        left_frame.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 20))
        left_frame.pack_propagate(False)

        barcode_path = phone[11]  # barcode_file_path
        if barcode_path and os.path.exists(barcode_path):
            try:
                barcode_image = Image.open(barcode_path)
                # create a thumbnail so UI stays responsive
                max_thumb = (240, 180)
                barcode_image.thumbnail(max_thumb)
                barcode_photo = ImageTk.PhotoImage(barcode_image)
                barcode_label = tk.Label(left_frame, image=barcode_photo, bg='white')
                barcode_label.image = barcode_photo
                barcode_label.pack(pady=12)
            except Exception:
                # if image fails to open, ignore and continue
                ttk.Label(
                    left_frame, 
                    text="Image non disponible", 
                    style='Value.TLabel'
                ).pack(pady=12)

        # Barcode buttons
        barcode_btn_frame = ttk.Frame(left_frame, style='Custom.TFrame')
        barcode_btn_frame.pack(pady=8)

        show_barcode_btn = ttk.Button(
            barcode_btn_frame, 
            text="Voir le Code-Barres",
            command=lambda: self.show_barcode_modal(barcode_path),
            width=20
        )
        show_barcode_btn.pack(pady=5)

        print_btn = ttk.Button(
            barcode_btn_frame, 
            text="Imprimer",
            command=lambda: self.print_barcode(barcode_path), 
            bootstyle="primary",
            width=20
        )
        print_btn.pack(pady=5)

        # Right: details
        right_frame = ttk.Frame(content_frame, style='Custom.TFrame')
        right_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)

        # Phone details section
        phone_frame = ttk.Labelframe(
            right_frame, 
            text="Détails du Téléphone",
            style='Section.TLabelframe'
        )
        phone_frame.pack(fill=tk.X, pady=(0, 15))

        # Create a grid for phone details
        phone_details = [
            ("ID", phone[1]),
            ("Marque", phone[2]),
            ("Modèle", phone[3]),
            ("IMEI", phone[4]),
            ("Couleur", phone[5] or 'N/A'),
            ("Stockage", phone[6] or 'N/A'),
            ("RAM", phone[7] or 'N/A'),
            ("État Batterie", phone[18] or 'N/A'),
            ("Prix", f"{phone[8]:.2f} MAD"),
            ("Statut", "Disponible" if phone[13] else "Vendu")
        ]

        for i, (label, value) in enumerate(phone_details):
            row_frame = ttk.Frame(phone_frame, style='Custom.TFrame')
            row_frame.pack(fill=tk.X, pady=2)
            
            ttk.Label(
                row_frame, 
                text=f"{label}:", 
                style='Title.TLabel',
                width=15,
                anchor=tk.W
            ).pack(side=tk.LEFT)
            
            ttk.Label(
                row_frame, 
                text=value, 
                style='Value.TLabel',
                anchor=tk.W
            ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Seller information section
        seller_frame = ttk.Labelframe(
            right_frame, 
            text="Informations du Vendeur",
            style='Section.TLabelframe'
        )
        seller_frame.pack(fill=tk.X, pady=(0, 15))

        seller_details = [
            ("Nom", phone[14] or 'N/A'),
            ("Contact", phone[15] or 'N/A'),
            ("Prix d'Achat", f"{phone[17]:.2f} MAD" if phone[17] is not None else 'N/A'),
            ("Description", phone[16] or 'N/A')
        ]

        for i, (label, value) in enumerate(seller_details):
            row_frame = ttk.Frame(seller_frame, style='Custom.TFrame')
            row_frame.pack(fill=tk.X, pady=2)
            
            ttk.Label(
                row_frame, 
                text=f"{label}:", 
                style='Title.TLabel',
                width=15,
                anchor=tk.W
            ).pack(side=tk.LEFT)
            
            # Special handling for description to allow wrapping
            if label == "Description":
                desc_frame = ttk.Frame(row_frame, style='Custom.TFrame')
                desc_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
                
                desc_label = tk.Label(
                    desc_frame,
                    text=value,
                    bg='white',
                    font=('Segoe UI', 10),
                    wraplength=400,
                    justify=tk.LEFT,
                    anchor=tk.W
                )
                desc_label.pack(fill=tk.X)
            else:
                ttk.Label(
                    row_frame, 
                    text=value, 
                    style='Value.TLabel',
                    anchor=tk.W
                ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        # Phone description section
        if phone[9]:
            desc_frame = ttk.Labelframe(
                right_frame, 
                text="Description du Téléphone",
                style='Section.TLabelframe'
            )
            desc_frame.pack(fill=tk.X, pady=(0, 15))

            desc_text = tk.Text(
                desc_frame,
                height=4,
                wrap=tk.WORD,
                font=('Segoe UI', 10),
                bg='white',
                relief=tk.FLAT,
                padx=5,
                pady=5
            )
            desc_text.insert(1.0, phone[9] or 'N/A')
            desc_text.config(state=tk.DISABLED)
            desc_text.pack(fill=tk.X, padx=5, pady=5)

        # Actions frame
        action_frame = ttk.Frame(scrollable_frame, style='Custom.TFrame')
        action_frame.pack(fill=tk.X, pady=20)

        # Sell button (only if available)
        if phone[13]:
            sell_btn = ttk.Button(
                action_frame, 
                text="Vendre le Téléphone",
                command=lambda: self.sell_phone_dialog(phone_id), 
                bootstyle="success",
                width=20
            )
            sell_btn.pack(side=tk.LEFT, padx=5)

        if self.current_user.get('role') == 'admin':
            edit_btn = ttk.Button(
                action_frame, 
                text="Modifier le Téléphone",
                command=lambda: self.edit_phone_dialog(None), 
                bootstyle="warning",
                width=20
            )
            edit_btn.pack(side=tk.LEFT, padx=5)

            delete_btn = ttk.Button(
                action_frame, 
                text="Supprimer le Téléphone",
                command=lambda: self.delete_phone_from_details(phone_id, details_window), 
                bootstyle="danger",
                width=20
            )
            delete_btn.pack(side=tk.LEFT, padx=5)

        # Center the details window on screen
        details_window.update_idletasks()
        x = (details_window.winfo_screenwidth() // 2) - (details_window.winfo_width() // 2)
        y = (details_window.winfo_screenheight() // 2) - (details_window.winfo_height() // 2)
        details_window.geometry(f"+{x}+{y}")

        # Bind mouse wheel to scroll
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        
        canvas.bind_all("<MouseWheel>", _on_mousewheel)


    def show_barcode_modal(self, image_path):
        """Open a larger view of the barcode with print option."""
        if not image_path or not os.path.exists(image_path):
            messagebox.showerror("Erreur", "Fichier code-barres introuvable.")
            return
        modal = tk.Toplevel(self.root)
        modal.title("Code-Barres")
        modal.transient(self.root)
        modal.grab_set()

        img = Image.open(image_path)
        # Resize to fit screen but keep aspect ratio
        screen_w = modal.winfo_screenwidth() * 0.6
        screen_h = modal.winfo_screenheight() * 0.6
        img.thumbnail((int(screen_w), int(screen_h)))
        photo = ImageTk.PhotoImage(img)

        lbl = tk.Label(modal, image=photo, bg=self.bg_color)
        lbl.image = photo
        lbl.pack(padx=10, pady=10)

        btn_frame = ttk.Frame(modal, style="Main.TFrame")
        btn_frame.pack(pady=(0, 10))
        ttk.Button(btn_frame, text="Imprimer", command=lambda: self.print_barcode(image_path), bootstyle="primary").pack(side=tk.LEFT, padx=5)
        ttk.Button(btn_frame, text="Fermer", command=modal.destroy).pack(side=tk.LEFT, padx=5)

        modal.update_idletasks()
        x = (modal.winfo_screenwidth() // 2) - (modal.winfo_width() // 2)
        y = (modal.winfo_screenheight() // 2) - (modal.winfo_height() // 2)
        modal.geometry(f"+{x}+{y}")

    def delete_phone_from_details(self, phone_id, details_window):
        """Supprimer un téléphone depuis la fenêtre de détails"""
        if messagebox.askyesno("Confirmer la Suppression", "Êtes-vous sûr de vouloir supprimer ce téléphone?"):
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT barcode_file_path FROM phones WHERE id = ?", (phone_id,))
            barcode_path = cursor.fetchone()
            if barcode_path and barcode_path[0] and os.path.exists(barcode_path[0]):
                os.remove(barcode_path[0])
            cursor.execute("DELETE FROM phones WHERE id = ?", (phone_id,))
            conn.commit()
            conn.close()
            messagebox.showinfo("Succès", "Téléphone supprimé avec succès!")
            details_window.destroy()
            self.load_phones_data()

    def scan_barcode_dialog(self):
        """Dialogue pour scanner un téléphone ou un accessoire."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Scanner Code-Barres")
        dialog.geometry("460x240")
        dialog.transient(self.root)
        dialog.grab_set()
        self.center_window(dialog)

        main_frame = ttk.Frame(dialog, style="Main.TFrame", padding=22)
        main_frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main_frame, text="Scanner un Produit", style="Heading.TLabel").pack(pady=(0, 12))
        ttk.Label(main_frame, text="Scannez ou saisissez un ID téléphone, IMEI, SKU ou code-barres:", style="TLabel").pack(anchor="w")

        self.scan_entry = ttk.Entry(main_frame, width=42)
        self.scan_entry.pack(fill=tk.X, pady=10, ipady=6)
        self.scan_entry.focus()

        button_frame = ttk.Frame(main_frame, style="Main.TFrame")
        button_frame.pack(fill=tk.X, pady=(8, 0))

        self.icon_button(button_frame, "Rechercher", "search", command=lambda: self.search_by_barcode(self.scan_entry.get(), dialog), bootstyle="primary").pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Button(button_frame, text="Annuler", command=dialog.destroy).pack(side=tk.RIGHT)

        dialog.bind('<Return>', lambda event: self.search_by_barcode(self.scan_entry.get(), dialog))

    def search_by_barcode(self, code, dialog=None):
        """Rechercher un téléphone ou accessoire par ID/IMEI/SKU/code-barres."""
        code = (code or "").strip()
        if not code:
            messagebox.showwarning("Avertissement", "Veuillez entrer ou scanner un code.")
            return

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id FROM phones
            WHERE ID_phone = ? OR imei = ? OR barcode = ?
            LIMIT 1
        """, (code, code, code))
        result = cursor.fetchone()
        if result:
            conn.close()
            if dialog:
                dialog.destroy()
            self.show_phone_details_by_id(result[0])
            return

        cursor.execute("""
            SELECT id FROM accessories
            WHERE SKU = ? OR barcode = ?
            LIMIT 1
        """, (code, code))
        result = cursor.fetchone()
        conn.close()
        if result:
            if dialog:
                dialog.destroy()
            self.show_accessory_details(result[0])
        else:
            messagebox.showerror("Non trouvé", f"Aucun produit trouvé pour le code: {code}")

    def show_phone_details_by_id(self, phone_id):
        """Open details for phone DB id -- helper used by scanner."""
        # select item in the tree for usability
        for item in self.phones_tree.get_children():
            values = self.phones_tree.item(item).get('values', [])
            if values and values[0] == phone_id:
                self.phones_tree.selection_set(item)
                self.phones_tree.focus(item)
                break
        # call the main details function with phone_id
        self.show_phone_details(phone_id=phone_id)

    def sell_phone_dialog(self, phone_id):
        """Dialogue pour vendre un téléphone à un acheteur"""
        dialog = tk.Toplevel(self.root)
        dialog.title("Vendre le Téléphone")
        dialog.geometry("500x500")
        dialog.transient(self.root)
        dialog.grab_set()

        # center
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (dialog.winfo_width() // 2)
        y = (dialog.winfo_screenheight() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")

        main_frame = ttk.Frame(dialog, style="Main.TFrame", padding=18)
        main_frame.pack(fill=tk.BOTH, expand=True)

        title_label = ttk.Label(main_frame, text="Vendre le Téléphone à l'Acheteur", style="Heading.TLabel")
        title_label.pack(pady=(0, 12))

        # Sélection de l'acheteur
        buyer_frame = ttk.Labelframe(main_frame, text="Informations de l'Acheteur", padding=12, style="TLabelframe")
        buyer_frame.pack(fill=tk.X, pady=(0, 12))

        ttk.Label(buyer_frame, text="Sélectionner l'Acheteur:").pack(anchor="w")
        self.buyer_combo = ttk.Combobox(buyer_frame, width=40)
        self.buyer_combo.pack(fill=tk.X, pady=6)

        new_buyer_btn = ttk.Button(buyer_frame, text="+ Ajouter Nouvel Acheteur", command=lambda: self.add_buyer_dialog(self.buyer_combo))
        new_buyer_btn.pack(pady=6)

        # Détails de la vente
        sale_frame = ttk.Labelframe(main_frame, text="Détails de la Vente", padding=12, style="TLabelframe")
        sale_frame.pack(fill=tk.X, pady=(0, 12))

        ttk.Label(sale_frame, text="Prix de Vente:").pack(anchor="w")
        self.sale_price_entry = ttk.Entry(sale_frame, width=20)
        self.sale_price_entry.pack(fill=tk.X, pady=6)

        # Charger le prix actuel du téléphone
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT price FROM phones WHERE id = ?", (phone_id,))
        phone_price = cursor.fetchone()[0]
        conn.close()

        self.sale_price_entry.insert(0, str(phone_price))

        button_frame = ttk.Frame(main_frame, style="Main.TFrame")
        button_frame.pack(fill=tk.X, pady=12)

        cancel_btn = ttk.Button(button_frame, text="Annuler", command=dialog.destroy)
        cancel_btn.pack(side=tk.RIGHT, padx=(10, 0))

        sell_btn = self.icon_button(button_frame, "Confirmer la Vente", "sell", command=lambda: self.process_sale(phone_id, dialog), bootstyle="success")
        sell_btn.pack(side=tk.RIGHT)

        self.load_buyers()

    def load_buyers(self):
        """Charger les acheteurs dans la combobox"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id, name FROM buyers")
        buyers = cursor.fetchall()
        conn.close()

        buyer_list = [f"{buyer[1]} (ID: {buyer[0]})" for buyer in buyers]
        self.buyer_combo['values'] = buyer_list
        if buyer_list:
            self.buyer_combo.set("Sélectionner un acheteur...")


    def add_buyer_dialog(self, combo_widget=None):
        """Modern, simple dialog to add a buyer (ttkbootstrap-friendly, light theme)."""
        dialog = tk.Toplevel(self.root)
        dialog.title("Ajouter un Nouvel Acheteur")
        dialog.geometry("520x320")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.resizable(False, False)
        dialog.configure(bg="white")

        # Center dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (dialog.winfo_width() // 2)
        y = (dialog.winfo_screenheight() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")

        # Main card/frame
        main = ttk.Frame(dialog, padding=(18, 14), style="Card.TFrame")
        main.pack(fill=tk.BOTH, expand=True)

        title = ttk.Label(main, text="Ajouter un Nouvel Acheteur", style="Heading.TLabel")
        title.pack(anchor="w", pady=(0, 12))

        form = ttk.Frame(main)
        form.pack(fill=tk.BOTH, expand=True)

        # Grid layout with consistent spacing
        form.columnconfigure(1, weight=1)

        ttk.Label(form, text="Nom de l'Acheteur *", anchor="w").grid(row=0, column=0, sticky="w", padx=(0,8), pady=6)
        name_entry = ttk.Entry(form)
        name_entry.grid(row=0, column=1, sticky="ew", pady=6)

        ttk.Label(form, text="Contact de l'Acheteur *", anchor="w").grid(row=1, column=0, sticky="w", padx=(0,8), pady=6)
        contact_entry = ttk.Entry(form)
        contact_entry.grid(row=1, column=1, sticky="ew", pady=6)

        ttk.Label(form, text="Description", anchor="nw").grid(row=2, column=0, sticky="nw", padx=(0,8), pady=6)
        desc_text = scrolledtext.ScrolledText(form, width=40, height=4, font=("Segoe UI", 10))
        desc_text.grid(row=2, column=1, sticky="ew", pady=6)

        # Validation label (hidden until needed)
        validation_lbl = ttk.Label(main, text="", foreground="red")
        validation_lbl.pack(anchor="w", pady=(0,4))

        # Buttons
        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(8,0))

        cancel_btn = ttk.Button(btn_frame, text="Annuler", command=dialog.destroy, bootstyle="secondary")
        cancel_btn.pack(side=tk.RIGHT, padx=(8,0))

        def on_save():
            name = name_entry.get().strip()
            contact = contact_entry.get().strip()
            desc = desc_text.get("1.0", tk.END).strip()
            if not name or not contact:
                validation_lbl.config(text="Les champs marqués * sont obligatoires.")
                return
            # call your existing save function
            self.save_new_buyer(name, contact, desc, dialog, combo_widget)

        save_btn = ttk.Button(btn_frame, text="Enregistrer", command=on_save, bootstyle="primary")
        save_btn.pack(side=tk.RIGHT)

        name_entry.focus()


    def save_new_buyer(self, name, contact, description, dialog, combo_widget):
        if not name or not contact:
            messagebox.showwarning("Avertissement", "Le nom et les coordonnées de l'acheteur sont requis.")
            return

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO buyers (name, contact_info, description) VALUES (?, ?, ?)", (name, contact, description.strip()))
        buyer_id = cursor.lastrowid
        conn.commit()
        conn.close()

        messagebox.showinfo("Succès", "Acheteur ajouté avec succès!")
        dialog.destroy()
        # mettre à jour la combobox existante (si fournie) et la sélectionner automatiquement
        try:
            self.load_buyers()
        except Exception:
            pass

        if combo_widget is not None:
            try:
                new_label = f"{name} (ID: {buyer_id})"
                existing = list(combo_widget['values']) if combo_widget['values'] else []
                # ajouter si pas déjà présent
                if new_label not in existing:
                    existing.append(new_label)
                combo_widget['values'] = existing
                combo_widget.set(new_label)
            except Exception:
                pass


    def process_sale(self, phone_id, dialog, product_type="phone", quantity_entry=None):
        """Traiter la vente (phones: qty=1 always; accessories: qty from dialog)."""
        buyer_text = self.buyer_combo.get()
        sale_price_str = self.sale_price_entry.get()

        if not buyer_text or buyer_text in ("", "Sélectionner un acheteur...", "Sélectionner un acheteur."):
            messagebox.showwarning("Avertissement", "Veuillez sélectionner un acheteur.")
            return

        try:
            unit_price = float(sale_price_str)
            if unit_price <= 0:
                raise ValueError
        except ValueError:
            messagebox.showwarning("Avertissement", "Veuillez entrer un prix de vente valide.")
            return

        # determine quantity
        if product_type == "phone":
            qty = 1
        else:
            try:
                qty = int(quantity_entry.get().strip() or 1) if quantity_entry is not None else 1
                if qty <= 0:
                    raise ValueError
            except Exception:
                messagebox.showwarning("Avertissement", "Veuillez entrer une quantité valide.")
                return

        buyer_id = int(buyer_text.split("(ID: ")[1].split(")")[0])

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        product_ref = ""
        product_name_snapshot = ""
        product_brand_snapshot = ""
        product_model_snapshot = ""
        product_imei_snapshot = ""

        if product_type == "phone":
            cursor.execute("SELECT available, price, ID_phone, brand, model, imei FROM phones WHERE id = ?", (phone_id,))
            row = cursor.fetchone()
            if not row:
                messagebox.showerror("Erreur", "Téléphone introuvable.")
                conn.close()
                return
            available = row[0]
            if not available:
                messagebox.showerror("Erreur", "Ce téléphone est déjà vendu.")
                conn.close()
                return
            product_ref = row[2] or ""
            product_brand_snapshot = row[3] or ""
            product_model_snapshot = row[4] or ""
            product_imei_snapshot = row[5] or ""
            product_name_snapshot = f"{product_brand_snapshot} {product_model_snapshot}".strip()
            # force qty=1, unit_price already set (from UI)
        else:
            cursor.execute("SELECT quantity, SKU, name, brand, model FROM accessories WHERE id = ?", (phone_id,))
            row = cursor.fetchone()
            if not row:
                messagebox.showerror("Erreur", "Accessoire introuvable.")
                conn.close()
                return
            available_qty = row[0] or 0
            if qty > available_qty:
                messagebox.showerror("Erreur", f"Quantité demandée ({qty}) supérieure au stock disponible ({available_qty}).")
                conn.close()
                return
            product_ref = row[1] or ""
            product_name_snapshot = row[2] or ""
            product_brand_snapshot = row[3] or ""
            product_model_snapshot = row[4] or product_name_snapshot

        cursor.execute("SELECT name, contact_info FROM buyers WHERE id = ?", (buyer_id,))
        buyer_row = cursor.fetchone() or ("", "")
        buyer_name_snapshot = buyer_row[0] or ""
        buyer_contact_snapshot = buyer_row[1] or ""

        sale_date = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sale_total = unit_price * qty

        try:
            cursor.execute("""
                INSERT INTO sales (phone_id, buyer_id, sale_date, sale_price, product_type, product_id, sale_qty, sale_unit_price, sale_total,
                                   product_ref, product_name_snapshot, product_brand_snapshot, product_model_snapshot, product_imei_snapshot,
                                   buyer_name_snapshot, buyer_contact_snapshot)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (phone_id if product_type == "phone" else None, buyer_id, sale_date, sale_total, product_type, phone_id, qty, unit_price, sale_total,
                  product_ref, product_name_snapshot, product_brand_snapshot, product_model_snapshot, product_imei_snapshot, buyer_name_snapshot, buyer_contact_snapshot))
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible d'enregistrer la vente: {e}")
            conn.close()
            return

        # Update stock / availability
        if product_type == "phone":
            cursor.execute("UPDATE phones SET available = 0 WHERE id = ?", (phone_id,))
        else:
            cursor.execute("UPDATE accessories SET quantity = quantity - ? WHERE id = ?", (qty, phone_id))
            # if quantity becomes 0 set available = 0
            cursor.execute("UPDATE accessories SET available = CASE WHEN COALESCE(quantity,0) <= 0 THEN 0 ELSE 1 END WHERE id = ?", (phone_id,))

        conn.commit()
        conn.close()

        messagebox.showinfo("Succès", f"Vente enregistrée!\nTotal: {sale_total:.2f} MAD (Qté: {qty})")
        if dialog:
            dialog.destroy()
        # Refresh UI
        self.load_phones_data()
        self.load_accessories_data()
        self.load_recent_sales()


    def print_barcode(self, image_path):
        if not os.path.exists(image_path):
            messagebox.showerror("Erreur", "Fichier image non trouvé.")
            return
        try:
            temp_pdf_fd, temp_pdf_path = tempfile.mkstemp(suffix=".pdf")
            os.close(temp_pdf_fd)
            c = canvas.Canvas(temp_pdf_path, pagesize=letter)
            width, height = letter
            img = Image.open(image_path)
            img_width, img_height = img.size
            max_size = 4 * inch
            if img_width > max_size or img_height > max_size:
                scale = min(max_size / img_width, max_size / img_height)
                img_width *= scale
                img_height *= scale
            x_pos = (width - img_width) / 2
            y_pos = (height - img_height) / 2
            c.drawImage(image_path, x_pos, y_pos, width=img_width, height=img_height)
            c.save()
            if sys.platform == "win32":
                os.startfile(temp_pdf_path, "print")
            elif sys.platform == "darwin":
                os.system(f'lpr "{temp_pdf_path}"')
            else:
                os.system(f'lp "{temp_pdf_path}"')
            messagebox.showinfo("Info", "Tâche d'impression envoyée à l'imprimante par défaut.")
        except Exception as e:
            messagebox.showerror("Erreur d'Impression", f"Impossible d'imprimer le code-barres: {str(e)}\n\nAssurez-vous d'avoir une imprimante par défaut configurée.")


    def edit_phone_dialog(self, event):
        if self.current_user['role'] != 'admin':
            messagebox.showwarning("Accès Refusé", "Seuls les administrateurs peuvent modifier les téléphones.")
            return
        selection = self.phones_tree.selection()
        if not selection:
            return
        item = self.phones_tree.item(selection[0])
        phone_id = item['values'][0]
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM phones WHERE id = ?", (phone_id,))
        phone = cursor.fetchone()
        conn.close()
        if not phone:
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Modifier le Téléphone")
        dialog.geometry("600x700")
        dialog.transient(self.root)
        dialog.grab_set()
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (dialog.winfo_width() // 2)
        y = (dialog.winfo_screenheight() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")
        main_frame = ttk.Frame(dialog, style="Main.TFrame", padding=20)
        main_frame.pack(fill=tk.BOTH, expand=True)
        title_label = ttk.Label(main_frame, text="Modifier le Téléphone", style="Heading.TLabel")
        title_label.pack(pady=(0, 12))

        # Créer un notebook pour les onglets
        notebook = ttk.Notebook(main_frame)
        notebook.pack(fill=tk.BOTH, expand=True)

        # Onglet Info Téléphone
        phone_frame = ttk.Frame(notebook, style="Main.TFrame")
        notebook.add(phone_frame, text="  Info Téléphone", image=self.icon("phone"), compound=tk.LEFT)

        form_frame = ttk.Frame(phone_frame, style="Main.TFrame")
        form_frame.pack(fill=tk.X, pady=(0, 12), padx=10)

        field_map = {
            1: ("ID Téléphone", ttk.Label), 2: ("Marque *", ttk.Entry), 3: ("Modèle *", ttk.Entry),
            4: ("IMEI *", ttk.Entry), 5: ("Couleur", ttk.Entry), 6: ("Stockage", ttk.Entry),
            7: ("RAM", ttk.Entry), 8: ("Etat Batterie *", ttk.Entry), 9: ("Prix *", ttk.Entry), 10: ("Description", scrolledtext.ScrolledText)
        }

        form_fields = {}
        for i, (label_text, widget_class) in field_map.items():
            ttk.Label(form_frame, text=label_text).grid(row=i - 1, column=0, sticky="w", pady=6)

            if label_text == "IMEI *":
                # Create a special container for the IMEI entry and button
                imei_container = ttk.Frame(form_frame)
                imei_container.grid(row=i - 1, column=1, padx=(10, 0), pady=6, sticky="ew")

                # **FIX**: Create the Entry with `imei_container` as its parent
                widget = widget_class(imei_container, width=40)
                widget.insert(0, phone[i] or "")
                widget.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=4)

                scan_btn = ttk.Button(imei_container, text="Scan", command=widget.focus_set)
                scan_btn.pack(side=tk.LEFT, padx=(5, 0))
            else:
                # Create and grid all other widgets normally
                if widget_class == ttk.Label:
                    widget = widget_class(form_frame, text=phone[i], font=("Segoe UI", 11, "bold"))
                elif widget_class == scrolledtext.ScrolledText:
                    widget = scrolledtext.ScrolledText(form_frame, width=30, height=4, font=("Segoe UI", 10), bg=self.surface_color, fg="#111111", wrap=tk.WORD)
                    widget.insert("1.0", phone[i] or "")
                else:
                    widget = widget_class(form_frame, width=40)
                    widget.insert(0, phone[i] or "")
                
                widget.grid(row=i - 1, column=1, padx=(10, 0), pady=6, ipady=4 if widget_class not in [scrolledtext.ScrolledText, ttk.Label] else 0, sticky="ew")

            form_fields[label_text] = widget
            
        form_frame.grid_columnconfigure(1, weight=1)

        # Onglet Info Vendeur
        seller_frame = ttk.Frame(notebook, style="Main.TFrame")
        notebook.add(seller_frame, text="  Info Vendeur", image=self.icon("user"), compound=tk.LEFT)

        seller_form_frame = ttk.Frame(seller_frame, style="Main.TFrame")
        seller_form_frame.pack(fill=tk.X, pady=(0, 12), padx=10)

        seller_field_map = {
            15: ("Nom du Vendeur *", ttk.Entry),
            17: ("Contact du Vendeur *", ttk.Entry),
            16: ("Prix d'Achat du Vendeur", ttk.Entry),
            18: ("Description du Vendeur", scrolledtext.ScrolledText)
        }

        seller_fields = {}
        for i, (label_text, widget_class) in seller_field_map.items():
            ttk.Label(seller_form_frame, text=label_text).grid(row=i - 13, column=0, sticky="w", pady=6)
            if widget_class == scrolledtext.ScrolledText:
                widget = scrolledtext.ScrolledText(seller_form_frame, width=30, height=4, font=("Segoe UI", 10), bg=self.surface_color, fg="#111111", wrap=tk.WORD)
                widget.insert("1.0", phone[i] or "")
            else:
                widget = widget_class(seller_form_frame, width=40)
                widget.insert(0, phone[i] or "")
            widget.grid(row=i - 13, column=1, padx=(10, 0), pady=6, ipady=4 if widget_class != scrolledtext.ScrolledText else 0, sticky="ew")
            seller_fields[label_text] = widget
        seller_form_frame.grid_columnconfigure(1, weight=1)

        button_frame = ttk.Frame(main_frame, style="Main.TFrame")
        button_frame.pack(fill=tk.X, pady=(8, 0))
        cancel_btn = ttk.Button(button_frame, text="Annuler", command=dialog.destroy)
        cancel_btn.pack(side=tk.RIGHT, padx=(10, 0))
        update_btn = ttk.Button(button_frame, text="Mettre à Jour le Téléphone", command=lambda: self.update_phone(phone_id, form_fields, seller_fields, dialog), bootstyle="primary")
        update_btn.pack(side=tk.RIGHT)


    def update_phone(self, phone_id, fields, seller_fields, dialog):
        def read_widget(mapping, *keys):
            widget = None
            for key in keys:
                if key in mapping:
                    widget = mapping.get(key)
                    break
            if widget is None:
                return ""
            try:
                if isinstance(widget, tk.Text):
                    return widget.get("1.0", tk.END).strip()
                return widget.get().strip()
            except Exception:
                return str(widget).strip() if widget is not None else ""

        try:
            brand = read_widget(fields, "brand", "Marque *")
            model = read_widget(fields, "model", "Modèle *")
            imei = read_widget(fields, "imei", "IMEI *")
            color = read_widget(fields, "color", "Couleur")
            storage = read_widget(fields, "storage", "Stockage")
            ram = read_widget(fields, "ram", "RAM")
            battery_state = read_widget(fields, "battery_state", "Etat Batterie *", "Etat Batterie")
            price_str = read_widget(fields, "price", "Prix *")
            description = read_widget(fields, "description", "Description")

            if not all([brand, model, imei, price_str]):
                messagebox.showwarning("Avertissement", "Les champs marqués avec * sont requis.")
                return

            price_val = float(price_str)
        except ValueError:
            messagebox.showerror("Erreur", "Le prix doit être un nombre.")
            return

        seller_name_val = read_widget(seller_fields, "seller_name", "Nom du Vendeur *")
        seller_contact_val = read_widget(seller_fields, "seller_contact", "Contact du Vendeur *")
        seller_description_val = read_widget(seller_fields, "seller_description", "Description du Vendeur")
        try:
            seller_price_text = read_widget(seller_fields, "seller_price", "Prix d'Achat du Vendeur")
            seller_price_val = float(seller_price_text) if seller_price_text else None
        except ValueError:
            seller_price_val = None

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        # update barcode image (recreate)
        cursor.execute("SELECT ID_phone, barcode_file_path FROM phones WHERE id = ?", (phone_id,))
        row = cursor.fetchone()
        old_barcode_path = row[1] if row and len(row) > 1 else None
        if old_barcode_path and os.path.exists(old_barcode_path):
            try:
                os.remove(old_barcode_path)
            except Exception:
                pass

        barcode_data_url = row[0] if row and len(row) > 0 else None
        if barcode_data_url:
            barcode_img = self.create_barcode_with_text(barcode_data_url, f"{brand} {model}")
            barcode_filename = f"{barcode_data_url}_{brand}_{model}.png".replace(" ", "_")
            barcode_filepath = os.path.join(self.barcode_folder, barcode_filename)
            barcode_img.save(barcode_filepath)
        else:
            barcode_filepath = None
            barcode_data_url = None

        try:
            cursor.execute("""
                UPDATE phones SET 
                    brand=?, model=?, imei=?, color=?, storage=?, ram=?, battery_state=?, price=?, description=?, 
                    barcode=?, barcode_file_path=?, seller_name=?, seller_contact=?, seller_description=?, seller_price=?
                WHERE id=?
            """, (
                brand, model, imei, color, storage, ram, battery_state, price_val, description,
                barcode_data_url, barcode_filepath,
                seller_name_val, seller_contact_val, seller_description_val, seller_price_val,
                phone_id
            ))
            conn.commit()
            conn.close()
            messagebox.showinfo("Succès", "Téléphone mis à jour avec succès!")
            dialog.destroy()
            self.load_phones_data()
        except sqlite3.IntegrityError as e:
            messagebox.showerror("Erreur", f"Un téléphone avec cet ID ou IMEI existe déjà: {e}")
        except Exception as e:
            messagebox.showerror("Erreur de Base de Données", f"Une erreur est survenue: {e}")


    def delete_phone(self):
        if self.current_user['role'] != 'admin':
            messagebox.showwarning("Accès Refusé", "Seuls les administrateurs peuvent supprimer les téléphones.")
            return
        selection = self.phones_tree.selection()
        if not selection:
            messagebox.showwarning("Avertissement", "Veuillez sélectionner un téléphone à supprimer.")
            return
        item = self.phones_tree.item(selection[0])
        phone_id, id_phone, brand, model = item['values'][0], item['values'][1], item['values'][2], item['values'][3]
        if messagebox.askyesno("Confirmer la Suppression", f"Êtes-vous sûr de vouloir supprimer {brand} {model} (ID: {id_phone})?"):
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT barcode_file_path FROM phones WHERE id = ?", (phone_id,))
            barcode_path = cursor.fetchone()
            if barcode_path and barcode_path[0] and os.path.exists(barcode_path[0]):
                os.remove(barcode_path[0])
            cursor.execute("DELETE FROM phones WHERE id = ?", (phone_id,))
            conn.commit()
            conn.close()
            messagebox.showinfo("Succès", "Téléphone supprimé avec succès!")
            self.load_phones_data()


    def _select_sales_date(self):
        """Compatibility helper for older buttons; DateEntry is used by setup_sales_section."""
        try:
            if hasattr(self, 'sales_date_entry'):
                self.sales_date_entry.entry.focus_set()
                return
        except Exception as e:
            print(f"Date picker focus error: {e}")


    def setup_sales_section(self):
        sales_toolbar = ttk.Frame(self.sales_frame, style="Main.TFrame")
        sales_toolbar.pack(fill=tk.X, pady=(0, 12))
        
        search_frame = ttk.Labelframe(sales_toolbar, text="Recherche & Filtre", padding=12, style="TLabelframe")
        search_frame.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0,12))
        
        inner = ttk.Frame(search_frame)
        inner.pack(fill=tk.X)
        inner.columnconfigure(1, weight=1)

        # Row 0: Search Text Entry
        ttk.Label(inner, text="Rechercher:").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        self.sales_search_var = tk.StringVar()
        search_entry = ttk.Entry(inner, textvariable=self.sales_search_var)
        search_entry.grid(row=0, column=1, sticky="ew", pady=4)
        
        # Row 1: Date Filter using DateEntry
        ttk.Label(inner, text="Date:").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        self.sales_date_entry = DateEntry(inner, dateformat="%Y-%m-%d", firstweekday=0) # Monday is 0
        self.sales_date_entry.grid(row=1, column=1, sticky="ew", pady=4)

        # Row 2: Action Buttons
        action_button_frame = ttk.Frame(inner)
        action_button_frame.grid(row=2, column=1, sticky="e", pady=(8, 0))

        clear_btn = ttk.Button(action_button_frame, text="Effacer", command=self.clear_sales_search, bootstyle="secondary")
        clear_btn.pack(side=tk.LEFT, padx=(0, 8))
        
        search_btn = self.icon_button(action_button_frame, "Rechercher", "search", command=self.search_sales, bootstyle="primary")
        search_btn.pack(side=tk.LEFT)

        top_actions = ttk.Labelframe(sales_toolbar, text="Actions sur la sélection", padding=12, style="TLabelframe")
        top_actions.pack(side=tk.RIGHT, fill=tk.Y)
        ttk.Button(top_actions, text="Voir Produit", command=self.show_phone_from_sale_selection, bootstyle="info-outline").pack(pady=2, fill=tk.X)
        ttk.Button(top_actions, text="Voir Acheteur", command=self.show_buyer_from_sale_selection, bootstyle="info-outline").pack(pady=2, fill=tk.X)
        
        list_frame = ttk.Labelframe(self.sales_frame, text="Ventes", padding=12, style="TLabelframe")
        list_frame.pack(fill=tk.BOTH, expand=True)
        columns = ("ID", "Type", "Produit", "Quantité", "Prix Unité", "Prix Total", "Acheteur", "Contact", "Date")
        self.sales_tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=18)
        widths = {"ID":50, "Type":80, "Produit":220, "Quantité":80, "Prix Unité":100, "Prix Total":100, "Acheteur":160, "Contact":140, "Date":140}
        for col in columns:
            self.sales_tree.heading(col, text=col)
            self.sales_tree.column(col, width=widths.get(col,100), anchor="center" if col in ("ID","Quantité","Prix Unité","Prix Total") else "w")
        v_scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.sales_tree.yview)
        h_scrollbar = ttk.Scrollbar(list_frame, orient=tk.HORIZONTAL, command=self.sales_tree.xview)
        self.sales_tree.configure(yscrollcommand=v_scrollbar.set, xscrollcommand=h_scrollbar.set)
        self.sales_tree.grid(row=0, column=0, sticky="nsew")
        v_scrollbar.grid(row=0, column=1, sticky="ns")
        h_scrollbar.grid(row=1, column=0, sticky="ew")
        list_frame.grid_rowconfigure(0, weight=1)
        list_frame.grid_columnconfigure(0, weight=1)
        self.load_recent_sales()


    def load_recent_sales(self):
        for i in self.sales_tree.get_children():
            self.sales_tree.delete(i)
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        q = """
            SELECT s.id, s.product_type,
                COALESCE(p.brand, a.brand, s.product_brand_snapshot, '') AS brand,
                COALESCE(p.model, a.model, s.product_model_snapshot, s.product_name_snapshot, '') AS model,
                COALESCE(s.sale_qty,1), COALESCE(s.sale_unit_price, s.sale_price,0), COALESCE(s.sale_total, s.sale_price,0),
                COALESCE(b.name, s.buyer_name_snapshot, ''), COALESCE(b.contact_info, s.buyer_contact_snapshot, ''), s.sale_date
            FROM sales s
            LEFT JOIN phones p ON s.product_type = 'phone' AND s.product_id = p.id
            LEFT JOIN accessories a ON s.product_type = 'accessory' AND s.product_id = a.id
            LEFT JOIN buyers b ON s.buyer_id = b.id
        """
        conds = []
        params = []
        if getattr(self, 'sales_search_var', None) and self.sales_search_var.get().strip():
            term = f"%{self.sales_search_var.get().strip().lower()}%"
            conds.append("(LOWER(COALESCE(p.brand,'')) LIKE ? OR LOWER(COALESCE(p.model,'')) LIKE ? OR LOWER(COALESCE(a.brand,'')) LIKE ? OR LOWER(COALESCE(a.model,'')) LIKE ? OR LOWER(COALESCE(s.product_name_snapshot,'')) LIKE ? OR LOWER(COALESCE(b.name, s.buyer_name_snapshot,'')) LIKE ?)")
            params.extend([term, term, term, term, term, term])
        
        # Get date from the DateEntry widget's associated entry field
        if getattr(self, 'sales_date_entry', None) and self.sales_date_entry.entry.get().strip():
            conds.append("DATE(s.sale_date) = ?")
            params.append(self.sales_date_entry.entry.get().strip())
            
        if conds:
            q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY s.sale_date DESC LIMIT 500"
        cursor.execute(q, params)
        rows = cursor.fetchall()
        conn.close()
        if not rows:
            self.sales_tree.insert("", tk.END, values=("", "Aucune vente", "", "", "", "", "", "", ""))
            return
        for r in rows:
            sale_id, ptype, brand, model, qty, unit_price, total_price, buyer, contact, date = r
            prod_label = f"{brand or '-'} {model or '-'}"
            type_label = "Téléphone" if ptype == "phone" else "Accessoire"
            unit_label = f"{(unit_price or 0):.2f}MAD"
            total_label = f"{(total_price or 0):.2f}MAD"
            self.sales_tree.insert("", tk.END, values=(sale_id, type_label, prod_label, qty or 1, unit_label, total_label, buyer or "-", contact or "-", date or "-"))


    def show_buyer_from_sale_selection(self):
        """Open buyer info modal for the buyer related to the selected sale."""
        sel = self.sales_tree.selection()
        if not sel:
            messagebox.showwarning("Avertissement", "Veuillez sélectionner une vente.")
            return
        iid = sel[0]  # like "sale_123"
        try:
            sale_id = int(self.sales_tree.item(iid)['values'][0])
        except Exception:
            messagebox.showerror("Erreur", "Impossible de lire la vente sélectionnée.")
            return

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT b.id, b.name, b.contact_info, b.description
            FROM buyers b
            JOIN sales s ON s.buyer_id = b.id
            WHERE s.id = ?
            LIMIT 1
        """, (sale_id,))
        buyer = cursor.fetchone()
        conn.close()

        if not buyer:
            messagebox.showinfo("Info", "Acheteur introuvable.")
            return

        b_id, name, contact, description = buyer
        dialog = tk.Toplevel(self.root)
        dialog.title("Détails de l'Acheteur")
        dialog.geometry("480x320")
        dialog.transient(self.root)
        dialog.grab_set()

        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (dialog.winfo_width() // 2)
        y = (dialog.winfo_screenheight() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")

        main = ttk.Frame(dialog, style="Main.TFrame", padding=14)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main, text=f"{name}", style="Heading.TLabel").pack(anchor="w")
        ttk.Label(main, text=f"Contact: {contact or '-'}", style="TLabel").pack(anchor="w", pady=(8,0))
        ttk.Label(main, text="Description:", style="TLabel").pack(anchor="w", pady=(8,0))
        desc = scrolledtext.ScrolledText(main, width=40, height=6, font=("Segoe UI", 10), bg=self.surface_color, fg="#111111", wrap=tk.WORD)
        desc.insert("1.0", description or "")
        desc.configure(state="disabled")
        desc.pack(fill=tk.BOTH, expand=True, pady=(4,0))

        btn_frame = ttk.Frame(main, style="Main.TFrame")
        btn_frame.pack(fill=tk.X, pady=(8,0))
        ttk.Button(btn_frame, text="Fermer", command=dialog.destroy).pack(side=tk.RIGHT)


    def show_phone_from_sale_selection(self):
        """Open the product details modal for the product related to the selected sale."""
        sel = self.sales_tree.selection()
        if not sel:
            messagebox.showwarning("Avertissement", "Veuillez sélectionner une vente.")
            return
        iid = sel[0]
        try:
            sale_id = int(self.sales_tree.item(iid)['values'][0])
        except Exception:
            messagebox.showerror("Erreur", "Impossible de lire la vente sélectionnée.")
            return

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT product_type, product_id FROM sales WHERE id = ?", (sale_id,))
        row = cursor.fetchone()
        conn.close()
        if not row:
            messagebox.showerror("Erreur", "Produit associé introuvable.")
            return
        ptype, pid = row
        try:
            if ptype == "phone":
                self.show_phone_details_by_id(pid)
            elif ptype == "accessory":
                self.show_accessory_details(pid)
            else:
                messagebox.showinfo("Info", "Type de produit inconnu.")
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible d'ouvrir la fiche: {e}")


###############################################################################################################################
    def get_downloads_folder(self):
        """
        Return the user's Downloads folder path.
        Simple and reliable fallback: ~/Downloads (will be created if missing).
        This avoids NameError and works cross-platform.
        """
        try:
            downloads = Path.home() / "Downloads"
            downloads.mkdir(parents=True, exist_ok=True)
            return downloads
        except Exception:
            # final fallback to current working directory
            return Path.cwd()


    def setup_reports_section(self):
        """Only the two period reports: bought_in_period & sales_in_period (PDF export)."""
        controls_frame = ttk.Labelframe(self.reports_frame, text="Configuration du Rapport", padding=12)
        controls_frame.pack(fill=tk.X, pady=(0, 12))

        date_frame = ttk.Frame(controls_frame)
        date_frame.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(date_frame, text="Période de Dates:").pack(side=tk.LEFT)
        self.from_date = ttk.Entry(date_frame, width=12)
        self.from_date.pack(side=tk.LEFT, padx=(8, 6))
        self.from_date.insert(0, (datetime.datetime.now() - datetime.timedelta(days=30)).strftime("%Y-%m-%d"))

        ttk.Label(date_frame, text="à").pack(side=tk.LEFT, padx=4)
        self.to_date = ttk.Entry(date_frame, width=12)
        self.to_date.pack(side=tk.LEFT, padx=(6, 20))
        self.to_date.insert(0, datetime.datetime.now().strftime("%Y-%m-%d"))

        type_frame = ttk.Frame(controls_frame)
        type_frame.pack(fill=tk.X, pady=(8, 8))

        ttk.Label(type_frame, text="Type de Rapport:").pack(side=tk.LEFT, anchor="n")
        self.report_type = tk.StringVar(value="bought_period")
        types_frame = ttk.Frame(type_frame)
        types_frame.pack(side=tk.LEFT, padx=(8,0))

        ttk.Radiobutton(types_frame, text="Téléphones achetés (période)", variable=self.report_type, value="bought_period").pack(anchor="w")
        ttk.Radiobutton(types_frame, text="Accessoires achetés (période)", variable=self.report_type, value="bought_accessories_period").pack(anchor="w")
        ttk.Radiobutton(types_frame, text="Ventes (période)", variable=self.report_type, value="sales_period").pack(anchor="w")

        actions_frame = ttk.Frame(controls_frame)
        actions_frame.pack(fill=tk.X, pady=(6,0))

        generate_btn = ttk.Button(actions_frame, text="Générer le Rapport", command=self.generate_report, bootstyle="primary")
        generate_btn.pack(side=tk.LEFT)

        export_frame = ttk.Frame(actions_frame)
        export_frame.pack(side=tk.RIGHT)
        ttk.Button(export_frame, text="Exporter PDF", command=self.export_to_pdf, bootstyle="secondary-outline").pack(side=tk.LEFT)

        # results preview
        results_frame = ttk.Labelframe(self.reports_frame, text="Résultats du Rapport", padding=10)
        results_frame.pack(fill=tk.BOTH, expand=True)
        self.results_text = scrolledtext.ScrolledText(results_frame, wrap=tk.WORD, height=18, font=("Consolas", 10))
        self.results_text.pack(fill=tk.BOTH, expand=True)

        self.last_report = None


    def generate_report(self):
        """Route to the chosen report type (period-based)."""
        report_type = self.report_type.get()
        from_date = self.from_date.get().strip()
        to_date = self.to_date.get().strip()

        # require dates for all period reports
        if not from_date or not to_date:
            messagebox.showwarning("Avertissement", "Veuillez sélectionner une période de dates.")
            return

        self.results_text.delete(1.0, tk.END)
        self.last_report = None

        if report_type == "bought_period":
            self.generate_bought_phones_report(from_date, to_date)
        elif report_type == "bought_accessories_period":
            self.generate_bought_accessories_report(from_date, to_date)
        elif report_type == "sales_period":
            self.generate_sales_report(from_date, to_date)
        else:
            messagebox.showwarning("Avertissement", "Type de rapport inconnu.")


    def generate_bought_phones_report(self, from_date, to_date):
        """Phones bought during period with seller info. Filters by purchase date if detected."""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        # detect possible purchase date column in phones table
        cursor.execute("PRAGMA table_info(phones)")
        cols = [r[1].lower() for r in cursor.fetchall()]
        date_candidates = ["seller_date", "purchase_date", "bought_date", "date_bought", "date_added", "created_at", "added_at", "purchase_at"]
        used_date_col = None
        for c in date_candidates:
            if c in cols:
                used_date_col = c
                break

        if used_date_col:
            q = f"""
                SELECT ID_phone, brand, model, imei, price, COALESCE(seller_name,''), COALESCE(seller_price,0), COALESCE(seller_contact,''), {used_date_col}
                FROM phones
                WHERE DATE({used_date_col}) BETWEEN ? AND ?
                ORDER BY {used_date_col} DESC
            """
            cursor.execute(q, (from_date, to_date))
        else:
            # No date column — show all phones that have seller info
            q = """
                SELECT ID_phone, brand, model, imei, price, COALESCE(seller_name,''), COALESCE(seller_price,0), COALESCE(seller_contact,''), NULL
                FROM phones
                WHERE (seller_name IS NOT NULL AND TRIM(seller_name) <> '') OR seller_price IS NOT NULL
                ORDER BY brand, model
            """
            cursor.execute(q)
        phones = cursor.fetchall()
        conn.close()

        if not phones:
            self.results_text.insert(tk.END, "Aucun téléphone acheté trouvé pour la période.\n")
            if not used_date_col:
                messagebox.showinfo("Information", "Aucune colonne de date d'achat détectée; affichage de tous les téléphones achetés.")
            self.last_report = {"type": "bought_period", "from": from_date, "to": to_date, "phones": []}
            return

        # preview
        hdr = f"TÉLÉPHONES ACHETÉS — {from_date} → {to_date}\n\n"
        if not used_date_col:
            hdr += "(Note: Aucun champ date détecté — impossible de filtrer par période.)\n\n"
        self.results_text.insert(tk.END, hdr)

        self.results_text.insert(tk.END, f"{'ID':<6} {'Marque':<12} {'Modèle':<18} {'IMEI':<16} {'Prix':<10} {'Vendeur':<18} {'Contact':<18} {'Date':<20}\n")
        self.results_text.insert(tk.END, "-" * 120 + "\n")
        for id_phone, brand, model, imei, price, seller_name, seller_price, seller_contact, date_col in phones:
            paid = seller_price or price or 0
            seller_name = seller_name or "-"
            seller_contact = seller_contact or "-"
            display_date = date_col or "-"
            self.results_text.insert(tk.END, f"{id_phone:<6} {brand or '-':<12} {model or '-':<18} {imei or '-':<16} {paid:<9.2f}MAD {seller_name:<18} {seller_contact:<18} {display_date:<20}\n")

        self.last_report = {
            "type": "bought_period",
            "from": from_date,
            "to": to_date,
            "date_column_used": used_date_col,
            "phones": phones
        }


    def generate_bought_accessories_report(self, from_date, to_date):
        """Accessories bought during period with seller info."""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        q = """
            SELECT name, brand, model, quantity, price, 
                   COALESCE(seller_name,''), COALESCE(seller_price,0), 
                   COALESCE(seller_total_price, 0), COALESCE(seller_contact,''), date_added
            FROM accessories
            WHERE DATE(date_added) BETWEEN ? AND ?
            ORDER BY date_added DESC
        """
        cursor.execute(q, (from_date, to_date))
        accessories = cursor.fetchall()
        conn.close()

        if not accessories:
            self.results_text.insert(tk.END, "Aucun accessoire acheté trouvé pour la période.\n")
            self.last_report = {"type": "bought_accessories_period", "from": from_date, "to": to_date, "accessories": []}
            return

        # Prepare data for display and storage
        report_data = []
        total_cost = 0
        for name, brand, model, qty, price, s_name, s_price, s_total, s_contact, date in accessories:
            cost = s_total if s_total is not None and s_total > 0 else (s_price * qty if s_price and qty else 0)
            total_cost += cost
            report_data.append({
                "name": name, "brand": brand, "model": model, "qty": qty, 
                "s_name": s_name or "-", "cost": cost, "s_contact": s_contact or "-", "date": date
            })

        # Display preview in the text widget
        hdr = f"ACCESSOIRES ACHETÉS — {from_date} → {to_date}\n\n"
        self.results_text.insert(tk.END, hdr)
        self.results_text.insert(tk.END, f"{'Nom':<25} {'Marque':<15} {'Modèle':<15} {'Qté':<5} {'Vendeur':<18} {'Contact':<18} {'Coût':<12} {'Date':<20}\n")
        self.results_text.insert(tk.END, "-" * 135 + "\n")

        for item in report_data:
            self.results_text.insert(tk.END, f"{item['name']:<25} {item['brand'] or '-':<15} {item['model'] or '-':<15} {item['qty']:<5} {item['s_name']:<18} {item['s_contact']:<18} {item['cost']:<11.2f}MAD {item['date']:<20}\n")
        
        self.results_text.insert(tk.END, f"\n\nCoût Total des Achats d'Accessoires: {total_cost:.2f} MAD\n")

        # Store data for potential PDF export
        self.last_report = {
            "type": "bought_accessories_period",
            "from": from_date,
            "to": to_date,
            "accessories": report_data,
            "total_cost": total_cost
        }


    def generate_sales_report(self, from_date, to_date):
        """Phones and accessories sold during period with buyer info."""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT s.id,
                COALESCE(p.ID_phone, a.SKU, s.product_ref, '') AS item_id,
                COALESCE(p.brand || ' ' || p.model, a.name, s.product_name_snapshot, '') AS item_name,
                COALESCE(b.name, s.buyer_name_snapshot, '') AS buyer, COALESCE(b.contact_info, s.buyer_contact_snapshot, '') as buyer_contact,
                COALESCE(s.sale_total, s.sale_price, 0), s.sale_date, COALESCE(p.imei, s.product_imei_snapshot, '') as imei, s.product_type
            FROM sales s
            LEFT JOIN phones p ON s.product_type = 'phone' AND s.product_id = p.id
            LEFT JOIN accessories a ON s.product_type = 'accessory' AND s.product_id = a.id
            LEFT JOIN buyers b ON s.buyer_id = b.id
            WHERE DATE(s.sale_date) BETWEEN ? AND ?
            ORDER BY s.sale_date DESC
        """, (from_date, to_date))
        sales_rows = cursor.fetchall()

        cursor.execute("""
            SELECT COALESCE(SUM(COALESCE(sale_total, sale_price, 0)),0) as total_revenue, COUNT(id) as tx_count
            FROM sales
            WHERE DATE(sale_date) BETWEEN ? AND ?
        """, (from_date, to_date))
        sales_summary = cursor.fetchone() or (0, 0)

        conn.close()

        if not sales_rows:
            self.results_text.insert(tk.END, "Aucune vente trouvée pour la période.\n")
            self.last_report = {"type": "sales_period", "from": from_date, "to": to_date, "sales": [], "summary": (0,0)}
            return

        hdr = f"VENTES — {from_date} → {to_date}\n\n"
        self.results_text.insert(tk.END, hdr)
        # header for combined table
        self.results_text.insert(tk.END, f"{'ID':<6} {'Réf/ID':<12} {'Produit':<28} {'Type':<10} {'Acheteur':<18} {'Contact':<16} {'Prix':<10} {'Date':<20}\n")
        self.results_text.insert(tk.END, "-" * 120 + "\n")
        for sale_id, item_id, item_name, buyer, buyer_contact, price, sale_date, imei, product_type in sales_rows:
            buyer = buyer or "-"
            buyer_contact = buyer_contact or "-"
            product_type_label = "Tel." if product_type == "phone" else "Accessoire"
            self.results_text.insert(tk.END, f"{sale_id:<6} {item_id or '-':<12} {item_name or '-':<28} {product_type_label:<10} {buyer:<18} {buyer_contact:<16} {price:<9.2f}MAD {sale_date or '-':<20}\n")

        total_revenue, total_tx = sales_summary if sales_summary else (0,0)
        self.results_text.insert(tk.END, f"\nRevenu total: {total_revenue:.2f} MAD | Transactions: {total_tx}\n")

        self.last_report = {
            "type": "sales_period",
            "from": from_date,
            "to": to_date,
            "sales": sales_rows,
            "summary": sales_summary
        }


    def generate_sales_report_modal(self, from_date, to_date):
        """Show sales report in a table modal (phones + accessories) and allow PDF export."""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT s.id, s.product_type, COALESCE(p.brand, a.brand, s.product_brand_snapshot, '') AS brand,
                COALESCE(p.model, a.model, s.product_model_snapshot, s.product_name_snapshot, '') AS model,
                COALESCE(s.sale_qty,1), COALESCE(s.sale_unit_price, s.sale_price, 0), COALESCE(s.sale_total, s.sale_price, 0),
                COALESCE(b.name, s.buyer_name_snapshot, '') AS buyer, COALESCE(b.contact_info, s.buyer_contact_snapshot, '') as contact, s.sale_date
            FROM sales s
            LEFT JOIN phones p ON s.product_type = 'phone' AND s.product_id = p.id
            LEFT JOIN accessories a ON s.product_type = 'accessory' AND s.product_id = a.id
            LEFT JOIN buyers b ON s.buyer_id = b.id
            WHERE DATE(s.sale_date) BETWEEN ? AND ?
            ORDER BY s.sale_date DESC
        """, (from_date, to_date))
        rows = cursor.fetchall()
        conn.close()

        modal = tk.Toplevel(self.root)
        modal.title(f"Rapport Ventes {from_date} → {to_date}")
        modal.geometry("900x600")
        modal.transient(self.root)
        modal.grab_set()

        frame = ttk.Frame(modal, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        cols = ("ID", "Type", "Marque", "Modèle", "Qté", "Prix Unité", "Prix Total", "Acheteur", "Contact", "Date")
        tree = ttk.Treeview(frame, columns=cols, show="headings")
        widths = {"ID":50, "Type":80, "Marque":120, "Modèle":220, "Qté":60, "Prix Unité":100, "Prix Total":100, "Acheteur":150, "Contact":140, "Date":140}
        for c in cols:
            tree.heading(c, text=c)
            tree.column(c, width=widths.get(c, 100), anchor="center" if c in ("ID","Qté","Prix Unité","Prix Total") else "w")
        vs = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=vs.set)
        tree.grid(row=0, column=0, sticky="nsew")
        vs.grid(row=0, column=1, sticky="ns")
        frame.grid_rowconfigure(0, weight=1)
        frame.grid_columnconfigure(0, weight=1)

        for r in rows:
            sale_id, ptype, brand, model, qty, unit, total, buyer, contact, date = r
            typelabel = "Téléphone" if ptype == "phone" else "Accessoire"
            tree.insert("", tk.END, values=(sale_id, typelabel, brand or "-", model or "-", qty or 1, f"{(unit or 0):.2f}MAD", f"{(total or 0):.2f}MAD", buyer or "-", contact or "-", date or "-"))

        btn_frame = ttk.Frame(modal)
        btn_frame.pack(fill=tk.X, pady=(8,0))
        ttk.Button(btn_frame, text="Fermer", command=modal.destroy).pack(side=tk.RIGHT, padx=(8,0))

        def export_pdf():
            # build a simple table for ReportLab
            try:
                from reportlab.platypus import Table, TableStyle, SimpleDocTemplate, Paragraph, Spacer
                from reportlab.lib import colors
                from reportlab.lib.pagesizes import A4
                from reportlab.lib.styles import getSampleStyleSheet
            except Exception:
                messagebox.showerror("Erreur", "reportlab requis pour exporter. pip install reportlab")
                return

            data = [cols]
            for item in tree.get_children():
                data.append(list(tree.item(item)['values']))
            doc_title = f"Rapport_Ventes_{from_date}_to_{to_date}"
            elements = []
            styles = getSampleStyleSheet()
            elements.append(Paragraph(f"Rapport Ventes — {from_date} → {to_date}", styles['Heading2']))
            elements.append(Spacer(1, 12))
            t = Table(data, repeatRows=1)
            t.setStyle(TableStyle([
                ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#f0f0f0")),
                ('GRID', (0,0), (-1,-1), 0.5, colors.black),
                ('VALIGN',(0,0),(-1,-1),'MIDDLE'),
            ]))
            elements.append(t)
            # use your _save_pdf helper to save the PDF; it expects title and elements
            self._save_pdf(doc_title, elements)

        ttk.Button(btn_frame, text="Exporter en PDF", command=export_pdf, bootstyle="primary").pack(side=tk.RIGHT, padx=(0,8))


    def _save_pdf(self, doc_title, elements):
        """Save reportlab elements to a PDF inside the user's Downloads folder and open it."""
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.platypus import SimpleDocTemplate
        except Exception:
            messagebox.showerror("Erreur", "Le module reportlab est requis pour exporter en PDF. Installez-le: pip install reportlab")
            return None

        downloads = self.get_downloads_folder()
        try:
            downloads.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_title = "".join(c for c in doc_title if c.isalnum() or c in (" ", "_", "-")).rstrip().replace(" ", "_")
        filename = f"{safe_title}_{timestamp}.pdf"
        filepath = downloads / filename

        try:
            doc = SimpleDocTemplate(str(filepath), pagesize=A4, leftMargin=36, rightMargin=36, topMargin=36, bottomMargin=36)
            doc.build(elements)
        except Exception as ex:
            # fallback to home directory
            try:
                fallback = Path.home() / filename
                doc = SimpleDocTemplate(str(fallback), pagesize=A4)
                doc.build(elements)
                filepath = fallback
            except Exception as ex2:
                messagebox.showerror("Erreur", f"Impossible de créer le PDF:\n{ex}\n{ex2}")
                return None

        # try to open the generated file
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(filepath))
            elif sys.platform == "darwin":
                subprocess.call(["open", str(filepath)])
            else:
                subprocess.call(["xdg-open", str(filepath)])
        except Exception:
            pass

        return filepath


    def export_to_pdf(self):
        """Exporter le rapport texte actuel (results_text) vers le dossier 'reports' à côté de l'application."""
        content = self.results_text.get("1.0", tk.END).strip()
        if not content:
            messagebox.showwarning("Avertissement", "Aucun rapport à exporter.")
            return

        # Determine application directory (works for script and frozen exe)
        import sys
        from pathlib import Path as _Path
        try:
            if getattr(sys, "frozen", False):
                app_dir = _Path(sys.argv[0]).resolve().parent
            else:
                app_dir = _Path(__file__).resolve().parent
        except Exception:
            app_dir = _Path.cwd()

        reports_dir = app_dir / "reports"
        try:
            reports_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            # fallback to home directory
            reports_dir = _Path.home()
            reports_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"rapport_{timestamp}.pdf"
        filepath = reports_dir / filename

        try:
            # create a simple PDF using reportlab canvas
            c = canvas.Canvas(str(filepath), pagesize=letter)
            width, height = letter
            margin = 40
            y = height - margin
            max_line_width = width - margin * 2
            lines_content = content.splitlines()
            font_size = 10
            leading = font_size + 2
            c.setFont("Helvetica", font_size)
            for line in lines_content:
                remaining = line
                # naive wrapping based on number of characters estimate
                while remaining:
                    # approximate characters per line
                    approx_chars = int(max_line_width / (font_size * 0.6))
                    part = remaining[:approx_chars]
                    remaining = remaining[approx_chars:]
                    c.drawString(margin, y, part)
                    y -= leading
                    if y < margin:
                        c.showPage()
                        c.setFont("Helvetica", font_size)
                        y = height - margin
            c.save()
            messagebox.showinfo("Exportation", f"Rapport PDF enregistré dans : {filepath}")
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible d'exporter en PDF: {e}")


###############################################################################################################################
    def setup_settings_section(self):
        for w in self.settings_frame.winfo_children():
            w.destroy()

        settings_frame = ttk.Labelframe(self.settings_frame, text="Paramètres Système", padding=14)
        settings_frame.pack(fill=tk.X, pady=(0, 12))

        vendor_frame = ttk.Labelframe(settings_frame, text="Comptes Vendeurs", padding=10)
        vendor_frame.pack(fill=tk.X, pady=(0, 10))

        form_frame = ttk.Frame(vendor_frame)
        form_frame.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(form_frame, text="Nom d'utilisateur:").grid(row=0, column=0, sticky="w")
        self.new_vendor_username = ttk.Entry(form_frame, width=28)
        self.new_vendor_username.grid(row=0, column=1, padx=(8, 0), pady=4)

        ttk.Label(form_frame, text="Mot de passe:").grid(row=1, column=0, sticky="w")
        self.new_vendor_password = ttk.Entry(form_frame, show="*", width=28)
        self.new_vendor_password.grid(row=1, column=1, padx=(8, 0), pady=4)

        ttk.Label(form_frame, text="Confirmer mot de passe:").grid(row=2, column=0, sticky="w")
        self.new_vendor_confirm = ttk.Entry(form_frame, show="*", width=28)
        self.new_vendor_confirm.grid(row=2, column=1, padx=(8, 0), pady=4)

        btn_frame = ttk.Frame(vendor_frame)
        btn_frame.pack(fill=tk.X, pady=(6, 0))
        self.icon_button(btn_frame, "Créer Vendeur", "plus", command=lambda: self.create_vendor_account(
            self.new_vendor_username.get().strip(),
            self.new_vendor_password.get().strip(),
            self.new_vendor_confirm.get().strip()
        )).pack(side=tk.LEFT)
        self.icon_button(btn_frame, "Réinitialiser", "refresh", command=lambda: (
            self.new_vendor_username.delete(0, tk.END),
            self.new_vendor_password.delete(0, tk.END),
            self.new_vendor_confirm.delete(0, tk.END)
        )).pack(side=tk.LEFT, padx=(8,0))

        list_frame = ttk.Frame(vendor_frame)
        list_frame.pack(fill=tk.X, pady=(8,0))
        ttk.Label(list_frame, text="Vendeurs existants:").pack(anchor="w")
        self.vendors_listbox = tk.Listbox(list_frame, height=6)
        self.vendors_listbox.pack(fill=tk.X, pady=(4,0))
        vendors_btn_frame = ttk.Frame(list_frame)
        vendors_btn_frame.pack(fill=tk.X, pady=(6,0))
        ttk.Button(vendors_btn_frame, text="Supprimer sélection", command=self.delete_selected_vendor).pack(side=tk.LEFT)
        ttk.Button(vendors_btn_frame, text="Actualiser", command=self.load_vendors_list).pack(side=tk.LEFT, padx=(8,0))

        # Sauvegarde et suppression DB (seulement admin)
        backup_frame = ttk.Labelframe(settings_frame, text="Sauvegarde / Base de Données", padding=10)
        backup_frame.pack(fill=tk.X, pady=(0,10))

        backup_btn = self.icon_button(backup_frame, "Sauvegarder la base de données", "database", command=self.create_db_backup)
        backup_btn.pack(side=tk.LEFT)
        delete_btn = self.icon_button(backup_frame, "Supprimer la base de données", "delete", command=self.delete_database_file)
        delete_btn.pack(side=tk.LEFT, padx=(8,0))

        if not (self.current_user and self.current_user.get('role') == 'admin'):
            try:
                backup_btn.state(['disabled'])
                delete_btn.state(['disabled'])
            except Exception:
                pass

        # Toggle scanner option
        scan_frame = ttk.Labelframe(settings_frame, text="Scanner Global (optionnel)", padding=10)
        scan_frame.pack(fill=tk.X, pady=(0, 10))
        self.global_scan_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(scan_frame, text="Activer le scan global (ouvrir fiche après scan + Enter)", variable=self.global_scan_var, command=self.toggle_global_scanner).pack(anchor="w")
        ttk.Label(scan_frame, text="(Le scanner doit envoyer le code puis la touche Enter.)").pack(anchor="w", pady=(6,0))

        self.load_vendors_list()


    def prompt_admin_password(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("Confirmer le mot de passe")
        dlg.geometry("360x140")
        dlg.transient(self.root)
        dlg.grab_set()
        res = {'password': None}

        frm = ttk.Frame(dlg, padding=12)
        frm.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frm, text="Entrez votre mot de passe administrateur:", wraplength=320).pack(anchor="w", pady=(0,8))
        pw_entry = ttk.Entry(frm, show="*", width=30)
        pw_entry.pack(fill=tk.X, pady=(0,10))
        pw_entry.focus()

        btnf = ttk.Frame(frm)
        btnf.pack(fill=tk.X)
        def on_ok():
            res['password'] = pw_entry.get()
            dlg.destroy()
        def on_cancel():
            dlg.destroy()

        ttk.Button(btnf, text="Valider", command=on_ok).pack(side=tk.RIGHT, padx=(8,0))
        ttk.Button(btnf, text="Annuler", command=on_cancel).pack(side=tk.RIGHT)
        self.root.wait_window(dlg)
        return res['password']


    def delete_database_file(self):
        if not (self.current_user and self.current_user.get('role') == 'admin'):
            messagebox.showwarning("Accès Refusé", "Seuls les administrateurs peuvent supprimer la base de données.")
            return

        pwd = self.prompt_admin_password()
        if not pwd:
            return

        try:
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("SELECT password FROM users WHERE username = ? LIMIT 1", (self.current_user.get('username'),))
            row = cursor.fetchone()
            conn.close()
            if not row or not verify_password(row[0], pwd):
                messagebox.showerror("Erreur", "Mot de passe incorrect.")
                return
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de vérifier le mot de passe: {e}")
            return

        ok = messagebox.askyesno("Confirmation", "Êtes-vous sûr ? Cette opération supprimera définitivement le fichier de la base de données.\n\nCela ne pourra pas être annulé.")
        if not ok:
            return

        try:
            if os.path.exists(DB_PATH):
                os.remove(DB_PATH)
            # optionally keep backups folder; notify user
            messagebox.showinfo("Succès", f"Fichier de base de données supprimé:\n{DB_PATH}\n\nL'application va maintenant se fermer.")
            try:
                self.root.destroy()
            except Exception:
                pass
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de supprimer la base de données: {e}")


    def create_db_backup(self):
        if not (self.current_user and self.current_user.get('role') == 'admin'):
            messagebox.showwarning("Accès Refusé", "Seuls les administrateurs peuvent faire une sauvegarde.")
            return
        try:
            backups_dir = os.path.join(DB_DIR, "backups")
            os.makedirs(backups_dir, exist_ok=True)
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            dest = os.path.join(backups_dir, f"phone_shop_backup_{timestamp}.db")
            shutil.copy2(DB_PATH, dest)
            messagebox.showinfo("Sauvegarde", f"Sauvegarde créée:\n{dest}")
        except Exception as e:
            messagebox.showerror("Erreur", f"Impossible de sauvegarder la base: {e}")


    def create_vendor_account(self, username, password, confirm_password):
        """Créer un compte de role 'vendor'"""
        if not username or not password or not confirm_password:
            messagebox.showwarning("Erreur", "Tous les champs sont requis.")
            return
        if password != confirm_password:
            messagebox.showwarning("Erreur", "Les mots de passe ne correspondent pas.")
            return
        if len(password) < 4:
            messagebox.showwarning("Erreur", "Mot de passe trop court (min 4 caractères).")
            return

        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
        if cursor.fetchone():
            conn.close()
            messagebox.showerror("Erreur", "Nom d'utilisateur déjà utilisé.")
            return
        cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", (username, hash_password(password), "vendor"))
        conn.commit()
        conn.close()
        messagebox.showinfo("Succès", f"Compte vendeur '{username}' créé.")
        # clear form and refresh list
        try:
            self.new_vendor_username.delete(0, tk.END)
            self.new_vendor_password.delete(0, tk.END)
            self.new_vendor_confirm.delete(0, tk.END)
        except Exception:
            pass
        self.load_vendors_list()

    def load_vendors_list(self):
        """Charger la liste des vendeurs dans la listbox"""
        try:
            self.vendors_listbox.delete(0, tk.END)
        except Exception:
            pass
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT id, username FROM users WHERE role = 'vendor' ORDER BY username")
        rows = cursor.fetchall()
        conn.close()
        for r in rows:
            self.vendors_listbox.insert(tk.END, f"{r[0]} | {r[1]}")

    def delete_selected_vendor(self):
        sel = self.vendors_listbox.curselection()
        if not sel:
            messagebox.showwarning("Avertissement", "Veuillez sélectionner un vendeur à supprimer.")
            return
        entry = self.vendors_listbox.get(sel[0])
        vendor_id = int(entry.split("|",1)[0].strip())
        if messagebox.askyesno("Confirmer", "Supprimer ce vendeur ?"):
            conn = sqlite3.connect(DB_PATH)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM users WHERE id = ? AND role = 'vendor'", (vendor_id,))
            conn.commit()
            conn.close()
            messagebox.showinfo("Succès", "Vendeur supprimé.")
            self.load_vendors_list()


    def toggle_global_scanner(self):
        """Activer / désactiver l'écoute des touches pour scanner via pistolet."""
        enabled = self.global_scan_var.get()
        self.scan_buffer = ""  # reset
        if enabled:
            self.root.bind_all("<Key>", self._on_keypress)
            messagebox.showinfo("Scan global", "Scan global activé. Scannez un code puis appuyez sur Enter.")
        else:
            try:
                self.root.unbind_all("<Key>")
            except Exception:
                pass
            messagebox.showinfo("Scan global", "Scan global désactivé.")

    def _on_keypress(self, event):
        """Collecte les caractères envoyés par le scanner. Ignore si focus dans un Entry/Text."""
        focus_widget = self.root.focus_get()
        if focus_widget and hasattr(focus_widget, "winfo_class"):
            cls = focus_widget.winfo_class()
            if cls in ("Entry", "TEntry", "Text"):
                return

        ch = event.char
        if not ch:
            # handle control keys
            if event.keysym == "Return":
                if hasattr(self, "scan_buffer") and self.scan_buffer:
                    code = self.scan_buffer.strip()
                    self.scan_buffer = ""
                    if code:
                        self.handle_scanned_barcode(code)
            return

        if ch.isprintable():
            if not hasattr(self, "scan_buffer"):
                self.scan_buffer = ""
            self.scan_buffer += ch
            # limit buffer size
            if len(self.scan_buffer) > 200:
                self.scan_buffer = self.scan_buffer[-200:]

    def handle_scanned_barcode(self, code):
        """Rechercher le produit scanné et ouvrir sa fiche si trouvé."""
        self.search_by_barcode(code, dialog=None)

    def get_phone_count(self):
        """Obtenir le nombre total de téléphones"""
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM phones")
        count = cursor.fetchone()[0]
        conn.close()
        return count

    def get_available_phone_count(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM phones WHERE available = 1")
        count = cursor.fetchone()[0]
        conn.close()
        return count

    def get_sold_phone_count(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM phones WHERE available = 0")
        count = cursor.fetchone()[0]
        conn.close()
        return count

    def get_buyer_count(self):
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM buyers")
        count = cursor.fetchone()[0]
        conn.close()
        return count

    def backup_database(self):
        """Créer une sauvegarde de la base de données"""
        try:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_filename = f"phone_shop_backup_{timestamp}.db"
            shutil.copy2(DB_PATH, backup_filename)
            messagebox.showinfo("Succès", f"Sauvegarde de la base de données créée avec succès:\n{backup_filename}")
        except Exception as e:
            messagebox.showerror("Erreur", f"Échec de la création de la sauvegarde: {str(e)}")


if __name__ == "__main__":
    root = tk.Tk()
    app = PhoneShopApp(root)
    root.mainloop()
