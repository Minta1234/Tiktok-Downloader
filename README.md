# 🚀 AI Media Suite: Pro TikTok & Media Toolkit

A high-performance, AI-powered desktop application for media professionals. This suite combines state-of-the-art AI models for upscaling, translation, and object removal with a powerful media downloader.

![Version](https://img.shields.io/badge/Version-1.0.0-fe2c55?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.10+-25f4ee?style=for-the-badge)

---

##  Core Features

###  **TikTok Image Agent (SnapTik Logic)**
Extract hidden, high-quality images from TikTok photo posts.
*   **Metadata Scanner**: Parses embedded JSON blobs to find source URLs.
*   **No Watermark**: Downloads the original images without platform overlays.
*   **Batch Extraction**: One-click download for entire galleries.

###  **Pro Media Downloader**
Universal downloader with integrated AI enhancement.
*   **Multi-Platform**: Support for TikTok, YouTube, and more via `yt-dlp`.
*   **AI Auto-Upscale**: Automatically upscale downloads to **4K** using Real-ESRGAN.
*   **Queue Management**: Batch process multiple links simultaneously.

###  **AI Object Remover**
Professional-grade inpainting for photos and videos.
*   **Big-LaMa Model**: High-precision object removal using deep learning.
*   **Video Inpainting**: Process entire video segments to remove unwanted logos or people.

###  **AI Video Translator**
Break language barriers with automated transcription and translation.
*   **OpenAI Whisper**: High-accuracy speech-to-text.
*   **Deep Translation**: Support for 15+ languages including Thai, Japanese, and Korean.

###  **AI Image Finder**
Find similar images in your local library.
*   **Perceptual Hashing**: Uses `a-hash` and pixel-level comparison to find visual matches.
*   **Hybrid Scan**: Combines fast hashing with deep pixel analysis for 99% accuracy.

###  **Video Annotation & Frame Extraction**
*   **Frame Extractor**: Extract specific frames from TikTok videos and upscale them to PNG.
*   **Live Draw**: Add drawings or annotations directly onto video frames.

### **BuildInstaller**
* **Make EXE**:Use pyinstaller
* **installer**: Use inno Setup compiler For Build installer.
---

##  Technical Architecture

*   **GUI Framework**: Python `Tkinter` with a custom-engineered "Obsidian Dark" theme.
*   **AI Engine**: `PyTorch` (CUDA acceleration supported).
*   **Models**:
    *   **Upscaling**: `Real-ESRGAN (NCNN-Vulkan)`
    *   **Speech**: `OpenAI Whisper (Base)`
    *   **Inpainting**: `Big-LaMa (TorchScript)`
*   **Media Core**: `yt-dlp` & `FFmpeg`.

---

##  Getting Started

### Prerequisites
*   Windows 10/11 (Recommended)
*   Python 3.10 or higher
*   NVIDIA GPU with 4GB+ VRAM (Optional, for 10x faster AI processing)

### Installation
1.  Clone the repository:
    ```bash
    git clone https://github.com/Minta1234/Tiktok-Downloader.git
    cd Tiktok-Downloader
    ```
2.  Run the application:
    ```bash
    python app.py
    ```
3.  **Auto-Setup**: Upon first run, the app will detect missing AI models and offer to download them automatically (approx. 2-5GB).

---

---

## 🤝 Support
For bugs or feature requests, please open an issue or contact the development team.

---

