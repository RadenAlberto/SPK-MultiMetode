import os
import sqlite3
from flask import Flask, render_template, request, redirect, url_for, jsonify, flash

app = Flask(__name__)
app.secret_key = 'super_secret_key_for_spk_app'
DB_NAME = 'spk_master.db'

def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn

# 1. Inisialisasi Database Relasional
def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    # Buat tabel kriteria
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS kriteria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama_kriteria TEXT NOT NULL,
            bobot REAL NOT NULL,
            tipe TEXT NOT NULL CHECK(tipe IN ('Benefit', 'Cost'))
        )
    ''')
    # Buat tabel alternatif
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS alternatif (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama_alternatif TEXT NOT NULL UNIQUE
        )
    ''')
    # Buat tabel nilai_rating
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS nilai_rating (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alternatif_id INTEGER NOT NULL,
            kriteria_id INTEGER NOT NULL,
            nilai_evaluasi REAL NOT NULL,
            FOREIGN KEY (alternatif_id) REFERENCES alternatif (id) ON DELETE CASCADE,
            FOREIGN KEY (kriteria_id) REFERENCES kriteria (id) ON DELETE CASCADE,
            UNIQUE(alternatif_id, kriteria_id)
        )
    ''')
    conn.commit()
    conn.close()

# 2. Fungsi Seeding Studi Kasus Default (Transportasi dari PPT)
def seed_default_data():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Hapus data lama terlebih dahulu
    cursor.execute("DELETE FROM nilai_rating")
    cursor.execute("DELETE FROM kriteria")
    cursor.execute("DELETE FROM alternatif")
    
    # Insert Kriteria Default (Sesuai slide: total bobot awal = 1.0)
    kriteria_data = [
        ('Keamanan', 0.40, 'Benefit'),
        ('Kepadatan', 0.25, 'Cost'),
        ('Jalur Macet', 0.15, 'Cost'),
        ('Ongkos', 0.20, 'Cost')
    ]
    cursor.executemany("INSERT INTO kriteria (nama_kriteria, bobot, tipe) VALUES (?, ?, ?)", kriteria_data)
    
    # Ambil id kriteria yang baru saja dimasukkan
    cursor.execute("SELECT id, nama_kriteria FROM kriteria")
    k_ids = {row['nama_kriteria']: row['id'] for row in cursor.fetchall()}
    
    # Insert Alternatif Default
    alternatifs = ['Bis', 'Angkot', 'Ojek']
    for alt in alternatifs:
        cursor.execute("INSERT INTO alternatif (nama_alternatif) VALUES (?)", (alt,))
    
    # Ambil id alternatif
    cursor.execute("SELECT id, nama_alternatif FROM alternatif")
    alt_ids = {row['nama_alternatif']: row['id'] for row in cursor.fetchall()}
    
    # Insert Rating (Evaluasi Faktor skala 1-9)
    ratings = [
        # Bis
        (alt_ids['Bis'], k_ids['Keamanan'], 6.0),
        (alt_ids['Bis'], k_ids['Kepadatan'], 4.0),
        (alt_ids['Bis'], k_ids['Jalur Macet'], 3.0),
        (alt_ids['Bis'], k_ids['Ongkos'], 8.0),
        # Angkot
        (alt_ids['Angkot'], k_ids['Keamanan'], 8.0),
        (alt_ids['Angkot'], k_ids['Kepadatan'], 7.0),
        (alt_ids['Angkot'], k_ids['Jalur Macet'], 5.0),
        (alt_ids['Angkot'], k_ids['Ongkos'], 6.0),
        # Ojek
        (alt_ids['Ojek'], k_ids['Keamanan'], 5.0),
        (alt_ids['Ojek'], k_ids['Kepadatan'], 9.0),
        (alt_ids['Ojek'], k_ids['Jalur Macet'], 9.0),
        (alt_ids['Ojek'], k_ids['Ongkos'], 3.0),
    ]
    cursor.executemany("INSERT INTO nilai_rating (alternatif_id, kriteria_id, nilai_evaluasi) VALUES (?, ?, ?)", ratings)
    
    conn.commit()
    conn.close()

# 3. KELAS ENGINE SPK (MFEP & SAW)
class DSS_Engine:
    def __init__(self):
        self.conn = get_db_connection()
        self.kriteria = self._get_kriteria()
        self.alternatif = self._get_alternatif()
        self.matrix = self._get_matrix()
        self.conn.close()

    def _get_kriteria(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM kriteria")
        rows = cursor.fetchall()
        # Normalisasi bobot otomatis agar total sum = 1.0
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
        cursor.execute("SELECT * FROM alternatif")
        return [dict(row) for row in cursor.fetchall()]

    def _get_matrix(self):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM nilai_rating")
        rows = cursor.fetchall()
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
                k_id = k['id']
                val = self.matrix.get(alt_id, {}).get(k_id, 0.0)
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
            k_id = k['id']
            vals = [self.matrix.get(alt['id'], {}).get(k_id, 0.0) for alt in self.alternatif]
            extremes[k_id] = {
                'max': max(vals) if vals else 1.0,
                'min': min(vals) if vals else 1.0
            }

        for alt in self.alternatif:
            alt_id = alt['id']
            total_skor = 0.0
            alt_steps = []

            for k in self.kriteria:
                k_id = k['id']
                val = self.matrix.get(alt_id, {}).get(k_id, 0.0)
                
                # Normalisasi SAW
                if k['tipe'] == 'Benefit':
                    max_val = extremes[k_id]['max']
                    norm_val = val / max_val if max_val > 0 else 0.0
                else:  # Cost
                    min_val = extremes[k_id]['min']
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

# 4. ROUTE CONTROLLERS
@app.route('/')
def index():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM kriteria")
    kriteria_list = [dict(row) for row in cursor.fetchall()]
    
    cursor.execute("SELECT * FROM alternatif")
    alternatif_list = [dict(row) for row in cursor.fetchall()]
    
    cursor.execute('''
        SELECT nr.*, a.nama_alternatif, k.nama_kriteria 
        FROM nilai_rating nr
        JOIN alternatif a ON nr.alternatif_id = a.id
        JOIN kriteria k ON nr.kriteria_id = k.id
    ''')
    rating_rows = cursor.fetchall()
    
    rating_matrix = {}
    for alt in alternatif_list:
        rating_matrix[alt['id']] = {k['id']: '-' for k in kriteria_list}
        
    for row in rating_rows:
        rating_matrix[row['alternatif_id']][row['kriteria_id']] = row['nilai_evaluasi']
        
    conn.close()

    engine = DSS_Engine()
    results_mfep, steps_mfep = engine.run_mfep()
    results_saw, steps_saw = engine.run_saw()
    
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
        audit_warning=audit_warning
    )

# 5. CRUD KRITERIA
@app.route('/kriteria/add', methods=['POST'])
def add_kriteria():
    nama = request.form['nama_kriteria']
    bobot = float(request.form['bobot'])
    tipe = request.form['tipe']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO kriteria (nama_kriteria, bobot, tipe) VALUES (?, ?, ?)", (nama, bobot, tipe))
        conn.commit()
        cursor.execute("SELECT id FROM alternatif")
        alts = cursor.fetchall()
        cursor.execute("SELECT id FROM kriteria WHERE nama_kriteria = ?", (nama,))
        k_id = cursor.fetchone()['id']
        for alt in alts:
            cursor.execute("INSERT OR IGNORE INTO nilai_rating (alternatif_id, kriteria_id, nilai_evaluasi) VALUES (?, ?, ?)", (alt['id'], k_id, 0.0))
        conn.commit()
        flash('Kriteria berhasil ditambahkan!', 'success')
    except Exception as e:
        flash(f'Gagal menambahkan kriteria: {str(e)}', 'danger')
    finally:
        conn.close()
    return redirect(url_for('index'))

@app.route('/kriteria/edit/<int:id>', methods=['POST'])
def edit_kriteria(id):
    nama = request.form['nama_kriteria']
    bobot = float(request.form['bobot'])
    tipe = request.form['tipe']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE kriteria SET nama_kriteria = ?, bobot = ?, tipe = ? WHERE id = ?", (nama, bobot, tipe, id))
    conn.commit()
    conn.close()
    flash('Kriteria berhasil diperbarui!', 'success')
    return redirect(url_for('index'))

@app.route('/kriteria/delete/<int:id>')
def delete_kriteria(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM kriteria WHERE id = ?", (id,))
    cursor.execute("DELETE FROM nilai_rating WHERE kriteria_id = ?", (id,))
    conn.commit()
    conn.close()
    flash('Kriteria berhasil dihapus!', 'success')
    return redirect(url_for('index'))

# 6. CRUD ALTERNATIF & RATING
@app.route('/alternatif/add', methods=['POST'])
def add_alternatif():
    nama = request.form['nama_alternatif']
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO alternatif (nama_alternatif) VALUES (?)", (nama,))
        alt_id = cursor.lastrowid
        
        cursor.execute("SELECT id FROM kriteria")
        kriteria_rows = cursor.fetchall()
        for k in kriteria_rows:
            input_name = f"kriteria_{k['id']}"
            val = float(request.form.get(input_name, 0.0))
            cursor.execute("INSERT INTO nilai_rating (alternatif_id, kriteria_id, nilai_evaluasi) VALUES (?, ?, ?)", (alt_id, k['id'], val))
            
        conn.commit()
        flash('Alternatif beserta nilai rating berhasil disimpan!', 'success')
    except sqlite3.IntegrityError:
        flash('Nama alternatif sudah terdaftar!', 'danger')
    except Exception as e:
        flash(f'Gagal menambahkan alternatif: {str(e)}', 'danger')
    finally:
        conn.close()
    return redirect(url_for('index'))

@app.route('/alternatif/delete/<int:id>')
def delete_alternatif(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM alternatif WHERE id = ?", (id,))
    cursor.execute("DELETE FROM nilai_rating WHERE alternatif_id = ?", (id,))
    conn.commit()
    conn.close()
    flash('Alternatif berhasil dihapus!', 'success')
    return redirect(url_for('index'))

# 7. ROUTE SISTEM (SEED & RESET)
@app.route('/seed')
def seed():
    seed_default_data()
    flash('Studi kasus default berhasil dimuat!', 'info')
    return redirect(url_for('index'))

@app.route('/reset')
def reset():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM nilai_rating")
    cursor.execute("DELETE FROM kriteria")
    cursor.execute("DELETE FROM alternatif")
    conn.commit()
    conn.close()
    flash('Database berhasil dibersihkan!', 'warning')
    return redirect(url_for('index'))

if __name__ == '__main__':
    os.makedirs('templates', exist_ok=True)
    init_db()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as count FROM kriteria")
    if cursor.fetchone()['count'] == 0:
        seed_default_data()
    conn.close()
    
    app.run(debug=True, host='0.0.0.0', port=5000)