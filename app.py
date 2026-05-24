import os
import sqlite3
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, g, session, send_from_directory
from sympy import true
from database import get_db, close_db, init_db
from routes.admin import admin_bp


def validate_string(value, field_name, min_len=1, max_len=None):
    if not isinstance(value, str):
        return f'{field_name} must be text'
    stripped = value.strip()
    if len(stripped) < min_len:
        return f'{field_name} must be at least {min_len} character{"s" if min_len > 1 else ""}'
    if max_len and len(stripped) > max_len:
        return f'{field_name} must not exceed {max_len} characters'
    return None


def validate_int(value, field_name, min_val=None, max_val=None):
    if not isinstance(value, int) or isinstance(value, bool):
        return f'{field_name} must be a number'
    if min_val is not None and value < min_val:
        return f'{field_name} must be at least {min_val}'
    if max_val is not None and value > max_val:
        return f'{field_name} must not exceed {max_val}'
    return None


def require_admin(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        admin_id = session.get('admin_id')
        if not admin_id:
            return jsonify({'error': 'Authentication required'}), 401
        db = get_db()
        admin = db.execute("SELECT * FROM admins WHERE id = ?", (admin_id,)).fetchone()
        if not admin:
            session.clear()
            return jsonify({'error': 'Admin not found'}), 401
        g.admin = admin
        return f(*args, **kwargs)
    return decorated


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CLIENT_DIR = os.path.join(BASE_DIR, 'client')

app = Flask(__name__)

# Sessions: signed cookie config
app.secret_key = os.environ.get('FLASK_SECRET_KEY', os.urandom(24).hex())
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=True,  # Set to True in production with HTTPS
    SESSION_PERMANENT=True,
    PERMANENT_SESSION_LIFETIME=timedelta(days=7),
)

# CORS: Trusted frontend origins.
# No wildcards — credentials (session cookies) require exact origin matching.
# In production, only the HTTPS frontend URL from env is allowed.
DEV_FRONTENDS = {'http://localhost:5173', 'http://127.0.0.1:5173'}
PROD_FRONTEND = os.environ.get('FRONTEND_URL', '').rstrip('/')
TRUSTED_ORIGINS = DEV_FRONTENDS | ({PROD_FRONTEND} if PROD_FRONTEND else set())

app.teardown_appcontext(close_db)
app.register_blueprint(admin_bp)


# CORS + security headers.
# Manual CORS (no library) — origins are strictly validated so session cookies
# (which require `Access-Control-Allow-Credentials: true`) are never sent to
# untrusted domains. A wildcard `*` is never used because it is incompatible
# with credentialed requests and would allow any site to read the response.
@app.after_request
def add_cors_and_security_headers(response):
    origin = request.headers.get('Origin')
    if origin in TRUSTED_ORIGINS:
        response.headers['Access-Control-Allow-Origin'] = origin
        response.headers['Access-Control-Allow-Credentials'] = 'true'
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    response.headers['Access-Control-Max-Age'] = '3600'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    return response


def recalc_positions(shop_id):
    db = get_db()
    rows = db.execute(
        "SELECT id FROM queue WHERE shop_id = ? AND status IN ('waiting', 'current') ORDER BY position",
        (shop_id,)
    ).fetchall()
    for idx, row in enumerate(rows):
        new_pos = idx + 1
        db.execute("UPDATE queue SET position = ? WHERE id = ?", (new_pos, row['id']))
        if idx == 0:
            db.execute("UPDATE queue SET status = 'current' WHERE id = ? AND status = 'waiting'", (row['id'],))
    db.commit()


@app.route('/api/join', methods=['POST'])
def join_queue():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Request body is required'}), 400
    name = data.get('customer_name', '').strip()
    shop_id = data.get('shop_id', 1)

    err = validate_string(name, 'customer_name', max_len=50)
    if err:
        return jsonify({'error': err}), 400

    db = get_db()
    shop = db.execute("SELECT * FROM shops WHERE id = ?", (shop_id,)).fetchone()
    if not shop:
        return jsonify({'error': 'Shop not found'}), 404
    if not shop['is_open']:
        return jsonify({'error': 'Shop is closed'}), 400

    new_number = shop['next_number']
    db.execute("UPDATE shops SET next_number = next_number + 1 WHERE id = ?", (shop_id,))

    row = db.execute(
        "SELECT COALESCE(MAX(position), 0) as max_pos FROM queue WHERE shop_id = ? AND status IN ('waiting', 'current')",
        (shop_id,)
    ).fetchone()
    new_pos = row['max_pos'] + 1

    cur = db.execute(
        "INSERT INTO queue (shop_id, customer_name, queue_number, position, status) VALUES (?, ?, ?, ?, 'waiting')",
        (shop_id, name, new_number, new_pos)
    )
    db.commit()
    recalc_positions(shop_id)

    entry = db.execute("SELECT * FROM queue WHERE id = ?", (cur.lastrowid,)).fetchone()

    return jsonify({
        'id': entry['id'],
        'queue_number': entry['queue_number'],
        'position': entry['position'],
        'customer_name': entry['customer_name'],
        'status': entry['status']
    }), 201


@app.route('/api/queue', methods=['GET'])
def get_queue():
    # Public: anyone can view queue status
    shop_id = request.args.get('shop_id', 1, type=int)
    customer_id = request.args.get('customer_id', None, type=int)

    db = get_db()
    shop = db.execute("SELECT * FROM shops WHERE id = ?", (shop_id,)).fetchone()
    if not shop:
        return jsonify({'error': 'Shop not found'}), 404

    active = db.execute(
        "SELECT * FROM queue WHERE shop_id = ? AND status IN ('waiting', 'current') ORDER BY position",
        (shop_id,)
    ).fetchall()

    now = datetime.utcnow()

    queue_list = []
    wait_time = 0
    current_entry = None

    for i, e in enumerate(active):
        entry = {
            'id': e['id'],
            'queue_number': e['queue_number'],
            'customer_name': e['customer_name'],
            'position': e['position'],
            'status': e['status'],
            'estimated_wait_minutes': None,
            'created_at': e['created_at']
        }
        if e['status'] == 'current':
            current_entry = entry
            created = datetime.strptime(e['created_at'], '%Y-%m-%d %H:%M:%S')
            elapsed = (now - created).total_seconds() / 60
            avg = shop['avg_haircut_minutes']
            wait_time = max(0, avg - elapsed if elapsed < avg else 2)
            entry['estimated_wait_minutes'] = round(wait_time, 1)
        queue_list.append(entry)

    for entry in queue_list:
        if entry['status'] == 'waiting':
            est = wait_time + (entry['position'] - 1) * shop['avg_haircut_minutes']
            entry['estimated_wait_minutes'] = round(est, 1)

    customer_data = None
    if customer_id:
        entry = db.execute(
            "SELECT * FROM queue WHERE id = ? AND shop_id = ?",
            (customer_id, shop_id)
        ).fetchone()
        if entry:
            customer_data = {
                'id': entry['id'],
                'queue_number': entry['queue_number'],
                'customer_name': entry['customer_name'],
                'position': entry['position'],
                'status': entry['status'],
                'estimated_wait_minutes': None
            }
            if entry['status'] in ('waiting', 'current'):
                est = 0
                if entry['position'] > 1:
                    est = wait_time + (entry['position'] - 1) * shop['avg_haircut_minutes']
                elif entry['position'] == 1:
                    est = max(0, wait_time)
                customer_data['estimated_wait_minutes'] = round(est, 1)

    today_q = db.execute(
        "SELECT status, COUNT(*) as cnt FROM queue WHERE shop_id = ? AND DATE(created_at) = DATE('now') GROUP BY status",
        (shop_id,)
    ).fetchall()
    today_stats = {r['status']: r['cnt'] for r in today_q}

    return jsonify({
        'shop': {
            'id': shop['id'],
            'name': shop['name'],
            'is_open': bool(shop['is_open']),
            'is_paused': bool(shop['is_paused']),
            'pause_reason': shop['pause_reason'],
            'avg_haircut_minutes': shop['avg_haircut_minutes'],
            'instagram': shop['instagram'],
            'facebook': shop['facebook'],
            'youtube': shop['youtube'],
            'whatsapp': shop['whatsapp'],
            'phone': shop['phone'],
            'location': shop['location'],
            'working_hours': shop['working_hours'],
            'hero_title': shop['hero_title'],
            'hero_desc': shop['hero_desc']
        },
        'queue': queue_list,
        'current_customer': queue_list[0] if queue_list and queue_list[0]['status'] == 'current' else None,
        'waiting_count': len([e for e in active if e['status'] == 'waiting']),
        'stats': {
            'completed_today': today_stats.get('completed', 0),
            'skipped_today': today_stats.get('skipped', 0),
            'total_served_today': today_stats.get('completed', 0) + today_stats.get('skipped', 0),
            'currently_waiting': len([e for e in active if e['status'] == 'waiting']),
            'avg_wait_time': shop['avg_haircut_minutes']
        },
        'customer': customer_data
    })


# Admin: modifies queue state by marking current as completed
@app.route('/api/finish', methods=['POST'])
@require_admin
def finish_customer():
    data = request.get_json()
    shop_id = data.get('shop_id', 1)

    db = get_db()
    current = db.execute(
        "SELECT * FROM queue WHERE shop_id = ? AND status = 'current' LIMIT 1",
        (shop_id,)
    ).fetchone()

    if not current:
        return jsonify({'error': 'No current customer to finish'}), 400

    db.execute("UPDATE queue SET status = 'completed' WHERE id = ?", (current['id'],))
    db.commit()
    recalc_positions(shop_id)

    return jsonify({'message': 'Customer finished', 'customer': current['customer_name']})


# Admin: skips current or a specific customer
@app.route('/api/skip', methods=['POST'])
@require_admin
def skip_customer():
    data = request.get_json()
    shop_id = data.get('shop_id', 1)
    entry_id = data.get('entry_id', None)

    db = get_db()

    if entry_id:
        entry = db.execute("SELECT * FROM queue WHERE id = ? AND shop_id = ?", (entry_id, shop_id)).fetchone()
        if not entry:
            return jsonify({'error': 'Entry not found'}), 404
        if entry['status'] not in ('waiting', 'current'):
            return jsonify({'error': 'Cannot skip this entry'}), 400
        db.execute("UPDATE queue SET status = 'skipped' WHERE id = ?", (entry_id,))
    else:
        current = db.execute(
            "SELECT * FROM queue WHERE shop_id = ? AND status = 'current' LIMIT 1",
            (shop_id,)
        ).fetchone()
        if not current:
            return jsonify({'error': 'No customer to skip'}), 400
        db.execute("UPDATE queue SET status = 'skipped' WHERE id = ?", (current['id'],))

    db.commit()
    recalc_positions(shop_id)
    return jsonify({'message': 'Customer skipped'})


@app.route('/api/leave', methods=['POST'])
def leave_queue():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Request body is required'}), 400
    entry_id = data.get('entry_id')
    shop_id = data.get('shop_id', 1)

    if not entry_id:
        return jsonify({'error': 'Entry ID is required'}), 400
    if not isinstance(entry_id, int) or entry_id < 1:
        return jsonify({'error': 'Invalid entry ID'}), 400

    db = get_db()
    entry = db.execute("SELECT * FROM queue WHERE id = ? AND shop_id = ?", (entry_id, shop_id)).fetchone()
    if not entry:
        return jsonify({'error': 'Entry not found'}), 404
    if entry['status'] == 'left':
        return jsonify({'error': 'Already left'}), 400

    db.execute("UPDATE queue SET status = 'left' WHERE id = ?", (entry_id,))
    db.commit()
    recalc_positions(shop_id)
    return jsonify({'message': 'Successfully left the queue'})


# Admin: resets entire queue and shop numbers
@app.route('/api/reset', methods=['POST'])
@require_admin
def reset_queue():
    data = request.get_json()
    shop_id = data.get('shop_id', 1)

    db = get_db()
    db.execute(
        "UPDATE queue SET status = 'left' WHERE shop_id = ? AND status IN ('waiting', 'current')",
        (shop_id,)
    )
    db.execute("UPDATE shops SET is_paused = 0, pause_reason = NULL, next_number = 1 WHERE id = ?", (shop_id,))
    db.commit()

    return jsonify({'message': 'Queue reset successfully. New customers start from #1.'})


# Admin: pauses queue with a reason
@app.route('/api/pause', methods=['POST'])
@require_admin
def pause_queue():
    data = request.get_json()
    shop_id = data.get('shop_id', 1)
    reason = data.get('reason', 'break')

    valid_reasons = ['lunch', 'break', 'prayer', 'busy']
    if reason not in valid_reasons:
        return jsonify({'error': f'Invalid reason. Valid: {", ".join(valid_reasons)}'}), 400

    db = get_db()
    shop = db.execute("SELECT * FROM shops WHERE id = ?", (shop_id,)).fetchone()
    if not shop:
        return jsonify({'error': 'Shop not found'}), 404

    db.execute("UPDATE shops SET is_paused = 1, pause_reason = ? WHERE id = ?", (reason, shop_id))
    db.commit()

    return jsonify({'message': 'Queue paused', 'reason': reason})


# Admin: resumes queue
@app.route('/api/resume', methods=['POST'])
@require_admin
def resume_queue():
    data = request.get_json()
    shop_id = data.get('shop_id', 1)

    db = get_db()
    shop = db.execute("SELECT * FROM shops WHERE id = ?", (shop_id,)).fetchone()
    if not shop:
        return jsonify({'error': 'Shop not found'}), 404

    db.execute("UPDATE shops SET is_paused = 0, pause_reason = NULL WHERE id = ?", (shop_id,))
    db.commit()

    return jsonify({'message': 'Queue resumed'})


# Admin: toggles shop open/closed status
@app.route('/api/toggle-open', methods=['POST'])
@require_admin
def toggle_open():
    data = request.get_json()
    shop_id = data.get('shop_id', 1)
    db = get_db()
    shop = db.execute("SELECT * FROM shops WHERE id = ?", (shop_id,)).fetchone()
    if not shop:
        return jsonify({'error': 'Shop not found'}), 404
    new_status = 0 if shop['is_open'] else 1
    db.execute("UPDATE shops SET is_open = ? WHERE id = ?", (new_status, shop_id))
    db.commit()
    return jsonify({'is_open': bool(new_status), 'message': 'Shop is now ' + ('open' if new_status else 'closed')})


# Public: shop info displayed on portfolio page
@app.route('/api/shop/info', methods=['GET'])
def get_shop_info():
    shop_id = request.args.get('shop_id', 1, type=int)
    db = get_db()
    shop = db.execute("SELECT * FROM shops WHERE id = ?", (shop_id,)).fetchone()
    if not shop:
        return jsonify({'error': 'Shop not found'}), 404
    return jsonify({
        'id': shop['id'],
        'name': shop['name'],
        'is_open': bool(shop['is_open']),
        'is_paused': bool(shop['is_paused']),
        'pause_reason': shop['pause_reason'],
        'avg_haircut_minutes': shop['avg_haircut_minutes'],
        'instagram': shop['instagram'],
        'facebook': shop['facebook'],
        'youtube': shop['youtube'],
        'whatsapp': shop['whatsapp'],
        'phone': shop['phone'],
        'location': shop['location'],
        'working_hours': shop['working_hours'],
        'hero_title': shop['hero_title'],
        'hero_desc': shop['hero_desc']
    })


# Admin: detailed analytics (sensitive business data)
@app.route('/api/stats', methods=['GET'])
@require_admin
def get_stats():
    shop_id = request.args.get('shop_id', 1, type=int)
    period = request.args.get('period', 'day')

    db = get_db()
    shop = db.execute("SELECT * FROM shops WHERE id = ?", (shop_id,)).fetchone()
    if not shop:
        return jsonify({'error': 'Shop not found'}), 404

    if period == 'day':
        date_filter = "DATE(created_at) = DATE('now')"
    elif period == 'week':
        date_filter = "created_at >= datetime('now', '-7 days')"
    elif period == 'month':
        date_filter = "strftime('%Y-%m', created_at) = strftime('%Y-%m', 'now')"
    elif period == 'year':
        date_filter = "strftime('%Y', created_at) = strftime('%Y', 'now')"
    else:
        return jsonify({'error': 'Invalid period. Use: day, week, month, year'}), 400

    rows = db.execute(
        f"SELECT status, COUNT(*) as cnt FROM queue WHERE shop_id = ? AND {date_filter} GROUP BY status",
        (shop_id,)
    ).fetchall()

    stats = {'completed': 0, 'skipped': 0, 'left': 0, 'waiting': 0, 'current': 0, 'total': 0}
    for r in rows:
        stats[r['status']] = r['cnt']
    stats['total'] = stats['completed'] + stats['skipped'] + stats['left'] + stats['waiting'] + stats['current']

    period_label = {'day': "DATE(created_at)", 'week': "DATE(created_at)", 'month': "DATE(created_at)", 'year': "strftime('%Y-%m', created_at)"}
    group_key = period_label.get(period, "DATE(created_at)")
    group_label = 'date' if period in ('day', 'week', 'month') else 'month'

    detail = db.execute(
        f"SELECT {group_key} as period, status, COUNT(*) as cnt FROM queue WHERE shop_id = ? AND {date_filter} GROUP BY period, status ORDER BY period",
        (shop_id,)
    ).fetchall()

    detail_map = {}
    for r in detail:
        p = r['period']
        if p not in detail_map:
            detail_map[p] = {group_label: p, 'completed': 0, 'skipped': 0, 'left': 0, 'total': 0}
        if r['status'] in detail_map[p]:
            detail_map[p][r['status']] = r['cnt']
        detail_map[p]['total'] += r['cnt']

    stats['breakdown'] = sorted(detail_map.values(), key=lambda x: x[group_label])

    trend_filter = "created_at >= datetime('now', '-30 days')"
    trend_data = db.execute(
        f"SELECT DATE(created_at) as date, status, COUNT(*) as cnt FROM queue WHERE shop_id = ? AND {trend_filter} GROUP BY date, status ORDER BY date",
        (shop_id,)
    ).fetchall()
    trend_map = {}
    for r in trend_data:
        d = r['date']
        if d not in trend_map:
            trend_map[d] = {'date': d, 'completed': 0, 'skipped': 0, 'left': 0, 'total': 0}
        if r['status'] in trend_map[d]:
            trend_map[d][r['status']] = r['cnt']
        trend_map[d]['total'] += r['cnt']
    stats['trend'] = sorted(trend_map.values(), key=lambda x: x['date'])

    return jsonify(stats)


# Admin: updates shop settings (already protected)
@app.route('/api/shop/update', methods=['POST'])
@require_admin
def update_shop():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Request body is required'}), 400
    shop_id = data.get('shop_id', 1)

    allowed = ['name', 'instagram', 'facebook', 'youtube', 'whatsapp', 'phone', 'location', 'working_hours', 'hero_title', 'hero_desc', 'avg_haircut_minutes']
    db = get_db()
    shop = db.execute("SELECT * FROM shops WHERE id = ?", (shop_id,)).fetchone()
    if not shop:
        return jsonify({'error': 'Shop not found'}), 404

    validations = {
        'name': ('Shop name', 1, 100),
        'instagram': ('Instagram URL', 0, 200),
        'facebook': ('Facebook URL', 0, 200),
        'youtube': ('YouTube URL', 0, 200),
        'whatsapp': ('WhatsApp URL', 0, 200),
        'phone': ('Phone number', 0, 50),
        'location': ('Location', 0, 300),
        'working_hours': ('Working hours', 0, 200),
        'hero_title': ('Hero title', 0, 200),
        'hero_desc': ('Hero description', 0, 500),
    }

    for key in allowed:
        if key not in data:
            continue
        val = data[key]
        if key == 'avg_haircut_minutes':
            err = validate_int(val, 'Average haircut time', 5, 120)
            if err:
                return jsonify({'error': err}), 400
            db.execute("UPDATE shops SET avg_haircut_minutes = ? WHERE id = ?", (val, shop_id))
        elif key in validations:
            label, min_l, max_l = validations[key]
            err = validate_string(val, label, min_l, max_l)
            if err:
                return jsonify({'error': err}), 400
            db.execute(f"UPDATE shops SET {key} = ? WHERE id = ?", (val.strip(), shop_id))

    db.commit()
    return jsonify({'message': 'Shop updated successfully'})





# Admin: dashboard data (sensitive operational data)
@app.route('/api/dashboard', methods=['GET'])
@require_admin
def get_dashboard():
    shop_id = request.args.get('shop_id', 1, type=int)

    db = get_db()
    shop = db.execute("SELECT * FROM shops WHERE id = ?", (shop_id,)).fetchone()
    if not shop:
        return jsonify({'error': 'Shop not found'}), 404

    stats = db.execute("""
        SELECT status, COUNT(*) as count FROM queue
        WHERE shop_id = ? AND DATE(created_at) = DATE('now')
        GROUP BY status
    """, (shop_id,)).fetchall()

    stat_map = {'completed': 0, 'skipped': 0, 'left': 0, 'waiting': 0, 'current': 0}
    for s in stats:
        stat_map[s['status']] = s['count']

    current = db.execute(
        "SELECT * FROM queue WHERE shop_id = ? AND status = 'current' LIMIT 1",
        (shop_id,)
    ).fetchone()

    waiting = db.execute(
        "SELECT * FROM queue WHERE shop_id = ? AND status = 'waiting' ORDER BY position LIMIT 5",
        (shop_id,)
    ).fetchall()

    return jsonify({
        'shop': {
            'id': shop['id'],
            'name': shop['name'],
            'is_open': bool(shop['is_open']),
            'is_paused': bool(shop['is_paused']),
            'pause_reason': shop['pause_reason'],
            'avg_haircut_minutes': shop['avg_haircut_minutes'],
            'instagram': shop['instagram'],
            'facebook': shop['facebook'],
            'youtube': shop['youtube'],
            'whatsapp': shop['whatsapp'],
            'phone': shop['phone'],
            'location': shop['location'],
            'working_hours': shop['working_hours'],
            'hero_title': shop['hero_title'],
            'hero_desc': shop['hero_desc']
        },
        'current_customer': {
            'id': current['id'],
            'customer_name': current['customer_name'],
            'queue_number': current['queue_number'],
            'position': current['position']
        } if current else None,
        'next_customers': [{
            'id': e['id'],
            'customer_name': e['customer_name'],
            'queue_number': e['queue_number'],
            'position': e['position']
        } for e in waiting],
        'stats': {
            'completed_today': stat_map['completed'],
            'skipped_today': stat_map['skipped'],
            'left_today': stat_map['left'],
            'waiting_now': stat_map['waiting'],
            'total_served_today': stat_map['completed'] + stat_map['skipped'],
            'avg_service_time': shop['avg_haircut_minutes']
        }
    })


# Handle preflight CORS requests for all API routes
@app.before_request
def handle_preflight():
    if request.method == 'OPTIONS':
        return jsonify({}), 200


@app.route('/')
def index():
    return send_from_directory(CLIENT_DIR, 'index.html')


@app.route('/assets/<path:filename>')
def serve_client_assets(filename):
    file_path = os.path.join(CLIENT_DIR, 'assets', filename)
    if os.path.exists(file_path) and os.path.isfile(file_path):
        return send_from_directory(os.path.join(CLIENT_DIR, 'assets'), filename)
    return jsonify({"success": False, "message": "Not found"}), 404


@app.route('/<path:subpath>')
def serve_client_static(subpath):
    if subpath.startswith('api/'):
        return jsonify({"success": False, "message": "Not found"}), 404
    if subpath.startswith('icons/') or subpath in ('manifest.json',):
        file_path = os.path.join(CLIENT_DIR, subpath)
        if os.path.exists(file_path) and os.path.isfile(file_path):
            return send_from_directory(CLIENT_DIR, subpath)
    return send_from_directory(CLIENT_DIR, 'index.html')


if __name__ == '__main__':
    init_db()
    debug_mode = os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(debug=debug_mode, port=5000)
