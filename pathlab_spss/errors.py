"""Stable, value-free error contract shared by the engine and SPSS adapter."""


class LabError(Exception):
    def __init__(self, code="INVALID_DATA"):
        self.code = code
        super().__init__(code)
