"""Guardrail tests: run with `python tests/test_guards.py` (no model needed)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import main


def check(name, got, want):
    status = "PASS" if got == want else "FAIL"
    print(f"[{status}] {name}: got={got!r} want={want!r}")
    if got != want:
        raise SystemExit(f"FAILED: {name}")


v = main.TextRefiner._is_valid_correction
check("truncation rejected", v("ทดสอบ 1 2 3 4 5", "ทดสอบ"), False)
check("addition rejected", v("สวัสดีครับ", "สวัสดีครับ ยินดีให้บริการครับ"), False)
check("multiline rejected", v("abc def", "line1\nline2"), False)
check("empty rejected", v("abc", ""), False)
check("th->en translation rejected", v("ทดสอบระบบ", "this is a system test"), False)
check("en->th translation rejected", v("hello world test", "สวัสดี"), False)
check("legit tech fix accepted", v("ผมใช้เจมินายในการทำงาน", "ผมใช้ Gemini ในการทำงาน"), True)
check("identical accepted", v("สอบ 1 2 3", "สอบ 1 2 3"), True)

s = main.TextRefiner._strip_unspoken_polite
check("strip unspoken ครับ", s("สวัสดี", "สวัสดีครับ"), "สวัสดี")
check("keep spoken ครับ", s("สวัสดีครับ", "สวัสดีครับ"), "สวัสดีครับ")

check("tech casing html", main.format_tech_casing("เปิด html แล้ว"), "เปิด HTML แล้ว")
check("tech casing ai api", main.format_tech_casing("ทดสอบ ai และ api"), "ทดสอบ AI และ API")
check("tech casing python", main.format_tech_casing("เขียนโค้ด python"), "เขียนโค้ด Python")
check("tech casing g4speak", main.format_tech_casing("โปรแกรม g4speak"), "โปรแกรม G4Speak")

check("spacing th-en", main.format_spacing("ใช้Geminiทำงาน"), "ใช้ Gemini ทำงาน")
check("spacing collapse", main.format_spacing("a  b"), "a b")
check("thai trailing dot dropped", main.format_spacing("สวัสดีครับ."), "สวัสดีครับ")
check("thai comma dropped", main.format_spacing("ทดสอบ, ครับ"), "ทดสอบ ครับ")
check("english comma kept", main.format_spacing("Hello, world."), "Hello, world.")
check("decimal kept", main.format_spacing("version 3.5"), "version 3.5")
check("thai dot kept out of english", main.format_spacing("สวัสดี. Hello"), "สวัสดี Hello")

h = main.is_silence_hallucination
check("thanks for watching dropped", h("Thanks for watching."), True)
check("THANKS FOR WATCHING dropped", h("THANKS FOR WATCHING"), True)
check("please subscribe dropped", h("Please subscribe!"), True)
check("thai closer dropped", h("ขอบคุณสำหรับการรับชม"), True)
check("hum dropped", h("อืม"), True)
check("real english kept", h("Hello world"), False)
check("real thai kept", h("ทดสอบระบบ"), False)
check("confident closer passes", h("Thanks for watching.", strict=False), False)
check("hum still dropped when confident", h("อืม", strict=False), True)
check("fuzzy partial closer", main.is_fuzzy_closer("Thank for wa"), True)
check("fuzzy legit short kept", main.is_fuzzy_closer("thank you"), False)
check("fuzzy legit thanks kept", main.is_fuzzy_closer("thanks"), False)
check("fuzzy unrelated kept", main.is_fuzzy_closer("hello world test"), False)
check("amara credit dropped", main.is_provider_credit("Subtitles by the Amara.org community"), True)
check("amara credit casefold", main.is_provider_credit("SUBTITLES BY THE AMARA.ORG COMMUNITY."), True)
check("normal text not credit", main.is_provider_credit("Hello world"), False)

print("All guardrail tests passed.")
