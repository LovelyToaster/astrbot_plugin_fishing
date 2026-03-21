"""
银行系统数据仓储层
"""

import sqlite3
import threading
from datetime import datetime
from typing import Optional, List

from astrbot.api import logger

from ..domain.bank_models import BankAccount, DepositRecord, DepositType


class SqliteBankRepository:
    """银行数据仓储的 SQLite 实现"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._local = threading.local()
        self._init_tables()

    def _get_connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "connection", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON;")
            self._local.connection = conn
        return conn

    def _init_tables(self):
        """初始化数据库表"""
        conn = self._get_connection()
        cursor = conn.cursor()

        # 创建银行账户表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS bank_accounts (
                user_id TEXT PRIMARY KEY,
                current_balance INTEGER DEFAULT 0,
                fixed_balance INTEGER DEFAULT 0,
                total_interest INTEGER DEFAULT 0,
                last_interest_date TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # 创建存款记录表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS deposit_records (
                record_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                deposit_type TEXT NOT NULL,
                amount INTEGER NOT NULL,
                interest_rate REAL NOT NULL,
                term_days INTEGER,
                start_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                end_date TIMESTAMP,
                interest_earned INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES bank_accounts(user_id)
            )
        """)

        # 检查是否需要添加 last_interest_date 列（迁移）
        cursor.execute("PRAGMA table_info(bank_accounts)")
        columns = [col[1] for col in cursor.fetchall()]
        if "last_interest_date" not in columns:
            logger.info("添加 last_interest_date 列到 bank_accounts 表")
            cursor.execute("""
                ALTER TABLE bank_accounts
                ADD COLUMN last_interest_date TIMESTAMP
            """)
            conn.commit()

        conn.commit()

    def _row_to_account(self, row: sqlite3.Row) -> Optional[BankAccount]:
        """将数据库行转换为 BankAccount 对象"""
        if not row:
            return None

        return BankAccount(
            user_id=row["user_id"],
            current_balance=row["current_balance"],
            fixed_balance=row["fixed_balance"],
            total_interest=row["total_interest"],
            last_interest_date=self._parse_datetime(row["last_interest_date"]),
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"])
        )

    def _row_to_deposit_record(self, row: sqlite3.Row) -> Optional[DepositRecord]:
        """将数据库行转换为 DepositRecord 对象"""
        if not row:
            return None

        return DepositRecord(
            record_id=row["record_id"],
            user_id=row["user_id"],
            deposit_type=DepositType(row["deposit_type"]),
            amount=row["amount"],
            interest_rate=row["interest_rate"],
            term_days=row["term_days"],
            start_date=self._parse_datetime(row["start_date"]),
            end_date=self._parse_datetime(row["end_date"]),
            interest_earned=row["interest_earned"],
            status=row["status"],
            created_at=self._parse_datetime(row["created_at"]),
            updated_at=self._parse_datetime(row["updated_at"])
        )

    def _parse_datetime(self, dt_val):
        """安全解析日期时间，兼容所有常见格式，始终返回 naive datetime"""
        if dt_val is None:
            return None
        if isinstance(dt_val, datetime):
            # 如果是时区感知的，移除时区信息（直接丢弃时区）
            if dt_val.tzinfo is not None:
                return dt_val.replace(tzinfo=None)
            return dt_val
        if isinstance(dt_val, (str, bytes)):
            val = dt_val.decode('utf-8') if isinstance(dt_val, bytes) else dt_val
            val = val.strip()
            if not val:
                return None
            # 统一分隔符：ISO 8601 的 T → 空格
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
            # 最后尝试 fromisoformat（兼容带时区的格式）
            try:
                dt = datetime.fromisoformat(dt_val if isinstance(dt_val, str) else val)
                # 如果有时区信息，直接移除
                if dt.tzinfo is not None:
                    return dt.replace(tzinfo=None)
                return dt
            except (ValueError, TypeError):
                pass
            logger.warning(f"无法解析日期时间值：{dt_val!r}")
        return None

    def get_account(self, user_id: str) -> Optional[BankAccount]:
        """获取用户银行账户"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM bank_accounts WHERE user_id = ?", (user_id,))
        row = cursor.fetchone()
        return self._row_to_account(row)

    def create_account(self, user_id: str) -> BankAccount:
        """创建银行账户"""
        conn = self._get_connection()
        cursor = conn.cursor()
        now = datetime.now()
        cursor.execute("""
            INSERT INTO bank_accounts (
                user_id, current_balance, fixed_balance, total_interest,
                last_interest_date, created_at, updated_at
            ) VALUES (?, 0, 0, 0, ?, ?, ?)
        """, (user_id, now, now, now))
        conn.commit()
        return BankAccount(
            user_id=user_id,
            current_balance=0,
            fixed_balance=0,
            total_interest=0,
            last_interest_date=now,
            created_at=now,
            updated_at=now
        )

    def update_account(self, account: BankAccount) -> bool:
        """更新银行账户"""
        conn = self._get_connection()
        cursor = conn.cursor()
        now = datetime.now()
        cursor.execute("""
            UPDATE bank_accounts
            SET current_balance = ?, fixed_balance = ?, total_interest = ?,
                last_interest_date = ?, updated_at = ?
            WHERE user_id = ?
        """, (
            account.current_balance,
            account.fixed_balance,
            account.total_interest,
            account.last_interest_date,
            now,
            account.user_id
        ))
        conn.commit()
        return cursor.rowcount > 0

    def create_deposit_record(self, record: DepositRecord) -> int:
        """创建存款记录"""
        conn = self._get_connection()
        cursor = conn.cursor()
        now = datetime.now()
        cursor.execute("""
            INSERT INTO deposit_records (
                user_id, deposit_type, amount, interest_rate, term_days,
                start_date, end_date, interest_earned, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.user_id, record.deposit_type.value, record.amount, record.interest_rate,
            record.term_days, record.start_date or now, record.end_date, record.interest_earned,
            record.status, now, now
        ))
        conn.commit()
        return cursor.lastrowid

    def get_deposit_record(self, record_id: int) -> Optional[DepositRecord]:
        """根据 ID 获取存款记录"""
        conn = self._get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM deposit_records WHERE record_id = ?", (record_id,))
        row = cursor.fetchone()
        return self._row_to_deposit_record(row)

    def get_deposit_records_by_user(
        self,
        user_id: str,
        deposit_type: Optional[DepositType] = None,
        status: Optional[str] = None
    ) -> List[DepositRecord]:
        """获取用户的存款记录"""
        conn = self._get_connection()
        cursor = conn.cursor()

        query = "SELECT * FROM deposit_records WHERE user_id = ?"
        params = [user_id]

        if deposit_type:
            query += " AND deposit_type = ?"
            params.append(deposit_type.value)

        if status:
            query += " AND status = ?"
            params.append(status)

        query += " ORDER BY created_at DESC"

        cursor.execute(query, params)
        return [self._row_to_deposit_record(row) for row in cursor.fetchall()]

    def update_deposit_record(self, record: DepositRecord) -> bool:
        """更新存款记录"""
        conn = self._get_connection()
        cursor = conn.cursor()
        now = datetime.now()
        cursor.execute("""
            UPDATE deposit_records
            SET interest_earned = ?, status = ?, updated_at = ?
            WHERE record_id = ?
        """, (record.interest_earned, record.status, now, record.record_id))
        conn.commit()
        return cursor.rowcount > 0
