"""Aid in locating a given feature in a reference spectrum.

This module is a wrapper for the contained "FeatureLocator" class.
"""
import numpy as np
import logging
from scipy import signal
from typing import Dict, List, Tuple, Union
Dict  # Dummy usage to prevent "imported but unused" warning.

LOGGER = logging.getLogger('pyodine.controller.feature_locator')
SomeArray = Union[List[float], np.ndarray]  # Either python list or np array.


class FeatureLocator:

    def __init__(self, feature_threshold: float=0.2) -> None:
        self._FEATURE_THRESH = feature_threshold
        self._ref = None  # type: np.ndarray
        self._ref_xvals = None  # type: np.ndarray
        self._sample = None  # type: np.ndarray
        self._corr = None  # type: np.ndarray
        self._norms = {}  # type: Dict[int, np.ndarray]

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

        # Mark quantities that need to be recalculated when a new reference was
        # set.
        self._corr = None
        self._norms = {}

    @property
    def sample(self) -> np.ndarray:
        return self._sample

    @sample.setter
    def sample(self, sample: SomeArray) -> None:
        self._sample = np.array(sample)

        # Mark quantities that need to be recalculated when a new reference was
        # set.
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

    def correlate(sf) -> np.ndarray:
        if sf._corr is not None:
            return sf._corr

        if sf._ref is not None and sf._sample is not None:
            sf._corr = signal.correlate(sf._ref, sf._sample,
                                        mode='valid')
            sf._corr = np.divide(sf._corr, sf._get_normalization())
            return sf._corr
        else:
            LOGGER.error("Set reference and sample before correlating.")
            return np.array([])

    def _get_normalization(sf) -> np.ndarray:
        if len(sf._sample) in sf._norms:
            return sf._norms[len(sf._sample)]

        # Normalization wasn't calculated yet for current sample length.
        sf._calc_normalization()
        return sf._norms[len(sf.sample)]

    def _calc_normalization(sf) -> None:
        # Calculate the reference signal normalization factors for the current
        # sample width.
        # This is necessary in order to avoid ill-fitting, high-amplitude
        # matches overpowering well-fitting low-amplitude ones.

        # "Correlate" a sample-sized slice of the reference to itself,
        # resulting in a scalar product with itself == norm**2.
        # Repeat this for every possible sample placement.
        factors = np.array([np.linalg.norm(sf._ref[s:s + len(sf._sample)])
                            for s
                            in range(len(sf._ref) - len(sf._sample) + 1)])
        maxval = factors.max()
        for f in np.nditer(factors, op_flags=['readwrite']):

            # Does this part of the reference spectrum contain actual features?
            if f > maxval * sf._FEATURE_THRESH:
                f[...] = f / maxval  # Normalize to max() == 1
            else:
                # There is no feature here. Set a high normalization divisor to
                # effectively block this section from matching anything. (1.0
                # is the highest regular divisor, see above.)
                f[...] = 1.11111111

        # Cache the result.
        sf._norms[len(sf._sample)] = factors
