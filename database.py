import os
import sqlite3
from pathlib import Path

DB_NAME = os.environ.get("DATABASE_PATH", "tutor_match.db").strip() or "tutor_match.db"
SESSION_DAYS = 7  # how long a login (wristband) stays valid


def get_connection():
    db_path = Path(DB_NAME).expanduser()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # lets us read rows like dictionaries
    return conn


def delete_expired_scheduled_requests():
    conn = get_connection()
    conn.execute(
        "DELETE FROM trial_bookings WHERE preferred_date < date('now', 'localtime')"
    )
    conn.execute(
        """
        DELETE FROM tutoring_requests
        WHERE end_date != '' AND end_date < date('now', 'localtime')
        """
    )
    conn.commit()
    conn.close()


def init_db():
    conn = get_connection()
    cur = conn.cursor()

    # Register 1: areas (the city map)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS areas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL
        )
    """)

    # Register 2: users (the membership register)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('student', 'tutor')),
            area_id INTEGER NOT NULL,
            avatar TEXT,
            FOREIGN KEY (area_id) REFERENCES areas (id)
        )
    """)

    # Upgrade an older database that was created before the avatar column existed
    user_columns = [r["name"] for r in cur.execute("PRAGMA table_info(users)").fetchall()]
    if "avatar" not in user_columns:
        cur.execute("ALTER TABLE users ADD COLUMN avatar TEXT")

    # Register 3: tutors (the visiting cards)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tutors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            qualification TEXT NOT NULL,
            min_class INTEGER NOT NULL,
            max_class INTEGER NOT NULL,
            available_from INTEGER NOT NULL,
            available_to INTEGER NOT NULL,
            max_hours_per_day INTEGER,
            phone TEXT,
            bio TEXT NOT NULL DEFAULT '',
            is_accepting INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)

    # Upgrade an older database that was created before these columns existed
    tutor_columns = [r["name"] for r in cur.execute("PRAGMA table_info(tutors)").fetchall()]
    if "phone" not in tutor_columns:
        cur.execute("ALTER TABLE tutors ADD COLUMN phone TEXT")
    if "bio" not in tutor_columns:
        cur.execute("ALTER TABLE tutors ADD COLUMN bio TEXT NOT NULL DEFAULT ''")
    if "is_accepting" not in tutor_columns:
        cur.execute("ALTER TABLE tutors ADD COLUMN is_accepting INTEGER NOT NULL DEFAULT 1")

    # Register 4: tutor_subjects (the sticky notes)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tutor_subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tutor_id INTEGER NOT NULL,
            subject TEXT NOT NULL,
            FOREIGN KEY (tutor_id) REFERENCES tutors (id)
        )
    """)

    # Register 5: sessions (the wristbands)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)

    # Register 6: contact_requests (the doorbell log)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS contact_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            tutor_id INTEGER NOT NULL,
            message TEXT,
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'accepted', 'declined')),
            decline_reason TEXT NOT NULL DEFAULT '',
            student_contact_hidden INTEGER NOT NULL DEFAULT 0,
            tutor_contact_hidden INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (student_id, tutor_id),
            FOREIGN KEY (student_id) REFERENCES users (id),
            FOREIGN KEY (tutor_id) REFERENCES tutors (id)
        )
    """)

    # Register 7: password_resets (the one-time codes)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS password_resets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            code_hash TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS trial_bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            tutor_id INTEGER NOT NULL,
            child_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            class_level INTEGER NOT NULL,
            subject TEXT NOT NULL,
            preferred_date TEXT NOT NULL,
            preferred_time TEXT NOT NULL,
            message TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'accepted', 'declined')),
            decline_reason TEXT NOT NULL DEFAULT '',
            student_contact_hidden INTEGER NOT NULL DEFAULT 0,
            tutor_contact_hidden INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES users (id),
            FOREIGN KEY (tutor_id) REFERENCES tutors (id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tutor_reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            tutor_id INTEGER NOT NULL,
            rating INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
            review TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (student_id, tutor_id),
            FOREIGN KEY (student_id) REFERENCES users (id),
            FOREIGN KEY (tutor_id) REFERENCES tutors (id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tutoring_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            tutor_id INTEGER NOT NULL,
            child_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            class_level INTEGER NOT NULL,
            subject TEXT NOT NULL,
            weekdays TEXT NOT NULL,
            start_date TEXT NOT NULL DEFAULT '',
            end_date TEXT NOT NULL DEFAULT '',
            preferred_from TEXT NOT NULL,
            preferred_to TEXT NOT NULL,
            message TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending', 'accepted', 'declined')),
            decline_reason TEXT NOT NULL DEFAULT '',
            student_contact_hidden INTEGER NOT NULL DEFAULT 0,
            tutor_contact_hidden INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES users (id),
            FOREIGN KEY (tutor_id) REFERENCES tutors (id)
        )
    """)

    for table in ("contact_requests", "trial_bookings", "tutoring_requests"):
        columns = {
            row["name"]
            for row in cur.execute(f"PRAGMA table_info({table})").fetchall()
        }
        for column in (
            "student_contact_hidden", "tutor_contact_hidden", "decline_reason"
        ):
            if column not in columns:
                cur.execute(
                    f"ALTER TABLE {table} ADD COLUMN {column} "
                    + ("TEXT NOT NULL DEFAULT ''" if column == "decline_reason"
                       else "INTEGER NOT NULL DEFAULT 0")
                )

    tutoring_columns = {
        row["name"]
        for row in cur.execute("PRAGMA table_info(tutoring_requests)").fetchall()
    }
    for column in ("start_date", "end_date"):
        if column not in tutoring_columns:
            cur.execute(
                f"ALTER TABLE tutoring_requests ADD COLUMN {column} TEXT NOT NULL DEFAULT ''"
            )

    conn.commit()
    conn.close()


# Approximate coordinates, good enough for an MVP
HYDERABAD_AREAS = [
    ("Kondapur", 17.4600, 78.3650),
    ("Gachibowli", 17.4401, 78.3489),
    ("Madhapur", 17.4486, 78.3908),
    ("Hitech City", 17.4435, 78.3772),
    ("Manikonda", 17.4021, 78.3866),
    ("Miyapur", 17.4967, 78.3570),
    ("Kukatpally", 17.4948, 78.3996),
    ("Nizampet", 17.5190, 78.3860),
    ("Bachupally", 17.5440, 78.3580),
    ("Jubilee Hills", 17.4326, 78.4071),
    ("Banjara Hills", 17.4156, 78.4347),
    ("Ameerpet", 17.4375, 78.4483),
    ("Begumpet", 17.4440, 78.4676),
    ("Secunderabad", 17.4399, 78.4983),
    ("Habsiguda", 17.4150, 78.5400),
    ("Uppal", 17.4058, 78.5591),
    ("Nagole", 17.3920, 78.5600),
    ("Kothapet", 17.3660, 78.5400),
    ("Dilsukhnagar", 17.3688, 78.5247),
    ("LB Nagar", 17.3457, 78.5522),
]


def seed_areas():
    conn = get_connection()
    cur = conn.cursor()
    for name, lat, lon in HYDERABAD_AREAS:
        # INSERT OR IGNORE = skip if the area is already there
        cur.execute(
            "INSERT OR IGNORE INTO areas (name, latitude, longitude) VALUES (?, ?, ?)",
            (name, lat, lon),
        )
    conn.commit()
    conn.close()


def get_all_areas():
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, name, latitude, longitude FROM areas ORDER BY name"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def area_exists(area_id):
    conn = get_connection()
    row = conn.execute("SELECT id FROM areas WHERE id = ?", (area_id,)).fetchone()
    conn.close()
    return row is not None


# ---------- users ----------

def get_user_by_email(email):
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()
    return dict(row) if row else None


def create_user(name, email, password_hash, role, area_id):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (name, email, password_hash, role, area_id) VALUES (?, ?, ?, ?, ?)",
        (name, email, password_hash, role, area_id),
    )
    conn.commit()
    user_id = cur.lastrowid
    conn.close()
    return user_id


def get_password_hash(user_id):
    conn = get_connection()
    row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return row["password_hash"] if row else None


def update_password(user_id, password_hash):
    conn = get_connection()
    conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (password_hash, user_id))
    conn.commit()
    conn.close()


def update_user_profile(user_id, name, area_id, avatar_action, avatar):
    """Saves name + area. The photo is only touched if avatar_action says so:
    'set' = save the new photo, 'remove' = delete it, 'keep' = leave it alone."""
    conn = get_connection()
    if avatar_action == "set":
        conn.execute(
            "UPDATE users SET name = ?, area_id = ?, avatar = ? WHERE id = ?",
            (name, area_id, avatar, user_id),
        )
    elif avatar_action == "remove":
        conn.execute(
            "UPDATE users SET name = ?, area_id = ?, avatar = NULL WHERE id = ?",
            (name, area_id, user_id),
        )
    else:
        conn.execute(
            "UPDATE users SET name = ?, area_id = ? WHERE id = ?",
            (name, area_id, user_id),
        )
    conn.commit()
    conn.close()


# ---------- sessions (wristbands) ----------

def create_session(token, user_id):
    conn = get_connection()
    conn.execute("INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, user_id))
    conn.commit()
    conn.close()


def get_user_by_token(token):
    """Only returns the user if the wristband exists AND hasn't expired."""
    conn = get_connection()
    row = conn.execute(
        f"""
        SELECT users.id, users.name, users.email, users.role, users.avatar,
               areas.id AS area_id, areas.name AS area_name,
               areas.latitude, areas.longitude
        FROM sessions
        JOIN users ON users.id = sessions.user_id
        JOIN areas ON areas.id = users.area_id
        WHERE sessions.token = ?
          AND sessions.created_at > datetime('now', '-{SESSION_DAYS} days')
        """,
        (token,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_session(token):
    conn = get_connection()
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
    conn.commit()
    conn.close()


def delete_sessions_for_user(user_id):
    """Deactivates every wristband this person has (all devices)."""
    conn = get_connection()
    conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def delete_expired_sessions():
    """Tidy up old wristbands so the table doesn't grow forever."""
    conn = get_connection()
    conn.execute(
        f"DELETE FROM sessions WHERE created_at <= datetime('now', '-{SESSION_DAYS} days')"
    )
    conn.commit()
    conn.close()


# ---------- tutor profiles (visiting cards) ----------

def save_tutor_profile(user_id, qualification, subjects, min_class, max_class,
                       available_from, available_to, max_hours_per_day, phone, bio):
    """Create the visiting card, or overwrite it if the tutor already has one.
    The OPEN/CLOSED switch (is_accepting) is NOT touched here."""
    conn = get_connection()
    cur = conn.cursor()

    existing = cur.execute(
        "SELECT id FROM tutors WHERE user_id = ?", (user_id,)
    ).fetchone()

    if existing:
        tutor_id = existing["id"]
        cur.execute(
            """
            UPDATE tutors
            SET qualification = ?, min_class = ?, max_class = ?,
                available_from = ?, available_to = ?, max_hours_per_day = ?,
                phone = ?, bio = ?
            WHERE id = ?
            """,
            (qualification, min_class, max_class,
             available_from, available_to, max_hours_per_day, phone, bio, tutor_id),
        )
        # wipe the old sticky notes, we'll write fresh ones
        cur.execute("DELETE FROM tutor_subjects WHERE tutor_id = ?", (tutor_id,))
    else:
        cur.execute(
            """
            INSERT INTO tutors (user_id, qualification, min_class, max_class,
                                available_from, available_to, max_hours_per_day, phone, bio)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user_id, qualification, min_class, max_class,
             available_from, available_to, max_hours_per_day, phone, bio),
        )
        tutor_id = cur.lastrowid

    for subject in subjects:
        cur.execute(
            "INSERT INTO tutor_subjects (tutor_id, subject) VALUES (?, ?)",
            (tutor_id, subject),
        )

    conn.commit()
    conn.close()


def get_tutor_profile(user_id):
    conn = get_connection()
    row = conn.execute("SELECT * FROM tutors WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        conn.close()
        return None

    profile = dict(row)
    subjects = conn.execute(
        "SELECT subject FROM tutor_subjects WHERE tutor_id = ?", (row["id"],)
    ).fetchall()
    profile["subjects"] = [s["subject"] for s in subjects]
    conn.close()
    return profile


def get_public_tutor_profile(tutor_id, student_id):
    conn = get_connection()
    row = conn.execute(
        """
        SELECT tutors.id AS tutor_id, users.name, users.avatar, tutors.qualification,
               tutors.bio, tutors.min_class, tutors.max_class,
               tutors.available_from, tutors.available_to, tutors.max_hours_per_day,
               tutors.is_accepting,
               areas.name AS area_name
        FROM tutors
        JOIN users ON users.id = tutors.user_id
        JOIN areas ON areas.id = users.area_id
        WHERE tutors.id = ?
        """,
        (tutor_id,),
    ).fetchone()
    if not row:
        conn.close()
        return None

    profile = dict(row)
    profile["subjects"] = [
        subject["subject"]
        for subject in conn.execute(
            "SELECT subject FROM tutor_subjects WHERE tutor_id = ? ORDER BY subject",
            (tutor_id,),
        ).fetchall()
    ]
    profile["request_status"] = conn.execute(
        """
        SELECT CASE
            WHEN EXISTS (
                SELECT 1 FROM contact_requests
                WHERE student_id = ? AND tutor_id = ? AND status = 'accepted'
            ) OR EXISTS (
                SELECT 1 FROM trial_bookings
                WHERE student_id = ? AND tutor_id = ? AND status = 'accepted'
            ) OR EXISTS (
                SELECT 1 FROM tutoring_requests
                WHERE student_id = ? AND tutor_id = ? AND status = 'accepted'
            ) THEN 'accepted'
            WHEN EXISTS (
                SELECT 1 FROM contact_requests
                WHERE student_id = ? AND tutor_id = ? AND status = 'pending'
            ) OR EXISTS (
                SELECT 1 FROM trial_bookings
                WHERE student_id = ? AND tutor_id = ? AND status = 'pending'
            ) OR EXISTS (
                SELECT 1 FROM tutoring_requests
                WHERE student_id = ? AND tutor_id = ? AND status = 'pending'
            ) THEN 'pending'
            WHEN EXISTS (
                SELECT 1 FROM contact_requests
                WHERE student_id = ? AND tutor_id = ? AND status = 'declined'
            ) OR EXISTS (
                SELECT 1 FROM trial_bookings
                WHERE student_id = ? AND tutor_id = ? AND status = 'declined'
            ) OR EXISTS (
                SELECT 1 FROM tutoring_requests
                WHERE student_id = ? AND tutor_id = ? AND status = 'declined'
            ) THEN 'declined'
            ELSE NULL
        END
        """,
        (student_id, tutor_id, student_id, tutor_id, student_id, tutor_id,
         student_id, tutor_id, student_id, tutor_id, student_id, tutor_id,
         student_id, tutor_id, student_id, tutor_id, student_id, tutor_id),
    ).fetchone()[0]
    profile["can_review"] = conn.execute(
        """
        SELECT 1 FROM contact_requests
        WHERE student_id = ? AND tutor_id = ? AND status = 'accepted'
        UNION
        SELECT 1 FROM trial_bookings
        WHERE student_id = ? AND tutor_id = ? AND status = 'accepted'
        UNION
        SELECT 1 FROM tutoring_requests
        WHERE student_id = ? AND tutor_id = ? AND status = 'accepted'
        LIMIT 1
        """,
        (student_id, tutor_id, student_id, tutor_id, student_id, tutor_id),
    ).fetchone() is not None
    profile["existing_review"] = conn.execute(
        "SELECT 1 FROM tutor_reviews WHERE student_id = ? AND tutor_id = ?",
        (student_id, tutor_id),
    ).fetchone() is not None
    profile["rating_average"] = conn.execute(
        "SELECT AVG(rating) FROM tutor_reviews WHERE tutor_id = ?", (tutor_id,)
    ).fetchone()[0]
    profile["reviews"] = [
        dict(review)
        for review in conn.execute(
            """
            SELECT tutor_reviews.rating, tutor_reviews.review, tutor_reviews.created_at,
                   users.name AS student_name
            FROM tutor_reviews
            JOIN users ON users.id = tutor_reviews.student_id
            WHERE tutor_reviews.tutor_id = ?
            ORDER BY tutor_reviews.id DESC
            """,
            (tutor_id,),
        ).fetchall()
    ]
    conn.close()
    return profile


def create_tutor_review(student_id, tutor_id, rating, review):
    conn = get_connection()
    try:
        cur = conn.execute(
            "INSERT INTO tutor_reviews (student_id, tutor_id, rating, review) VALUES (?, ?, ?, ?)",
            (student_id, tutor_id, rating, review),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def get_tutor_accepting(tutor_id):
    """Returns None if the tutor doesn't exist, otherwise 1 (open) or 0 (paused)."""
    conn = get_connection()
    row = conn.execute("SELECT is_accepting FROM tutors WHERE id = ?", (tutor_id,)).fetchone()
    conn.close()
    return row["is_accepting"] if row else None


def set_tutor_accepting(user_id, accepting):
    """Flip the OPEN/CLOSED sign. Returns False if this tutor has no profile yet."""
    conn = get_connection()
    cur = conn.execute(
        "UPDATE tutors SET is_accepting = ? WHERE user_id = ?",
        (1 if accepting else 0, user_id),
    )
    conn.commit()
    updated = cur.rowcount > 0
    conn.close()
    return updated


def get_all_tutors_for_search():
    """Every tutor with a finished visiting card, in the shape matching.py expects.
    NOTE: phone is included here for the server's use only. main.py decides
    whether a student is allowed to see it. The photo (avatar) is what the
    tutor card shows on top."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT tutors.id AS tutor_id, users.name, users.avatar, tutors.qualification,
               tutors.min_class, tutors.max_class,
               tutors.available_from, tutors.available_to, tutors.phone,
               tutors.is_accepting,
               (SELECT AVG(rating) FROM tutor_reviews WHERE tutor_id = tutors.id) AS rating_average,
               (SELECT COUNT(*) FROM tutor_reviews WHERE tutor_id = tutors.id) AS review_count,
               areas.name AS area_name, areas.latitude AS lat, areas.longitude AS lon
        FROM tutors
        JOIN users ON users.id = tutors.user_id
        JOIN areas ON areas.id = users.area_id
        """
    ).fetchall()

    tutors = []
    for row in rows:
        tutor = dict(row)
        subjects = conn.execute(
            "SELECT subject FROM tutor_subjects WHERE tutor_id = ?", (row["tutor_id"],)
        ).fetchall()
        tutor["subjects"] = [s["subject"] for s in subjects]
        tutors.append(tutor)

    conn.close()
    return tutors


# ---------- contact requests (the doorbell) ----------

def get_request_between(student_id, tutor_id):
    conn = get_connection()
    row = conn.execute(
        "SELECT id, status FROM contact_requests WHERE student_id = ? AND tutor_id = ?",
        (student_id, tutor_id),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def create_contact_request(student_id, tutor_id, message):
    """Returns the new request id, or None if this student already rang this tutor."""
    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO contact_requests (student_id, tutor_id, message) VALUES (?, ?, ?)",
            (student_id, tutor_id, message),
        )
        conn.commit()
        return cur.lastrowid
    except sqlite3.IntegrityError:
        return None
    finally:
        conn.close()


def get_request_statuses_for_student(student_id):
    """{tutor_id: status} for every request this student has sent."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT tutor_id, status FROM contact_requests WHERE student_id = ?",
        (student_id,),
    ).fetchall()
    conn.close()
    return {row["tutor_id"]: row["status"] for row in rows}


def get_requests_by_student(student_id):
    """The student's 'My requests' list. Phone is only filled in when accepted."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT cr.id, cr.tutor_id, cr.status, cr.message, cr.decline_reason,
               cr.student_contact_hidden, cr.tutor_contact_hidden, cr.created_at,
               u.name AS tutor_name, u.avatar AS tutor_avatar, a.name AS area_name,
               CASE WHEN cr.status = 'accepted' AND cr.tutor_contact_hidden = 0
                    THEN t.phone END AS phone,
               CASE WHEN cr.status = 'accepted' AND cr.tutor_contact_hidden = 0
                    THEN u.email END AS tutor_email
        FROM contact_requests cr
        JOIN tutors t ON t.id = cr.tutor_id
        JOIN users u ON u.id = t.user_id
        JOIN areas a ON a.id = u.area_id
        WHERE cr.student_id = ?
        ORDER BY cr.id DESC
        """,
        (student_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_incoming_requests(tutor_user_id):
    """The tutor's inbox, with waiting requests first."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT cr.id, cr.status, cr.message, cr.decline_reason, cr.created_at,
               cr.student_id, cr.tutor_id,
               cr.student_contact_hidden, cr.tutor_contact_hidden,
               s.name AS student_name, s.avatar AS student_avatar, a.name AS student_area
        FROM contact_requests cr
        JOIN tutors t ON t.id = cr.tutor_id
        JOIN users s ON s.id = cr.student_id
        JOIN areas a ON a.id = s.area_id
        WHERE t.user_id = ?
        ORDER BY CASE cr.status WHEN 'pending' THEN 0 ELSE 1 END, cr.id DESC
        """,
        (tutor_user_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_request_for_response(request_id):
    conn = get_connection()
    row = conn.execute(
        """
        SELECT cr.id, cr.status, cr.student_id, cr.tutor_id,
               t.user_id AS tutor_user_id, t.phone AS tutor_phone
        FROM contact_requests cr
        JOIN tutors t ON t.id = cr.tutor_id
        WHERE cr.id = ?
        """,
        (request_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_request_status(request_id, status, decline_reason=""):
    conn = get_connection()
    conn.execute(
        "UPDATE contact_requests SET status = ?, decline_reason = ? WHERE id = ?",
        (status, decline_reason, request_id),
    )
    conn.commit()
    conn.close()


def delete_resolved_student_request(table, request_id, student_id):
    table_names = {
        "requests": "contact_requests",
        "trials": "trial_bookings",
        "booking-requests": "tutoring_requests",
    }
    table_name = table_names.get(table)
    if table_name is None:
        return False
    conn = get_connection()
    cursor = conn.execute(
        f"DELETE FROM {table_name} "
        "WHERE id = ? AND student_id = ? AND status IN ('accepted', 'declined')",
        (request_id, student_id),
    )
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()
    return deleted


def delete_resolved_tutor_request(table, request_id, tutor_user_id):
    table_names = {
        "requests": ("contact_requests", "tutor_id"),
        "trials": ("trial_bookings", "tutor_id"),
        "booking-requests": ("tutoring_requests", "tutor_id"),
    }
    table_info = table_names.get(table)
    if table_info is None:
        return False
    table_name, tutor_id_column = table_info
    conn = get_connection()
    cursor = conn.execute(
        f"DELETE FROM {table_name} WHERE id = ? AND status IN ('accepted', 'declined') "
        f"AND {tutor_id_column} IN (SELECT id FROM tutors WHERE user_id = ?)",
        (request_id, tutor_user_id),
    )
    conn.commit()
    deleted = cursor.rowcount > 0
    conn.close()
    return deleted


def create_trial_booking(student_id, tutor_id, child_name, phone, class_level,
                         subject, preferred_date, preferred_time, message):
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            """
            SELECT id FROM trial_bookings
            WHERE student_id = ? AND tutor_id = ? AND subject = ?
            """,
            (student_id, tutor_id, subject),
        ).fetchone()
        if existing:
            conn.rollback()
            return None

        cur = conn.execute(
            """
            INSERT INTO trial_bookings
                (student_id, tutor_id, child_name, phone, class_level, subject,
                 preferred_date, preferred_time, message)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (student_id, tutor_id, child_name, phone, class_level, subject,
             preferred_date, preferred_time, message),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_trial_bookings_by_student(student_id):
    delete_expired_scheduled_requests()
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT trial_bookings.id, trial_bookings.tutor_id, trial_bookings.child_name,
               trial_bookings.class_level, trial_bookings.subject,
               trial_bookings.preferred_date, trial_bookings.preferred_time,
               trial_bookings.message, trial_bookings.status, trial_bookings.decline_reason,
               trial_bookings.student_contact_hidden, trial_bookings.tutor_contact_hidden,
               trial_bookings.created_at,
               users.name AS tutor_name, users.avatar AS tutor_avatar, areas.name AS area_name,
               CASE WHEN trial_bookings.status = 'accepted'
                          AND trial_bookings.tutor_contact_hidden = 0
                    THEN tutors.phone END AS tutor_phone,
               CASE WHEN trial_bookings.status = 'accepted'
                          AND trial_bookings.tutor_contact_hidden = 0
                    THEN users.email END AS tutor_email
        FROM trial_bookings
        JOIN tutors ON tutors.id = trial_bookings.tutor_id
        JOIN users ON users.id = tutors.user_id
        JOIN areas ON areas.id = users.area_id
        WHERE trial_bookings.student_id = ?
        ORDER BY trial_bookings.id DESC
        """,
        (student_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_incoming_trial_bookings(tutor_user_id):
    delete_expired_scheduled_requests()
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT trial_bookings.id, trial_bookings.child_name,
               CASE WHEN trial_bookings.status = 'accepted'
                          AND trial_bookings.student_contact_hidden = 0
                    THEN trial_bookings.phone END AS phone,
               trial_bookings.class_level, trial_bookings.subject,
               trial_bookings.preferred_date, trial_bookings.preferred_time,
               trial_bookings.message, trial_bookings.status, trial_bookings.decline_reason,
               trial_bookings.student_contact_hidden, trial_bookings.tutor_contact_hidden,
               trial_bookings.created_at,
               students.name AS student_name, students.avatar AS student_avatar,
               areas.name AS student_area,
               CASE WHEN trial_bookings.status = 'accepted'
                          AND trial_bookings.student_contact_hidden = 0
                    THEN students.email END AS student_email
        FROM trial_bookings
        JOIN tutors ON tutors.id = trial_bookings.tutor_id
        JOIN users AS students ON students.id = trial_bookings.student_id
        JOIN areas ON areas.id = students.area_id
        WHERE tutors.user_id = ?
        ORDER BY CASE trial_bookings.status WHEN 'pending' THEN 0 ELSE 1 END,
                 trial_bookings.id DESC
        """,
        (tutor_user_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_trial_booking_for_response(booking_id):
    delete_expired_scheduled_requests()
    conn = get_connection()
    row = conn.execute(
        """
        SELECT trial_bookings.id, trial_bookings.status, trial_bookings.student_id,
               trial_bookings.decline_reason,
               tutors.user_id AS tutor_user_id
        FROM trial_bookings
        JOIN tutors ON tutors.id = trial_bookings.tutor_id
        WHERE trial_bookings.id = ?
        """,
        (booking_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_trial_booking_status(booking_id, status, decline_reason=""):
    conn = get_connection()
    conn.execute(
        "UPDATE trial_bookings SET status = ?, decline_reason = ? WHERE id = ?",
        (status, decline_reason, booking_id),
    )
    conn.commit()
    conn.close()


def set_pair_contact_visibility(student_id, tutor_id, role, visible):
    column = {
        "student": "student_contact_hidden",
        "tutor": "tutor_contact_hidden",
    }.get(role)
    if column is None:
        return False
    conn = get_connection()
    conn.execute("BEGIN IMMEDIATE")
    updated = 0
    for table in ("contact_requests", "trial_bookings", "tutoring_requests"):
        cursor = conn.execute(
            f"UPDATE {table} SET {column} = ? "
            f"WHERE student_id = ? AND tutor_id = ? AND status = 'accepted'",
            (0 if visible else 1, student_id, tutor_id),
        )
        updated += cursor.rowcount
    conn.commit()
    conn.close()
    return updated > 0


def set_trial_contact_visibility(booking_id, role, visible):
    conn = get_connection()
    row = conn.execute(
        "SELECT student_id, tutor_id FROM trial_bookings WHERE id = ? AND status = 'accepted'",
        (booking_id,),
    ).fetchone()
    conn.close()
    if not row:
        return False
    return set_pair_contact_visibility(row["student_id"], row["tutor_id"], role, visible)


def create_tutoring_request(student_id, tutor_id, child_name, phone, class_level,
                            subjects, weekdays, preferred_from, preferred_to,
                            start_date, end_date, message):
    conn = get_connection()
    conn.execute("BEGIN IMMEDIATE")
    existing_rows = conn.execute(
        """
        SELECT subject FROM tutoring_requests
        WHERE student_id = ? AND tutor_id = ? AND status = 'pending'
        """,
        (student_id, tutor_id),
    ).fetchall()
    requested_subjects = {subject.casefold() for subject in subjects}
    pending_subjects = {
        subject.strip().casefold()
        for row in existing_rows
        for subject in row["subject"].split(",")
    }
    if requested_subjects & pending_subjects:
        conn.rollback()
        conn.close()
        return None

    cur = conn.execute(
        """
        INSERT INTO tutoring_requests
            (student_id, tutor_id, child_name, phone, class_level, subject,
             weekdays, preferred_from, preferred_to, start_date, end_date, message)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (student_id, tutor_id, child_name, phone, class_level, ", ".join(subjects),
         weekdays, preferred_from, preferred_to, start_date, end_date, message),
    )
    conn.commit()
    request_id = cur.lastrowid
    conn.close()
    return request_id


def update_tutoring_request(request_id, student_id, tutor_id, child_name, phone,
                            class_level, subjects, weekdays, preferred_from,
                            preferred_to, start_date, end_date, message):
    conn = get_connection()
    conn.execute("BEGIN IMMEDIATE")
    request = conn.execute(
        """
        SELECT subject FROM tutoring_requests
        WHERE id = ? AND student_id = ? AND tutor_id = ? AND status = 'pending'
          AND created_at > datetime('now', '-5 minutes')
        """,
        (request_id, student_id, tutor_id),
    ).fetchone()
    if not request:
        conn.rollback()
        conn.close()
        return "expired"

    existing_rows = conn.execute(
        """
        SELECT subject FROM tutoring_requests
        WHERE student_id = ? AND tutor_id = ? AND status = 'pending' AND id != ?
        """,
        (student_id, tutor_id, request_id),
    ).fetchall()
    requested_subjects = {subject.casefold() for subject in subjects}
    pending_subjects = {
        subject.strip().casefold()
        for row in existing_rows
        for subject in row["subject"].split(",")
    }
    if requested_subjects & pending_subjects:
        conn.rollback()
        conn.close()
        return "duplicate"

    cursor = conn.execute(
        """
        UPDATE tutoring_requests
        SET child_name = ?, phone = ?, class_level = ?, subject = ?, weekdays = ?,
            preferred_from = ?, preferred_to = ?, start_date = ?, end_date = ?, message = ?
        WHERE id = ? AND student_id = ? AND tutor_id = ? AND status = 'pending'
          AND created_at > datetime('now', '-5 minutes')
        """,
        (child_name, phone, class_level, ", ".join(subjects), weekdays,
         preferred_from, preferred_to, start_date, end_date, message,
         request_id, student_id, tutor_id),
    )
    if cursor.rowcount == 0:
        conn.rollback()
        conn.close()
        return "expired"
    conn.commit()
    conn.close()
    return "updated"


def get_tutoring_requests_by_student(student_id):
    delete_expired_scheduled_requests()
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT tutoring_requests.id, tutoring_requests.tutor_id,
               tutoring_requests.child_name, tutoring_requests.phone,
               tutoring_requests.class_level,
               tutoring_requests.subject, tutoring_requests.weekdays,
               tutoring_requests.start_date, tutoring_requests.end_date,
               tutoring_requests.preferred_from, tutoring_requests.preferred_to,
               tutoring_requests.message, tutoring_requests.status,
               tutoring_requests.decline_reason,
               CASE WHEN tutoring_requests.status = 'pending'
                          AND tutoring_requests.created_at > datetime('now', '-5 minutes')
                    THEN 1 ELSE 0 END AS can_edit,
               CASE WHEN tutoring_requests.status = 'pending'
                    THEN MAX(0, CAST((julianday(datetime(tutoring_requests.created_at, '+5 minutes'))
                                      - julianday('now')) * 86400 AS INTEGER))
                    ELSE 0 END AS edit_seconds_remaining,
               tutoring_requests.student_contact_hidden, tutoring_requests.tutor_contact_hidden,
               tutoring_requests.created_at,
               tutor_users.name AS tutor_name, tutor_users.avatar AS tutor_avatar,
               areas.name AS area_name,
               CASE WHEN tutoring_requests.status = 'accepted'
                          AND tutoring_requests.tutor_contact_hidden = 0
                    THEN tutors.phone END AS tutor_phone,
               CASE WHEN tutoring_requests.status = 'accepted'
                          AND tutoring_requests.tutor_contact_hidden = 0
                    THEN tutor_users.email END AS tutor_email
        FROM tutoring_requests
        JOIN tutors ON tutors.id = tutoring_requests.tutor_id
        JOIN users AS tutor_users ON tutor_users.id = tutors.user_id
        JOIN areas ON areas.id = tutor_users.area_id
        WHERE tutoring_requests.student_id = ?
        ORDER BY tutoring_requests.id DESC
        """,
        (student_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_incoming_tutoring_requests(tutor_user_id):
    delete_expired_scheduled_requests()
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT tutoring_requests.id, tutoring_requests.child_name,
               tutoring_requests.class_level, tutoring_requests.subject,
               tutoring_requests.weekdays, tutoring_requests.start_date,
               tutoring_requests.end_date, tutoring_requests.preferred_from,
               tutoring_requests.preferred_to, tutoring_requests.message,
               tutoring_requests.status, tutoring_requests.decline_reason,
               tutoring_requests.created_at,
               tutoring_requests.student_contact_hidden, tutoring_requests.tutor_contact_hidden,
               students.name AS student_name, students.avatar AS student_avatar,
               areas.name AS student_area,
               CASE WHEN tutoring_requests.status = 'accepted'
                          AND tutoring_requests.student_contact_hidden = 0
                    THEN tutoring_requests.phone END AS student_phone,
               CASE WHEN tutoring_requests.status = 'accepted'
                          AND tutoring_requests.student_contact_hidden = 0
                    THEN students.email END AS student_email
        FROM tutoring_requests
        JOIN tutors ON tutors.id = tutoring_requests.tutor_id
        JOIN users AS students ON students.id = tutoring_requests.student_id
        JOIN areas ON areas.id = students.area_id
        WHERE tutors.user_id = ?
        ORDER BY CASE tutoring_requests.status WHEN 'pending' THEN 0 ELSE 1 END,
                 tutoring_requests.id DESC
        """,
        (tutor_user_id,),
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_tutoring_request_for_response(request_id):
    delete_expired_scheduled_requests()
    conn = get_connection()
    row = conn.execute(
        """
        SELECT tutoring_requests.id, tutoring_requests.status,
               tutoring_requests.decline_reason,
               tutoring_requests.student_id, tutoring_requests.tutor_id,
               tutors.user_id AS tutor_user_id
        FROM tutoring_requests
        JOIN tutors ON tutors.id = tutoring_requests.tutor_id
        WHERE tutoring_requests.id = ?
        """,
        (request_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_tutoring_request_status(request_id, status, decline_reason=""):
    conn = get_connection()
    conn.execute(
        "UPDATE tutoring_requests SET status = ?, decline_reason = ? WHERE id = ?",
        (status, decline_reason, request_id),
    )
    conn.commit()
    conn.close()


def set_tutoring_contact_visibility(request_id, role, visible):
    conn = get_connection()
    row = conn.execute(
        "SELECT student_id, tutor_id FROM tutoring_requests WHERE id = ? AND status = 'accepted'",
        (request_id,),
    ).fetchone()
    conn.close()
    if not row:
        return False
    return set_pair_contact_visibility(row["student_id"], row["tutor_id"], role, visible)


def set_contact_request_visibility(request_id, role, visible):
    conn = get_connection()
    row = conn.execute(
        "SELECT student_id, tutor_id FROM contact_requests WHERE id = ? AND status = 'accepted'",
        (request_id,),
    ).fetchone()
    conn.close()
    if not row:
        return False
    return set_pair_contact_visibility(row["student_id"], row["tutor_id"], role, visible)


# ---------- password reset codes ----------

def recent_reset_exists(user_id):
    """True if a code was already made in the last 60 seconds (stops code spamming)."""
    conn = get_connection()
    row = conn.execute(
        """
        SELECT id FROM password_resets
        WHERE user_id = ? AND created_at > datetime('now', '-60 seconds')
        """,
        (user_id,),
    ).fetchone()
    conn.close()
    return row is not None


def create_password_reset(user_id, code_hash):
    """One active code per person: older ones are thrown away."""
    conn = get_connection()
    conn.execute("DELETE FROM password_resets WHERE user_id = ?", (user_id,))
    conn.execute(
        """
        INSERT INTO password_resets (user_id, code_hash, expires_at)
        VALUES (?, ?, datetime('now', '+15 minutes'))
        """,
        (user_id, code_hash),
    )
    conn.commit()
    conn.close()


def get_active_reset(user_id):
    """The code that is still valid: not expired, and fewer than 5 wrong tries."""
    conn = get_connection()
    row = conn.execute(
        """
        SELECT id, code_hash, attempts FROM password_resets
        WHERE user_id = ? AND expires_at > datetime('now') AND attempts < 5
        """,
        (user_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def bump_reset_attempts(reset_id):
    conn = get_connection()
    conn.execute("UPDATE password_resets SET attempts = attempts + 1 WHERE id = ?", (reset_id,))
    conn.commit()
    conn.close()


def delete_resets_for_user(user_id):
    conn = get_connection()
    conn.execute("DELETE FROM password_resets WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


if __name__ == "__main__":
    init_db()
    seed_areas()
    print(f"Done! {len(get_all_areas())} areas saved.")