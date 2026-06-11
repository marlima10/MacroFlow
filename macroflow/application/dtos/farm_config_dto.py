from dataclasses import dataclass


@dataclass(frozen=True)
class FarmConfigDTO:
    interval_ms: int
    roulette_quantity: int
    shutdown_on_finish: bool
