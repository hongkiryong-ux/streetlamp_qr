# scripts/build_lamp_codes_csv.py
# 첨부 스프레드시트(가로등 코드 목록) 기준으로 data/lamp_codes.csv 생성
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "lamp_codes.csv"

# (prefix, max_number) — 이미지 열 순서·개수 기준
CODE_GROUPS: list[tuple[str, int]] = [
    # 숫자 접두
    ("1", 20),
    ("7", 20),
    ("8", 20),
    ("12", 20),
    ("51", 32),
    ("53", 15),
    ("56", 32),
    ("57", 54),
    ("60", 56),
    # 영문
    ("GH", 20),
    ("GL", 71),
    ("G", 17),
    ("BH", 32),
    ("Ts", 20),
    ("PP", 16),
    ("Bh", 4),
    ("BJ", 18),
    ("Be", 4),
    ("Jus", 21),
    ("JJ", 21),
    ("TU", 16),
    ("TD", 31),
    ("PS", 30),
    ("Bd", 15),
    ("Jh", 16),
    ("H", 16),
    ("R", 5),
    # 한글
    ("명", 20),
    ("백", 53),
    ("모", 21),
    ("러", 21),
    ("스3", 18),
    ("소1", 21),
    ("중", 15),
    ("연", 7),
    ("폭", 14),
    ("성", 37),
    ("프", 10),
    ("본", 2),
    ("부", 5),
    ("마", 28),
    ("브", 8),
    ("기", 8),
    ("어", 58),
    ("어정", 21),
    ("무", 21),
    ("제", 7),
    ("8정", 18),
    ("임1", 18),
]


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for prefix, max_n in CODE_GROUPS:
        for n in range(1, max_n + 1):
            code = f"{prefix}-{n}"
            if code in seen:
                raise ValueError(f"duplicate code: {code}")
            seen.add(code)
            rows.append({"code": code, "group_prefix": prefix})

    with OUT.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["code", "group_prefix"])
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote {len(rows)} codes to {OUT}")


if __name__ == "__main__":
    main()
