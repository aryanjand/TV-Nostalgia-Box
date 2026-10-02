"""TvPower that never sends HDMI-CEC. Parents turn the television on themselves."""


class NullTvPower:
    def standby(self) -> None:
        return None

    def power_on(self) -> None:
        return None

    def is_in_standby(self) -> bool:
        return False
