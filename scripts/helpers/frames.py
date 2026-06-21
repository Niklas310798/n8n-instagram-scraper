"""Extract distinct frames from a video for OCR.

Uses ffmpeg scene-change detection so we capture one frame per visual "slide"
instead of hundreds of near-identical frames. Falls back to fixed-interval
sampling if no scene cuts are detected (e.g. a static talking-head with
persistent on-screen text).
"""
import glob
import os
import subprocess


def extract_keyframes(video_path: str, output_dir: str, max_frames: int = 12,
                      scene_threshold: float = 0.3) -> list:
    base = os.path.splitext(os.path.basename(video_path))[0]
    pattern = os.path.join(output_dir, f"{base}_frame_%03d.jpg")

    def _run(vf: str):
        subprocess.run(
            ["ffmpeg", "-i", video_path, "-vf", vf, "-vsync", "vfr",
             "-frames:v", str(max_frames), "-q:v", "3", "-y", pattern],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        return sorted(glob.glob(os.path.join(output_dir, f"{base}_frame_*.jpg")))

    # Always include frame 0, then any scene changes.
    frames = _run(f"select='eq(n,0)+gt(scene,{scene_threshold})'")
    if not frames:
        # Fallback: one frame every 2 seconds.
        frames = _run("fps=1/2")
    return frames
