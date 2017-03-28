"""Aid in locating a given feature in a reference spectrum.

This module is a wrapper for the contained "FeatureLocator" class.
"""
import numpy as np
import logging
from scipy import signal
from typing import List, Tuple, Union

LOGGER = logging.getLogger('pyodine.controller.feature_locator')
SomeArray = Union[List[float], np.ndarray]


class FeatureLocator:

    def __init__(self) -> None:
        self._ref = None  # type: np.ndarray
        self._ref_xvals = None  # type: np.ndarray
        self._sample = None  # type: np.ndarray
        self._corr = None  # type: np.ndarray

    @property
    def reference(self) -> np.ndarray:
        if self._ref is not None:
            return self._ref
        else:
            LOGGER.error("Set reference before accessing it.")
            return np.array([])

    @reference.setter
    def reference(self, ref: SomeArray) -> None:
        self._ref = np.array(ref)
        self._corr = None

    @property
    def sample(self) -> np.ndarray:
        return self._sample

    @sample.setter
    def sample(self, sample: SomeArray) -> None:
        self._sample = np.array(sample)
        self._corr = None

    def load_reference(self, filename_txt: str='') -> None:
        self._ref_xvals, self.reference = np.loadtxt(filename_txt, unpack=True)

    def locate_sample(self) -> Tuple[int, float]:
        position = self.correlate().argmax()

        # Returns a 1-element tuple of array indices where local maximums are
        # located. We need to set the mode to 'wrap' in order to also catch
        # relative max's at the very start and end of the corr. signal.
        relative_maxima_positions = signal.argrelmax(self.correlate(),
                                                     mode='wrap')[0]
        maxima = [self.correlate()[i] for i in relative_maxima_positions]
        maxima = np.sort(maxima)
        if len(maxima) > 1:

            # Compare highest maximum to second highest.
            confidence = (maxima[-1] - maxima[-2]) / maxima[-1]
        elif len(maxima) == 1:
            confidence = 1  # Only one maximum was found.
        else:
            confidence = 0  # No maximum was found.
        return (position, confidence)

    def correlate(self) -> np.ndarray:
        if self._ref is not None and self._sample is not None:
            if self._corr is None:
                self._corr = signal.correlate(self._ref, self._sample,
                                              mode='valid')
            return self._corr
        else:
            LOGGER.error("Set reference and sample before correlating.")
            return np.array([])
