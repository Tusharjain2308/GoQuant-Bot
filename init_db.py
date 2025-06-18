# init_db.py ✅
from db.session import engine, Base
import models  # ← Force import so models register with Base

if __name__ == "__main__":
    print(f"Database file path: {engine.url}")
    print("🛠️ Creating tables in:", engine.url)
    Base.metadata.create_all(bind=engine)

    print("✅ Tables created successfully.")

    # Debug: Show registered tables
    print("Tables created:", Base.metadata.tables.keys())
