"""
_html_escape_utils.py — HTML escape 共用 module（P1#3 fix 2026-05-22）

用法：
    from _html_escape_utils import esc_text, esc_attr, safe_img_src

設計：
  - esc_text(x)  : 對 HTML 文字節點 escape（&, <, >）
  - esc_attr(x)  : 對 HTML attribute 值 escape（&, <, >, "）
  - safe_img_src : allowlist 驗 img/a href — 只接受相對路徑 jpg/jpeg/png/gif/webp
                   svg 故意不在 allowlist（外來 SVG 可帶 script）

適用場景：
  build_index.py / build_all.py / build_beauty.py / build_bappu.py / build_achi.py
  的 article 渲染函式 — title/insight/scene/cta/pie/ts/say/sub/mirror/platform/po_time/hashtag

注意：hashtag data-hashtags attribute 直接 join(' ')，本模組提供 esc_attr 讓 caller 自行 escape 每個 tag。
"""

import html as _html
import re as _re

# img/a href allowlist：只接受相對路徑 + 安全副檔名（不含 svg）
_IMG_PATH_PATTERN = _re.compile(
    r'^[a-zA-Z0-9_\-./]+\.(jpg|jpeg|png|gif|webp)$',
    _re.IGNORECASE,
)

_BLOCKED_SCHEMES = ('javascript:', 'data:', 'vbscript:', 'http://', 'https://')


def esc_text(x) -> str:
    """對 HTML 文字節點 escape（& < >）。None/非字串轉為空字串。"""
    if x is None:
        return ''
    return _html.escape(str(x), quote=False)


def esc_attr(x) -> str:
    """對 HTML attribute 值 escape（& < > "）。None/非字串轉為空字串。"""
    if x is None:
        return ''
    return _html.escape(str(x), quote=True)


def safe_img_src(src) -> str:
    """
    驗證 img src / a href 只接受相對路徑 + 安全副檔名。
    通過 → 回傳 esc_attr(src)
    不通過 → raise ValueError（caller 可選 try/except 或讓它炸）
    """
    if not src:
        return ''
    s = str(src)
    for scheme in _BLOCKED_SCHEMES:
        if s.lower().startswith(scheme):
            raise ValueError(f'img src 不允許 scheme: {s!r}')
    if not _IMG_PATH_PATTERN.match(s):
        raise ValueError(f'img src 不符 allowlist（只接受相對路徑 jpg/jpeg/png/gif/webp）: {s!r}')
    return esc_attr(s)
