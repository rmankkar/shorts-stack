import json
import os
import subprocess
import sys

def get_audio_duration(audio_path):
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path
        ],
        capture_output=True,
        text=True,
        check=True
    )
    return float(result.stdout.strip())

def timestamp(seconds):
    milliseconds = round(seconds * 1000)
    hours, milliseconds = divmod(milliseconds, 3_600_000)
    minutes, milliseconds = divmod(milliseconds, 60_000)
    seconds, milliseconds = divmod(milliseconds, 1000)
    return (
        f"{hours:02}:{minutes:02}:{seconds:02},"
        f"{milliseconds:03}"
    )

def main():
    job_dir = sys.argv[1] if len(sys.argv) > 1 else "/data/jobs/test"
    script_path = os.path.join(job_dir, "script.json")
    audio_path = os.path.join(job_dir, "voice.mp3")
    output_path = os.path.join(job_dir, "captions.srt")

    with open(script_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    words = data.get("narration", "").split()
    if not words:
        raise ValueError("Narration is empty")

    duration = get_audio_duration(audio_path)

    # Approximately 5 words per caption.
    chunks = [
        words[i:i + 5]
        for i in range(0, len(words), 5)
    ]

    with open(output_path, "w", encoding="utf-8") as f:
        for index, chunk in enumerate(chunks):
            start = duration * index / len(chunks)
            end = duration * (index + 1) / len(chunks)

            f.write(f"{index + 1}\n")
            f.write(
                f"{timestamp(start)} --> {timestamp(end)}\n"
            )
            f.write(" ".join(chunk) + "\n\n")

    print(f"Captions saved to: {output_path}")

if __name__ == "__main__":
    main()