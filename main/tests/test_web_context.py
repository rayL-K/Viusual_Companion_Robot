from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "main" / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from visual_companion_robot.integrations.web_context import (
    build_weather_summary,
    detect_weather_location,
    format_open_meteo_weather,
    is_weather_query,
)


class WebContextTests(unittest.TestCase):
    def test_weather_query_detects_jiangning(self) -> None:
        self.assertTrue(is_weather_query("今日江宁天气如何"))
        self.assertEqual(detect_weather_location("今日江宁天气如何")["name"], "南京市江宁区")

    def test_open_meteo_weather_is_formatted_for_llm(self) -> None:
        fact = format_open_meteo_weather(
            {"name": "南京市江宁区", "latitude": 31.95, "longitude": 118.84},
            {
                "current": {
                    "time": "2026-05-17T17:00",
                    "temperature_2m": 22.4,
                    "relative_humidity_2m": 61,
                    "precipitation": 0,
                    "weather_code": 2,
                    "wind_speed_10m": 9.2,
                },
                "daily": {
                    "weather_code": [2],
                    "temperature_2m_max": [26.1],
                    "temperature_2m_min": [18.2],
                    "precipitation_probability_max": [20],
                },
            },
            "https://api.open-meteo.com/v1/forecast",
        )

        self.assertEqual(fact["current"]["weather"], "多云")
        self.assertEqual(fact["today"]["max_temperature_c"], 26.1)
        self.assertIn("南京市江宁区当前多云", build_weather_summary(fact))


if __name__ == "__main__":
    unittest.main()
