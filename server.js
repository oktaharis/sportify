const express = require('express');
const { exec } = require('child_process');
const path = require('path');
const fs = require('fs');
const app = express();
require('dotenv').config();
const cors = require('cors');

app.use(cors());
app.use(express.json());
app.use(express.static(path.join(__dirname, 'public')));

const outputDir = path.join(__dirname, 'downloads');
if (!fs.existsSync(outputDir)) {
  fs.mkdirSync(outputDir, { recursive: true });
}

function getActualFilename(tempFileName) {
  try {
    const files = fs.readdirSync(outputDir);
    const matchedFiles = files.filter(file => 
      file.startsWith(tempFileName) && 
      (file.endsWith('.mp3') || file.endsWith('.webm'))
    );

    if (matchedFiles.length > 0) {
      return {
        fullPath: path.join(outputDir, matchedFiles[0]),
        filename: matchedFiles[0],
        isAudio: true
      };
    }
    
    const possibleDir = path.join(outputDir, tempFileName);
    if (fs.existsSync(possibleDir) && fs.lstatSync(possibleDir).isDirectory()) {
      const dirFiles = fs.readdirSync(possibleDir).filter(f => f.endsWith('.mp3'));
      if (dirFiles.length > 0) {
        return {
          fullPath: path.join(possibleDir, dirFiles[0]),
          filename: dirFiles[0],
          isAudio: true
        };
      }
    }
  } catch (err) {
    console.error('File search error:', err);
  }
  return null;
}

app.post('/api/download', (req, res) => {
  const { url } = req.body;
  
  if (!url || !url.includes('spotify.com')) {
    return res.status(400).json({ 
      success: false, 
      error: 'URL Spotify tidak valid' 
    });
  }
  
  const tempFileName = `song-${Date.now()}`;
  const outputFile = path.join(outputDir, tempFileName);
  let commandOutput = '';
  
  const childProcess = exec(
    `spotdl "${url}" --output "${outputFile}" --format mp3`,
    { timeout: 120000 },
    (error, stdout, stderr) => {
      if (error) {
        console.error('Download error:', error.message);
        return res.status(500).json({ 
          success: false, 
          error: 'Gagal mengunduh lagu',
          details: stderr || error.message
        });
      }
      
      const fileInfo = getActualFilename(tempFileName);
      if (!fileInfo || !fileInfo.isAudio) {
        return res.status(404).json({
          success: false,
          error: 'File audio tidak ditemukan'
        });
      }

      const stats = fs.statSync(fileInfo.fullPath);
      res.json({
        success: true,
        directDownloadUrl: `/api/direct-download/${tempFileName}`,
        fileName: fileInfo.filename,
        songName: fileInfo.filename.replace('.mp3', ''),
        fileSize: {
          bytes: stats.size,
          megabytes: (stats.size / (1024 * 1024)).toFixed(2) + ' MB'
        }
      });
    }
  );

  childProcess.stdout.on('data', (data) => commandOutput += data);
  childProcess.stderr.on('data', (data) => commandOutput += data);
  
  childProcess.on('timeout', () => {
    childProcess.kill();
    res.status(504).json({
      success: false,
      error: 'Proses timeout'
    });
  });
});

app.get('/api/direct-download/:tempFileName', (req, res) => {
  const tempFileName = req.params.tempFileName;
  console.log('[Direct Download] Mencari file untuk:', tempFileName); // Log 1
  
  try {
    const fileInfo = getActualFilename(tempFileName);
    console.log('[Direct Download] File info:', fileInfo); // Log 2

    if (!fileInfo || !fileInfo.isAudio) {
      console.error('[Direct Download] File tidak ditemukan untuk:', tempFileName); // Log 3
      return res.status(404).json({
        success: false,
        error: 'File tidak ditemukan'
      });
    }

    console.log('[Direct Download] Mengirim file:', fileInfo.filename); // Log 4
    
    res.setHeader('Content-Disposition', `attachment; filename="${encodeURIComponent(fileInfo.filename)}"`);
    res.setHeader('Content-Type', 'audio/mpeg');

    const fileStream = fs.createReadStream(fileInfo.fullPath);
    
    fileStream.on('error', (err) => {
      console.error('[Direct Download] Error streaming:', err); // Log 5
      if (!res.headersSent) {
        res.status(500).json({
          success: false,
          error: 'Gagal mengirim file'
        });
      }
    });

    fileStream.pipe(res);

    fileStream.on('end', () => {
      console.log('[Direct Download] File berhasil dikirim, membersihkan...'); // Log 6
      try {
        // Hapus file utama
        fs.unlinkSync(fileInfo.fullPath);
        console.log('[Direct Download] File utama dihapus');
        
        // Hapus folder kosong jika ada
        const parentDir = path.dirname(fileInfo.fullPath);
        if (parentDir !== outputDir) {
          const filesInDir = fs.readdirSync(parentDir);
          if (filesInDir.length === 0) {
            fs.rmdirSync(parentDir);
            console.log('[Direct Download] Folder kosong dihapus');
          }
        }
      } catch (err) {
        console.error('[Direct Download] Gagal membersihkan file:', err);
      }
    });

  } catch (err) {
    console.error('[Direct Download] Error:', err); // Log 7
    res.status(500).json({
      success: false,
      error: 'Terjadi kesalahan server'
    });
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Server running on port ${PORT}`);
});