from enum import StrEnum


class Underlying(StrEnum):
    SPY = "SPY"
    QQQ = "QQQ"
    IWM = "IWM"


class DecisionWindow(StrEnum):
    MORNING = "10:05"
    MIDDAY = "11:35"
    AFTERNOON = "13:05"
    LATE = "14:20"


class Strategy(StrEnum):
    LONG_VOL = "LONG_VOL"
    SHORT_VOL = "SHORT_VOL"


class OptionRight(StrEnum):
    CALL = "C"
    PUT = "P"


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class Scenario(StrEnum):
    BASE = "BASE"
    VOL_UP = "VOL_UP"
    VOL_DOWN = "VOL_DOWN"
    LEFT_TAIL = "LEFT_TAIL"
    RIGHT_TAIL = "RIGHT_TAIL"
    VETO = "VETO"


class ExecutionState(StrEnum):
    SUBMITTED = "SUBMITTED"
    REPLACED = "REPLACED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    RECONCILE_REQUIRED = "RECONCILE_REQUIRED"
