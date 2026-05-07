# qr_generate.py
# Render(실서버) 배포 주소를 BASE_URL에 넣어 QR을 생성합니다.
import os
import qrcode

# ========= 여기만 수정(필요 시) =========
# BASE_URL에 사용 중인 Render 서버 주소만 넣으면 됩니다.
BASE_URL = "https://streetlamp-qr.onrender.com/lamp/"

# 생성할 가로등 번호: 테스트는 [1] 만, 많이 만들 때는 range(1, 101) 등
LAMP_IDS = range(1, 101)  # 1~100번 한꺼번에
# LAMP_IDS = range(1, 101)  # 1~100번 한꺼번에
# ==============================

OUTPUT_DIR = "qr_codes"


def generate_qr_for_lamp(lamp_id: int):
    url = f"{BASE_URL}{lamp_id}"
    img = qrcode.make(url)

    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR, exist_ok=True)

    filename = os.path.join(OUTPUT_DIR, f"lamp_{lamp_id:05d}.png")
    img.save(filename)
    print(f"생성 완료: {filename}")
    print(f"  URL: {url}")


if __name__ == "__main__":
    for lamp_id in LAMP_IDS:
        generate_qr_for_lamp(lamp_id)
    print("\n끝. qr_codes 폴더의 PNG 를 인쇄하거나 폰으로 보내서 스캔하세요.")
