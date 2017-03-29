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

    def __init__(self, feature_threshold: float=0.001) -> None:
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
        smpl = np.array(sample)
        norm = np.linalg.norm(smpl)
        self._sample = np.divide(smpl, norm)

        # Mark quantities that need to be recalculated when a new reference was
        # set.
        self._corr = None

    def load_reference_from_txt(self, filename_txt: str) -> int:
        self._ref_xvals, self.reference = np.loadtxt(filename_txt, unpack=True)
        return len(self.reference)

    def load_reference_from_binary(self, filename: str) -> int:
        self.reference = np.fromfile(filename)
        return len(self.reference)

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
        """The (tweaked) cross correlation between sample and reference.

        This may be used for visual control of match quality.
        """
        if self._corr is not None:
            return self._corr

        if self._ref is not None and self._sample is not None:
            self._corr = signal.correlate(self._ref, self._sample,
                                          mode='valid')
            self._corr = np.divide(self._corr, self._get_normalization())
            return self._corr
        else:
            LOGGER.error("Set reference and sample before correlating.")
            return np.array([])

    def _get_normalization(self) -> np.ndarray:
        if len(self._sample) in self._norms:
            return self._norms[len(self._sample)]

        # Normalization wasn't calculated yet for current sample length.
        self._calc_normalization()
        return self._norms[len(self.sample)]

    def _calc_normalization(self) -> None:
        # Calculate the reference signal normalization factors for the current
        # sample width.
        # This is necessary in order to avoid ill-fitting, high-amplitude
        # matches overpowering well-fitting low-amplitude ones.

        # "Correlate" a sample-sized slice of the reference to itself,
        # effectively calculating the norm of this section. Repeat this for
        # every possible sample placement.
        # PERF: Calculating those norms is ineffective: obviously the same
        # elements get accounted for over and over again. This is however only
        # run once for each sample size and thus usually only once at all,
        # leading to negligible perfomance impact.
        factors = np.array([np.linalg.norm(self._ref[s:s + len(self._sample)])
                            for s
                            in range(len(self._ref) - len(self._sample) + 1)])
        maxval = factors.max()
        for f in np.nditer(factors, op_flags=['readwrite']):

            # Does this part of the reference spectrum contain actual features?
            if f < maxval * self._FEATURE_THRESH:
                # There is no feature here. Set a high normalization divisor to
                # effectively block this section from matching anything. (1.0
                # is the highest regular divisor, see above.)
                # This part is also important to avoid division by zero
                # problems.
                f[...] = 1.11111111

        # Cache the result.
        self._norms[len(self._sample)] = factors
