# qr_generate.py
# 핸드폰으로 QR 스캔 테스트하려면 아래 PC_IP 를 본인 PC의 IPv4 로 바꾸세요. (127.0.0.1 은 폰에서 안 됨)
import os
import qrcode

# ========= 여기만 수정 =========
# PowerShell 에서 ipconfig → "IPv4 주소" (예: 192.168.0.15)
PC_IP = "192.168.0.15"
PORT = 8000

# 인터넷에 배포한 뒤에는 아래처럼 쓰고, PC_IP/PORT 대신 고정 URL 사용:
# BASE_URL = "https://내서비스.onrender.com/lamp/"
BASE_URL = f"http://{PC_IP}:{PORT}/lamp/"

# 생성할 가로등 번호: 테스트는 [1] 만, 많이 만들 때는 range(1, 101) 등
LAMP_IDS = range(1, 2)  # 지금은 1번 QR만 생성
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
