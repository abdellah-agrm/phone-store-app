# PhoneShopApp - setup and safe database update

## Run from source

1. Install Python 3.11 or newer.
2. Open a terminal in this folder.
3. Create and activate a virtual environment:

```bat
py -3.11 -m venv penv
penv\Scripts\activate
```

4. Install dependencies:

```bat
pip install -r requirements.txt
```

5. Start the app:

```bat
python main.py
```

Default login on a new database:

```text
admin / admin123
vendeur / vendeur123
```

## Build EXE

```bat
penv\Scripts\activate
pip install -r requirements-build.txt
python build_exe.py
```

The EXE will be created in `dist\main.exe`.


## Updated in this version

- Accessories now have a **Code-Barres / SKU** field in the add/edit dialogs. Put the cursor in the field, scan the accessory barcode, then save. If the field is left empty, the app creates an automatic SKU as before.
- The global scanner and the top **Scanner Code-Barres** dialog now search both phones and accessories.
- The UI has been cleaned up with consistent spacing, larger default window size, organized accessory dialogs, and reusable Pillow-drawn line icons instead of emoji icons.

## Database location

The app stores live data here:

```text
%APPDATA%\PhoneShopManager\phone_shop.db
%APPDATA%\PhoneShopManager\codes_barres\
```

Example Windows path:

```text
C:\Users\YOUR_NAME\AppData\Roaming\PhoneShopManager\phone_shop.db
```

Backups are stored here:

```text
%APPDATA%\PhoneShopManager\backups\
```

## How the old database crash is fixed

Older versions may have `phone_shop.db` beside `main.py` or beside `main.exe`. This version checks for that old local database on first run. If no database exists yet in `%APPDATA%\PhoneShopManager`, it copies the old database there.

After opening the database, the app automatically adds missing columns instead of crashing. Before changing an old database schema, it creates a backup named like:

```text
%APPDATA%\PhoneShopManager\backups\pre_migration_YYYYMMDD_HHMMSS.db
```

## Safe update steps for a customer PC

1. Close the old app.
2. Make a manual copy of the old `phone_shop.db` before installing the new version.
3. Install/copy the new version.
4. Run the new app once as admin.
5. Check phones, accessories, buyers, and sales history.
6. Keep the backup folder until you confirm all old data is OK.

## Installer password

The installer script no longer contains a visible password. If you want installer password protection, set an environment variable before compiling the installer:

```bat
set PHONESHOP_INSTALL_PASSWORD=YourPasswordHere
```

If the variable is empty, the installer builds without a password page.
