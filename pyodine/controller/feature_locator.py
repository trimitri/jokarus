"""Aid in locating a given feature in a reference spectrum.

This module is a wrapper for the contained "FeatureLocator" class.
"""
import logging
from typing import Dict, List, Tuple, Union  # pylint: disable=unused-import

import numpy as np
from scipy import signal

LOGGER = logging.getLogger('pyodine.controller.feature_locator')


class FeatureLocator:
    """Find distorted samples' positions inside a reference signal.

    We assume that the supplied reference signal/spectrum etc. has a nontrivial
    shape (a sufficient density of distinguishable features). Presented with a
    sample resembling a part of the reference spectrum, this class may then
    determine the position in the reference at which that sample once belonged.

    It also provides a "confidence" rating, which may be used to determine if
    the sample at hand does belong in the reference at all.
    """
    def __init__(self, feature_threshold: float = 0.001) -> None:
        self.feature_threshold = feature_threshold
        self._ref = None  # type: np.ndarray
        self._ref_xvals = None  # type: np.ndarray
        self._sample = None  # type: np.ndarray
        self._corr = None  # type: np.ndarray
        self._norms = {}  # type: Dict[int, np.ndarray]

    @property
    def reference(self) -> np.ndarray:
        return self._ref

    @reference.setter
    def reference(self, ref: np.ndarray) -> None:
        self._ref = ref

        # Mark quantities that need to be recalculated when a new reference was
        # set.
        self._corr = None
        self._norms = {}


    def load_reference_from_txt(self, filename_txt: str) -> int:
        self._ref_xvals, self.reference = np.loadtxt(filename_txt, unpack=True)
        return len(self.reference)

    def load_reference_from_binary(self, filename: str) -> int:
        self.reference = np.fromfile(filename)
        return len(self.reference)

    def locate_sample(self, sample: np.ndarray, width: float) -> List[Tuple[int, float]]:
        """The classes core functionality. Locate a sample in a reference.

        :param width: The span of the sample relative to the full reference
                    width. Has to be ]0, 1[. As the sample rate may be
                    different for reference and sample, this is not obvious
                    from the array length.
        :returns: A list of tuples (position, confidence) indicating the most
                    probable locations in the reference from where the sample
                    may have originated.
                    `position` is a float in [0, 1[, indicating the position of
                    the sample's left edge. This will always be <1, as the
                    sample itself has a finite width.
                    `confidence` is an *arbitrary* indicator in [0, 1] of how
                    probable it is for the sample to have originated from
                    `position`.
                    For no matches, the list may be empty.
        """
        self._set_sample(sample)
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
            self._corr = signal.correlate(self._ref, self._sample, mode='valid')
            self._corr = np.divide(self._corr, self._get_normalization())
            return self._corr

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
        for feat in np.nditer(factors, op_flags=['readwrite']):

            # Does this part of the reference spectrum contain actual features?
            if feat < maxval * self.feature_threshold:
                # There is no feature here. Set a high normalization divisor to
                # effectively block this section from matching anything. (1.0
                # is the highest regular divisor, see above.)
                # This part is also important to avoid division by zero
                # problems.
                feat[...] = 1.11111111

        # Cache the result.
        self._norms[len(self._sample)] = factors

    def _interpolate_sample(self, length: float) -> np.ndarray:
        # We assume, that for our signal type, cubic splines present a much
        # more reasonable approximation than linear interpolation.
        pass

    def _set_sample(self, sample: np.ndarray) -> None:
        norm = np.linalg.norm(sample)
        self._sample = np.divide(sample, norm)

        # Mark quantities that need to be recalculated when a new reference was
        # set.
        self._corr = None
