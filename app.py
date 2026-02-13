import os
import re
import subprocess
import threading
import zipfile
import shutil
import time
from pathlib import Path
from flask import Flask, request, jsonify, send_file, Response, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
import requests
from ytmusicapi import YTMusic 

load_dotenv()

app = Flask(__name__, static_folder="public")
CORS(app)

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "downloads"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

active_downloads: dict[str, dict] = {}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}


# ---------------------------------------------------------------------------
# Fungsi baru: Cari videoId terbaik dari YouTube Music
# ---------------------------------------------------------------------------
def get_best_video_id(query):
    """Mengembalikan videoId YouTube terbaik untuk query lagu."""
    try:
        print(f"[YTMusicAPI] Searching for: '{query}'")
        ytmusic = YTMusic()
        # Filter="songs" memastikan hanya lagu yang dicari
        search_results = ytmusic.search(query, filter="songs", limit=1)
        
        if search_results and len(search_results) > 0:
            result = search_results[0]
            video_id = result.get('videoId')
            title = result.get('title', 'Unknown')
            artists = ', '.join([artist['name'] for artist in result.get('artists', [])])
            
            if video_id:
                print(f"[YTMusicAPI] Found: '{title}' by {artists} (ID: {video_id})")
                return video_id
            else:
                print(f"[YTMusicAPI] No videoId found for: '{query}'")
                return None
        print(f"[YTMusicAPI] No results for: '{query}'")
        return None
    except Exception as e:
        print(f"[YTMusicAPI] Error: {e}")
        return None


# ---------------------------------------------------------------------------
# Spotify oEmbed — gratis, tanpa API key, tidak kena bot detection
# ---------------------------------------------------------------------------
def get_track_info_oembed(spotify_url: str) -> dict | None:
    """
    Gunakan Spotify oEmbed API untuk ambil judul lagu.
    Endpoint: https://open.spotify.com/oembed?url=<spotify_url>
    Response: {"title": "Song Name", "author_name": "Artist", ...}
    Tidak butuh auth, tidak ada rate limit ketat.
    """
    try:
        # Bersihkan query params dari URL (?si=xxx)
        clean_url = spotify_url.split("?")[0]
        oembed_url = f"https://open.spotify.com/oembed?url={clean_url}"
        print(f"[oEmbed] Fetching: {oembed_url}")

        resp = requests.get(oembed_url, headers=HEADERS, timeout=10)
        print(f"[oEmbed] Status: {resp.status_code}")

        if resp.status_code != 200:
            print(f"[oEmbed] Failed with status {resp.status_code}")
            return None

        data = resp.json()
        print(f"[oEmbed] Response: {data}")

        # oEmbed mengembalikan: title = "Song Name", author_name = "Artist"
        title  = data.get("title", "").strip()
        artist = data.get("author_name", "").strip()

        if not title:
            print("[oEmbed] No title in response")
            return None

        # Build query YouTube yang akurat
        query = f"{title} {artist}" if artist else title
        print(f"[oEmbed] title={title!r}, artist={artist!r}, query={query!r}")

        return {"title": title, "artist": artist, "query": query}

    except Exception as e:
        print(f"[oEmbed] Exception: {type(e).__name__}: {e}")
        return None


def get_playlist_info_oembed(spotify_url: str) -> dict | None:
    """Ambil nama playlist via oEmbed."""
    try:
        clean_url = spotify_url.split("?")[0]
        oembed_url = f"https://open.spotify.com/oembed?url={clean_url}"
        resp = requests.get(oembed_url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        return {
            "name": data.get("title", "Playlist"),
            "author": data.get("author_name", ""),
        }
    except Exception as e:
        print(f"[oEmbed Playlist] Exception: {e}")
        return None


# ---------------------------------------------------------------------------
# Scrape playlist tracks — Spotify embed page (tidak butuh auth)
# ---------------------------------------------------------------------------
def scrape_playlist_tracks(spotify_url: str) -> list[dict] | None:
    """
    Scrape track list dari Spotify embed page.
    URL: https://open.spotify.com/embed/playlist/<id>
    Halaman embed lebih ringan dan lebih mudah di-parse.
    """
    try:
        # Extract playlist ID
        m = re.search(r"/playlist/([a-zA-Z0-9]+)", spotify_url)
        if not m:
            print("[Playlist Scrape] Cannot extract playlist ID")
            return None

        playlist_id = m.group(1)
        embed_url   = f"https://open.spotify.com/embed/playlist/{playlist_id}"
        print(f"[Playlist Scrape] Fetching embed: {embed_url}")

        resp = requests.get(embed_url, headers=HEADERS, timeout=20)
        print(f"[Playlist Scrape] Status: {resp.status_code}, HTML: {len(resp.text)} chars")

        if resp.status_code != 200:
            return None

        html = resp.text

        # Cari JSON data yang di-embed di halaman
        # Spotify menyimpan track data di window.__NEXT_DATA__ atau script JSON
        tracks = []

        # Pattern 1: next data JSON blob
        next_data = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.+?)</script>', html, re.DOTALL)
        if next_data:
            import json
            try:
                jdata = json.loads(next_data.group(1))
                # Navigate ke track list
                # Path: props.pageProps.state.data.entity.trackList
                entity = (jdata.get("props", {})
                               .get("pageProps", {})
                               .get("state", {})
                               .get("data", {})
                               .get("entity", {}))

                track_list = entity.get("trackList", [])
                print(f"[Playlist Scrape] __NEXT_DATA__ found {len(track_list)} tracks")

                for t in track_list:
                    title  = t.get("title", "")
                    artist = t.get("subtitle", "")  # subtitle = artist name(s)
                    if title:
                        tracks.append({
                            "title": title,
                            "artist": artist,
                            "query": f"{title} {artist}" if artist else title,
                        })
            except Exception as e:
                print(f"[Playlist Scrape] __NEXT_DATA__ parse error: {e}")

        # Pattern 2: fallback regex on raw HTML
        if not tracks:
            print("[Playlist Scrape] Trying regex fallback...")
            entries = re.findall(
                r'"title"\s*:\s*"([^"]+)"[^}]*?"subtitle"\s*:\s*"([^"]+)"',
                html
            )
            seen = set()
            for title, artist in entries:
                key = f"{title}|{artist}"
                if key not in seen:
                    seen.add(key)
                    tracks.append({
                        "title": title,
                        "artist": artist,
                        "query": f"{title} {artist}",
                    })
            print(f"[Playlist Scrape] Regex fallback found {len(tracks)} tracks")

        if tracks:
            print(f"[Playlist Scrape] SUCCESS: {len(tracks)} tracks")
            for t in tracks[:3]:
                print(f"  - {t['title']} by {t['artist']}")
            return tracks

        print("[Playlist Scrape] No tracks found")
        return None

    except Exception as e:
        print(f"[Playlist Scrape] Exception: {type(e).__name__}: {e}")
        return None


# ---------------------------------------------------------------------------
# Helper: find downloaded file(s)
# ---------------------------------------------------------------------------
def get_actual_filename(temp_file_name: str) -> dict | None:
    print(f"[File Search] Looking for files with prefix: {temp_file_name}")
    try:
        files = list(OUTPUT_DIR.iterdir())
        print(f"[File Search] Files in output directory: {[f.name for f in files]}")

        # Cek apakah ini folder playlist
        possible_dir = OUTPUT_DIR / temp_file_name
        if possible_dir.exists() and possible_dir.is_dir():
            dir_files = [f for f in possible_dir.iterdir() if f.suffix == ".mp3"]
            if dir_files:
                # Cek apakah ini playlist atau single song dalam directory
                info = active_downloads.get(temp_file_name, {})
                if info.get("is_playlist"):
                    return {
                        "directory_path": str(possible_dir),
                        "files": [{"full_path": str(f), "filename": f.name} for f in dir_files],
                        "is_playlist": True,
                    }
                else:
                    return {
                        "full_path": str(dir_files[0]),
                        "filename": dir_files[0].name,
                        "is_audio": True,
                        "in_directory": True,
                        "directory_path": str(possible_dir),
                    }

        # Cek file langsung (single song)
        matched = [
            f for f in files
            if f.name.startswith(temp_file_name) and f.suffix in (".mp3", ".webm", ".m4a")
        ]
        if matched:
            return {"full_path": str(matched[0]), "filename": matched[0].name, "is_audio": True}

    except Exception as err:
        print(f"[File Search] Error: {err}")

    print(f"[File Search] No files found for: {temp_file_name}")
    return None


# ---------------------------------------------------------------------------
# yt-dlp worker — single track
# ---------------------------------------------------------------------------
def download_single(download_id: str, query: str, output_template: str):
    print(f"[Single Track] Starting: {download_id}")
    print(f"[Single Track] Query: {query}")

    info = active_downloads.get(download_id)
    if not info:
        return

    # 1. Coba dapatkan videoId yang tepat dari YouTube Music
    video_id = get_best_video_id(query)
    
    # 2. Tentukan URL target
    if video_id:
        target_url = f"https://www.youtube.com/watch?v={video_id}"
        print(f"[Single Track] Using specific video URL: {target_url}")
    else:
        target_url = f"ytsearch1:{query}"
        print(f"[Single Track] Fallback to general search: {target_url}")

    args = [
        "yt-dlp",
        target_url,
        "--extract-audio",
        "--audio-format", "mp3",
        "--audio-quality", "0",
        "--no-playlist",
        "--output", output_template,
        "--no-warnings",
        "--progress",
        "--force-overwrites",
    ]

    try:
        process = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
        )
        print(f"[Single Track] PID: {process.pid}")

        for line in process.stdout:
            line = line.rstrip()
            print(f"[yt-dlp] {line}")

            if not active_downloads.get(download_id):
                break

            if "[download]" in line and "%" in line:
                m = re.search(r"(\d+\.?\d*)%", line)
                if m:
                    pct = float(m.group(1))
                    info["progress"] = 10 + pct * 0.7
                    info["status"]   = "downloading"

            elif "[ExtractAudio]" in line:
                info["status"]   = "converting"
                info["progress"] = 85

        process.wait()
        code = process.returncode
        print(f"[Single Track] Exit code: {code}")

        if not active_downloads.get(download_id):
            return

        if code != 0:
            info["status"] = "error"
            return

        info["status"]   = "complete"
        info["progress"] = 100

    except Exception as e:
        print(f"[Single Track] Exception: {e}")
        if active_downloads.get(download_id):
            active_downloads[download_id]["status"] = "error"


# ---------------------------------------------------------------------------
# yt-dlp worker — playlist
# ---------------------------------------------------------------------------
def download_playlist_worker(download_id: str, tracks: list[dict], output_dir: str):
    print(f"[Playlist Worker] Starting: {download_id}, {len(tracks)} tracks")

    info = active_downloads.get(download_id)
    if not info:
        return

    total            = len(tracks)
    info["total_items"] = total
    info["status"]      = "downloading"

    for idx, track in enumerate(tracks, start=1):
        if not active_downloads.get(download_id):
            return

        query = track["query"]
        title = track["title"]
        info["current_item"] = title
        print(f"[Playlist Worker] {idx}/{total}: {title}")

        safe_title = re.sub(r'[\\/*?:"<>|]', "_", title)
        out_tmpl   = os.path.join(output_dir, f"{safe_title}.%(ext)s")

        # Cari videoId yang tepat untuk setiap lagu di playlist
        video_id = get_best_video_id(query)
        target_url = f"https://www.youtube.com/watch?v={video_id}" if video_id else f"ytsearch1:{query}"
        
        args = [
            "yt-dlp",
            target_url,
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "--no-playlist",
            "--output", out_tmpl,
            "--no-warnings",
            "--quiet",
            "--force-overwrites",
        ]

        try:
            result = subprocess.run(args, check=False, timeout=120, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"[Playlist Worker] Failed: {query}")
                if result.stderr:
                    print(f"[Playlist Worker] Error: {result.stderr[:200]}")
        except subprocess.TimeoutExpired:
            print(f"[Playlist Worker] Timeout: {query}")
        except Exception as e:
            print(f"[Playlist Worker] Error: {e}")

        info["completed_items"] = idx
        info["progress"]        = min(99, (idx / total) * 100)

    if active_downloads.get(download_id):
        info["status"]   = "complete"
        info["progress"] = 100
        pl_dir = Path(output_dir)
        info["files"] = [
            {"filename": f.name, "full_path": str(f)}
            for f in pl_dir.iterdir() if f.suffix == ".mp3"
        ]
        print(f"[Playlist Worker] Done: {len(info['files'])} files")


# ---------------------------------------------------------------------------
# POST /api/download
# ---------------------------------------------------------------------------
@app.route("/api/download", methods=["POST"])
def download():
    body = request.get_json(silent=True) or {}
    url  = body.get("url", "").strip()

    print(f"[Download API] URL: {url}")

    if not url or "spotify.com" not in url:
        return jsonify({"success": False, "error": "URL Spotify tidak valid"}), 400

    is_playlist     = "/playlist/" in url
    is_single_track = "/track/"   in url

    if not is_playlist and not is_single_track:
        return jsonify({"success": False, "error": "URL harus berupa lagu atau playlist Spotify"}), 400

    prefix      = "playlist" if is_playlist else "song"
    download_id = f"{prefix}-{int(time.time() * 1000)}"
    output_path = str(OUTPUT_DIR / download_id)

    active_downloads[download_id] = {
        "progress": 0, "total_items": 0, "completed_items": 0,
        "current_item": "", "status": "preparing",
        "is_playlist": is_playlist, "files": [],
    }

    if is_single_track:
        # --- Gunakan oEmbed API, jauh lebih reliable dari scraping ---
        track_info = get_track_info_oembed(url)

        if track_info:
            query = track_info["query"]
            active_downloads[download_id]["current_item"] = track_info["title"]
            print(f"[Download API] oEmbed OK → {query!r}")
        else:
            query = "spotify song"
            active_downloads[download_id]["current_item"] = "Unknown Track"
            print(f"[Download API] oEmbed FAILED, cannot determine song title")
            active_downloads[download_id]["status"] = "error"
            return jsonify({
                "success": False,
                "error": "Tidak dapat mengambil info lagu. Coba lagi beberapa saat."
            }), 400

        active_downloads[download_id]["status"]   = "downloading"
        active_downloads[download_id]["progress"] = 5

        threading.Thread(
            target=download_single,
            args=(download_id, query, f"{output_path}.%(ext)s"),
            daemon=True,
        ).start()

    else:
        Path(output_path).mkdir(parents=True, exist_ok=True)

        # Ambil info playlist via oEmbed
        pl_info = get_playlist_info_oembed(url)
        if pl_info:
            active_downloads[download_id]["current_item"] = pl_info["name"]

        # Scrape track list dari embed page
        tracks = scrape_playlist_tracks(url)
        if not tracks:
            active_downloads[download_id]["status"] = "error"
            return jsonify({"success": False, "error": "Gagal mengambil daftar lagu dari playlist"}), 400

        active_downloads[download_id]["total_items"] = len(tracks)
        active_downloads[download_id]["status"]      = "downloading"

        threading.Thread(
            target=download_playlist_worker,
            args=(download_id, tracks, output_path),
            daemon=True,
        ).start()

    return jsonify({
        "success": True,
        "downloadId": download_id,
        "isPlaylist": is_playlist,
        "checkStatusUrl": f"/api/download-status/{download_id}",
    })


# ---------------------------------------------------------------------------
# GET /api/download-status/<downloadId>
# ---------------------------------------------------------------------------
@app.route("/api/download-status/<download_id>", methods=["GET"])
def download_status(download_id: str):
    if download_id not in active_downloads:
        return jsonify({"success": False, "error": "Download tidak ditemukan"}), 404

    info = active_downloads[download_id]
    print(f"[Status] {download_id}: {info['status']} {info['progress']:.0f}%")

    if info["status"] == "complete":
        if info["is_playlist"]:
            # Untuk playlist, langsung cek apakah folder exists
            playlist_dir = OUTPUT_DIR / download_id
            
            print(f"[Status Check] Checking playlist dir: {playlist_dir}")
            print(f"[Status Check] Dir exists: {playlist_dir.exists()}")
            print(f"[Status Check] Is dir: {playlist_dir.is_dir()}")
            
            if playlist_dir.exists() and playlist_dir.is_dir():
                # Hitung semua file MP3 di folder
                mp3_files = list(playlist_dir.glob("*.mp3"))
                total_size = sum(f.stat().st_size for f in mp3_files if f.exists())
                
                response_data = {
                    "success": True,
                    "status": info["status"],
                    "progress": info["progress"],
                    "isPlaylist": info["is_playlist"],
                    "totalItems": info.get("total_items", 0),
                    "completedItems": info.get("completed_items", 0),
                    "currentItem": info.get("current_item", ""),
                    "playlistPath": download_id,
                    "totalFiles": len(mp3_files),
                    "fileSize": {
                        "bytes": total_size,
                        "megabytes": f"{total_size / (1024 * 1024):.2f} MB",
                    },
                    "downloadUrl": f"/api/download-playlist/{download_id}",
                }
                
                print(f"[Status Response] Sending response: {response_data}")
                return jsonify(response_data)
            else:
                print(f"[Status] ERROR: Playlist directory not found or not a dir")
                return jsonify({
                    "success": False,
                    "error": "Playlist directory not found",
                    **info
                })
        else:
            # Untuk single song
            file_info = get_actual_filename(download_id)
            
            print(f"[Status Check] File info: {file_info}")
            
            if file_info and (file_info.get("is_audio") or file_info.get("in_directory")):
                try:
                    size = Path(file_info["full_path"]).stat().st_size
                    response_data = {
                        "success": True,
                        "status": info["status"],
                        "progress": info["progress"],
                        "isPlaylist": info["is_playlist"],
                        "fileName": file_info["filename"],
                        "songName": Path(file_info["filename"]).stem,
                        "fileSize": {
                            "bytes": size,
                            "megabytes": f"{size / (1024 * 1024):.2f} MB",
                        },
                        "directDownloadUrl": f"/api/direct-download/{download_id}",
                    }
                    print(f"[Status Response] Sending response: {response_data}")
                    return jsonify(response_data)
                except Exception as e:
                    print(f"[Status] ERROR: File info error: {e}")
                    return jsonify({
                        "success": False,
                        "error": f"File error: {e}",
                        **info
                    })
            else:
                print(f"[Status] ERROR: File not found for: {download_id}")
                return jsonify({
                    "success": False,
                    "error": "File not found",
                    **info
                })

    # Return in-progress status
    return jsonify({"success": True, **info})


# ---------------------------------------------------------------------------
# GET /api/direct-download/<tempFileName>
# ---------------------------------------------------------------------------
@app.route("/api/direct-download/<temp_file_name>", methods=["GET"])
def direct_download(temp_file_name: str):
    try:
        file_info = get_actual_filename(temp_file_name)
        if not file_info or (
            file_info.get("is_playlist")
            and not file_info.get("is_audio")
            and not file_info.get("in_directory")
        ):
            return jsonify({"success": False, "error": "File tidak ditemukan"}), 404

        full_path = Path(file_info["full_path"])
        filename  = file_info["filename"]

        def generate_and_cleanup():
            try:
                with open(full_path, "rb") as fh:
                    while chunk := fh.read(65536):
                        yield chunk
            finally:
                time.sleep(1)
                try:
                    full_path.unlink()
                except Exception:
                    pass
                active_downloads.pop(temp_file_name, None)
                if file_info.get("in_directory"):
                    shutil.rmtree(file_info["directory_path"], ignore_errors=True)
                else:
                    parent = full_path.parent
                    if parent != OUTPUT_DIR:
                        try:
                            if not any(parent.iterdir()):
                                parent.rmdir()
                        except Exception:
                            pass

        response = Response(generate_and_cleanup(), mimetype="audio/mpeg")
        response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response

    except Exception as err:
        print(f"[Direct Download] Error: {err}")
        return jsonify({"success": False, "error": "Terjadi kesalahan server"}), 500


# ---------------------------------------------------------------------------
# GET /api/download-playlist/<playlistId>
# ---------------------------------------------------------------------------
@app.route("/api/download-playlist/<playlist_id>", methods=["GET"])
def download_playlist_zip(playlist_id: str):
    playlist_dir = OUTPUT_DIR / playlist_id
    if not playlist_dir.exists() or not playlist_dir.is_dir():
        return jsonify({"success": False, "error": "Playlist tidak ditemukan"}), 404

    zip_path = OUTPUT_DIR / f"{playlist_id}.zip"
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for mp3 in playlist_dir.rglob("*.mp3"):
                zf.write(mp3, arcname=f"{playlist_id}/{mp3.name}")
    except Exception:
        return jsonify({"success": False, "error": "Gagal membuat file ZIP"}), 500

    def stream_and_cleanup():
        try:
            with open(zip_path, "rb") as fh:
                while chunk := fh.read(65536):
                    yield chunk
        finally:
            zip_path.unlink(missing_ok=True)
            shutil.rmtree(playlist_dir, ignore_errors=True)
            active_downloads.pop(playlist_id, None)

    response = Response(stream_and_cleanup(), mimetype="application/zip")
    response.headers["Content-Disposition"] = f'attachment; filename="{playlist_id}.zip"'
    return response


# ---------------------------------------------------------------------------
# GET /api/playlist-files/<playlistId> - FIXED!
# ---------------------------------------------------------------------------
@app.route("/api/playlist-files/<playlist_id>", methods=["GET"])
def playlist_files(playlist_id: str):
    """Get list of files in a playlist directory."""
    print(f"[Playlist Files] Request for playlist: {playlist_id}")
    
    playlist_dir = OUTPUT_DIR / playlist_id
    
    print(f"[Playlist Files] Checking directory: {playlist_dir}")
    print(f"[Playlist Files] Directory exists: {playlist_dir.exists()}")
    print(f"[Playlist Files] Is directory: {playlist_dir.is_dir()}")
    
    if not playlist_dir.exists() or not playlist_dir.is_dir():
        print(f"[Playlist Files] ERROR: Directory not found or not a directory")
        return jsonify({"success": False, "error": "Playlist tidak ditemukan"}), 404

    try:
        files = []
        all_files = list(playlist_dir.iterdir())
        print(f"[Playlist Files] Found {len(all_files)} total files")
        
        for f in sorted(all_files):
            if f.suffix != ".mp3":
                print(f"[Playlist Files] Skipping non-MP3 file: {f.name}")
                continue
            
            try:
                size = f.stat().st_size
                file_data = {
                    "fileName": f.name,
                    "songName": f.stem,
                    "fileSize": {
                        "bytes": size,
                        "megabytes": f"{size / (1024 * 1024):.2f} MB",
                    },
                    "downloadUrl": f"/api/playlist-file/{playlist_id}/{f.name}",
                }
                files.append(file_data)
                print(f"[Playlist Files] Added file: {f.name} ({size} bytes)")
            except Exception as file_err:
                print(f"[Playlist Files] Error processing file {f.name}: {file_err}")
                continue
        
        print(f"[Playlist Files] Returning {len(files)} MP3 files")
        return jsonify({"success": True, "files": files})
        
    except Exception as e:
        print(f"[Playlist Files] ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": "Terjadi kesalahan server"}), 500


# ---------------------------------------------------------------------------
# GET /api/playlist-file/<playlistId>/<fileName>
# ---------------------------------------------------------------------------
@app.route("/api/playlist-file/<playlist_id>/<file_name>", methods=["GET"])
def playlist_file(playlist_id: str, file_name: str):
    """Download a single file from a playlist."""
    print(f"[Playlist File] Request for: {playlist_id}/{file_name}")
    
    file_path = OUTPUT_DIR / playlist_id / file_name
    
    print(f"[Playlist File] Checking path: {file_path}")
    print(f"[Playlist File] File exists: {file_path.exists()}")
    
    if not file_path.exists():
        print(f"[Playlist File] ERROR: File not found")
        return jsonify({"success": False, "error": "File tidak ditemukan"}), 404
    
    try:
        return send_file(
            str(file_path),
            mimetype="audio/mpeg",
            as_attachment=True,
            download_name=file_name
        )
    except Exception as e:
        print(f"[Playlist File] ERROR: {type(e).__name__}: {e}")
        return jsonify({"success": False, "error": "Gagal mengirim file"}), 500


# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------
@app.route("/", defaults={"path": ""})
@app.route("/<path:path>")
def serve_static(path):
    static_folder = app.static_folder
    if static_folder and path and (Path(static_folder) / path).exists():
        return send_from_directory(static_folder, path)
    index = Path(static_folder) / "index.html" if static_folder else None
    if index and index.exists():
        return send_file(str(index))
    return jsonify({"error": "Not found"}), 404


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 3001))
    print(f"Server berjalan di http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)