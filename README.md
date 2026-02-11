# 🎵 Spotify Downloader

Aplikasi untuk mengunduh lagu dan playlist Spotify dalam format MP3.

## 📋 Persyaratan

- Python 3.8+
- pip (Python package manager)
- spotdl (Spotify Downloader CLI)

## 🚀 Instalasi

1. **Clone repository**
   ```bash
   git clone <repository-url>
   cd sportify
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```
   Atau jika terjadi error:
   ```bash
   pip install -r requirements.txt --break-system-packages
   ```

## 💻 Penggunaan

### Development Server

Jalankan server dengan port default (3001):
```bash
python3 app.py
```

Atau dengan port kustom:
```bash
PORT=8080 python3 app.py
```

Server akan berjalan di:
- http://localhost:3001 (default)
- http://0.0.0.0:3001 (all interfaces)

### Menggunakan Aplikasi

1. Buka browser dan kunjungi http://localhost:3001
2. Paste URL Spotify lagu atau playlist
3. Klik tombol "Unduh Sekarang"
4. Tunggu proses download selesai
5. Download file MP3 atau ZIP (untuk playlist)

## 📁 Struktur Project

```
sportify/
├── app.py              # Flask backend server
├── requirements.txt    # Python dependencies
├── .env                # Environment variables
├── public/             # Static files
│   └── index.html      # Frontend UI
├── downloads/          # Tempat penyimpanan download (auto-created)
└── README.md          # Dokumentasi
```

## 🔧 API Endpoints

### Download
- `POST /api/download` - Mulai download lagu/playlist
  - Body: `{"url": "https://spotify.com/track/..."}`

### Status Check
- `GET /api/download-status/<downloadId>` - Cek status download

### Download File
- `GET /api/direct-download/<tempFileName>` - Download lagu single
- `GET /api/download-playlist/<playlistId>` - Download playlist sebagai ZIP
- `GET /api/playlist-files/<playlistId>` - List file dalam playlist
- `GET /api/playlist-file/<playlistId>/<fileName>` - Download single lagu dari playlist

## 🎨 Fitur

- ✅ Download lagu single dari Spotify
- ✅ Download seluruh playlist sekaligus
- ✅ Progress tracking real-time
- ✅ Output format MP3 berkualitas tinggi
- ✅ Auto cleanup setelah download
- ✅ Responsive UI dengan tema Spotify
- ✅ Toast notifications
- ✅ Playlist sebagai ZIP file

## 🛠️ Tech Stack

### Backend
- Flask - Web framework
- Flask-CORS - CORS support
- spotdl - Spotify downloader CLI
- python-dotenv - Environment variables

### Frontend
- HTML5
- Tailwind CSS (via CDN)
- Vanilla JavaScript
- Animate.css (via CDN)

## ⚠️ Catatan

- Gunakan untuk penggunaan pribadi dan legal
- Pastikan memiliki hak untuk mengunduh konten
- Support format: Track dan Playlist Spotify

## 🐛 Troubleshooting

### Port sudah digunakan
```bash
# Cari proses yang menggunakan port 3001
lsof -i :3001

# Kill proses
kill -9 <PID>

# Atau gunakan port lain
PORT=3002 python3 app.py
```

### spotdl tidak terinstall
```bash
pip install spotdl --break-system-packages
```

### Error dependencies
```bash
pip install --upgrade pip
pip install -r requirements.txt --break-system-packages
```

## 📝 License

Project ini untuk tujuan edukasi. Gunakan dengan tanggung jawab.

## 🙏 Credits

- [spotdl](https://github.com/spotDL/spotdl) - Spotify Downloader
- [Flask](https://flask.palletsprojects.com/) - Web Framework
- [Tailwind CSS](https://tailwindcss.com/) - CSS Framework
