#!/usr/bin/env python3
"""
Phone Shop Management System - Database Seeder & Reset Tool
Interactive CLI utility to seed test data or reset the database.
"""

import os
import sys
import sqlite3
import datetime
import random
import shutil
import hashlib
import hmac
from pathlib import Path

# --- DATABASE & BARCODE PATHS (Matches main.py) ---
APP_NAME = "PhoneShopManager"
DB_DIR = os.path.join(os.getenv("APPDATA") or os.path.expanduser("~"), APP_NAME)
os.makedirs(DB_DIR, exist_ok=True)

DB_PATH = os.path.join(DB_DIR, "phone_shop.db")
BARCODES_DIR = os.path.join(DB_DIR, "codes_barres")
os.makedirs(BARCODES_DIR, exist_ok=True)


def hash_password(password: str) -> str:
    """PBKDF2 sha256 hash matching main.py."""
    salt = os.urandom(16).hex()
    rounds = 120000
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), rounds).hex()
    return f"pbkdf2_sha256${rounds}${salt}${digest}"


def init_db_schema():
    """Ensure all required tables and columns exist before seeding."""
    with sqlite3.connect(DB_PATH) as conn:
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

        # Ensure default accounts
        cursor.execute("SELECT id FROM users WHERE username = 'admin'")
        if not cursor.fetchone():
            cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                           ("admin", hash_password("admin123"), "admin"))

        cursor.execute("SELECT id FROM users WHERE username = 'vendeur'")
        if not cursor.fetchone():
            cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                           ("vendeur", hash_password("vendeur123"), "vendor"))

        cursor.execute("SELECT id FROM users WHERE username = 'rachid_tech'")
        if not cursor.fetchone():
            cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                           ("rachid_tech", hash_password("rachid123"), "vendor"))

        conn.commit()


def create_barcode_image(barcode_data: str, label_text: str) -> str:
    """Generate barcode PNG file and return its path."""
    safe_name = "".join(c if c.isalnum() or c in ("_", "-") else "_" for c in f"{barcode_data}_{label_text}")
    file_path = os.path.join(BARCODES_DIR, f"{safe_name}.png")

    try:
        import barcode
        from barcode.writer import ImageWriter
        from PIL import Image, ImageDraw, ImageFont

        CODE128 = barcode.get_barcode_class('code128')
        code_obj = CODE128(barcode_data, writer=ImageWriter())
        
        # Save without extension first
        base_tmp = os.path.join(BARCODES_DIR, f"tmp_{barcode_data}")
        full_tmp = code_obj.save(base_tmp)
        
        # Add label under barcode
        with Image.open(full_tmp) as b_img:
            w, h = b_img.size
            canvas_img = Image.new('RGB', (w, h + 50), 'white')
            canvas_img.paste(b_img, (0, 0))
            draw = ImageDraw.Draw(canvas_img)
            try:
                font = ImageFont.truetype("arial.ttf", 18)
            except Exception:
                font = ImageFont.load_default()
            
            try:
                bbox = draw.textbbox((0, 0), label_text, font=font)
                tw = bbox[2] - bbox[0]
            except Exception:
                tw = 80
            draw.text(((w - tw) // 2, h + 10), label_text, fill="black", font=font)
            canvas_img.save(file_path)

        if os.path.exists(full_tmp):
            os.remove(full_tmp)
        return file_path
    except Exception:
        # Fallback simple PNG via PIL
        try:
            from PIL import Image, ImageDraw
            img = Image.new('RGB', (320, 100), color='white')
            d = ImageDraw.Draw(img)
            d.rectangle([10, 10, 310, 90], outline='black', width=2)
            d.text((20, 30), f"CODE: {barcode_data}", fill='black')
            d.text((20, 55), label_text[:35], fill='gray')
            img.save(file_path)
            return file_path
        except Exception:
            return ""


def seed_data():
    """Populate database with rich, realistic data covering all app features."""
    init_db_schema()
    print("\n⏳ Insertion des données en cours...")

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()

        # 1. CLIENTS / ACHETEURS
        buyers_data = [
            ("Karim El Amrani", "0661123456", "Client fidèle, recherche principalement iPhones récents"),
            ("Youssef Benjelloun", "0662987654", "Paiement comptant, gérant boutique Casablanca"),
            ("Fatima Zahra Mansouri", "0663456789", "Cliente occasionnelle, accessoires et smartphones milieu de gamme"),
            ("Mehdi Chraibi", "0664112233", "Intéressé par la gamme Samsung Galaxy S et écouteurs"),
            ("Salma Berrada", "0665998877", "Achat pour ses enfants (Xiaomi / protecteurs d'écran)"),
            ("Omar Tazi", "0666334455", "Technophile, cherche Google Pixel et pièces premium"),
            ("Nouhaila Idrissi", "0667778899", "Achète des accessoires en lot (câbles, coques)"),
            ("Hamza Bennani", "0668223344", "Client régulier, réparations et reventes"),
            ("Sara Kabbaj", "0669556677", "Particulier, recherche iPhone reconditionné avec batterie > 90%"),
            ("Amine Alami", "0670112233", "Acheteur grossiste d'accessoires"),
        ]

        buyer_ids = []
        for name, contact, desc in buyers_data:
            cursor.execute("SELECT id FROM buyers WHERE name = ? AND contact_info = ?", (name, contact))
            row = cursor.fetchone()
            if row:
                buyer_ids.append(row[0])
            else:
                cursor.execute("INSERT INTO buyers (name, contact_info, description) VALUES (?, ?, ?)", (name, contact, desc))
                buyer_ids.append(cursor.lastrowid)

        # 2. TÉLÉPHONES
        phones_data = [
            # In-Stock Phones (available = 1)
            ("00001", "Apple", "iPhone 14 Pro Max", "354892019482011", "Deep Purple", "256GB", "6GB", "94%", 8900.0,
             "Très bon état, écran d'origine sans micro-rayures, boîte incluse", True, "Hassan El Fassi", 7400.0, "0661882233", "Reprise client"),
            ("00002", "Apple", "iPhone 13", "358920104820192", "Midnight", "128GB", "4GB", "89%", 5400.0,
             "État impeccable avec protège écran posé", True, "Tariq Naciri", 4500.0, "0662771199", "Vendeur particulier"),
            ("00003", "Apple", "iPhone 12", "356789012345678", "Blue", "64GB", "4GB", "86%", 3800.0,
             "Quelques traces d'usure sur le châssis, FaceID fonctionnel", True, "Rachid Tech", 3100.0, "0663445566", "Fournisseur"),
            ("00004", "Samsung", "Galaxy S23 Ultra", "351234567890123", "Phantom Black", "512GB", "12GB", "98%", 8200.0,
             "Comme neuf, S-Pen inclus, garantie constructeur restante", True, "Adil Slaoui", 6900.0, "0665112244", "Particulier"),
            ("00005", "Samsung", "Galaxy S22", "352345678901234", "Green", "128GB", "8GB", "91%", 4200.0,
             "Fonctionnement parfait, livré avec câble chargeur rapide", True, "Hicham Tahiri", 3400.0, "0666332211", "Client boutique"),
            ("00006", "Samsung", "Galaxy A54 5G", "353456789012345", "Awesome Violet", "128GB", "8GB", "100%", 2950.0,
             "Neuf sous blister ouvert pour vérification", True, "Import Mobile", 2350.0, "0667998877", "Grossiste"),
            ("00007", "Xiaomi", "Redmi Note 12 Pro", "354567890123456", "Polar White", "256GB", "8GB", "95%", 2200.0,
             "Chargeur 67W fourni, écran AMOLED 120Hz impeccable", True, "Zouhair Berrada", 1700.0, "0668443322", "Particulier"),
            ("00008", "Google", "Pixel 7", "355678901234567", "Obsidian", "128GB", "8GB", "90%", 3600.0,
             "Appareil photo exceptionnel, Android 14 à jour", True, "Mustapha Lahlou", 2900.0, "0669110022", "Client magasin"),

            # Sold Phones (available = 0)
            ("00009", "Apple", "iPhone 11", "356789098765432", "Black", "128GB", "4GB", "84%", 3100.0,
             "Vendu avec câble de charge", False, "Khalid Rami", 2400.0, "0661994433", "Reprise client"),
            ("00010", "Samsung", "Galaxy S21 FE", "357890123456789", "Graphite", "128GB", "6GB", "88%", 2800.0,
             "Vendu en boutique", False, "Yassine Filali", 2200.0, "0662883344", "Particulier"),
            ("00011", "Apple", "iPhone 13 Pro", "358901234567890", "Sierra Blue", "256GB", "6GB", "91%", 6800.0,
             "Vendu avec facture", False, "Nabil Idrissi", 5600.0, "0663772211", "Client fidèle"),
            ("00012", "Xiaomi", "11T Pro", "359012345678901", "Meteorite Gray", "256GB", "8GB", "87%", 2400.0,
             "Vendu complet avec boîte", False, "Samir Ouali", 1850.0, "0664661100", "Particulier"),
        ]

        phone_db_ids = {}
        for p in phones_data:
            id_phone, brand, model, imei, color, storage, ram, bat, price, desc, avail, s_name, s_price, s_contact, s_desc = p
            barcode_str = id_phone
            b_path = create_barcode_image(barcode_str, f"{brand} {model}")
            
            cursor.execute("SELECT id FROM phones WHERE imei = ? OR ID_phone = ?", (imei, id_phone))
            row = cursor.fetchone()
            if row:
                phone_db_ids[id_phone] = row[0]
            else:
                cursor.execute("""
                    INSERT INTO phones (ID_phone, brand, model, imei, color, storage, ram, battery_state,
                                        price, description, barcode, barcode_file_path, available,
                                        seller_name, seller_price, seller_contact, seller_description, date_added)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', ?))
                """, (id_phone, brand, model, imei, color, storage, ram, bat, price, desc,
                      barcode_str, b_path, 1 if avail else 0, s_name, s_price, s_contact, s_desc,
                      f"-{random.randint(2, 40)} days"))
                phone_db_ids[id_phone] = cursor.lastrowid

        # 3. ACCESSOIRES
        accessories_data = [
            # In stock
            ("ACC00001", "Chargeur 20W USB-C", "Apple", "Original", 250.0, 35,
             "Adaptateur secteur USB-C rapide 20W certifié Apple", "0194252157014", "Grossiste Casablanca", 130.0, "0661223344"),
            ("ACC00002", "Câble USB-C vers Lightning 1m", "Apple", "Origine", 120.0, 50,
             "Câble de charge et synchronisation officiel", "0194252157021", "Grossiste Casablanca", 45.0, "0661223344"),
            ("ACC00003", "Coque MagSafe Silicone iPhone 14 Pro", "Apple", "Midnight", 150.0, 20,
             "Coque avec aimants intégrés MagSafe", "ACC-CASE-IP14P", "Accessoires Direct", 40.0, "0662334455"),
            ("ACC00004", "Galaxy Buds 2", "Samsung", "Graphite", 750.0, 8,
             "Écouteurs sans fil avec réduction active du bruit (ANC)", "8806092523451", "Samsung Import", 520.0, "0663445566"),
            ("ACC00005", "Chargeur Rapide 45W Type-C", "Samsung", "Super Fast 2.0", 320.0, 15,
             "Chargeur officiel 45W pour Galaxy S23/S22/S24", "8806092523999", "Samsung Import", 180.0, "0663445566"),
            ("ACC00006", "Verre Trempé Antichoc 9H", "Generique", "Universel / iPhone", 50.0, 80,
             "Protection écran haute résistance avec kit d'installation", "ACC-GLASS-9H", "Alpha Mobile", 12.0, "0664556677"),
            ("ACC00007", "Power Bank 20000mAh 22.5W", "Anker", "PowerCore 20K", 390.0, 12,
             "Batterie externe haute capacité double sortie USB-C / USB-A", "194644021034", "Anker Maroc", 250.0, "0665667788"),
            ("ACC00008", "Câble USB-C vers USB-C 60W 1.8m", "Anker", "PowerLine III", 90.0, 40,
             "Câble tressé ultra résistant charge rapide 60W", "194644021058", "Anker Maroc", 35.0, "0665667788"),
            ("ACC00009", "Support Téléphone Voiture Magnétique", "Baseus", "Air Vent MagSafe", 130.0, 18,
             "Fixation grille d'aération avec aimants puissants", "6953156201245", "Baseus Store", 55.0, "0666778899"),
            ("ACC00010", "Chargeur Voiture Rapide 30W", "Baseus", "Dual USB + Type-C", 110.0, 22,
             "Allume-cigare compact en métal QuickCharge 4.0", "6953156201290", "Baseus Store", 45.0, "0666778899"),

            # Out of stock (quantity = 0 to test Out-of-Stock filter)
            ("ACC00011", "AirPods Pro 2ème Génération", "Apple", "MagSafe USB-C", 1850.0, 0,
             "Actuellement en rupture de stock, réapprovisionnement prévu", "0194253397471", "Import Dubai", 1450.0, "0667889900"),
            ("ACC00012", "Coque Transparente Antichoc Galaxy S23", "Spigen", "Ultra Hybrid", 160.0, 0,
             "Rupture temporaire", "8809811867890", "Spigen Maroc", 70.0, "0668990011"),
        ]

        acc_db_ids = {}
        for a in accessories_data:
            sku, name, brand, model, price, qty, desc, barcode_str, s_name, s_price, s_contact = a
            b_path = create_barcode_image(barcode_str or sku, f"{brand} {name}")
            tot_cost = (s_price * qty) if s_price and qty > 0 else 0.0

            cursor.execute("SELECT id FROM accessories WHERE SKU = ? OR barcode = ?", (sku, barcode_str))
            row = cursor.fetchone()
            if row:
                acc_db_ids[sku] = row[0]
            else:
                cursor.execute("""
                    INSERT INTO accessories (SKU, name, brand, model, price, quantity, description,
                                            barcode, barcode_file_path, available, seller_name,
                                            seller_price, seller_contact, seller_total_price, date_added)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now', ?))
                """, (sku, name, brand, model, price, qty, desc, barcode_str, b_path,
                      1 if qty > 0 else 0, s_name, s_price, s_contact, tot_cost,
                      f"-{random.randint(3, 45)} days"))
                acc_db_ids[sku] = cursor.lastrowid

        # 4. HISTORIQUE DES VENTES (Phones & Accessories)
        # Seed realistic sales across past 30 days to populate KPI cards and detailed reports
        today = datetime.datetime.now()
        sales_data = [
            # Phone Sales
            ("phone", "00009", buyer_ids[0], 3100.0, today - datetime.timedelta(days=2)),
            ("phone", "00010", buyer_ids[1], 2800.0, today - datetime.timedelta(days=6)),
            ("phone", "00011", buyer_ids[3], 6800.0, today - datetime.timedelta(days=12)),
            ("phone", "00012", buyer_ids[5], 2400.0, today - datetime.timedelta(days=18)),

            # Accessory Sales
            ("accessory", "ACC00001", buyer_ids[2], 250.0, today - datetime.timedelta(days=1), 2, 250.0, 500.0),
            ("accessory", "ACC00002", buyer_ids[4], 120.0, today - datetime.timedelta(days=2), 1, 120.0, 120.0),
            ("accessory", "ACC00003", buyer_ids[0], 150.0, today - datetime.timedelta(days=3), 1, 150.0, 150.0),
            ("accessory", "ACC00004", buyer_ids[3], 750.0, today - datetime.timedelta(days=5), 1, 750.0, 750.0),
            ("accessory", "ACC00005", buyer_ids[6], 320.0, today - datetime.timedelta(days=7), 2, 320.0, 640.0),
            ("accessory", "ACC00006", buyer_ids[7], 50.0,  today - datetime.timedelta(days=9), 3, 50.0,  150.0),
            ("accessory", "ACC00007", buyer_ids[8], 390.0, today - datetime.timedelta(days=14), 1, 390.0, 390.0),
            ("accessory", "ACC00008", buyer_ids[1], 90.0,  today - datetime.timedelta(days=16), 2, 90.0,  180.0),
            ("accessory", "ACC00009", buyer_ids[2], 130.0, today - datetime.timedelta(days=21), 1, 130.0, 130.0),
            ("accessory", "ACC00010", buyer_ids[9], 110.0, today - datetime.timedelta(days=25), 1, 110.0, 110.0),
            ("accessory", "ACC00001", buyer_ids[5], 250.0, today - datetime.timedelta(days=28), 1, 250.0, 250.0),
            ("accessory", "ACC00006", buyer_ids[4], 50.0,  today - datetime.timedelta(days=29), 2, 50.0,  100.0),
        ]

        # Insert sales records
        for s in sales_data:
            ptype = s[0]
            ref_code = s[1]
            b_id = s[2]
            s_price = s[3]
            s_date = s[4].strftime("%Y-%m-%d %H:%M:%S")

            cursor.execute("SELECT name, contact_info FROM buyers WHERE id = ?", (b_id,))
            b_row = cursor.fetchone()
            b_name = b_row[0] if b_row else "Client Inconnu"
            b_contact = b_row[1] if b_row else "-"

            if ptype == "phone":
                db_id = phone_db_ids.get(ref_code)
                cursor.execute("SELECT brand, model, imei FROM phones WHERE id = ?", (db_id,))
                p_row = cursor.fetchone()
                p_brand = p_row[0] if p_row else "Apple"
                p_model = p_row[1] if p_row else "Phone"
                p_imei = p_row[2] if p_row else ""
                p_name = f"{p_brand} {p_model}"

                cursor.execute("""
                    INSERT INTO sales (phone_id, product_id, buyer_id, sale_date, sale_price, product_type,
                                       sale_qty, sale_unit_price, sale_total, product_ref, product_name_snapshot,
                                       product_brand_snapshot, product_model_snapshot, product_imei_snapshot,
                                       buyer_name_snapshot, buyer_contact_snapshot)
                    VALUES (?, ?, ?, ?, ?, 'phone', 1, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (db_id, db_id, b_id, s_date, s_price, s_price, s_price, ref_code, p_name,
                      p_brand, p_model, p_imei, b_name, b_contact))
            else:
                db_id = acc_db_ids.get(ref_code)
                qty = s[5]
                u_price = s[6]
                tot = s[7]

                cursor.execute("SELECT name, brand, model FROM accessories WHERE id = ?", (db_id,))
                a_row = cursor.fetchone()
                a_name = a_row[0] if a_row else "Accessoire"
                a_brand = a_row[1] if a_row else "Marque"
                a_model = a_row[2] if a_row else ""

                cursor.execute("""
                    INSERT INTO sales (product_id, buyer_id, sale_date, sale_price, product_type,
                                       sale_qty, sale_unit_price, sale_total, product_ref, product_name_snapshot,
                                       product_brand_snapshot, product_model_snapshot,
                                       buyer_name_snapshot, buyer_contact_snapshot)
                    VALUES (?, ?, ?, ?, 'accessory', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (db_id, b_id, s_date, tot, qty, u_price, tot, ref_code, a_name,
                      a_brand, a_model, b_name, b_contact))

        conn.commit()

    print("\n" + "=" * 60)
    print(" ✅ DONNÉES DE TEST AJOUTÉES AVEC SUCCÈS !")
    print("=" * 60)
    print(f" 📱 Téléphones insérés : 12 (8 disponibles en stock, 4 vendus)")
    print(f" 🔌 Accessoires insérés : 12 (10 en stock, 2 en rupture)")
    print(f" 👥 Clients ajoutés    : {len(buyers_data)}")
    print(f" 💰 Ventes enregistrées: {len(sales_data)} transactions récentes")
    print(f" 🏷️  Codes-barres créés : Dossier '{BARCODES_DIR}'")
    print(f" 👤 Comptes par défaut :")
    print(f"    - admin       / admin123   (Rôle: Administrateur)")
    print(f"    - vendeur     / vendeur123 (Rôle: Vendeur)")
    print(f"    - rachid_tech / rachid123  (Rôle: Vendeur)")
    print("=" * 60 + "\n")


def clear_data():
    """Wipe all operational data safely and restore clean default users."""
    print("\n" + "!" * 60)
    print(" ⚠️  ATTENTION : Cette action va effacer :")
    print("    - Tous les téléphones")
    print("    - Tous les accessoires")
    print("    - Tous les clients (acheteurs)")
    print("    - Tout l'historique des ventes")
    print("    - Les images de codes-barres générées")
    print("!" * 60)
    
    choice = input(" Êtes-vous sûr de vouloir tout effacer ? (o/n ou y/n) : ").strip().lower()
    if choice not in ("o", "oui", "y", "yes"):
        print("\n❌ Opération annulée par l'utilisateur.\n")
        return

    init_db_schema()

    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sales")
        cursor.execute("DELETE FROM phones")
        cursor.execute("DELETE FROM accessories")
        cursor.execute("DELETE FROM buyers")
        
        # Reset auto-increment counters
        try:
            cursor.execute("DELETE FROM sqlite_sequence WHERE name IN ('sales', 'phones', 'accessories', 'buyers')")
        except Exception:
            pass

        # Clean users down to standard defaults
        cursor.execute("DELETE FROM users WHERE username NOT IN ('admin', 'vendeur')")

        # Make sure standard users exist with clean password hashes
        cursor.execute("SELECT id FROM users WHERE username = 'admin'")
        if not cursor.fetchone():
            cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                           ("admin", hash_password("admin123"), "admin"))
        else:
            cursor.execute("UPDATE users SET password = ?, role = 'admin' WHERE username = 'admin'",
                           (hash_password("admin123"),))

        cursor.execute("SELECT id FROM users WHERE username = 'vendeur'")
        if not cursor.fetchone():
            cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                           ("vendeur", hash_password("vendeur123"), "vendor"))
        else:
            cursor.execute("UPDATE users SET password = ?, role = 'vendor' WHERE username = 'vendeur'",
                           (hash_password("vendeur123"),))

        conn.commit()

    # Clean generated barcode images
    cleaned_barcodes = 0
    if os.path.exists(BARCODES_DIR):
        for fname in os.listdir(BARCODES_DIR):
            fpath = os.path.join(BARCODES_DIR, fname)
            if os.path.isfile(fpath) and fname.lower().endswith(".png"):
                try:
                    os.remove(fpath)
                    cleaned_barcodes += 1
                except Exception:
                    pass

    print("\n" + "=" * 60)
    print(" 🗑️  BASE DE DONNÉES RÉINITIALISÉE AVEC SUCCÈS !")
    print("=" * 60)
    print(f" • Toutes les tables ont été vidées.")
    print(f" • {cleaned_barcodes} fichiers codes-barres supprimés.")
    print(f" • Comptes par défaut restaurés : admin / admin123 | vendeur / vendeur123")
    print("=" * 60 + "\n")


def print_menu():
    """Print the interactive selection menu."""
    print("=" * 60)
    print("   📱 PHONESHOPMANAGER - GESTIONNAIRE DE DONNÉES (SEEDER)")
    print("=" * 60)
    print(f" Base : {DB_PATH}")
    print("-" * 60)
    print("  [1]  📥  Add data (Remplir avec des données de test)")
    print("  [2]  🗑️   Clear all the data (Tout effacer / Réinitialiser)")
    print("  [3]  ❌  Exit (Quitter)")
    print("=" * 60)


def main():
    while True:
        print_menu()
        try:
            choice = input("\n👉 Choisissez une option (1, 2, ou 3) : ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\n\nAu revoir !")
            break

        if choice == "1":
            seed_data()
            input("Appuyez sur [Entrée] pour continuer...")
            print("\n")
        elif choice == "2":
            clear_data()
            input("Appuyez sur [Entrée] pour continuer...")
            print("\n")
        elif choice == "3" or choice.lower() in ("exit", "quit", "q"):
            print("\n👋 Fermeture du seeder. À bientôt !\n")
            break
        else:
            print("\n❌ Option invalide. Veuillez saisir 1, 2 ou 3.\n")


if __name__ == "__main__":
    main()
