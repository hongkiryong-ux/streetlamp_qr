# qr_generate.py
# Render(실서버) 배포 주소 + data/lamp_codes.csv 기준 QR PNG 생성
import csv
import os
import re
from pathlib import Path
from urllib.parse import quote

import qrcode

BASE_URL = "https://streetlamp-qr.onrender.com/lamp/"
CSV_PATH = Path(__file__).resolve().parent / "data" / "lamp_codes.csv"
OUTPUT_DIR = "qr_codes"


def _safe_filename(code: str) -> str:
    safe = re.sub(r'[<>:"/\\|?*]', "_", code)
    return f"lamp_{safe}.png"


def load_codes() -> list[str]:
    if not CSV_PATH.is_file():
        raise FileNotFoundError(
            f"{CSV_PATH} 없음. scripts/build_lamp_codes_csv.py 를 먼저 실행하세요."
        )
    codes: list[str] = []
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            code = (row.get("code") or "").strip()
            if code:
                codes.append(code)
    return codes


def generate_qr_for_code(code: str) -> str:
    url = f"{BASE_URL}{quote(code, safe='')}"
    img = qrcode.make(url)

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    filename = os.path.join(OUTPUT_DIR, _safe_filename(code))
    img.save(filename)
    return url


if __name__ == "__main__":
    codes = load_codes()
    print(f"QR 생성 시작: {len(codes)}개 → {OUTPUT_DIR}/")
    for i, code in enumerate(codes, 1):
        url = generate_qr_for_code(code)
        if i <= 5 or i == len(codes):
            print(f"  [{i}/{len(codes)}] {code} → {url}")
        elif i == 6:
            print("  ...")
    print(f"\n완료. {len(codes)}개 PNG → {OUTPUT_DIR}/")
