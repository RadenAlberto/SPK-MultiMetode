import os
import json
import traceback
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, render_template, request, redirect, url_for, flash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__, template_folder=os.path.join(BASE_DIR, 'templates'))
app.secret_key = os.environ.get('SECRET_KEY', 'super_secret_key_for_spk_app_2026')

DATABASE_URL = os.environ.get('DATABASE_URL')

def get_db_connection():
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL belum dikonfigurasi di Environment Render!")
    
    db_url = DATABASE_URL
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)
        
    conn = psycopg2.connect(db_url, cursor_factory=RealDictCursor)
    return conn

def init_db():
    if not DATABASE_URL:
        return
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS kriteria (
                id SERIAL PRIMARY KEY,
                nama_kriteria VARCHAR(255) NOT NULL,
                bobot DOUBLE PRECISION NOT NULL,
                tipe VARCHAR(50) NOT NULL CHECK(tipe IN ('Benefit', 'Cost'))
            );
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS alternatif (
                id SERIAL PRIMARY KEY,
                nama_alternatif VARCHAR(255) NOT NULL UNIQUE
            );
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS nilai_rating (
                id SERIAL PRIMARY KEY,
                alternatif_id INTEGER NOT NULL REFERENCES alternatif (id) ON DELETE CASCADE,
                kriteria_id INTEGER NOT NULL REFERENCES kriteria (id) ON DELETE CASCADE,
                nilai_evaluasi DOUBLE PRECISION NOT NULL,
                UNIQUE(alternatif_id, kriteria_id)
            );
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS db_backup_history (
                id SERIAL PRIMARY KEY,
                keterangan VARCHAR(255) NOT NULL,
                snapshot_data TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        ''')
        conn.commit()
        cursor.close()
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"[Init DB Error]: {e}")
    finally:
        if conn:
            conn.close()

def create_backup_snapshot(keterangan="Backup Otomatis"):
    """Menyimpan snapshot seluruh data saat ini ke tabel db_backup_history untuk fitur Undo"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM kriteria ORDER BY id ASC")
        k_data = [dict(r) for r in cursor.fetchall()]
        cursor.execute("SELECT * FROM alternatif ORDER BY id ASC")
        a_data = [dict(r) for r in cursor.fetchall()]
        cursor.execute("SELECT * FROM nilai_rating ORDER BY id ASC")
        r_data = [dict(r) for r in cursor.fetchall()]
        
        if k_data or a_data:
            payload = json.dumps({
                'kriteria': k_data,
                'alternatif': a_data,
                'nilai_rating': r_data
            })
            cursor.execute("INSERT INTO db_backup_history (keterangan, snapshot_data) VALUES (%s, %s)", (keterangan, payload))
            conn.commit()
        cursor.close()
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"[Backup Error]: {e}")
    finally:
        if conn:
            conn.close()

def restore_latest_snapshot():
    """Mengembalikan data dari snapshot cadangan terakhir"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM db_backup_history ORDER BY id DESC LIMIT 1")
        backup = cursor.fetchone()
        if not backup:
            return False, "Tidak ada data snapshot/cadangan yang bisa dipulihkan."
        
        data = json.loads(backup['snapshot_data'])
        
        cursor.execute("TRUNCATE TABLE nilai_rating, kriteria, alternatif RESTART IDENTITY CASCADE;")
        
        for k in data.get('kriteria', []):
            cursor.execute("INSERT INTO kriteria (id, nama_kriteria, bobot, tipe) VALUES (%s, %s, %s, %s)",
                           (k['id'], k['nama_kriteria'], k['bobot'], k['tipe']))
        if data.get('kriteria'):
            cursor.execute("SELECT setval(pg_get_serial_sequence('kriteria', 'id'), coalesce(max(id), 1)) FROM kriteria;")
        
        for a in data.get('alternatif', []):
            cursor.execute("INSERT INTO alternatif (id, nama_alternatif) VALUES (%s, %s)",
                           (a['id'], a['nama_alternatif']))
        if data.get('alternatif'):
            cursor.execute("SELECT setval(pg_get_serial_sequence('alternatif', 'id'), coalesce(max(id), 1)) FROM alternatif;")
        
        for r in data.get('nilai_rating', []):
            cursor.execute("INSERT INTO nilai_rating (id, alternatif_id, kriteria_id, nilai_evaluasi) VALUES (%s, %s, %s, %s)",
                           (r['id'], r['alternatif_id'], r['kriteria_id'], r['nilai_evaluasi']))
        if data.get('nilai_rating'):
            cursor.execute("SELECT setval(pg_get_serial_sequence('nilai_rating', 'id'), coalesce(max(id), 1)) FROM nilai_rating;")
            
        cursor.execute("DELETE FROM db_backup_history WHERE id = %s", (backup['id'],))
        conn.commit()
        cursor.close()
        return True, f"Berhasil memulihkan snapshot: '{backup['keterangan']}'"
    except Exception as e:
        if conn:
            conn.rollback()
        return False, f"Gagal memulihkan snapshot: {str(e)}"
    finally:
        if conn:
            conn.close()

def seed_default_data():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("TRUNCATE TABLE nilai_rating, kriteria, alternatif RESTART IDENTITY CASCADE;")
        
        kriteria_data = [
            ('Keamanan', 0.40, 'Benefit'),
            ('Kepadatan', 0.25, 'Cost'),
            ('Jalur Macet', 0.15, 'Cost'),
            ('Ongkos', 0.20, 'Cost')
        ]
        cursor.executemany("INSERT INTO kriteria (nama_kriteria, bobot, tipe) VALUES (%s, %s, %s)", kriteria_data)
        
        cursor.execute("SELECT id, nama_kriteria FROM kriteria")
        k_ids = {row['nama_kriteria']: row['id'] for row in cursor.fetchall()}
        
        alternatifs = ['Bis', 'Angkot', 'Ojek']
        alt_ids = {}
        for alt in alternatifs:
            cursor.execute("INSERT INTO alternatif (nama_alternatif) VALUES (%s) RETURNING id;", (alt,))
            alt_ids[alt] = cursor.fetchone()['id']
        
        ratings = [
            (alt_ids['Bis'], k_ids['Keamanan'], 6.0),
            (alt_ids['Bis'], k_ids['Kepadatan'], 4.0),
            (alt_ids['Bis'], k_ids['Jalur Macet'], 3.0),
            (alt_ids['Bis'], k_ids['Ongkos'], 8.0),
            (alt_ids['Angkot'], k_ids['Keamanan'], 8.0),
            (alt_ids['Angkot'], k_ids['Kepadatan'], 7.0),
            (alt_ids['Angkot'], k_ids['Jalur Macet'], 5.0),
            (alt_ids['Angkot'], k_ids['Ongkos'], 6.0),
            (alt_ids['Ojek'], k_ids['Keamanan'], 5.0),
            (alt_ids['Ojek'], k_ids['Kepadatan'], 9.0),
            (alt_ids['Ojek'], k_ids['Jalur Macet'], 9.0),
            (alt_ids['Ojek'], k_ids['Ongkos'], 3.0),
        ]
        cursor.executemany("INSERT INTO nilai_rating (alternatif_id, kriteria_id, nilai_evaluasi) VALUES (%s, %s, %s)", ratings)
        conn.commit()
        cursor.close()
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()

class DSS_Engine:
    def __init__(self):
        self.conn = get_db_connection()
        self.kriteria = self._get_kriteria()
        self.alternatif = self._get_alternatif()
        self.matrix = self._get_matrix()
        self.conn.close()

    def _get_kriteria(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM kriteria ORDER BY id ASC")
        rows = cursor.fetchall()
        cursor.close()
        total_bobot = sum([row['bobot'] for row in rows])
        kriteria_list = []
        for r in rows:
            normalized_weight = r['bobot'] / total_bobot if total_bobot > 0 else 0
            kriteria_list.append({
                'id': r['id'],
                'nama': r['nama_kriteria'],
                'bobot_asal': r['bobot'],
                'bobot': normalized_weight,
                'tipe': r['tipe']
            })
        return kriteria_list

    def _get_alternatif(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM alternatif ORDER BY id ASC")
        rows = [dict(row) for row in cursor.fetchall()]
        cursor.close()
        return rows

    def _get_matrix(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM nilai_rating")
        rows = cursor.fetchall()
        cursor.close()
        matrix = {}
        for r in rows:
            alt_id = r['alternatif_id']
            krit_id = r['kriteria_id']
            val = r['nilai_evaluasi']
            if alt_id not in matrix:
                matrix[alt_id] = {}
            matrix[alt_id][krit_id] = val
        return matrix

    def run_mfep(self):
        results = []
        steps = {}
        if not self.alternatif or not self.kriteria:
            return results, steps
        for alt in self.alternatif:
            alt_id = alt['id']
            total_skor = 0.0
            alt_steps = []
            for k in self.kriteria:
                val = self.matrix.get(alt_id, {}).get(k['id'], 0.0)
                sub_total = val * k['bobot']
                total_skor += sub_total
                alt_steps.append({
                    'kriteria': k['nama'],
                    'nilai_mentah': val,
                    'bobot': k['bobot'],
                    'hasil_kali': sub_total
                })
            results.append({
                'id': alt_id,
                'nama': alt['nama_alternatif'],
                'skor': round(total_skor, 4),
                'steps': alt_steps
            })
            steps[alt['nama_alternatif']] = alt_steps
        results.sort(key=lambda x: x['skor'], reverse=True)
        return results, steps

    def run_saw(self):
        results = []
        steps = {}
        if not self.alternatif or not self.kriteria:
            return results, steps
        extremes = {}
        for k in self.kriteria:
            vals = [self.matrix.get(alt['id'], {}).get(k['id'], 0.0) for alt in self.alternatif]
            extremes[k['id']] = {
                'max': max(vals) if vals else 1.0,
                'min': min(vals) if vals else 1.0
            }
        for alt in self.alternatif:
            alt_id = alt['id']
            total_skor = 0.0
            alt_steps = []
            for k in self.kriteria:
                val = self.matrix.get(alt_id, {}).get(k['id'], 0.0)
                if k['tipe'] == 'Benefit':
                    max_val = extremes[k['id']]['max']
                    norm_val = val / max_val if max_val > 0 else 0.0
                else:
                    min_val = extremes[k['id']]['min']
                    norm_val = min_val / val if val > 0 else 0.0
                sub_total = norm_val * k['bobot']
                total_skor += sub_total
                alt_steps.append({
                    'kriteria': k['nama'],
                    'nilai_mentah': val,
                    'tipe': k['tipe'],
                    'nilai_normalisasi': norm_val,
                    'bobot': k['bobot'],
                    'hasil_kali': sub_total
                })
            results.append({
                'id': alt_id,
                'nama': alt['nama_alternatif'],
                'skor': round(total_skor, 4),
                'steps': alt_steps
            })
            steps[alt['nama_alternatif']] = alt_steps
        results.sort(key=lambda x: x['skor'], reverse=True)
        return results, steps

    def run_wp(self):
        results = []
        steps = {}
        if not self.alternatif or not self.kriteria:
            return results, steps
        vector_S = {}
        total_S = 0.0
        for alt in self.alternatif:
            alt_id = alt['id']
            s_val = 1.0
            alt_steps = []
            for k in self.kriteria:
                val = self.matrix.get(alt_id, {}).get(k['id'], 1.0)
                if val <= 0:
                    val = 0.01
                power = k['bobot'] if k['tipe'] == 'Benefit' else -k['bobot']
                powered_val = val ** power
                s_val *= powered_val
                alt_steps.append({
                    'kriteria': k['nama'],
                    'nilai_mentah': val,
                    'tipe': k['tipe'],
                    'bobot_pangkat': power,
                    'hasil_pangkat': powered_val
                })
            vector_S[alt_id] = s_val
            total_S += s_val
            steps[alt['nama_alternatif']] = {'details': alt_steps, 'S_value': s_val}
        for alt in self.alternatif:
            alt_id = alt['id']
            s_val = vector_S[alt_id]
            v_val = s_val / total_S if total_S > 0 else 0.0
            results.append({
                'id': alt_id,
                'nama': alt['nama_alternatif'],
                'S_value': round(s_val, 4),
                'skor': round(v_val, 4)
            })
        results.sort(key=lambda x: x['skor'], reverse=True)
        return results, steps

    def run_smart(self):
        results = []
        steps = {}
        if not self.alternatif or not self.kriteria:
            return results, steps
        extremes = {}
        for k in self.kriteria:
            vals = [self.matrix.get(alt['id'], {}).get(k['id'], 0.0) for alt in self.alternatif]
            extremes[k['id']] = {
                'max': max(vals) if vals else 100.0,
                'min': min(vals) if vals else 0.0
            }
        for alt in self.alternatif:
            alt_id = alt['id']
            total_skor = 0.0
            alt_steps = []
            for k in self.kriteria:
                val = self.matrix.get(alt_id, {}).get(k['id'], 0.0)
                c_max = extremes[k['id']]['max']
                c_min = extremes[k['id']]['min']
                denom = (c_max - c_min)
                utility = 100.0 if denom == 0 else (100.0 * (val - c_min) / denom if k['tipe'] == 'Benefit' else 100.0 * (c_max - val) / denom)
                sub_total = (utility / 100.0) * k['bobot']
                total_skor += sub_total
                alt_steps.append({
                    'kriteria': k['nama'],
                    'nilai_mentah': val,
                    'tipe': k['tipe'],
                    'c_min': c_min,
                    'c_max': c_max,
                    'utility': round(utility, 2),
                    'bobot': k['bobot'],
                    'hasil_kali': sub_total
                })
            results.append({
                'id': alt_id,
                'nama': alt['nama_alternatif'],
                'skor': round(total_skor, 4),
                'steps': alt_steps
            })
            steps[alt['nama_alternatif']] = alt_steps
        results.sort(key=lambda x: x['skor'], reverse=True)
        return results, steps

@app.route('/')
def index():
    if not DATABASE_URL:
        return "<h2 style='color:red; text-align:center; margin-top:50px;'>Error: Environment variable DATABASE_URL belum diatur di Render!</h2>", 500

    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT * FROM kriteria ORDER BY id ASC")
        raw_kriteria = cursor.fetchall()
        kriteria_list = []
        for r in raw_kriteria:
            kriteria_list.append({
                'id': r['id'],
                'nama_kriteria': r['nama_kriteria'],
                'bobot': r['bobot'],
                'bobot_asal': r['bobot'],
                'tipe': r['tipe']
            })
        
        cursor.execute("SELECT * FROM alternatif ORDER BY id ASC")
        alternatif_list = [dict(row) for row in cursor.fetchall()]
        
        cursor.execute('''
            SELECT nr.*, a.nama_alternatif, k.nama_kriteria 
            FROM nilai_rating nr
            JOIN alternatif a ON nr.alternatif_id = a.id
            JOIN kriteria k ON nr.kriteria_id = k.id
        ''')
        rating_rows = cursor.fetchall()
        
        latest_backup = None
        try:
            cursor.execute("SELECT id, keterangan, created_at FROM db_backup_history ORDER BY id DESC LIMIT 1")
            latest_backup = cursor.fetchone()
        except Exception:
            conn.rollback()
    finally:
        cursor.close()
        conn.close()
    
    rating_matrix = {}
    for alt in alternatif_list:
        rating_matrix[alt['id']] = {k['id']: '-' for k in kriteria_list}
    for row in rating_rows:
        if row['alternatif_id'] in rating_matrix:
            rating_matrix[row['alternatif_id']][row['kriteria_id']] = row['nilai_evaluasi']

    engine = DSS_Engine()
    results_mfep, steps_mfep = engine.run_mfep()
    results_saw, steps_saw = engine.run_saw()
    results_wp, steps_wp = engine.run_wp()
    results_smart, steps_smart = engine.run_smart()

    audit_warning = False
    if len(alternatif_list) == 3 and len(kriteria_list) == 4:
        alt_names = sorted([a['nama_alternatif'].lower() for a in alternatif_list])
        krit_names = sorted([k['nama_kriteria'].lower() for k in kriteria_list])
        if alt_names == ['angkot', 'bis', 'ojek'] and 'kepadatan' in krit_names:
            audit_warning = True

    return render_template(
        'index.html',
        kriteria=kriteria_list,
        alternatif=alternatif_list,
        rating_matrix=rating_matrix,
        results_mfep=results_mfep, steps_mfep=steps_mfep,
        results_saw=results_saw, steps_saw=steps_saw,
        results_wp=results_wp, steps_wp=steps_wp,
        results_smart=results_smart, steps_smart=steps_smart,
        audit_warning=audit_warning,
        latest_backup=latest_backup
    )

@app.route('/kriteria/add', methods=['POST'])
def add_kriteria():
    nama = request.form.get('nama_kriteria', '').strip()
    bobot = float(request.form.get('bobot', 0.0))
    tipe = request.form.get('tipe', 'Benefit')
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO kriteria (nama_kriteria, bobot, tipe) VALUES (%s, %s, %s) RETURNING id;", (nama, bobot, tipe))
        k_id = cursor.fetchone()['id']
        cursor.execute("SELECT id FROM alternatif;")
        alts = cursor.fetchall()
        for alt in alts:
            cursor.execute("INSERT INTO nilai_rating (alternatif_id, kriteria_id, nilai_evaluasi) VALUES (%s, %s, %s) ON CONFLICT (alternatif_id, kriteria_id) DO NOTHING;", (alt['id'], k_id, 0.0))
        conn.commit()
        flash('Kriteria berhasil ditambahkan!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Gagal menambahkan kriteria: {str(e)}', 'danger')
    finally:
        cursor.close()
        conn.close()
    return redirect(url_for('index'))

@app.route('/kriteria/edit/<int:id>', methods=['POST'])
def edit_kriteria(id):
    nama = request.form.get('nama_kriteria', '').strip()
    bobot = float(request.form.get('bobot', 0.0))
    tipe = request.form.get('tipe', 'Benefit')
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE kriteria SET nama_kriteria = %s, bobot = %s, tipe = %s WHERE id = %s;", (nama, bobot, tipe, id))
        conn.commit()
        flash('Kriteria berhasil diperbarui!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Gagal memperbarui kriteria: {str(e)}', 'danger')
    finally:
        cursor.close()
        conn.close()
    return redirect(url_for('index'))

@app.route('/kriteria/delete/<int:id>')
def delete_kriteria(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM kriteria WHERE id = %s;", (id,))
        conn.commit()
        flash('Kriteria berhasil dihapus!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Gagal menghapus kriteria: {str(e)}', 'danger')
    finally:
        cursor.close()
        conn.close()
    return redirect(url_for('index'))

@app.route('/alternatif/add', methods=['POST'])
def add_alternatif():
    nama = request.form.get('nama_alternatif', '').strip()
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO alternatif (nama_alternatif) VALUES (%s) RETURNING id;", (nama,))
        alt_id = cursor.fetchone()['id']
        cursor.execute("SELECT id FROM kriteria;")
        kriteria_rows = cursor.fetchall()
        for k in kriteria_rows:
            val = float(request.form.get(f"kriteria_{k['id']}", 0.0))
            cursor.execute("INSERT INTO nilai_rating (alternatif_id, kriteria_id, nilai_evaluasi) VALUES (%s, %s, %s);", (alt_id, k['id'], val))
        conn.commit()
        flash('Alternatif beserta nilai rating berhasil disimpan!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Gagal menambahkan alternatif: {str(e)}', 'danger')
    finally:
        cursor.close()
        conn.close()
    return redirect(url_for('index'))

@app.route('/alternatif/delete/<int:id>')
def delete_alternatif(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM alternatif WHERE id = %s;", (id,))
        conn.commit()
        flash('Alternatif berhasil dihapus!', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Gagal menghapus alternatif: {str(e)}', 'danger')
    finally:
        cursor.close()
        conn.close()
    return redirect(url_for('index'))

@app.route('/backup/create')
def manual_backup():
    create_backup_snapshot("Snapshot Manual Pengguna")
    flash('Snapshot data berhasil dicadangkan! Anda bisa memulihkannya kapan saja via menu Undo.', 'info')
    return redirect(url_for('index'))

@app.route('/backup/undo')
def undo_restore():
    success, message = restore_latest_snapshot()
    if success:
        flash(f'⏪ {message}', 'success')
    else:
        flash(f'⚠️ {message}', 'warning')
    return redirect(url_for('index'))

@app.route('/seed')
def seed():
    try:
        create_backup_snapshot("Sebelum Muat Ulang Kasus PPT")
        seed_default_data()
        flash('Studi kasus default (Transportasi dari PPT) berhasil dimuat! Data lama otomatis dicadangkan (bisa di-Undo).', 'info')
    except Exception as e:
        flash(f'Gagal memuat data default: {str(e)}', 'danger')
    return redirect(url_for('index'))

@app.route('/reset')
def reset():
    conn = None
    try:
        create_backup_snapshot("Sebelum Reset Database Kosong")
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("TRUNCATE TABLE nilai_rating, kriteria, alternatif RESTART IDENTITY CASCADE;")
        conn.commit()
        cursor.close()
        flash('Database berhasil dikosongkan! Data lama otomatis dicadangkan (bisa di-Undo via menu Database).', 'warning')
    except Exception as e:
        if conn:
            conn.rollback()
        flash(f'Gagal membersihkan database: {str(e)}', 'danger')
    finally:
        if conn:
            conn.close()
    return redirect(url_for('index'))

# Error Handler Khusus agar tidak muncul 'Internal Server Error' tanpa jejak
@app.errorhandler(500)
def internal_error(error):
    err_msg = traceback.format_exc()
    return f"""
    <div style="font-family: sans-serif; padding: 30px; max-width: 800px; margin: 40px auto; border: 1px solid #dc3545; border-radius: 8px; background: #fff;">
        <h2 style="color: #dc3545; margin-top:0;">⚠️ Terjadi Kesalahan Internal (Error 500)</h2>
        <p>Aplikasi mengalami galat saat memproses data. Rincian error:</p>
        <pre style="background: #f8f9fa; padding: 15px; border-radius: 5px; border: 1px solid #e9ecef; overflow-x: auto; color: #d63384; font-size: 0.9em;">{err_msg}</pre>
        <a href="/" style="display: inline-block; padding: 10px 20px; background: #0d6efd; color: #fff; text-decoration: none; border-radius: 5px;">Kembali ke Beranda</a>
    </div>
    """, 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)
