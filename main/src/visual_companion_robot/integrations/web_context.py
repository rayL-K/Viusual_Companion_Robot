"""联网事实上下文。

当前先把最常见的实时天气查询做成确定性联网补充，再交给 LLM 组织成自然回复。
这样可以避免模型凭记忆编造天气，也为后续接入更多在线工具保留统一入口。
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple


OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
WEATHER_QUERY_KEYWORDS = ("天气", "气温", "温度", "下雨", "降雨", "风速")
WEATHER_LOCATIONS: List[Tuple[str, Dict[str, Any]]] = [
    ("江宁", {"name": "南京市江宁区", "latitude": 31.95, "longitude": 118.84}),
    ("江宁区", {"name": "南京市江宁区", "latitude": 31.95, "longitude": 118.84}),
    ("南京", {"name": "南京市", "latitude": 32.06, "longitude": 118.78}),
]


def build_web_context(user_text: str, now: Optional[datetime] = None, timeout_sec: int = 8) -> Dict[str, Any]:
    """根据用户输入构造默认开启的联网事实上下文。"""

    reference_time = now or datetime.now().astimezone().replace(microsecond=0)
    context: Dict[str, Any] = {
        "enabled": True,
        "queried_at": reference_time.isoformat(timespec="seconds"),
        "facts": [],
        "errors": [],
    }
    if not is_weather_query(user_text):
        return context

    location = detect_weather_location(user_text)
    if not location:
        context["errors"].append("检测到天气查询，但没有识别到城市或区域。")
        return context

    try:
        weather_data, source_url = fetch_open_meteo_weather(location, timeout_sec=timeout_sec)
        context["facts"].append(format_open_meteo_weather(location, weather_data, source_url))
    except (OSError, ValueError, KeyError, urllib.error.URLError, json.JSONDecodeError) as exc:
        context["errors"].append(f"天气联网查询失败：{exc}")
    return context


def is_weather_query(user_text: str) -> bool:
    """判断是否需要天气联网事实。"""

    text = str(user_text or "")
    return any(keyword in text for keyword in WEATHER_QUERY_KEYWORDS)


def detect_weather_location(user_text: str) -> Optional[Dict[str, Any]]:
    """从用户输入中识别当前支持的天气位置。"""

    text = str(user_text or "")
    for keyword, location in WEATHER_LOCATIONS:
        if keyword in text:
            return dict(location)
    return None


def fetch_open_meteo_weather(location: Dict[str, Any], timeout_sec: int = 8) -> Tuple[Dict[str, Any], str]:
    """调用 Open-Meteo 获取当前天气和今日预报。

    Raises:
        urllib.error.URLError: 网络不可达或超时。
        json.JSONDecodeError: 响应非 JSON。
        KeyError: location 缺少必要字段。
    """

    query = urllib.parse.urlencode(
        {
            "latitude": location["latitude"],
            "longitude": location["longitude"],
            "current": "temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_speed_10m",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "timezone": "Asia/Shanghai",
            "forecast_days": 1,
        }
    )
    url = f"{OPEN_METEO_URL}?{query}"
    try:
        with urllib.request.urlopen(url, timeout=timeout_sec) as response:
            data = json.loads(response.read().decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Open-Meteo 返回非 JSON 数据 [{url}]：{exc}") from exc
    return data, url


def format_open_meteo_weather(location: Dict[str, Any], data: Dict[str, Any], source_url: str) -> Dict[str, Any]:
    """把 Open-Meteo 响应压缩成 LLM 易用的中文事实。

    所有 dict 取值使用 .get() 安全退化，空字段不会抛异常。
    """

    current = data.get("current") or {}
    daily = data.get("daily") or {}
    daily_codes = daily.get("weather_code") or []
    max_temperatures = daily.get("temperature_2m_max") or []
    min_temperatures = daily.get("temperature_2m_min") or []
    precipitation_probs = daily.get("precipitation_probability_max") or []
    today_code = daily_codes[0] if daily_codes else current.get("weather_code")
    fact = {
        "type": "weather",
        "source": "Open-Meteo",
        "source_url": source_url,
        "location": location["name"],
        "observed_at": current.get("time", ""),
        "current": {
            "weather": weather_code_to_text(current.get("weather_code")),
            "temperature_c": current.get("temperature_2m"),
            "humidity_percent": current.get("relative_humidity_2m"),
            "precipitation_mm": current.get("precipitation"),
            "wind_speed_kmh": current.get("wind_speed_10m"),
        },
        "today": {
            "weather": weather_code_to_text(today_code),
            "max_temperature_c": max_temperatures[0] if max_temperatures else None,
            "min_temperature_c": min_temperatures[0] if min_temperatures else None,
            "precipitation_probability_percent": precipitation_probs[0] if precipitation_probs else None,
        },
    }
    fact["summary"] = build_weather_summary(fact)
    return fact


def build_weather_summary(fact: Dict[str, Any]) -> str:
    """生成可直接引用的天气事实摘要。"""

    current = fact["current"]
    today = fact["today"]
    parts = [
        f"{fact['location']}当前{current['weather']}",
        f"{current['temperature_c']}°C" if current["temperature_c"] is not None else "",
        f"湿度{current['humidity_percent']}%" if current["humidity_percent"] is not None else "",
        f"风速{current['wind_speed_kmh']}km/h" if current["wind_speed_kmh"] is not None else "",
        f"今日{today['weather']}",
        f"{today['min_temperature_c']}到{today['max_temperature_c']}°C"
        if today["min_temperature_c"] is not None and today["max_temperature_c"] is not None
        else "",
        f"最大降水概率{today['precipitation_probability_percent']}%"
        if today["precipitation_probability_percent"] is not None
        else "",
    ]
    return "，".join(part for part in parts if part)


def weather_code_to_text(raw_code: Any) -> str:
    """Open-Meteo 天气码转中文。"""

    try:
        code = int(raw_code)
    except (TypeError, ValueError):
        return "未知天气"
    if code == 0:
        return "晴"
    if code in {1, 2, 3}:
        return "多云"
    if code in {45, 48}:
        return "有雾"
    if code in {51, 53, 55, 56, 57}:
        return "毛毛雨"
    if code in {61, 63, 65, 66, 67, 80, 81, 82}:
        return "下雨"
    if code in {71, 73, 75, 77, 85, 86}:
        return "下雪"
    if code in {95, 96, 99}:
        return "雷雨"
    return "未知天气"
