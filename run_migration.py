import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.absolute()))

from utils.db.db_pool import DatabasePool
from sqlalchemy import text

def run_migration():
    pool = DatabasePool()
    sql_file = Path("sql/11_add_user_accounts.sql")
    print(f"Running migration: {sql_file}")
    
    with open(sql_file, "r") as f:
        sql_content = f.read()
        
    with pool.get_session() as session:
        session.execute(text(sql_content))
        session.commit()
    print("Migration complete!")

if __name__ == "__main__":
    run_migration()
