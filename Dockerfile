FROM python:3.12-slim

# ffmpeg: yt-dlp media + faster-whisper audio decode + frame extraction
# libgl1/libglib2.0-0: required by RapidOCR's OpenCV backend
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg libgl1 libglib2.0-0 && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install Python requirements
COPY requirements.txt /requirements.txt
RUN pip install --no-cache-dir -r /requirements.txt

# Run as non-root; pre-create the model cache so the named volume inherits
# node ownership (otherwise faster-whisper can't write to /home/node/.cache).
RUN useradd -ms /bin/bash node && \
    mkdir -p /home/node/.cache && \
    chown -R node:node /home/node
USER node
WORKDIR /home/node

EXPOSE 8000

CMD ["python", "/home/node/scripts/main.py"]
