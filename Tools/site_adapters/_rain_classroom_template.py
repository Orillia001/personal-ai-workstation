"""Rain Classroom adapter scaffold. Deliberately not registered or executable yet.

Implement only after the user supplies page evidence for the login state and
the top exam notice/dropdown. Keep credentials and cookies out of source code.
"""

from workstation_site_bridges import Assignment, LoginResult


class RainClassroomAdapter:
    key = "rain_classroom"

    def login(self, base_url: str) -> LoginResult:
        """Resolve the user's authorized entry and verify a loaded signed-in page."""
        raise NotImplementedError("待确认雨课堂登录后页面的就绪标记")

    def check_assignments(self, base_url: str) -> list[Assignment]:
        """Open the top notice and read its dropdown after login is ready."""
        raise NotImplementedError("待确认考试提醒的选择器与下拉字段")
