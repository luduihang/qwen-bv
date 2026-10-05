"""parse_up 测试：数字 / 数字字符串 / space URL 解析 + 非法输入（TASKS 场景 1~3）。"""
import pytest

from bili import BiliError, parse_up


@pytest.mark.parametrize(
    "value,expected",
    [
        (12345678, 12345678),  # 正整数 int
        (1, 1),
        ("12345678", 12345678),  # 纯数字字符串
        ("1", 1),
        (" 12345678 ", 12345678),  # 首尾空白
        ("007", 7),  # 前导零仍为纯数字
    ],
)
def test_numeric_inputs(value, expected):
    assert parse_up(value) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://space.bilibili.com/12345678",
        "http://space.bilibili.com/12345678",  # http 亦可
        "https://space.bilibili.com/12345678/",  # 尾部 /
        "https://space.bilibili.com/12345678/channel/coin",  # 尾随 path
        "https://space.bilibili.com/12345678?spm=foo.bar",  # query
        "https://space.bilibili.com/12345678/channel/video?spm=foo&offset=0",
        "  https://space.bilibili.com/12345678  ",  # 首尾空白
        "https://Space.bilibili.com/12345678",  # 域名大小写不敏感
    ],
)
def test_space_url(url):
    assert parse_up(url) == 12345678


@pytest.mark.parametrize(
    "value",
    [
        None,
        "",
        "   ",  # 空值
        0,
        -5,  # mid <= 0
        "0",
        "-5",
        "12a45",  # 非数字
        "abc",  # 昵称
        "某知名UP主",  # 中文昵称
        12.5,  # 非 int 数字
        [12345678],  # 非字符串/整数类型
        True,  # bool 不是合法 mid
        "https://bilibili.com/12345678",  # 其他域名
        "https://www.bilibili.com/video/BV1xx411c7mD",
        "https://space.bilibili.com.cn/12345678",  # 近似域名
        "ftp://space.bilibili.com/12345678",  # 非 http(s) 协议
        "https://space.bilibili.com/",  # URL 缺 mid
        "https://space.bilibili.com",
        "https://space.bilibili.com/abc",  # mid 段非数字
        "https://space.bilibili.com/0",  # mid = 0
    ],
)
def test_invalid_inputs(value):
    with pytest.raises(BiliError) as ei:
        parse_up(value)
    assert ei.value.code == "invalid_up"
