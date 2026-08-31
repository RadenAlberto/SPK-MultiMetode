from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3

app = Flask(__name__)
app.secret_key = 'spk_secret_key_123'

DATABASE = 'spk_master.db'

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS kriteria (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama_kriteria TEXT NOT NULL,
            bobot REAL NOT NULL,
            tipe TEXT NOT NULL CHECK(tipe IN ('Benefit', 'Cost'))
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS alternatif (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nama_alternatif TEXT NOT NULL
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS nilai_rating (
            alternatif_id INTEGER NOT NULL,
            kriteria_id INTEGER NOT NULL,
            rating REAL NOT NULL DEFAULT 0,
            PRIMARY KEY (alternatif_id, kriteria_id),
            FOREIGN KEY (alternatif_id) REFERENCES alternatif(id) ON DELETE CASCADE,
            FOREIGN KEY (kriteria_id) REFERENCES kriteria(id) ON DELETE CASCADE
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()

@app.route('/')
def index():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM kriteria")
    kriteria_list = [dict(row) for row in cursor.fetchall()]
    
    cursor.execute("SELECT * FROM alternatif")
    alternatif_list = [dict(row) for row in cursor.fetchall()]
    
    cursor.execute("SELECT * FROM nilai_rating")
    rating_rows = cursor.fetchall()
    
    matrix = {}
    for r in rating_rows:
        alt_id = r['alternatif_id']
        k_id = r['kriteria_id']
        val = r['rating']
        if alt_id not in matrix:
            matrix[alt_id] = {}
        matrix[alt_id][k_id] = val
        
    total_bobot_input = sum([k['bobot'] for k in kriteria_list])
    # Pencegahan Division by Zero jika kriteria belum diisi
    if total_bobot_input == 0:
        total_bobot_input = 1.0

    # ==========================
    # LOGIKA PERHITUNGAN MFEP
    # ==========================
    mfep_detail = []
    mfep_ranking = []
    
    for alt in alternatif_list:
        alt_id = alt['id']
        detail_kriteria = []
        total_skor = 0.0

        for k in kriteria_list:
            k_id = k['id']
            rating = matrix.get(alt_id, {}).get(k_id, 0.0)
            bobot_norm = k['bobot'] / total_bobot_input
            eval_terbobot = rating * bobot_norm
            total_skor += eval_terbobot

            detail_kriteria.append({
                'kriteria': k['nama_kriteria'],
                'rating': rating,
                'bobot_norm': bobot_norm,
                'eval_terbobot': eval_terbobot
            })

        mfep_detail.append({
            'nama_alternatif': alt['nama_alternatif'],
            'detail': detail_kriteria,
            'total_skor': total_skor
        })
        
        mfep_ranking.append({
            'nama_alternatif': alt['nama_alternatif'],
            'total_skor': total_skor
        })
        
    mfep_ranking = sorted(mfep_ranking, key=lambda x: x['total_skor'], reverse=True)

    # ==========================
    # LOGIKA PERHITUNGAN SAW
    # ==========================
    max_min_kriteria = {}
    for k in kriteria_list:
        k_id = k['id']
        ratings = [matrix.get(a['id'], {}).get(k_id, 0.0) for a in alternatif_list]
        
        # Penanganan aman jika nilai rating masih kosong/0
        valid_ratings = [r for r in ratings if r > 0]
        max_val = max(ratings) if ratings else 1.0
        min_val = min(valid_ratings) if valid_ratings else 1.0

        max_min_kriteria[k_id] = {
            'max': max_val if max_val > 0 else 1.0,
            'min': min_val if min_val > 0 else 1.0
        }

    saw_detail = []
    saw_ranking = []
    
    for alt in alternatif_list:
        alt_id = alt['id']
        detail_kriteria = []
        total_v = 0.0

        for k in kriteria_list:
            k_id = k['id']
            rating = matrix.get(alt_id, {}).get(k_id, 0.0)
            bobot_norm = k['bobot'] / total_bobot_input
            tipe = k['tipe'].lower()

            if tipe == 'benefit':
                max_v = max_min_kriteria[k_id]['max']
                r_ij = rating / max_v if max_v > 0 else 0.0
                rumus_str = f"{rating} / {max_v}"
            else: # Cost
                min_v = max_min_kriteria[k_id]['min']
                r_ij = min_v / rating if rating > 0 else 0.0
                rumus_str = f"{min_v} / {rating}"

            v_ij = bobot_norm * r_ij
            total_v += v_ij

            detail_kriteria.append({
                'kriteria': k['nama_kriteria'],
                'tipe': k['tipe'],
                'rating': rating,
                'rumus_str': rumus_str,
                'r_ij': r_ij,
                'bobot_norm': bobot_norm,
                'v_ij': v_ij
            })

        saw_detail.append({
            'nama_alternatif': alt['nama_alternatif'],
            'detail': detail_kriteria,
            'total_v': total_v
        })

        saw_ranking.append({
            'nama_alternatif': alt['nama_alternatif'],
            'total_v': total_v
        })

    saw_ranking = sorted(saw_ranking, key=lambda x: x['total_v'], reverse=True)

    conn.close()

    return render_template(
        'index.html',
        kriteria_list=kriteria_list,
        alternatif_list=alternatif_list,
        matrix=matrix,
        mfep_ranking=mfep_ranking,
        mfep_detail=mfep_detail,
        saw_ranking=saw_ranking,
        saw_detail=saw_detail
    )

@app.route('/add_kriteria', methods=['POST'])
def add_kriteria():
    nama = request.form['nama_kriteria']
    bobot = float(request.form['bobot'])
    tipe = request.form['tipe']

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO kriteria (nama_kriteria, bobot, tipe) VALUES (?, ?, ?)", (nama, bobot, tipe))
        conn.commit()
        
        k_id = cursor.lastrowid
        cursor.execute("SELECT id FROM alternatif")
        alts = cursor.fetchall()
        
        for alt in alts:
            cursor.execute("INSERT OR IGNORE INTO nilai_rating (alternatif_id, kriteria_id, rating) VALUES (?, ?, 0)", (alt['id'], k_id))
        conn.commit()
        flash('Kriteria berhasil ditambahkan!', 'success')
    except Exception as e:
        flash(f'Gagal menambahkan kriteria: {e}', 'danger')
    finally:
        conn.close()
    return redirect(url_for('index'))

@app.route('/edit_kriteria/<int:id>', methods=['POST'])
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

@app.route('/delete_kriteria/<int:id>', methods=['POST'])
def delete_kriteria(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM kriteria WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    flash('Kriteria berhasil dihapus!', 'warning')
    return redirect(url_for('index'))

@app.route('/add_alternatif', methods=['POST'])
def add_alternatif():
    nama = request.form['nama_alternatif']

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO alternatif (nama_alternatif) VALUES (?)", (nama,))
        conn.commit()
        alt_id = cursor.lastrowid

        cursor.execute("SELECT id FROM kriteria")
        kriterias = cursor.fetchall()
        for k in kriterias:
            cursor.execute("INSERT OR IGNORE INTO nilai_rating (alternatif_id, kriteria_id, rating) VALUES (?, ?, 0)", (alt_id, k['id']))
        conn.commit()
        flash('Alternatif berhasil ditambahkan!', 'success')
    except Exception as e:
        flash(f'Gagal menambahkan alternatif: {e}', 'danger')
    finally:
        conn.close()
    return redirect(url_for('index'))

@app.route('/delete_alternatif/<int:id>', methods=['POST'])
def delete_alternatif(id):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM alternatif WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    flash('Alternatif berhasil dihapus!', 'warning')
    return redirect(url_for('index'))

@app.route('/update_matrix', methods=['POST'])
def update_matrix():
    conn = get_db_connection()
    cursor = conn.cursor()

    for key, value in request.form.items():
        if key.startswith('rating_'):
            parts = key.split('_')
            alt_id = int(parts[1])
            k_id = int(parts[2])
            val = float(value) if value else 0.0

            cursor.execute('''
                INSERT INTO nilai_rating (alternatif_id, kriteria_id, rating)
                VALUES (?, ?, ?)
                ON CONFLICT(alternatif_id, kriteria_id) DO UPDATE SET rating=excluded.rating
            ''', (alt_id, k_id, val))

    conn.commit()
    conn.close()
    flash('Matriks penilaian berhasil diperbarui!', 'success')
    return redirect(url_for('index'))

@app.route('/seed')
def seed_data():
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM nilai_rating")
    cursor.execute("DELETE FROM alternatif")
    cursor.execute("DELETE FROM kriteria")

    cursor.execute("INSERT INTO kriteria (nama_kriteria, bobot, tipe) VALUES ('Harga', 30, 'Cost')")
    cursor.execute("INSERT INTO kriteria (nama_kriteria, bobot, tipe) VALUES ('Kualitas', 40, 'Benefit')")
    cursor.execute("INSERT INTO kriteria (nama_kriteria, bobot, tipe) VALUES ('Servis', 30, 'Benefit')")

    cursor.execute("INSERT INTO alternatif (nama_alternatif) VALUES ('Opsi A')")
    cursor.execute("INSERT INTO alternatif (nama_alternatif) VALUES ('Opsi B')")
    cursor.execute("INSERT INTO alternatif (nama_alternatif) VALUES ('Opsi C')")

    conn.commit()

    cursor.execute("SELECT id FROM kriteria")
    k_ids = [row['id'] for row in cursor.fetchall()]

    cursor.execute("SELECT id FROM alternatif")
    a_ids = [row['id'] for row in cursor.fetchall()]

    sample_ratings = [
        (a_ids[0], k_ids[0], 80), (a_ids[0], k_ids[1], 70), (a_ids[0], k_ids[2], 90),
        (a_ids[1], k_ids[0], 60), (a_ids[1], k_ids[1], 85), (a_ids[1], k_ids[2], 75),
        (a_ids[2], k_ids[0], 90), (a_ids[2], k_ids[1], 60), (a_ids[2], k_ids[2], 80)
    ]

    cursor.executemany("INSERT INTO nilai_rating (alternatif_id, kriteria_id, rating) VALUES (?, ?, ?)", sample_ratings)
    conn.commit()
    conn.close()
    flash('Data sampel dummy berhasil diisi!', 'info')
    return redirect(url_for('index'))

@app.route('/reset')
def reset_data():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM nilai_rating")
    cursor.execute("DELETE FROM alternatif")
    cursor.execute("DELETE FROM kriteria")
    conn.commit()
    conn.close()
    flash('Semua data berhasil dibersihkan!', 'warning')
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)