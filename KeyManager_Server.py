from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import sqlite3
import time
import os
import io
import traceback

# ---------- Configuration ----------
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "licenses.db")


# ---------- Utilities ----------
def now_ts():
    return int(time.time())


def format_time(ts):
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(ts))
    except:
        return str(ts)


def ensure_db_directory():
    """Ensure the database directory exists and is writable"""
    db_dir = os.path.dirname(DB_PATH)

    if not db_dir or db_dir == "":
        db_dir = "."

    if not os.path.exists(db_dir):
        try:
            os.makedirs(db_dir, exist_ok=True)
            print(f"✅ Created directory: {db_dir}")
        except Exception as e:
            print(f"❌ Failed to create directory {db_dir}: {e}")
            return False

    test_file = os.path.join(db_dir, ".write_test")
    try:
        with open(test_file, "w") as f:
            f.write("test")
        os.remove(test_file)
        print(f"✅ Directory {db_dir} is writable")
        return True
    except Exception as e:
        print(f"❌ Directory {db_dir} is not writable: {e}")
        return False


# ---------- Database & Migration ----------
def init_db():
    try:
        print(f"🔄 Initializing database at: {DB_PATH}")

        if not ensure_db_directory():
            print("❌ Cannot access database directory")
            return False

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        c.execute(
            """
            CREATE TABLE IF NOT EXISTS licenses(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner TEXT,
                code TEXT UNIQUE,
                ea_name TEXT,
                max_accounts INTEGER DEFAULT 1,
                expiry INTEGER,
                active INTEGER DEFAULT 1,
                created_at INTEGER DEFAULT (strftime('%s','now'))
            )
        """
        )

        c.execute(
            """
            CREATE TABLE IF NOT EXISTS license_accounts(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                license_id INTEGER,
                account_number TEXT,
                account_name TEXT,
                server TEXT,
                balance REAL,
                equity REAL,
                last_seen INTEGER,
                created_at INTEGER DEFAULT (strftime('%s','now')),
                FOREIGN KEY (license_id) REFERENCES licenses(id),
                UNIQUE(license_id, account_number)
            )
        """
        )

        c.execute(
            """
            CREATE TABLE IF NOT EXISTS predefined_accounts(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                license_id INTEGER,
                account_number TEXT,
                account_name TEXT,
                FOREIGN KEY (license_id) REFERENCES licenses(id),
                UNIQUE(license_id, account_number)
            )
        """
        )

        conn.commit()
        conn.close()
        print("✅ Database initialized successfully")
        return True
    except Exception as e:
        print(f"❌ Database initialization failed: {e}")
        traceback.print_exc()
        return False


def migrate_db():
    """Migrate database to add active column if it doesn't exist"""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        c.execute("PRAGMA table_info(licenses)")
        columns = [col[1] for col in c.fetchall()]

        if "active" not in columns:
            print("🔄 Migrating database: Adding 'active' column...")
            c.execute("ALTER TABLE licenses ADD COLUMN active INTEGER DEFAULT 1")
            conn.commit()
            print("✅ Migration completed: 'active' column added")

        conn.close()
        return True
    except Exception as e:
        print(f"❌ Database migration failed: {e}")
        traceback.print_exc()
        return False


# ---------- DB Helpers with Auto-Init ----------
def ensure_db_initialized():
    """Ensure database tables exist before any operation"""
    try:
        if not os.path.exists(DB_PATH):
            print("📦 Database file missing, initializing...")
            return init_db()

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='licenses'"
        )
        if not c.fetchone():
            conn.close()
            print("📦 Database tables missing, initializing...")
            return init_db()
        else:
            conn.close()
            migrate_db()
        return True
    except Exception as e:
        print(f"❌ Database check failed: {e}")
        return init_db()


def get_license_by_code(code):
    """Get license information by code"""
    if not ensure_db_initialized():
        return None
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        c.execute("PRAGMA table_info(licenses)")
        columns = [col[1] for col in c.fetchall()]

        if "active" in columns:
            c.execute(
                "SELECT id, owner, code, ea_name, max_accounts, expiry, active FROM licenses WHERE code=?",
                (code,),
            )
        else:
            c.execute(
                "SELECT id, owner, code, ea_name, max_accounts, expiry FROM licenses WHERE code=?",
                (code,),
            )
            row = c.fetchone()
            if row:
                row = row + (1,)

        row = c.fetchone()
        conn.close()
        return row
    except Exception as e:
        print(f"❌ Error getting license: {e}")
        return None


def get_predefined_accounts_for_license(license_id):
    """Get all predefined accounts for a license"""
    if not ensure_db_initialized():
        return []
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "SELECT account_number, account_name FROM predefined_accounts WHERE license_id=?",
            (license_id,),
        )
        rows = c.fetchall()
        conn.close()
        return [{"account_number": row[0], "account_name": row[1]} for row in rows]
    except Exception as e:
        print(f"❌ Error getting predefined accounts: {e}")
        return []


def add_or_update_account(
    license_id,
    account_number,
    account_name=None,
    server=None,
    balance=None,
    equity=None,
):
    """Add or update an account for a license"""
    if not ensure_db_initialized():
        return False

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        c.execute("PRAGMA table_info(licenses)")
        columns = [col[1] for col in c.fetchall()]

        if "active" in columns:
            c.execute("SELECT active FROM licenses WHERE id=?", (license_id,))
            row = c.fetchone()
            if not row or row[0] == 0:
                conn.close()
                return "LICENSE_DEACTIVATED"

        c.execute(
            "SELECT account_name FROM predefined_accounts WHERE license_id=? AND account_number=?",
            (license_id, account_number),
        )
        row = c.fetchone()

        if row:
            predefined_name = row[0]
            if predefined_name and not account_name:
                account_name = predefined_name
            elif predefined_name and account_name and account_name != predefined_name:
                conn.close()
                return "NAME_MISMATCH"

        now = now_ts()

        c.execute(
            "SELECT id FROM license_accounts WHERE license_id=? AND account_number=?",
            (license_id, account_number),
        )
        row = c.fetchone()

        if row:
            acct_id = row[0]
            c.execute(
                """
                UPDATE license_accounts
                   SET last_seen=?, account_name=COALESCE(?, account_name),
                       server=COALESCE(?, server),
                       balance=COALESCE(?, balance),
                       equity=COALESCE(?, equity)
                 WHERE id=?
            """,
                (now, account_name, server, balance, equity, acct_id),
            )
        else:
            c.execute(
                "SELECT COUNT(*) FROM license_accounts WHERE license_id=?",
                (license_id,),
            )
            used_count = c.fetchone()[0]
            c.execute("SELECT max_accounts FROM licenses WHERE id=?", (license_id,))
            r = c.fetchone()
            max_acc = r[0] if r else 1

            if used_count >= max_acc:
                conn.close()
                return "MAX_EXCEEDED"

            c.execute(
                """
                INSERT INTO license_accounts(license_id, account_number, account_name, server, balance, equity, last_seen)
                VALUES (?,?,?,?,?,?,?)
            """,
                (
                    license_id,
                    account_number,
                    account_name,
                    server,
                    balance,
                    equity,
                    now,
                ),
            )

        conn.commit()
        conn.close()
        return "SUCCESS"
    except Exception as e:
        print(f"❌ Error adding/updating account: {e}")
        traceback.print_exc()
        return False


def list_licenses():
    """List all licenses with their accounts"""
    if not ensure_db_initialized():
        return []

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        c.execute("PRAGMA table_info(licenses)")
        columns = [col[1] for col in c.fetchall()]

        if "active" in columns:
            c.execute(
                "SELECT id, owner, code, ea_name, max_accounts, expiry, active FROM licenses ORDER BY expiry ASC"
            )
        else:
            c.execute(
                "SELECT id, owner, code, ea_name, max_accounts, expiry FROM licenses ORDER BY expiry ASC"
            )

        rows = c.fetchall()
        licenses = []

        for row in rows:
            if len(row) == 7:
                lic_id, owner, code, ea_name, max_acc, expiry, active = row
            else:
                lic_id, owner, code, ea_name, max_acc, expiry = row
                active = 1

            c.execute(
                """
                SELECT account_number, account_name, server, balance, equity, last_seen
                  FROM license_accounts
                 WHERE license_id=?
                 ORDER BY last_seen DESC
            """,
                (lic_id,),
            )
            accounts = [
                {
                    "account": a,
                    "account_name": n,
                    "server": s,
                    "balance": b,
                    "equity": q,
                    "last_seen": format_time(ls),
                }
                for a, n, s, b, q, ls in c.fetchall()
            ]

            predefined = get_predefined_accounts_for_license(lic_id)

            now = now_ts()
            status = "active"

            if not active:
                status = "deactivated"
            elif expiry and now > expiry:
                status = "expired"
            elif not accounts:
                status = "inactive"
            elif expiry and expiry - now < 259200:
                status = "expiring"

            licenses.append(
                {
                    "owner": owner,
                    "code": code,
                    "ea": ea_name or "",
                    "max_accounts": max_acc or 1,
                    "expiry": expiry,
                    "expiry_human": format_time(expiry) if expiry else None,
                    "active": bool(active),
                    "status": status,
                    "active_accounts": len(accounts),
                    "accounts": accounts,
                    "predefined_accounts": predefined,
                }
            )
        conn.close()
        return licenses
    except Exception as e:
        print(f"❌ Error listing licenses: {e}")
        traceback.print_exc()
        return []


def store_license(owner, code, ea_name, max_accounts, expiry, predefined_accounts=None):
    """Store license with optional predefined accounts"""
    if not ensure_db_initialized():
        return False

    if predefined_accounts is None:
        predefined_accounts = []

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        c.execute("PRAGMA table_info(licenses)")
        columns = [col[1] for col in c.fetchall()]

        if "active" in columns:
            c.execute(
                """INSERT OR REPLACE INTO licenses(owner, code, ea_name, max_accounts, expiry, active)
                         VALUES (?,?,?,?,?,?)""",
                (owner, code, ea_name, max_accounts, expiry, 1),
            )
        else:
            c.execute(
                """INSERT OR REPLACE INTO licenses(owner, code, ea_name, max_accounts, expiry)
                         VALUES (?,?,?,?,?)""",
                (owner, code, ea_name, max_accounts, expiry),
            )

        license_id = c.lastrowid

        for acc in predefined_accounts:
            acc_number = acc.get("account_number", "").strip()
            acc_name = acc.get("account_name", "").strip()
            if acc_number:
                try:
                    c.execute(
                        """INSERT INTO predefined_accounts(license_id, account_number, account_name)
                                 VALUES (?,?,?)""",
                        (license_id, acc_number, acc_name),
                    )
                except sqlite3.IntegrityError:
                    pass

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Error storing license: {e}")
        traceback.print_exc()
        return False


def update_expiry(code, new_expiry):
    """Update license expiry date"""
    if not ensure_db_initialized():
        return False
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE licenses SET expiry=? WHERE code=?", (new_expiry, code))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Error updating expiry: {e}")
        return False


def delete_license(code):
    """Delete a license and all associated data"""
    if not ensure_db_initialized():
        return False
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        c.execute("SELECT id FROM licenses WHERE code=?", (code,))
        r = c.fetchone()

        if r:
            lic_id = r[0]
            c.execute("DELETE FROM license_accounts WHERE license_id=?", (lic_id,))
            c.execute("DELETE FROM predefined_accounts WHERE license_id=?", (lic_id,))

        c.execute("DELETE FROM licenses WHERE code=?", (code,))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Error deleting license: {e}")
        traceback.print_exc()
        return False


def edit_license(
    code, owner=None, ea_name=None, max_accounts=None, predefined_accounts=None
):
    """Edit license information"""
    if not ensure_db_initialized():
        return False

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        c.execute("SELECT id FROM licenses WHERE code=?", (code,))
        row = c.fetchone()
        if not row:
            conn.close()
            return False

        license_id = row[0]

        updates = []
        params = []
        if owner is not None:
            updates.append("owner=?")
            params.append(owner)
        if ea_name is not None:
            updates.append("ea_name=?")
            params.append(ea_name)
        if max_accounts is not None:
            updates.append("max_accounts=?")
            params.append(max_accounts)

        if updates:
            params.append(code)
            sql = f"UPDATE licenses SET {', '.join(updates)} WHERE code=?"
            c.execute(sql, params)

        if predefined_accounts is not None:
            c.execute(
                "DELETE FROM predefined_accounts WHERE license_id=?", (license_id,)
            )
            for acc in predefined_accounts:
                acc_number = acc.get("account_number", "").strip()
                acc_name = acc.get("account_name", "").strip()
                if acc_number:
                    c.execute(
                        """INSERT INTO predefined_accounts(license_id, account_number, account_name)
                                 VALUES (?,?,?)""",
                        (license_id, acc_number, acc_name),
                    )

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Error editing license: {e}")
        traceback.print_exc()
        return False


def toggle_license_active(code, active=None):
    """Activate or deactivate a license"""
    if not ensure_db_initialized():
        return False

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        c.execute("PRAGMA table_info(licenses)")
        columns = [col[1] for col in c.fetchall()]

        if "active" not in columns:
            c.execute("ALTER TABLE licenses ADD COLUMN active INTEGER DEFAULT 1")
            conn.commit()

        if active is None:
            c.execute("SELECT active FROM licenses WHERE code=?", (code,))
            row = c.fetchone()
            if row:
                new_active = 0 if row[0] == 1 else 1
                c.execute(
                    "UPDATE licenses SET active=? WHERE code=?", (new_active, code)
                )
            else:
                conn.close()
                return False
        else:
            c.execute(
                "UPDATE licenses SET active=? WHERE code=?", (1 if active else 0, code)
            )

        conn.commit()
        conn.close()
        return True
    except Exception as e:
        print(f"❌ Error toggling license active state: {e}")
        traceback.print_exc()
        return False


# ---------- Flask App ----------
app = Flask(__name__)
CORS(app)

print("🚀 Starting License Server...")
print(f"✅ Database path: {DB_PATH}")
if init_db():
    migrate_db()


# ---------- Routes ----------

@app.route("/")
def health_check():
    try:
        if ensure_db_initialized():
            return jsonify(
                {
                    "status": "healthy",
                    "service": "license-server",
                    "timestamp": now_ts(),
                    "message": "Server is running successfully",
                    "database": "initialized",
                    "db_path": DB_PATH,
                }
            )
        else:
            return jsonify({"status": "error", "error": "Database initialization failed"}), 500
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500


@app.route("/check")
def check():
    """Check license validity and register account"""
    if not ensure_db_initialized():
        return jsonify({"valid": False, "reason": "Database not available"}), 500

    code = request.args.get("code", "")
    ea_name = request.args.get("ea", "")
    account_number = request.args.get("account", "")
    server_name = request.args.get("server", "")
    account_name = request.args.get("name", "")
    balance = request.args.get("balance")
    equity = request.args.get("equity")

    try:
        balance_val = float(balance) if balance else None
    except:
        balance_val = None
    try:
        equity_val = float(equity) if equity else None
    except:
        equity_val = None

    if not code:
        return jsonify({"valid": False, "reason": "Missing code"}), 400

    row = get_license_by_code(code)
    if not row:
        return jsonify({"valid": False, "reason": "License not found"})

    if len(row) == 7:
        lic_id, owner, db_code, lic_ea, max_acc, expiry, active = row
    else:
        lic_id, owner, db_code, lic_ea, max_acc, expiry = row
        active = 1

    now = now_ts()

    if not active:
        return jsonify(
            {
                "valid": False,
                "reason": "License deactivated",
                "expiry": expiry,
                "expiry_human": format_time(expiry) if expiry else None,
            }
        )

    if expiry and now > expiry:
        return jsonify(
            {
                "valid": False,
                "reason": "License expired",
                "expiry": expiry,
                "expiry_human": format_time(expiry),
            }
        )

    if ea_name and lic_ea and lic_ea not in ("", ea_name):
        return jsonify({"valid": False, "reason": f"License not valid for EA {ea_name}"})

    if account_number:
        result = add_or_update_account(
            lic_id,
            account_number,
            account_name=account_name,
            server=server_name,
            balance=balance_val,
            equity=equity_val,
        )

        if result == "NAME_MISMATCH":
            try:
                conn = sqlite3.connect(DB_PATH)
                c = conn.cursor()
                c.execute(
                    "SELECT account_name FROM predefined_accounts WHERE license_id=? AND account_number=?",
                    (lic_id, account_number),
                )
                row = c.fetchone()
                correct_name = row[0] if row else "Unknown"
                conn.close()
            except:
                correct_name = "Unknown"
            return jsonify({"valid": False, "reason": f"Account name must be '{correct_name}'"})
        elif result == "MAX_EXCEEDED":
            return jsonify({"valid": False, "reason": "Maximum accounts exceeded"})
        elif result == "LICENSE_DEACTIVATED":
            return jsonify({"valid": False, "reason": "License is deactivated"})
        elif result != "SUCCESS":
            return jsonify({"valid": False, "reason": "Account registration failed"})

    return jsonify(
        {
            "valid": True,
            "owner": owner,
            "ea": lic_ea or "",
            "max_accounts": max_acc or 1,
            "expiry": expiry,
            "expiry_human": format_time(expiry) if expiry else None,
            "active": bool(active),
        }
    )


@app.route("/list")
def list_all():
    """List all licenses"""
    try:
        if not ensure_db_initialized():
            return jsonify({"success": False, "error": "Database not initialized", "licenses": []}), 500
        licenses = list_licenses()
        return jsonify({"success": True, "licenses": licenses, "count": len(licenses), "timestamp": now_ts()})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e), "licenses": []}), 500


@app.route("/add", methods=["POST"])
def add_license():
    """Add a new license"""
    if not ensure_db_initialized():
        return jsonify({"success": False, "error": "Database not available"}), 500

    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "No JSON received"}), 400

    owner = data.get("owner")
    code = data.get("code")
    expiry = data.get("expiry")
    ea_name = data.get("ea_name", "")
    max_accounts = data.get("max_accounts", 1)
    predefined_accounts = data.get("predefined_accounts", [])

    if not owner or not code or not expiry:
        return jsonify({"success": False, "error": "Missing required fields (owner, code, expiry)"}), 400

    try:
        if predefined_accounts:
            for acc in predefined_accounts:
                if not acc.get("account_number") or not acc.get("account_name"):
                    return jsonify({"success": False, "error": "Each predefined account must have both number and name"}), 400
            max_accounts = len(predefined_accounts)

        success = store_license(owner, code, ea_name, max_accounts, expiry, predefined_accounts)
        if success:
            return jsonify({"success": True, "message": "License added successfully"})
        else:
            return jsonify({"success": False, "error": "Failed to store license"}), 500
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/get_predefined_accounts/<code>")
def get_predefined_accounts(code):
    """Get predefined accounts for a license"""
    if not ensure_db_initialized():
        return jsonify({"success": False, "error": "Database not available", "accounts": []}), 500

    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id FROM licenses WHERE code=?", (code,))
        row = c.fetchone()
        if not row:
            conn.close()
            return jsonify({"success": False, "error": "License not found", "accounts": []}), 404

        license_id = row[0]
        accounts = get_predefined_accounts_for_license(license_id)
        conn.close()
        return jsonify({"success": True, "accounts": accounts})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e), "accounts": []}), 500


@app.route("/update", methods=["POST"])
def update_license():
    """Update license expiry"""
    if not ensure_db_initialized():
        return jsonify({"success": False, "error": "Database not available"}), 500

    data = request.get_json()
    code = data.get("code")
    new_expiry = data.get("new_expiry")

    if not code or new_expiry is None:
        return jsonify({"success": False, "error": "Missing fields"}), 400

    try:
        update_expiry(code, new_expiry)
        return jsonify({"success": True, "message": "License updated successfully"})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/delete", methods=["POST"])
def delete_license_route():
    """Delete a license"""
    if not ensure_db_initialized():
        return jsonify({"success": False, "error": "Database not available"}), 500

    data = request.get_json()
    code = data.get("code")

    if not code:
        return jsonify({"success": False, "error": "Missing code"}), 400

    try:
        delete_license(code)
        return jsonify({"success": True, "message": "License deleted successfully"})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/edit", methods=["POST"])
def edit_license_route():
    """Edit license information"""
    if not ensure_db_initialized():
        return jsonify({"success": False, "error": "Database not available"}), 500

    data = request.get_json()
    if not data:
        return jsonify({"success": False, "error": "No JSON received"}), 400

    code = data.get("code")
    if not code:
        return jsonify({"success": False, "error": "Missing code"}), 400

    owner = data.get("owner")
    ea_name = data.get("ea_name")
    max_accounts = data.get("max_accounts")
    predefined_accounts = data.get("predefined_accounts")

    try:
        success = edit_license(code, owner=owner, ea_name=ea_name, max_accounts=max_accounts, predefined_accounts=predefined_accounts)
        if success:
            return jsonify({"success": True, "message": "License updated successfully"})
        else:
            return jsonify({"success": False, "error": "Failed to update license"}), 500
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/activate", methods=["POST"])
def activate_license():
    """Activate a license"""
    if not ensure_db_initialized():
        return jsonify({"success": False, "error": "Database not available"}), 500

    data = request.get_json()
    code = data.get("code")

    if not code:
        return jsonify({"success": False, "error": "Missing code"}), 400

    try:
        success = toggle_license_active(code, active=True)
        if success:
            return jsonify({"success": True, "message": "License activated successfully"})
        else:
            return jsonify({"success": False, "error": "Failed to activate license"}), 500
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/deactivate", methods=["POST"])
def deactivate_license():
    """Deactivate a license"""
    if not ensure_db_initialized():
        return jsonify({"success": False, "error": "Database not available"}), 500

    data = request.get_json()
    code = data.get("code")

    if not code:
        return jsonify({"success": False, "error": "Missing code"}), 400

    try:
        success = toggle_license_active(code, active=False)
        if success:
            return jsonify({"success": True, "message": "License deactivated successfully"})
        else:
            return jsonify({"success": False, "error": "Failed to deactivate license"}), 500
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/toggle_active", methods=["POST"])
def toggle_active_license():
    """Toggle license active state"""
    if not ensure_db_initialized():
        return jsonify({"success": False, "error": "Database not available"}), 500

    data = request.get_json()
    code = data.get("code")

    if not code:
        return jsonify({"success": False, "error": "Missing code"}), 400

    try:
        success = toggle_license_active(code)
        if success:
            return jsonify({"success": True, "message": "License active state toggled successfully"})
        else:
            return jsonify({"success": False, "error": "Failed to toggle license active state"}), 500
    except Exception as e:
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/backup")
def backup_db():
    """Download the database file"""
    try:
        if not os.path.exists(DB_PATH):
            return jsonify({"error": "Database file not found"}), 404
        return send_file(
            DB_PATH,
            mimetype="application/octet-stream",
            as_attachment=True,
            download_name="licenses.db"
        )
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/restore", methods=["POST"])
def restore_db():
    """Upload and restore a database file"""
    try:
        if "file" not in request.files:
            return jsonify({"success": False, "error": "No file provided"}), 400
        file = request.files["file"]
        if file.filename == "":
            return jsonify({"success": False, "error": "No file selected"}), 400
        file.save(DB_PATH)
        return jsonify({"success": True, "message": "Database restored successfully"})
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/initdb")
def initdb_route():
    """Manually initialize database"""
    try:
        success = init_db()
        if success:
            migrate_db()
            return jsonify({"status": "success", "message": "Database initialized successfully"})
        else:
            return jsonify({"status": "error", "message": "Database initialization failed"}), 500
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/migrate")
def migrate_route():
    """Manually run database migration"""
    try:
        success = migrate_db()
        if success:
            return jsonify({"status": "success", "message": "Database migration completed"})
        else:
            return jsonify({"status": "error", "message": "Database migration failed"}), 500
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/status")
def status():
    """Server status and statistics"""
    try:
        if not ensure_db_initialized():
            return jsonify({"status": "error", "error": "Database not initialized"}), 500

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()

        c.execute("SELECT COUNT(*) FROM licenses")
        license_count = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM license_accounts")
        account_count = c.fetchone()[0]

        c.execute("SELECT COUNT(*) FROM predefined_accounts")
        predefined_count = c.fetchone()[0]

        now = now_ts()
        c.execute("SELECT COUNT(*) FROM licenses WHERE expiry IS NULL OR expiry > ?", (now,))
        active_licenses = c.fetchone()[0]

        c.execute("PRAGMA table_info(licenses)")
        columns = [col[1] for col in c.fetchall()]

        if "active" in columns:
            c.execute("SELECT COUNT(*) FROM licenses WHERE active = 1")
            enabled_licenses = c.fetchone()[0]
        else:
            enabled_licenses = license_count

        conn.close()

        return jsonify(
            {
                "status": "healthy",
                "server_time": format_time(now),
                "database": "initialized",
                "db_path": DB_PATH,
                "statistics": {
                    "total_licenses": license_count,
                    "total_accounts": account_count,
                    "predefined_accounts": predefined_count,
                    "active_licenses": active_licenses,
                    "enabled_licenses": enabled_licenses,
                },
            }
        )
    except Exception as e:
        traceback.print_exc()
        return jsonify({"status": "error", "error": str(e)}), 500


# ---------- Error Handlers ----------
@app.errorhandler(404)
def not_found(error):
    return jsonify({"success": False, "error": "Endpoint not found"}), 404


@app.errorhandler(500)
def internal_error(error):
    return jsonify({"success": False, "error": "Internal server error"}), 500


# ---------- Main ----------
if __name__ == "__main__":
    print("🚀 Starting License Server...")
    print(f"✅ Database path: {DB_PATH}")
    if init_db():
        migrate_db()
    port = int(os.environ.get("PORT", 8000))
    print(f"📡 Server configured for port {port}")
    app.run(host="0.0.0.0", port=port, debug=False)
