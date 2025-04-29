const express = require("express")
const { exec, spawn } = require("child_process")
const path = require("path")
const fs = require("fs")
const app = express()
require("dotenv").config()
const cors = require("cors")
const archiver = require('archiver');

app.use(cors())
app.use(express.json())
app.use(express.static(path.join(__dirname, "public")))

const outputDir = path.join(__dirname, "downloads")
if (!fs.existsSync(outputDir)) {
  fs.mkdirSync(outputDir, { recursive: true })
}

// Track active downloads with their progress
const activeDownloads = new Map()

// Perbaiki fungsi getActualFilename untuk menangani kasus ketika single song disimpan dalam folder
function getActualFilename(tempFileName) {
  console.log(`[File Search] Looking for files with prefix: ${tempFileName}`)
  try {
    const files = fs.readdirSync(outputDir)
    console.log(`[File Search] Files in output directory:`, files)

    // Cek apakah ada file MP3 langsung dengan nama yang sesuai
    const matchedFiles = files.filter(
      (file) => file.startsWith(tempFileName) && (file.endsWith(".mp3") || file.endsWith(".webm")),
    )
    console.log(`[File Search] Matched files:`, matchedFiles)

    if (matchedFiles.length > 0) {
      return {
        fullPath: path.join(outputDir, matchedFiles[0]),
        filename: matchedFiles[0],
        isAudio: true,
      }
    }

    // Cek apakah ada folder dengan nama yang sesuai (bisa jadi playlist atau single song dalam folder)
    const possibleDir = path.join(outputDir, tempFileName)
    console.log(`[File Search] Checking if directory exists: ${possibleDir}`)

    if (fs.existsSync(possibleDir) && fs.lstatSync(possibleDir).isDirectory()) {
      const dirFiles = fs.readdirSync(possibleDir).filter((f) => f.endsWith(".mp3"))
      console.log(`[File Search] Files in directory:`, dirFiles)

      if (dirFiles.length > 0) {
        // Jika ini adalah single song yang disimpan dalam folder
        if (!activeDownloads.get(tempFileName)?.isPlaylist) {
          console.log(`[File Search] This is a single song stored in a directory`)
          return {
            fullPath: path.join(possibleDir, dirFiles[0]),
            filename: dirFiles[0],
            isAudio: true,
            inDirectory: true,
            directoryPath: possibleDir,
          }
        }
        // Jika ini adalah playlist
        else {
          return {
            directoryPath: possibleDir,
            files: dirFiles.map((file) => ({
              fullPath: path.join(possibleDir, file),
              filename: file,
            })),
            isPlaylist: true,
          }
        }
      }
    }
  } catch (err) {
    console.error("[File Search] Error:", err)
  }
  console.log(`[File Search] No files found for: ${tempFileName}`)
  return null
}

// Perbaiki deteksi URL untuk membedakan antara single song dan playlist
app.post("/api/download", (req, res) => {
  const { url } = req.body

  if (!url || !url.includes("spotify.com")) {
    return res.status(400).json({
      success: false,
      error: "URL Spotify tidak valid",
    })
  }

  // Perbaiki deteksi URL untuk membedakan antara single song dan playlist
  const isPlaylist = url.includes("/playlist/")
  const isSingleTrack = url.includes("/track/")

  if (!isPlaylist && !isSingleTrack) {
    return res.status(400).json({
      success: false,
      error: "URL harus berupa lagu atau playlist Spotify",
    })
  }

  const tempFileName = `${isPlaylist ? "playlist" : "song"}-${Date.now()}`
  const outputPath = path.join(outputDir, tempFileName)

  // Create a unique ID for tracking this download
  const downloadId = tempFileName

  // Initialize download info in our tracking map
  activeDownloads.set(downloadId, {
    progress: 0,
    totalItems: 0,
    completedItems: 0,
    currentItem: "",
    status: "preparing",
    isPlaylist,
    files: [],
  })

  // For playlists, create a directory
  if (isPlaylist && !fs.existsSync(outputPath)) {
    fs.mkdirSync(outputPath, { recursive: true })
  }

  // Prepare the command
  const command = isPlaylist
    ? `spotdl "${url}" --output "${outputPath}" --format mp3`
    : `spotdl "${url}" --output "${outputDir}/${tempFileName}" --format mp3`

  console.log(`Executing: ${command}`)

  // Use spawn instead of exec for better output handling
  const childProcess = spawn("spotdl", [
    url,
    "--output",
    isPlaylist ? outputPath : `${outputDir}/${tempFileName}`,
    "--format",
    "mp3",
  ])

  let commandOutput = ""
  const playlistInfo = {
    name: "",
    totalSongs: 0,
    downloadedSongs: [],
  }

  childProcess.stdout.on("data", (data) => {
    const output = data.toString()
    commandOutput += output
    console.log("spotdl output:", output) // Tambahkan log untuk debugging

    // Update progress information
    if (isPlaylist) {
      // Try to extract playlist name and song count
      const playlistMatch = output.match(/Found (\d+) songs in (.+)/)
      if (playlistMatch) {
        activeDownloads.get(downloadId).totalItems = Number.parseInt(playlistMatch[1])
        playlistInfo.totalSongs = Number.parseInt(playlistMatch[1])
        playlistInfo.name = playlistMatch[2].trim()
        activeDownloads.get(downloadId).status = "downloading"
      }

      // Extract downloaded song info
      const downloadedMatch = output.match(/Downloaded "([^"]+)": (https?:\/\/[^\s]+)/)
      if (downloadedMatch) {
        const songName = downloadedMatch[1]
        activeDownloads.get(downloadId).completedItems++
        activeDownloads.get(downloadId).currentItem = songName

        // Calculate progress as percentage
        const progress =
          (activeDownloads.get(downloadId).completedItems / activeDownloads.get(downloadId).totalItems) * 100
        activeDownloads.get(downloadId).progress = Math.min(99, progress) // Cap at 99% until fully complete

        // Add to downloaded songs
        playlistInfo.downloadedSongs.push(songName)
      }

      // Extract progress info
      const progressMatch = output.match(/Total\s+(\d+)\/(\d+) complete/)
      if (progressMatch) {
        activeDownloads.get(downloadId).completedItems = Number.parseInt(progressMatch[1])
        activeDownloads.get(downloadId).totalItems = Number.parseInt(progressMatch[2])

        // Calculate progress as percentage
        const progress = (Number.parseInt(progressMatch[1]) / Number.parseInt(progressMatch[2])) * 100
        activeDownloads.get(downloadId).progress = Math.min(99, progress) // Cap at 99% until fully complete
      }
    } else {
      // For single songs, parse progress differently
      if (output.includes("Downloading")) {
        activeDownloads.get(downloadId).status = "downloading"
        activeDownloads.get(downloadId).progress = 30
      } else if (output.includes("Converting")) {
        activeDownloads.get(downloadId).status = "converting"
        activeDownloads.get(downloadId).progress = 80
      } else if (output.includes("Downloaded")) {
        activeDownloads.get(downloadId).status = "finalizing"
        activeDownloads.get(downloadId).progress = 95

        // Try to extract song name
        const match = output.match(/Downloaded "([^"]+)"/)
        if (match && match[1]) {
          activeDownloads.get(downloadId).currentItem = match[1]
        }
      }
    }
  })

  childProcess.stderr.on("data", (data) => {
    const errorOutput = data.toString()
    commandOutput += errorOutput
    console.error("spotdl error:", errorOutput) // Tambahkan log untuk debugging
  })

  childProcess.on("close", (code) => {
    console.log(`Child process exited with code ${code}`)

    if (code !== 0) {
      activeDownloads.get(downloadId).status = "error"
      return
    }

    activeDownloads.get(downloadId).status = "complete"
    activeDownloads.get(downloadId).progress = 100

    // For playlists, update the files list
    if (isPlaylist) {
      try {
        const dirFiles = fs.readdirSync(outputPath).filter((f) => f.endsWith(".mp3"))
        activeDownloads.get(downloadId).files = dirFiles.map((file) => ({
          filename: file,
          fullPath: path.join(outputPath, file),
        }))
      } catch (err) {
        console.error("Error reading playlist directory:", err)
      }
    }
  })

  // Send initial response immediately
  res.json({
    success: true,
    downloadId,
    isPlaylist,
    checkStatusUrl: `/api/download-status/${downloadId}`,
  })
})

// New endpoint to check download status
// Tambahkan logging lebih detail untuk debugging
// Perbaiki endpoint status untuk menangani single song yang disimpan dalam folder
app.get("/api/download-status/:downloadId", (req, res) => {
  const downloadId = req.params.downloadId
  console.log(`[Status Check] Checking status for download: ${downloadId}`)

  if (!activeDownloads.has(downloadId)) {
    console.log(`[Status Check] Download not found: ${downloadId}`)
    return res.status(404).json({
      success: false,
      error: "Download tidak ditemukan",
    })
  }

  const downloadInfo = activeDownloads.get(downloadId)
  console.log(`[Status Check] Current status: ${downloadInfo.status}, Progress: ${downloadInfo.progress}%`)

  // For completed downloads, include file information
  if (downloadInfo.status === "complete") {
    if (downloadInfo.isPlaylist) {
      // For playlists, get the directory information
      const fileInfo = getActualFilename(downloadId)
      console.log(`[Status Check] Playlist file info:`, fileInfo)

      if (fileInfo && fileInfo.isPlaylist) {
        // Calculate total size
        let totalSize = 0
        fileInfo.files.forEach((file) => {
          try {
            const stats = fs.statSync(file.fullPath)
            totalSize += stats.size
          } catch (err) {
            console.error(`Error getting file size for ${file.filename}:`, err)
          }
        })

        return res.json({
          success: true,
          ...downloadInfo,
          playlistPath: downloadId,
          totalFiles: fileInfo.files.length,
          fileSize: {
            bytes: totalSize,
            megabytes: (totalSize / (1024 * 1024)).toFixed(2) + " MB",
          },
          downloadUrl: `/api/download-playlist/${downloadId}`,
        })
      }
    } else {
      // For single songs
      const fileInfo = getActualFilename(downloadId)
      console.log(`[Status Check] Single song file info:`, fileInfo)

      // Jika file ditemukan (baik langsung di folder downloads atau dalam subfolder)
      if (fileInfo && (fileInfo.isAudio || fileInfo.inDirectory)) {
        try {
          const stats = fs.statSync(fileInfo.fullPath)
          return res.json({
            success: true,
            ...downloadInfo,
            fileName: fileInfo.filename,
            songName: fileInfo.filename.replace(".mp3", ""),
            fileSize: {
              bytes: stats.size,
              megabytes: (stats.size / (1024 * 1024)).toFixed(2) + " MB",
            },
            directDownloadUrl: `/api/direct-download/${downloadId}`,
          })
        } catch (err) {
          console.error("Error getting file info:", err)
        }
      }
    }
  }

  // Return progress info
  return res.json({
    success: true,
    ...downloadInfo,
  })
})

// Direct download endpoint for single songs
// Perbaiki endpoint direct-download untuk menangani single song yang disimpan dalam folder
app.get("/api/direct-download/:tempFileName", (req, res) => {
  const tempFileName = req.params.tempFileName
  console.log("[Direct Download] Mencari file untuk:", tempFileName)

  try {
    const fileInfo = getActualFilename(tempFileName)
    console.log("[Direct Download] File info:", fileInfo)

    // Jika file tidak ditemukan atau terdeteksi sebagai playlist (dan bukan single song dalam folder)
    if (!fileInfo || (fileInfo.isPlaylist && !fileInfo.isAudio && !fileInfo.inDirectory)) {
      console.error("[Direct Download] File tidak ditemukan untuk:", tempFileName)
      return res.status(404).json({
        success: false,
        error: "File tidak ditemukan",
      })
    }

    console.log("[Direct Download] Mengirim file:", fileInfo.filename)

    res.setHeader("Content-Disposition", `attachment; filename="${encodeURIComponent(fileInfo.filename)}"`)
    res.setHeader("Content-Type", "audio/mpeg")

    const fileStream = fs.createReadStream(fileInfo.fullPath)

    fileStream.on("error", (err) => {
      console.error("[Direct Download] Error streaming:", err)
      if (!res.headersSent) {
        res.status(500).json({
          success: false,
          error: "Gagal mengirim file",
        })
      }
    })

    fileStream.pipe(res)

    fileStream.on("end", () => {
      console.log("[Direct Download] File berhasil dikirim, membersihkan...")
      try {
        // Delay file deletion to ensure it's fully sent
        setTimeout(() => {
          // Hapus file utama
          fs.unlinkSync(fileInfo.fullPath)
          console.log("[Direct Download] File utama dihapus")

          // Remove from active downloads
          activeDownloads.delete(tempFileName)

          // Hapus folder jika file berada dalam folder
          if (fileInfo.inDirectory && fileInfo.directoryPath) {
            fs.rmdirSync(fileInfo.directoryPath, { recursive: true })
            console.log("[Direct Download] Folder dihapus:", fileInfo.directoryPath)
          } else {
            // Hapus folder kosong jika ada
            const parentDir = path.dirname(fileInfo.fullPath)
            if (parentDir !== outputDir) {
              const filesInDir = fs.readdirSync(parentDir)
              if (filesInDir.length === 0) {
                fs.rmdirSync(parentDir)
                console.log("[Direct Download] Folder kosong dihapus")
              }
            }
          }
        }, 1000)
      } catch (err) {
        console.error("[Direct Download] Gagal membersihkan file:", err)
      }
    })
  } catch (err) {
    console.error("[Direct Download] Error:", err)
    res.status(500).json({
      success: false,
      error: "Terjadi kesalahan server",
    })
  }
})

// New endpoint for playlist downloads
app.get("/api/download-playlist/:playlistId", (req, res) => {
  const playlistId = req.params.playlistId;
  const playlistDir = path.join(outputDir, playlistId);

  if (!fs.existsSync(playlistDir) || !fs.lstatSync(playlistDir).isDirectory()) {
    return res.status(404).json({
      success: false,
      error: "Playlist tidak ditemukan",
    });
  }

  const zipFileName = `${playlistId}.zip`;

  res.setHeader("Content-Disposition", `attachment; filename="${encodeURIComponent(zipFileName)}"`);
  res.setHeader("Content-Type", "application/zip");

  const archive = archiver('zip', { zlib: { level: 9 } });

  archive.on('error', (err) => {
    console.error('Error creating ZIP archive:', err);
    if (!res.headersSent) {
      res.status(500).json({
        success: false,
        error: "Gagal membuat file ZIP"
      });
    }
  });

  archive.pipe(res);

  archive.directory(playlistDir, playlistId);

  archive.finalize();

  archive.on('close', () => {
    console.log(`ZIP archive for playlist ${playlistId} created. Cleaning up...`);
    try {
      fs.rmdirSync(playlistDir, { recursive: true });
      activeDownloads.delete(playlistId);
    } catch (err) {
      console.error('Gagal membersihkan direktori:', err);
    }
  });
})

// Download individual file from playlist
app.get("/api/playlist-file/:playlistId/:fileName", (req, res) => {
  const { playlistId, fileName } = req.params
  const filePath = path.join(outputDir, playlistId, fileName)

  if (!fs.existsSync(filePath)) {
    return res.status(404).json({
      success: false,
      error: "File tidak ditemukan",
    })
  }

  res.setHeader("Content-Disposition", `attachment; filename="${encodeURIComponent(fileName)}"`)
  res.setHeader("Content-Type", "audio/mpeg")

  const fileStream = fs.createReadStream(filePath)

  fileStream.on("error", (err) => {
    console.error(`Error streaming file ${fileName}:`, err)
    if (!res.headersSent) {
      res.status(500).json({
        success: false,
        error: "Gagal mengirim file",
      })
    }
  })

  fileStream.pipe(res)
})

// List files in a playlist
app.get("/api/playlist-files/:playlistId", (req, res) => {
  const playlistId = req.params.playlistId
  const playlistDir = path.join(outputDir, playlistId)

  if (!fs.existsSync(playlistDir) || !fs.lstatSync(playlistDir).isDirectory()) {
    return res.status(404).json({
      success: false,
      error: "Playlist tidak ditemukan",
    })
  }

  try {
    const files = fs
      .readdirSync(playlistDir)
      .filter((file) => file.endsWith(".mp3"))
      .map((file) => {
        const stats = fs.statSync(path.join(playlistDir, file))
        return {
          fileName: file,
          songName: file.replace(".mp3", ""),
          fileSize: {
            bytes: stats.size,
            megabytes: (stats.size / (1024 * 1024)).toFixed(2) + " MB",
          },
          downloadUrl: `/api/playlist-file/${playlistId}/${encodeURIComponent(file)}`,
        }
      })

    res.json({
      success: true,
      files,
    })
  } catch (err) {
    console.error("Error listing playlist files:", err)
    res.status(500).json({
      success: false,
      error: "Terjadi kesalahan server",
    })
  }
})

if (!process.env.VERCEL) {
  const PORT = process.env.PORT || 3000;
  app.listen(PORT, () => {
    console.log(`Server berjalan di http://localhost:${PORT}`);
  });
}
module.exports = app;