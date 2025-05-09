from __future__ import annotations


__all__ = (
    "SpawnViewFailed",
)


class SpawnViewFailed(Exception):
    def __init__(self, message : str):
        self.message = message
        super().__init__()
    
    def __str__(self):
        return self.message