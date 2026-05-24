from flask import Blueprint, request, jsonify, g, session
from database import get_db, hash_password
from functools import wraps


def validate_string(value, field_name, min_len=1, max_len=None):
    if not isinstance(value, str):
        return f'{field_name} must be text'
    stripped = value.strip()
    if len(stripped) < min_len:
        return f'{field_name} must be at least {min_len} character{"s" if min_len > 1 else ""}'
    if max_len and len(stripped) > max_len:
        return f'{field_name} must not exceed {max_len} characters'
    return None


def require_admin_session(f):
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


admin_bp = Blueprint('admin', __name__, url_prefix='/api/admin')


@admin_bp.route('/login', methods=['POST'])
def login():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Request body is required'}), 400
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()

    err = validate_string(username, 'Username', 1, 100)
    if err:
        return jsonify({'error': err}), 400
    err = validate_string(password, 'Password', 1, 200)
    if err:
        return jsonify({'error': err}), 400

    db = get_db()
    admin = db.execute(
        "SELECT * FROM admins WHERE username = ?", (username,)
    ).fetchone()

    if not admin or admin['password'] != hash_password(password):
        return jsonify({'error': 'Invalid username or password'}), 401

    session.permanent = True
    session['admin_id'] = admin['id']
    session['admin_username'] = admin['username']

    return jsonify({'message': 'Login successful', 'username': admin['username'], 'id': admin['id']})


@admin_bp.route('/change-password', methods=['POST'])
@require_admin_session
def change_password():
    admin = g.admin
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Request body is required'}), 400
    current_password = data.get('current_password', '')
    new_password = data.get('new_password', '')

    err = validate_string(current_password, 'Current password', 1)
    if err:
        return jsonify({'error': err}), 400
    err = validate_string(new_password, 'New password', 4, 200)
    if err:
        return jsonify({'error': err}), 400

    if admin['password'] != hash_password(current_password):
        return jsonify({'error': 'Current password is incorrect'}), 401

    db = get_db()
    db.execute("UPDATE admins SET password = ? WHERE id = ?",
               (hash_password(new_password), admin['id']))
    db.commit()

    return jsonify({'message': 'Password changed successfully'})


@admin_bp.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'message': 'Logged out successfully'})


@admin_bp.route('/me', methods=['GET'])
def me():
    admin_id = session.get('admin_id')
    if not admin_id:
        return jsonify({'authenticated': False}), 200
    db = get_db()
    admin = db.execute("SELECT id, username FROM admins WHERE id = ?", (admin_id,)).fetchone()
    if not admin:
        session.clear()
        return jsonify({'authenticated': False}), 200
    return jsonify({'authenticated': True, 'id': admin['id'], 'username': admin['username']})
