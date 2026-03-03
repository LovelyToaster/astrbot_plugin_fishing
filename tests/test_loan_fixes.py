"""
借贷系统修复验证测试 — 完全自包含，不依赖 astrbot 框架
覆盖全部 7 个修复项
运行: python tests/test_loan_fixes.py
"""

import os
import sys
import sqlite3
import unittest
import threading
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import Optional, List

# ============================================================
# 1.  重现 & 验证 TIMESTAMP 列的崩溃 / 修复
# ============================================================

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_loan_fix_test.db")

def _create_db():
    """创建与 041_add_loan_system.py 完全一致的 TIMESTAMP 列测试表"""
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("PRAGMA foreign_keys = ON;")
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            nickname TEXT,
            coins INTEGER DEFAULT 0,
            max_coins INTEGER DEFAULT 0
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS loans (
            loan_id INTEGER PRIMARY KEY AUTOINCREMENT,
            lender_id TEXT NOT NULL,
            borrower_id TEXT NOT NULL,
            principal INTEGER NOT NULL,
            interest_rate REAL NOT NULL DEFAULT 0.05,
            borrowed_at TIMESTAMP NOT NULL,
            due_amount INTEGER NOT NULL,
            repaid_amount INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active',
            due_date TIMESTAMP,
            created_at TIMESTAMP NOT NULL,
            updated_at TIMESTAMP NOT NULL,
            FOREIGN KEY (lender_id) REFERENCES users(user_id),
            FOREIGN KEY (borrower_id) REFERENCES users(user_id)
        )
    """)
    for uid, nick, coins, mx in [
        ("user_a", "A", 10000, 50000),
        ("user_b", "B", 5000, 20000),
        ("SYSTEM", "Bank", 0, 0),
    ]:
        cur.execute("INSERT OR REPLACE INTO users VALUES (?,?,?,?)", (uid, nick, coins, mx))
    conn.commit()
    conn.close()


def _insert_raw_loan(borrowed_at, due_date, created_at, updated_at,
                     lender="SYSTEM", borrower="user_a", principal=1000,
                     due_amount=1050, status="active"):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO loans (lender_id, borrower_id, principal, interest_rate,
            borrowed_at, due_amount, repaid_amount, status,
            due_date, created_at, updated_at)
        VALUES (?,?,?,0.05,?,?,0,?,?,?,?)
    """, (lender, borrower, principal, borrowed_at, due_amount, status,
          due_date, created_at, updated_at))
    conn.commit()
    lid = cur.lastrowid
    conn.close()
    return lid


# ---------- 从 sqlite_loan_repo.py 中提取的 _parse_datetime ----------

def _parse_datetime(dt_val):
    """与代码中完全一致的解析器（复制自 sqlite_loan_repo.py）"""
    if dt_val is None:
        return None
    if isinstance(dt_val, datetime):
        return dt_val
    if isinstance(dt_val, (str, bytes)):
        val = dt_val.decode('utf-8') if isinstance(dt_val, bytes) else dt_val
        val = val.strip()
        if not val:
            return None
        val = val.replace('T', ' ')
        for fmt in (
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d",
        ):
            try:
                return datetime.strptime(val, fmt)
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(dt_val if isinstance(dt_val, str) else val)
        except (ValueError, TypeError):
            pass
    return None


# ============================================================

class Test01_OldCodeCrash(unittest.TestCase):
    """重现旧代码的崩溃：使用 detect_types 读取 TIMESTAMP 列"""

    def setUp(self):
        _create_db()

    def tearDown(self):
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)

    def test_detect_types_crashes_on_iso_T(self):
        """【重现】detect_types 遇到 ISO T 格式会 ValueError"""
        _insert_raw_loan("2026-03-01T10:00:00", None,
                         "2026-03-01T10:00:00", "2026-03-01T10:00:00")

        conn = sqlite3.connect(
            DB_PATH,
            detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES
        )
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM loans WHERE loan_id = 1")
        with self.assertRaises(ValueError) as ctx:
            cur.fetchone()
        self.assertIn("not enough values to unpack", str(ctx.exception))
        conn.close()
        print("  ✅ 重现旧崩溃: ValueError: not enough values to unpack")

    def test_no_detect_types_reads_fine(self):
        """【修复】去掉 detect_types 后正常读取"""
        _insert_raw_loan("2026-03-01T10:00:00", "2026-03-08T14:30:00.123",
                         "2026-03-01T10:00:00", "2026-03-01T10:00:00")

        conn = sqlite3.connect(DB_PATH)          # ← 不传 detect_types
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM loans WHERE loan_id = 1")
        row = cur.fetchone()                      # ← 不再崩溃
        self.assertIsNotNone(row)

        # 手动解析
        dt = _parse_datetime(row["borrowed_at"])
        self.assertIsInstance(dt, datetime)
        self.assertEqual(dt.year, 2026)

        dt2 = _parse_datetime(row["due_date"])
        self.assertIsInstance(dt2, datetime)
        conn.close()
        print(f"  ✅ 去掉 detect_types 手动解析: borrowed_at={dt}")


class Test02_ParseDatetime(unittest.TestCase):
    """测试 _parse_datetime 对各种格式的兼容性"""

    def test_standard_space(self):
        self.assertEqual(
            _parse_datetime("2026-03-01 10:00:00"),
            datetime(2026, 3, 1, 10, 0, 0)
        )
        print("  ✅ 空格分隔格式")

    def test_iso_T(self):
        self.assertEqual(
            _parse_datetime("2026-03-01T10:00:00"),
            datetime(2026, 3, 1, 10, 0, 0)
        )
        print("  ✅ ISO T 格式")

    def test_microseconds(self):
        result = _parse_datetime("2026-03-01 10:00:00.123456")
        self.assertEqual(result.microsecond, 123456)
        print("  ✅ 带微秒")

    def test_date_only(self):
        self.assertEqual(
            _parse_datetime("2026-03-01"),
            datetime(2026, 3, 1, 0, 0, 0)
        )
        print("  ✅ 纯日期")

    def test_none(self):
        self.assertIsNone(_parse_datetime(None))
        print("  ✅ None")

    def test_bytes(self):
        result = _parse_datetime(b"2026-03-01 10:00:00")
        self.assertIsInstance(result, datetime)
        print("  ✅ bytes 输入")

    def test_bytes_iso_T(self):
        result = _parse_datetime(b"2026-03-01T10:00:00")
        self.assertIsInstance(result, datetime)
        print("  ✅ bytes ISO T 输入")


class Test03_MixedFormatFetchAll(unittest.TestCase):
    """fetchall 批量读取混合格式不崩溃"""

    def setUp(self):
        _create_db()
        _insert_raw_loan("2026-03-01 10:00:00", "2026-03-08 10:00:00",
                         "2026-03-01 10:00:00", "2026-03-01 10:00:00")
        _insert_raw_loan("2026-03-02T14:30:00", "2026-03-09T14:30:00",
                         "2026-03-02T14:30:00", "2026-03-02T14:30:00")
        _insert_raw_loan("2026-03-03 08:00:00.999", None,
                         "2026-03-03 08:00:00", "2026-03-03 08:00:00")
        _insert_raw_loan("2026-03-04", None,
                         "2026-03-04", "2026-03-04")

    def tearDown(self):
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)

    def test_fetchall_no_crash(self):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM loans WHERE borrower_id = 'user_a'")
        rows = cur.fetchall()
        self.assertEqual(len(rows), 4)
        for r in rows:
            dt = _parse_datetime(r["borrowed_at"])
            self.assertIsInstance(dt, datetime, f"failed: {r['borrowed_at']!r}")
        conn.close()
        print(f"  ✅ 混合格式 fetchall: 4/4 全部成功")


# ============================================================
# 2. 验证源码中的 SQL / 事务模式（静态分析）
# ============================================================

class Test04_SourceCodePatterns(unittest.TestCase):
    """静态检查源码中的修复模式"""

    @classmethod
    def setUpClass(cls):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        loan_repo_path = os.path.join(root, "core", "repositories", "sqlite_loan_repo.py")
        loan_svc_path = os.path.join(root, "core", "services", "loan_service.py")
        with open(loan_repo_path, encoding="utf-8") as f:
            cls.repo_src = f.read()
        with open(loan_svc_path, encoding="utf-8") as f:
            cls.svc_src = f.read()

    def test_no_detect_types_in_loan_repo(self):
        """修复#1: sqlite_loan_repo 不再在 connect() 中使用 detect_types"""
        # connect 调用不应包含 detect_types（注释中出现是合理的）
        self.assertNotIn("sqlite3.PARSE_DECLTYPES", self.repo_src)
        self.assertNotIn("sqlite3.PARSE_COLNAMES", self.repo_src)
        # 确认 connect 不传 detect_types
        self.assertIn("conn = sqlite3.connect(self.db_path)", self.repo_src)
        print("  ✅ loan_repo connect 无 detect_types")

    def test_parse_datetime_handles_bytes(self):
        """修复#1: _parse_datetime 兼容 bytes 输入"""
        self.assertIn("isinstance(dt_val, (str, bytes))", self.repo_src)
        self.assertIn("decode('utf-8')", self.repo_src)
        print("  ✅ _parse_datetime 处理 bytes")

    def test_parse_datetime_handles_T_separator(self):
        """修复#1: _parse_datetime 处理 ISO T 分隔符"""
        self.assertIn("replace('T', ' ')", self.repo_src)
        print("  ✅ _parse_datetime 处理 T 分隔符")

    def test_atomic_update_coins_uses_cursor(self):
        """修复#2: _atomic_update_coins 接受 cursor 参数"""
        self.assertIn("def _atomic_update_coins(self, cursor,", self.svc_src)
        self.assertIn("MAX(0, coins + ?)", self.svc_src)
        print("  ✅ _atomic_update_coins 原子 SQL")

    def test_force_collect_in_transaction(self):
        """修复#3: force_collect 在事务中执行"""
        idx = self.svc_src.index("def force_collect(")
        # 取到下一个 def 或文件末尾
        next_def = self.svc_src.find("\n    def ", idx + 10)
        block = self.svc_src[idx:next_def] if next_def != -1 else self.svc_src[idx:]
        self.assertIn("with self.user_repo._get_connection() as conn:", block)
        self.assertIn("cursor = conn.cursor()", block)
        # 原子扣减/增加在同一事务
        self.assertIn("coins - ?)", block)
        self.assertIn("coins + ?", block)
        print("  ✅ force_collect 事务封装")

    def test_borrow_from_system_in_transaction(self):
        """修复#4: borrow_from_system 在事务中同时发钱+记账"""
        idx = self.svc_src.index("def borrow_from_system(")
        block = self.svc_src[idx:idx + 3000]
        self.assertIn("with self.user_repo._get_connection() as conn:", block)
        self.assertIn("INSERT INTO loans", block)
        self.assertIn("_atomic_update_coins", block)
        print("  ✅ borrow_from_system 事务封装")

    def test_overdue_loans_visible_in_queries(self):
        """修复#5: 汇总/列表/总债务都查询 overdue 状态"""
        self.assertIn("def _get_active_and_overdue_loans(", self.svc_src)
        # get_user_loans_summary 使用新方法
        idx = self.svc_src.index("def get_user_loans_summary(")
        block = self.svc_src[idx:idx + 600]
        self.assertIn("_get_active_and_overdue_loans", block)
        # get_total_debt 使用新方法
        idx = self.svc_src.index("def get_total_debt(")
        block = self.svc_src[idx:idx + 300]
        self.assertIn("_get_active_and_overdue_loans", block)
        print("  ✅ 逾期借条查询可见")

    def test_repay_all_uses_atomic_deduction(self):
        """修复#6: repay_all 使用原子扣减而非绝对覆盖"""
        idx = self.svc_src.index("def repay_all_loans(")
        next_def = self.svc_src.find("\n    def ", idx + 10)
        block = self.svc_src[idx:next_def] if next_def != -1 else self.svc_src[idx:]
        self.assertIn("coins - ?)", block)
        # 不应存在 "SET coins = ?" 的绝对覆盖
        self.assertNotIn("SET coins = ?", block)
        print("  ✅ repay_all 原子扣减")

    def test_get_total_debt_no_write(self):
        """修复#7: get_total_debt 是只读方法，不触发状态更新"""
        idx = self.svc_src.index("def get_total_debt(")
        block = self.svc_src[idx:idx + 300]
        self.assertNotIn("update_loan_repayment", block)
        self.assertNotIn("UPDATE", block)
        print("  ✅ get_total_debt 无写副作用")


# ============================================================
# 3. 功能集成测试（使用真实 SQLite 事务）
# ============================================================

class Test05_TransactionAtomicity(unittest.TestCase):
    """验证事务在异常中正确回滚"""

    def setUp(self):
        _create_db()

    def tearDown(self):
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)

    def test_with_conn_rolls_back_on_error(self):
        """with conn: 块内出错时自动回滚"""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row

        initial_coins = conn.execute("SELECT coins FROM users WHERE user_id='user_a'").fetchone()[0]

        try:
            with conn:
                cur = conn.cursor()
                cur.execute("UPDATE users SET coins = coins + 999 WHERE user_id = 'user_a'")
                raise RuntimeError("模拟崩溃")
        except RuntimeError:
            pass

        after_coins = conn.execute("SELECT coins FROM users WHERE user_id='user_a'").fetchone()[0]
        self.assertEqual(initial_coins, after_coins, "事务应回滚")
        conn.close()
        print(f"  ✅ 事务回滚: {initial_coins} → (error) → {after_coins}")

    def test_atomic_coin_update_sql(self):
        """验证 MAX(0, coins + ?) 的 SQL 语义正确"""
        conn = sqlite3.connect(DB_PATH)

        # user_b 有 5000，扣 8000 应得 0 而非 -3000
        conn.execute("UPDATE users SET coins = MAX(0, coins + ?) WHERE user_id = ?", (-8000, "user_b"))
        conn.commit()
        row = conn.execute("SELECT coins FROM users WHERE user_id='user_b'").fetchone()
        self.assertEqual(row[0], 0)
        print("  ✅ MAX(0, coins + -8000) 下限保护: 0")

        # user_a 有 10000，加 5000
        conn.execute("UPDATE users SET coins = MAX(0, coins + ?) WHERE user_id = ?", (5000, "user_a"))
        conn.commit()
        row = conn.execute("SELECT coins FROM users WHERE user_id='user_a'").fetchone()
        self.assertEqual(row[0], 15000)
        print("  ✅ MAX(0, coins + 5000) = 15000")
        conn.close()


class Test06_OverdueVisibility(unittest.TestCase):
    """逾期借条在聚合查询中可见"""

    def setUp(self):
        _create_db()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        past = (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S")
        due_overdue = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")
        due_future = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")

        # 1 笔 active, 1 笔 overdue
        _insert_raw_loan(now, due_future, now, now,
                         lender="SYSTEM", borrower="user_a",
                         principal=1000, due_amount=1050, status="active")
        _insert_raw_loan(past, due_overdue, past, now,
                         lender="SYSTEM", borrower="user_a",
                         principal=2000, due_amount=2100, status="overdue")

    def tearDown(self):
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)

    def test_both_statuses_queried(self):
        """同时查询 active + overdue"""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM loans
            WHERE borrower_id = ? AND status IN ('active', 'overdue')
        """, ("user_a",))
        rows = cur.fetchall()
        self.assertEqual(len(rows), 2)
        statuses = {r["status"] for r in rows}
        self.assertEqual(statuses, {"active", "overdue"})
        conn.close()
        print(f"  ✅ 查到 active + overdue: {len(rows)} 笔")

    def test_total_debt_both(self):
        """总债务 = active + overdue"""
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT SUM(due_amount - repaid_amount) as total
            FROM loans
            WHERE borrower_id = ? AND status IN ('active', 'overdue')
        """, ("user_a",))
        total = cur.fetchone()["total"]
        self.assertEqual(total, 1050 + 2100)
        conn.close()
        print(f"  ✅ 总债务 = {total} (active 1050 + overdue 2100)")


class Test07_RepayAtomicDeduction(unittest.TestCase):
    """还款使用原子扣减"""

    def setUp(self):
        _create_db()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        due = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
        _insert_raw_loan(now, due, now, now,
                         lender="SYSTEM", borrower="user_a",
                         principal=2000, due_amount=2100, status="active")

    def tearDown(self):
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)

    def test_relative_vs_absolute_update(self):
        """原子扣减 vs 绝对覆盖的区别"""
        conn = sqlite3.connect(DB_PATH)

        # 模拟并发：先读初始值
        initial = conn.execute("SELECT coins FROM users WHERE user_id='user_a'").fetchone()[0]
        self.assertEqual(initial, 10000)

        # 模拟另一个事务增加了 500 金币
        conn.execute("UPDATE users SET coins = coins + 500 WHERE user_id='user_a'")
        conn.commit()

        # 还款 2100：用原子扣减
        conn.execute("UPDATE users SET coins = MAX(0, coins - ?) WHERE user_id = ?", (2100, "user_a"))
        conn.commit()

        final = conn.execute("SELECT coins FROM users WHERE user_id='user_a'").fetchone()[0]
        # 应为 10000 + 500 - 2100 = 8400
        self.assertEqual(final, 8400)
        print(f"  ✅ 原子扣减: 10000 + 500(并发) - 2100 = {final}")

        conn.close()


# ============================================================

if __name__ == "__main__":
    print("=" * 60)
    print("  借贷系统修复验证测试（自包含，无框架依赖）")
    print("=" * 60)
    unittest.main(verbosity=2)
