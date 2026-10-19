"""Immutable legacy v1 snapshot, used only to verify adoption into Alembic.

New schema changes belong in backend/storage/alembic/versions.
"""

SCHEMA_VERSION = 1

MIGRATIONS: dict[int, tuple[str, ...]] = {
    1: (
        """
        CREATE TABLE feedback (
            id TEXT PRIMARY KEY NOT NULL,
            satisfaction TEXT CHECK (satisfaction IN ('satisfied', 'neutral', 'dissatisfied')),
            category TEXT NOT NULL CHECK (category IN ('review', 'problem', 'suggestion')),
            message TEXT NOT NULL DEFAULT '' CHECK (length(message) <= 2000),
            source TEXT NOT NULL CHECK (source IN ('general', 'result', 'error')),
            status TEXT NOT NULL DEFAULT 'new'
                CHECK (status IN ('new', 'in_progress', 'resolved')),
            created_at INTEGER NOT NULL,
            CHECK (satisfaction IS NOT NULL OR length(trim(message)) > 0)
        ) STRICT
        """,
        "CREATE INDEX feedback_created_at ON feedback(created_at)",
        """
        CREATE TABLE feedback_contacts (
            feedback_id TEXT PRIMARY KEY NOT NULL REFERENCES feedback(id) ON DELETE CASCADE,
            email TEXT NOT NULL CHECK (length(email) BETWEEN 1 AND 254),
            consented_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL CHECK (expires_at > consented_at)
        ) STRICT
        """,
        "CREATE INDEX feedback_contacts_expiry ON feedback_contacts(expires_at)",
        """
        CREATE TABLE usage_events (
            event_id TEXT PRIMARY KEY NOT NULL,
            event_type TEXT NOT NULL CHECK (event_type IN (
                'page_view', 'calculation_success', 'calculation_failure',
                'gift_pdf_download', 'rate_pdf_download', 'feedback_submitted', 'support_click'
            )),
            visitor_id TEXT,
            source TEXT CHECK (source IN ('site', 'header', 'feedback')),
            target TEXT CHECK (target IN ('fairy', 'github')),
            occurred_at INTEGER NOT NULL
        ) STRICT
        """,
        "CREATE INDEX usage_events_time ON usage_events(occurred_at, event_type, visitor_id)",
        """
        CREATE TABLE daily_usage_counts (
            day TEXT NOT NULL,
            event_type TEXT NOT NULL CHECK (event_type IN (
                'page_view', 'calculation_success', 'calculation_failure',
                'gift_pdf_download', 'rate_pdf_download', 'feedback_submitted', 'support_click'
            )),
            event_count INTEGER NOT NULL CHECK (event_count >= 0),
            PRIMARY KEY (day, event_type)
        ) STRICT
        """,
        """
        CREATE TABLE admin_account (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            user_handle BLOB NOT NULL UNIQUE,
            created_at INTEGER NOT NULL
        ) STRICT
        """,
        """
        CREATE TABLE admin_credentials (
            credential_id BLOB PRIMARY KEY NOT NULL,
            admin_id INTEGER NOT NULL REFERENCES admin_account(id),
            public_key BLOB NOT NULL,
            sign_count INTEGER NOT NULL CHECK (sign_count >= 0),
            transports_json TEXT NOT NULL DEFAULT '[]',
            label TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            last_used_at INTEGER
        ) STRICT
        """,
        """
        CREATE TABLE admin_sessions (
            session_id TEXT PRIMARY KEY NOT NULL,
            admin_id INTEGER NOT NULL REFERENCES admin_account(id),
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL CHECK (expires_at > created_at)
        ) STRICT
        """,
        "CREATE INDEX admin_sessions_expiry ON admin_sessions(expires_at)",
        """
        CREATE TABLE admin_one_time_tokens (
            token_hash TEXT PRIMARY KEY NOT NULL,
            purpose TEXT NOT NULL CHECK (purpose IN ('registration', 'login')),
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL CHECK (expires_at > created_at)
        ) STRICT
        """,
        "CREATE INDEX admin_one_time_tokens_expiry ON admin_one_time_tokens(expires_at)",
        """
        CREATE TABLE admin_challenges (
            challenge_id TEXT PRIMARY KEY NOT NULL,
            challenge BLOB NOT NULL,
            purpose TEXT NOT NULL CHECK (purpose IN ('registration', 'authentication')),
            binding_hash TEXT NOT NULL,
            created_at INTEGER NOT NULL,
            expires_at INTEGER NOT NULL CHECK (expires_at > created_at)
        ) STRICT
        """,
        "CREATE INDEX admin_challenges_expiry ON admin_challenges(expires_at)",
    ),
}
