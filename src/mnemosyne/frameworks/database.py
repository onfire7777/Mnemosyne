import json
import sqlite3
import os
from datetime import datetime
from typing import List, Dict, Optional, Any

# Manages SQLite database for books and chunks
class BookDatabase:
    
    # Initialize database connection and create tables if needed
    def __init__(self, db_path: str = "data/books.db"):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._init_database()
    
    # Create tables if missing. Schema below is the full definition; `IF NOT EXISTS` does not add
    def _init_database(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Books — final schema (fresh DB); Rule 35 structural analysis JSON on upload.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                filename TEXT NOT NULL,
                file_path TEXT NOT NULL,
                author TEXT,
                edition_isbn TEXT,
                page_numbering_basis TEXT,
                target_audience TEXT,
                upload_date TEXT NOT NULL,
                total_pages INTEGER,
                embeddings_generated INTEGER DEFAULT 0,
                structural_analysis TEXT,
                UNIQUE(file_path)
            )
        ''')
        
        # Create chunks table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                page_number INTEGER NOT NULL,
                chunk_text TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                FOREIGN KEY (book_id) REFERENCES books (id) ON DELETE CASCADE
            )
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_book_id ON chunks(book_id)
        ''')
        
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_page_number ON chunks(page_number)
        ''')

        # Frameworks: canonical user-facing text is definitive_document; content column kept minimal.
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS frameworks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                content TEXT NOT NULL,
                audit_result TEXT,
                definitive_document TEXT,
                claimed_scope TEXT,
                evidenced_scope TEXT,
                overview_prose_json TEXT,
                mechanical_audit_result TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (book_id) REFERENCES books (id) ON DELETE CASCADE
            )
        ''')

        # Framework nodes for structured mind map (Option B): node-based hierarchy
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS framework_nodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                framework_id INTEGER NOT NULL,
                parent_id INTEGER,
                sort_order INTEGER NOT NULL,
                node_type TEXT NOT NULL,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                page_ref TEXT,
                depends_on_node_id INTEGER,
                context TEXT,
                epistemic_type TEXT,
                epistemic_note TEXT,
                definitive_fields TEXT,
                FOREIGN KEY (framework_id) REFERENCES frameworks (id) ON DELETE CASCADE,
                FOREIGN KEY (parent_id) REFERENCES framework_nodes (id),
                FOREIGN KEY (depends_on_node_id) REFERENCES framework_nodes (id)
            )
        ''')
        # Phase 1: store definitive per-node fields (template-aligned schema) as JSON.
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_framework_nodes_framework_id
            ON framework_nodes(framework_id)
        ''')

        # Framework edges for mind map relationships between nodes
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS framework_edges (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                framework_id INTEGER NOT NULL,
                from_node_id INTEGER NOT NULL,
                to_node_id INTEGER NOT NULL,
                edge_type TEXT NOT NULL,
                why TEXT,
                FOREIGN KEY (framework_id) REFERENCES frameworks (id) ON DELETE CASCADE,
                FOREIGN KEY (from_node_id) REFERENCES framework_nodes (id),
                FOREIGN KEY (to_node_id) REFERENCES framework_nodes (id)
            )
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_framework_edges_framework_id
            ON framework_edges(framework_id)
        ''')

        cursor.execute("PRAGMA table_info(frameworks)")
        fw_cols = [r[1] for r in cursor.fetchall()]
        if "overview_prose_json" not in fw_cols:
            cursor.execute("ALTER TABLE frameworks ADD COLUMN overview_prose_json TEXT")
        if "generation_status" not in fw_cols:
            cursor.execute("ALTER TABLE frameworks ADD COLUMN generation_status TEXT")
        if "generation_error" not in fw_cols:
            cursor.execute("ALTER TABLE frameworks ADD COLUMN generation_error TEXT")
        if "generation_started_at" not in fw_cols:
            cursor.execute("ALTER TABLE frameworks ADD COLUMN generation_started_at TEXT")
        if "generation_finished_at" not in fw_cols:
            cursor.execute("ALTER TABLE frameworks ADD COLUMN generation_finished_at TEXT")
        if "generation_last_log_line" not in fw_cols:
            cursor.execute("ALTER TABLE frameworks ADD COLUMN generation_last_log_line TEXT")

        # Per-book chat threads (Chat tab persistence)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                book_id INTEGER NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (book_id) REFERENCES books (id) ON DELETE CASCADE
            )
            """
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                used_chunks_json TEXT,
                status TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES chat_conversations (id) ON DELETE CASCADE
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_conversations_book_id
            ON chat_conversations(book_id)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_chat_messages_conversation_id
            ON chat_messages(conversation_id, id)
            """
        )

        conn.commit()
        conn.close()

    # Add a new book to the database and return its ID
    def add_book(
        self,
        title: str,
        filename: str,
        file_path: str,
        total_pages: int,
        author: Optional[str] = None,
        edition_isbn: Optional[str] = None,
        page_numbering_basis: Optional[str] = None,
        target_audience: Optional[str] = None,
    ) -> int:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        upload_date = datetime.now().isoformat()
        
        cursor.execute(
            '''
            INSERT OR IGNORE INTO books (
                title, filename, file_path,
                author, edition_isbn, page_numbering_basis, target_audience,
                upload_date, total_pages
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''',
            (
                title,
                filename,
                file_path,
                author,
                edition_isbn,
                page_numbering_basis,
                target_audience,
                upload_date,
                total_pages,
            ),
        )
        
        if cursor.rowcount == 0:
            cursor.execute('SELECT id FROM books WHERE file_path = ?', (file_path,))
            book_id = cursor.fetchone()[0]
        else:
            book_id = cursor.lastrowid

        # Metadata fields may be filled after initial insertion.
        cursor.execute(
            '''
            UPDATE books
            SET
                title = ?,
                filename = ?,
                total_pages = ?,
                upload_date = ?
                ,author = ?
                ,edition_isbn = ?
                ,page_numbering_basis = ?
                ,target_audience = ?
            WHERE id = ?
            ''',
            (
                title,
                filename,
                total_pages,
                upload_date,
                author,
                edition_isbn,
                page_numbering_basis,
                target_audience,
                book_id,
            ),
        )
        
        conn.commit()
        conn.close()
        return book_id
    
    # Add chunks for a book
    def add_chunks(self, book_id: int, chunks: List[Dict[str, any]]):
    
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM chunks WHERE book_id = ?', (book_id,))
        
        for chunk in chunks:
            cursor.execute('''
                INSERT INTO chunks (book_id, page_number, chunk_text, chunk_index)
                VALUES (?, ?, ?, ?)
            ''', (book_id, chunk['page_number'], chunk['chunk_text'], chunk['chunk_index']))
        
        conn.commit()
        conn.close()
    
    # Get all books from database
    def get_all_books(self) -> List[Dict[str, any]]:
        
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM books ORDER BY upload_date DESC')
        books = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        return books
    
    # Get a book by its ID
    def get_book_by_id(self, book_id: int) -> Optional[Dict[str, any]]:
    
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM books WHERE id = ?', (book_id,))
        row = cursor.fetchone()
        
        conn.close()
        return dict(row) if row else None

    # Update target_audience on a book (e.g. after framework-time retrieval + LLM extraction)
    def update_book_target_audience(self, book_id: int, target_audience: Optional[str]) -> None:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE books SET target_audience = ? WHERE id = ?",
            (target_audience, book_id),
        )
        conn.commit()
        conn.close()

    def set_book_structural_analysis(self, book_id: int, analysis: Dict[str, Any]) -> None:
        """Persist Rule 35 structural analysis JSON on the book row."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE books SET structural_analysis = ? WHERE id = ?",
            (json.dumps(analysis, ensure_ascii=False), book_id),
        )
        conn.commit()
        conn.close()
    
    # Get all chunks for a book
    def get_chunks_by_book_id(self, book_id: int) -> List[Dict[str, any]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM chunks 
            WHERE book_id = ? 
            ORDER BY page_number, chunk_index
        ''', (book_id,))
        
        chunks = [dict(row) for row in cursor.fetchall()]
        
        conn.close()
        return chunks
    
    # Get total number of chunks for a book
    def get_chunk_count(self, book_id: int) -> int:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT COUNT(*) FROM chunks WHERE book_id = ?', (book_id,))
        count = cursor.fetchone()[0]
        
        conn.close()
        return count
    
    # Get a chunk by its ID
    def get_chunk_by_id(self, chunk_id: int) -> Optional[Dict[str, any]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute('SELECT * FROM chunks WHERE id = ?', (chunk_id,))
        row = cursor.fetchone()
        
        conn.close()
        return dict(row) if row else None
    
    # Mark embeddings as generated for a book
    def set_embeddings_generated(self, book_id: int, status: int = 1):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
            UPDATE books SET embeddings_generated = ? WHERE id = ?
        ''', (status, book_id))
        
        conn.commit()
        conn.close()
    
    # Get embeddings status for a book
    def get_embeddings_status(self, book_id: int) -> bool:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('SELECT embeddings_generated FROM books WHERE id = ?', (book_id,))
        row = cursor.fetchone()
        
        conn.close()
        return bool(row[0]) if row else False
    
    # Delete a book and all its chunks
    def delete_book(self, book_id: int):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('DELETE FROM books WHERE id = ?', (book_id,))
        
        conn.commit()
        conn.close()

    # Add a new framework for a book
    def add_framework(
        self,
        book_id: int,
        name: str,
        content: str,
        audit_result: Optional[Dict[str, Any]] = None,
        generation_status: Optional[str] = None,
    ) -> int:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        audit_json = json.dumps(audit_result) if audit_result is not None else None
        cursor.execute(
            '''
            INSERT INTO frameworks (book_id, name, content, created_at, updated_at, audit_result, generation_status)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''',
            (book_id, name, content, now, now, audit_json, generation_status),
        )
        framework_id = cursor.lastrowid
        conn.commit()
        conn.close()
        return framework_id

    def mark_framework_generation_running(self, framework_id: int) -> None:
        """Mark job running and record start time (clears prior finish/error/progress)."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute(
            '''
            UPDATE frameworks
            SET generation_status = 'running',
                generation_started_at = ?,
                generation_finished_at = NULL,
                generation_error = NULL,
                generation_last_log_line = 'Starting framework generation…',
                updated_at = ?
            WHERE id = ?
            ''',
            (now, now, framework_id),
        )
        conn.commit()
        conn.close()

    def set_framework_generation_progress(self, framework_id: int, message: str) -> None:
        """Persist latest human-readable progress for polling clients."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        line = (message or "").strip() or "Working…"
        cursor.execute(
            '''
            UPDATE frameworks
            SET generation_last_log_line = ?, updated_at = ?
            WHERE id = ?
            ''',
            (line, now, framework_id),
        )
        conn.commit()
        conn.close()

    def mark_framework_generation_completed(self, framework_id: int) -> None:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute(
            '''
            UPDATE frameworks
            SET generation_status = 'completed',
                generation_finished_at = ?,
                generation_error = NULL,
                generation_last_log_line = 'Framework generation completed.',
                updated_at = ?
            WHERE id = ?
            ''',
            (now, now, framework_id),
        )
        conn.commit()
        conn.close()

    def mark_framework_generation_failed(self, framework_id: int, error: str) -> None:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        msg = (error or "Unknown error").strip()
        cursor.execute(
            '''
            UPDATE frameworks
            SET generation_status = 'failed',
                generation_finished_at = ?,
                generation_error = ?,
                generation_last_log_line = ?,
                updated_at = ?
            WHERE id = ?
            ''',
            (now, msg, f"Failed: {msg}", now, framework_id),
        )
        conn.commit()
        conn.close()

    # Get a framework by its ID (content is built from nodes when framework has nodes)
    def get_framework(self, framework_id: int) -> Optional[Dict[str, any]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM frameworks WHERE id = ?', (framework_id,))
        row = cursor.fetchone()
        conn.close()
        if row is None:
            return None
        out = dict(row)
        ar = out.get("audit_result")
        if ar and isinstance(ar, str):
            try:
                out["audit_result"] = json.loads(ar)
            except json.JSONDecodeError:
                out["audit_result"] = None
        mar = out.get("mechanical_audit_result")
        if mar and isinstance(mar, str):
            try:
                out["mechanical_audit_result"] = json.loads(mar)
            except json.JSONDecodeError:
                out["mechanical_audit_result"] = None
        opj = out.get("overview_prose_json")
        out["overview_prose"] = None
        if opj and isinstance(opj, str):
            try:
                parsed = json.loads(opj)
                out["overview_prose"] = parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                out["overview_prose"] = None
        nodes = self.get_framework_nodes(framework_id)
        edges = self.get_framework_edges(framework_id)
        out["nodes"] = nodes if nodes else []
        out["edges"] = edges if edges else []
        return out

    # List frameworks for a specific book
    def list_frameworks_for_book(self, book_id: int) -> List[Dict[str, any]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM frameworks
            WHERE book_id = ?
            ORDER BY created_at DESC
        ''', (book_id,))
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    # Update framework content (re-run extraction)
    def update_framework(
        self,
        framework_id: int,
        content: str,
        audit_result: Optional[Dict[str, Any]] = None,
        claimed_scope: Optional[str] = None,
        evidenced_scope: Optional[str] = None,
    ) -> None:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        audit_json = json.dumps(audit_result) if audit_result is not None else None

        cursor.execute(
            '''
            UPDATE frameworks
            SET content = ?, updated_at = ?, audit_result = ?,
                claimed_scope = ?, evidenced_scope = ?
            WHERE id = ?
            ''',
            (content, now, audit_json, claimed_scope, evidenced_scope, framework_id),
        )
        conn.commit()
        conn.close()

    def set_framework_overview_prose_json(self, framework_id: int, overview_prose_json: Optional[str]) -> None:
        """Persist structured Overview prose (Problem / Core Argument / Method / Document Structure) as JSON."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute(
            '''
            UPDATE frameworks
            SET overview_prose_json = ?, updated_at = ?
            WHERE id = ?
            ''',
            (overview_prose_json, now, framework_id),
        )
        conn.commit()
        conn.close()

    def set_framework_definitive_document(self, framework_id: int, definitive_document: Optional[str]) -> None:
        """Store the definitive fixed-structure markdown (canonical export/view body)."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        cursor.execute(
            '''
            UPDATE frameworks
            SET definitive_document = ?, updated_at = ?
            WHERE id = ?
            ''',
            (definitive_document, now, framework_id),
        )
        conn.commit()
        conn.close()

    def set_framework_mechanical_audit(self, framework_id: int, mechanical_audit: Optional[Dict[str, Any]]) -> None:
        """Store Phase 3 mechanical audit JSON (pass/fail + failures list)."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        now = datetime.now().isoformat()
        payload = json.dumps(mechanical_audit, ensure_ascii=False) if mechanical_audit is not None else None
        cursor.execute(
            '''
            UPDATE frameworks
            SET mechanical_audit_result = ?, updated_at = ?
            WHERE id = ?
            ''',
            (payload, now, framework_id),
        )
        conn.commit()
        conn.close()

    # Delete a framework by ID (and its nodes)
    def delete_framework(self, framework_id: int) -> None:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM framework_nodes WHERE framework_id = ?', (framework_id,))
        cursor.execute('DELETE FROM frameworks WHERE id = ?', (framework_id,))
        conn.commit()
        conn.close()

    # --- Framework nodes (structured mind map) ---

    def add_framework_nodes(
        self,
        framework_id: int,
        nodes: List[Dict[str, any]],
    ) -> None:
        """Add nodes for a framework. Each node: parent_index (int|None), sort_order, node_type, title, content, page_ref (str|None), depends_on_index (int|None)."""
        if not nodes:
            return
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM framework_nodes WHERE framework_id = ?', (framework_id,))
        # Pass 1: insert all nodes with parent_id=None, depends_on_node_id=None; collect index -> id
        index_to_id: Dict[int, int] = {}
        for i, n in enumerate(nodes):
            cursor.execute('''
                INSERT INTO framework_nodes (framework_id, parent_id, sort_order, node_type, title, content, page_ref, depends_on_node_id, context, epistemic_type, epistemic_note, definitive_fields)
                VALUES (?, NULL, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
            ''', (
                framework_id,
                n.get('sort_order', i),
                (n.get('node_type') or 'section'),
                n.get('title') or '',
                n.get('content') or '',
                n.get('page_ref'),
                n.get('context') or None,
                n.get('epistemic_type') or None,
                n.get('epistemic_note') or None,
                json.dumps(n.get('definitive_fields') or {}) if n.get('definitive_fields') is not None else None,
            ))
            index_to_id[i] = cursor.lastrowid
        # Pass 2: update parent_id and depends_on_node_id
        for i, n in enumerate(nodes):
            node_id = index_to_id[i]
            parent_index = n.get('parent_index')
            depends_index = n.get('depends_on_index')
            parent_id = index_to_id.get(parent_index) if parent_index is not None and parent_index in index_to_id else None
            depends_id = index_to_id.get(depends_index) if depends_index is not None and depends_index in index_to_id else None
            if parent_id is not None or depends_id is not None:
                cursor.execute(
                    'UPDATE framework_nodes SET parent_id = ?, depends_on_node_id = ? WHERE id = ?',
                    (parent_id, depends_id, node_id),
                )
        conn.commit()
        conn.close()

    def get_framework_nodes(self, framework_id: int) -> List[Dict[str, any]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            '''SELECT id, framework_id, parent_id, sort_order, node_type, title, content, page_ref, depends_on_node_id,
                      context, epistemic_type, epistemic_note, definitive_fields
               FROM framework_nodes WHERE framework_id = ? ORDER BY sort_order, id''',
            (framework_id,),
        )
        rows = cursor.fetchall()
        conn.close()
        out = []
        for r in rows:
            d = dict(r)
            df = d.get("definitive_fields")
            if df:
                try:
                    d["definitive_fields"] = json.loads(df)
                except Exception:
                    # Leave as raw text if parsing fails.
                    pass
            else:
                d["definitive_fields"] = None
            out.append(d)
        return out

    def delete_framework_nodes(self, framework_id: int) -> None:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM framework_nodes WHERE framework_id = ?', (framework_id,))
        conn.commit()
        conn.close()

    def update_framework_nodes_epistemic(
        self,
        framework_id: int,
        nodes: List[Dict[str, Any]],
    ) -> None:
        """Update epistemic_type and epistemic_note for each node by id. Nodes must have 'id' and optionally epistemic_type, epistemic_note."""
        if not nodes:
            return
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        for n in nodes:
            nid = n.get("id")
            if nid is None:
                continue
            epistemic_type = n.get("epistemic_type")
            epistemic_note = n.get("epistemic_note")
            cursor.execute(
                '''UPDATE framework_nodes SET epistemic_type = ?, epistemic_note = ?
                   WHERE id = ? AND framework_id = ?''',
                (epistemic_type or None, epistemic_note or None, nid, framework_id),
            )
        conn.commit()
        conn.close()

    def sync_framework_nodes_graph_fields(
        self,
        framework_id: int,
        nodes: List[Dict[str, Any]],
    ) -> None:
        """Persist depends_on_node_id and definitive_fields for each node (mechanical repair / graph fixes)."""
        if not nodes:
            return
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        for n in nodes:
            nid = n.get("id")
            if nid is None:
                continue
            dep = n.get("depends_on_node_id")
            df = n.get("definitive_fields")
            df_json = json.dumps(df, ensure_ascii=False) if isinstance(df, dict) else None
            cursor.execute(
                """
                UPDATE framework_nodes
                SET depends_on_node_id = ?, definitive_fields = ?
                WHERE id = ? AND framework_id = ?
                """,
                (dep, df_json, nid, framework_id),
            )
        conn.commit()
        conn.close()

    # --- Framework edges (mind map relationships) ---

    def add_framework_edges(
        self,
        framework_id: int,
        edges: List[Dict[str, Any]],
    ) -> None:
        """Replace edges for a framework with the provided list."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM framework_edges WHERE framework_id = ?', (framework_id,))
        if edges:
            for e in edges:
                cursor.execute(
                    '''
                    INSERT INTO framework_edges (framework_id, from_node_id, to_node_id, edge_type, why)
                    VALUES (?, ?, ?, ?, ?)
                    ''',
                    (
                        framework_id,
                        e.get("from_node_id"),
                        e.get("to_node_id"),
                        e.get("edge_type"),
                        e.get("why"),
                    ),
                )
        conn.commit()
        conn.close()

    def get_framework_edges(self, framework_id: int) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT id, framework_id, from_node_id, to_node_id, edge_type, why
            FROM framework_edges
            WHERE framework_id = ?
            ORDER BY id
            ''',
            (framework_id,),
        )
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def delete_framework_edges(self, framework_id: int) -> None:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute('DELETE FROM framework_edges WHERE framework_id = ?', (framework_id,))
        conn.commit()
        conn.close()

    # --- Chat (per-book conversations + messages) ---

    def create_chat_conversation(self, book_id: int, title: str = "") -> int:
        now = datetime.now().isoformat()
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO chat_conversations (book_id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (book_id, title or "New chat", now, now),
        )
        cid = int(cursor.lastrowid)
        conn.commit()
        conn.close()
        return cid

    def list_chat_conversations(self, book_id: int) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, book_id, title, created_at, updated_at
            FROM chat_conversations
            WHERE book_id = ?
            ORDER BY updated_at DESC
            """,
            (book_id,),
        )
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_chat_conversation(self, conversation_id: int) -> Optional[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, book_id, title, created_at, updated_at
            FROM chat_conversations
            WHERE id = ?
            """,
            (conversation_id,),
        )
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    def update_chat_conversation_title(self, conversation_id: int, title: str) -> None:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE chat_conversations SET title = ? WHERE id = ?",
            (title, conversation_id),
        )
        conn.commit()
        conn.close()

    def touch_chat_conversation(self, conversation_id: int) -> None:
        now = datetime.now().isoformat()
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE chat_conversations SET updated_at = ? WHERE id = ?",
            (now, conversation_id),
        )
        conn.commit()
        conn.close()

    def delete_chat_conversation(self, conversation_id: int) -> None:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM chat_conversations WHERE id = ?", (conversation_id,))
        conn.commit()
        conn.close()

    def add_chat_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
        used_chunks: Optional[List[Dict[str, Any]]] = None,
        status: Optional[str] = None,
    ) -> int:
        now = datetime.now().isoformat()
        chunks_json = json.dumps(used_chunks, ensure_ascii=False) if used_chunks else None
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO chat_messages (conversation_id, role, content, used_chunks_json, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (conversation_id, role, content, chunks_json, status, now),
        )
        mid = int(cursor.lastrowid)
        conn.commit()
        conn.close()
        self.touch_chat_conversation(conversation_id)
        return mid

    def list_chat_messages(self, conversation_id: int) -> List[Dict[str, Any]]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, conversation_id, role, content, used_chunks_json, status, created_at
            FROM chat_messages
            WHERE conversation_id = ?
            ORDER BY id ASC
            """,
            (conversation_id,),
        )
        rows = cursor.fetchall()
        conn.close()
        out: List[Dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            raw = d.get("used_chunks_json")
            if raw:
                try:
                    d["used_chunks"] = json.loads(raw)
                except json.JSONDecodeError:
                    d["used_chunks"] = []
            else:
                d["used_chunks"] = None
            d.pop("used_chunks_json", None)
            out.append(d)
        return out
