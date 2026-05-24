import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'queue.db')


def clear_queue(shop_id=None):
    if not os.path.exists(DB_PATH):
        print(f'Database not found at {DB_PATH}')
        return False

    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA foreign_keys=ON")

    if shop_id:
        count = db.execute("SELECT COUNT(*) FROM queue WHERE shop_id = ?", (shop_id,)).fetchone()[0]
        db.execute("DELETE FROM queue WHERE shop_id = ?", (shop_id,))
    else:
        count = db.execute("SELECT COUNT(*) FROM queue").fetchone()[0]
        db.execute("DELETE FROM queue")

    db.execute("UPDATE shops SET is_paused = 0, pause_reason = NULL, next_number = 1")

    db.commit()
    db.close()

    label = f'shop #{shop_id}' if shop_id else 'all shops'
    print(f'Queue cleared for {label}')
    print(f'  - {count} row(s) deleted')
    print(f'  - next_number reset to 1')
    print(f'  - Shop unpaused')
    return True


if __name__ == '__main__':
    import sys
    shop_id = int(sys.argv[1]) if len(sys.argv) > 1 else None
    clear_queue(shop_id)
