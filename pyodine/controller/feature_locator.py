"""Aid in locating a given feature in a reference spectrum.

This module is a wrapper for the contained "FeatureLocator" class.
"""
import numpy as np


class FeatureLocator:

    def __init__(self) -> None:
        self.ref_spectrum = None  # type: np.ndarray

    def load_reference_spectrum(self, filename: str) -> None:
        self.ref_spectrum = np.loadtxt(filename, unpack=True)

    def locate_feature(self, data: np.ndarray) -> None:
        pass

    def save_reference_spectrum(self, filename: str) -> None:
        pass
