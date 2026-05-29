from kiwipiepy import Kiwi

_kiwi = Kiwi()

# 의미를 가진 품사만 유지 (조사, 어미, 구두점 제외)
_KEEP_TAGS = frozenset({
    "NNG", "NNP", "NNB", "NR",
    "VV", "VA", "MAG",
    "SL", "SH", "SN",
})


def tokenize(text: str) -> list[str]:
    if not text or not text.strip():
        return [""]
    tokens = [t.form.lower() for t in _kiwi.tokenize(text) if t.tag in _KEEP_TAGS]
    return tokens if tokens else [""]
